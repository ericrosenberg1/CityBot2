import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import asyncio
from datetime import datetime
from .platforms.base import SocialPlatform
from .platforms.twitter import TwitterPlatform
from .platforms.bluesky import BlueSkyPlatform
from .platforms.facebook import FacebookPlatform
from .platforms.linkedin import LinkedInPlatform
from .utils import RateLimiter, ContentValidator, PostContent
from .formatters import PostFormatter

logger = logging.getLogger('CityBot2.social.manager')

@dataclass
class PlatformConfig:
    """Configuration for a social media platform."""
    enabled: bool = False
    post_types: List[str] = field(default_factory=list)
    credentials: Dict[str, str] = field(default_factory=dict)
    rate_limits: Dict[str, int] = field(default_factory=lambda: {
        'posts_per_hour': 10,
        'posts_per_day': 24,
        'minimum_interval': 300
    })

@dataclass
class PostResult:
    """Result of a social media post attempt."""
    success: bool
    error: Optional[str] = None
    platform_response: Optional[Dict[str, Any]] = None

class SocialMediaManager:
    """Manages posting to multiple social media platforms."""

    def __init__(self, config: Dict[str, Any], city_config: Dict[str, Any]):
        """Initialize the social media manager.
        
        Args:
            config: Dictionary containing platform configurations
            city_config: Dictionary containing city-specific settings
        """
        self._validate_config(config, city_config)
        self.config = config
        self.city_config = city_config
        self.platforms: Dict[str, SocialPlatform] = {}
        self.rate_limiter = RateLimiter(config=config.get('rate_limits'))
        self.content_validator = ContentValidator()
        self.post_formatter = PostFormatter(city_config)
        self.platform_retries: Dict[str, int] = {}
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 60)
        
        self.initialize_platforms()

    def _validate_config(self, config: Dict[str, Any], city_config: Dict[str, Any]) -> None:
        """Validate configuration dictionaries.
        
        Args:
            config: Platform configuration dictionary
            city_config: City configuration dictionary
        
        Raises:
            ValueError: If required configuration fields are missing
        """
        if 'platforms' not in config:
            raise ValueError("Configuration must include 'platforms' section")
            
        required_city_fields = ['name', 'state', 'coordinates']
        missing_fields = [field for field in required_city_fields if field not in city_config]
        if missing_fields:
            raise ValueError(f"Missing required city configuration fields: {', '.join(missing_fields)}")

    def initialize_platforms(self) -> None:
        platform_classes = {
            'bluesky': BlueSkyPlatform,
            'twitter': TwitterPlatform,
            'facebook': FacebookPlatform,
            'linkedin': LinkedInPlatform,
        }

        for platform_name, platform_class in platform_classes.items():
            platform_config = self.config['platforms'].get(platform_name, {})
            if not platform_config.get('enabled', False):
                continue

            try:
                if self._validate_platform_config(platform_name, platform_config):
                    # Pass both platform_config and city_config
                    self.platforms[platform_name] = platform_class(platform_config, self.city_config)
                    self.platform_retries[platform_name] = 0
                    logger.info(f"Initialized {platform_name} platform")
            except Exception as e:
                logger.error(f"Failed to initialize {platform_name}: {str(e)}")

    async def post_content(self, content: PostContent, post_type: str) -> Dict[str, PostResult]:
        """Post content to all enabled and appropriate platforms.
        
        Args:
            content: The content to post
            post_type: Type of post (e.g., 'weather', 'news', etc.)
        
        Returns:
            Dictionary mapping platform names to PostResult objects
        """
        results: Dict[str, PostResult] = {}
        tasks = []

        for platform_name, platform in self.platforms.items():
            can_post, reason = await self._can_post_to_platform(platform_name, post_type)
            if not can_post:
                results[platform_name] = PostResult(
                    success=False,
                    error=reason
                )
                continue

            tasks.append(self._post_to_platform_with_retry(platform_name, platform, content))

        if tasks:
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
            for platform_name, result in zip(self.platforms.keys(), completed_tasks):
                if isinstance(result, Exception):
                    results[platform_name] = PostResult(
                        success=False,
                        error=str(result)
                    )
                else:
                    results[platform_name] = result

        return results

    async def _post_to_platform_with_retry(
        self,
        platform_name: str,
        platform: SocialPlatform,
        content: PostContent
    ) -> PostResult:
        """Post to a platform with retry logic."""
        retries = 0
        last_error = None

        while retries < self.max_retries:
            try:
                result = await self._post_to_platform(platform_name, platform, content)
                if result.success:
                    self.platform_retries[platform_name] = 0
                    return result

                last_error = result.error

            except Exception as e:
                last_error = str(e)
                logger.error(f"Error posting to {platform_name} (attempt {retries + 1}): {last_error}")
                retries += 1
                self.platform_retries[platform_name] += 1
                
                if retries < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2 ** retries))
                continue

            break

        return PostResult(success=False, error=f"Max retries exceeded. Last error: {last_error}")

    async def _post_to_platform(
        self,
        platform_name: str,
        platform: SocialPlatform,
        content: PostContent
    ) -> PostResult:
        """Post to a specific platform with error handling."""
        try:
            formatted_content = platform.format_post(content)
            validation_errors = self.content_validator.validate_content(formatted_content, platform_name)

            if validation_errors:
                return PostResult(
                    success=False,
                    error=f"Content validation failed: {', '.join(validation_errors)}"
                )

            success = await platform.post_update(formatted_content)
            if success:
                await self.rate_limiter.record_post(platform_name, content.text[:100])
                logger.info(f"Successfully posted to {platform_name}")
                return PostResult(success=True)
            
            return PostResult(success=False, error="Platform post update failed")

        except Exception as e:
            logger.error(f"Error posting to {platform_name}: {str(e)}")
            raise

    def _validate_platform_config(self, platform: str, config: Dict) -> bool:
        """Validate platform configuration."""
        required_credentials = {
            'twitter': ['api_key', 'api_secret', 'access_token', 'access_secret'],
            'bluesky': ['handle', 'password'],
            'facebook': ['page_id', 'access_token'],
            'linkedin': ['client_id', 'client_secret', 'access_token'],
        }

        if platform not in required_credentials:
            logger.error(f"Unknown platform: {platform}")
            return False

        missing = [cred for cred in required_credentials[platform]
                  if not config.get('credentials', {}).get(cred)]

        if missing:
            logger.error(f"Missing credentials for {platform}: {', '.join(missing)}")
            return False

        return True

    async def _can_post_to_platform(self, platform_name: str, post_type: str) -> Tuple[bool, Optional[str]]:
        """Check if posting is allowed for the platform and type.
        
        Returns:
            Tuple of (can_post: bool, reason: Optional[str])
        """
        platform_config = self.config['platforms'].get(platform_name, {})
        
        if not platform_config.get('enabled', False):
            return False, "Platform not enabled"

        if post_type not in platform_config.get('post_types', []):
            return False, f"Post type '{post_type}' not enabled for platform"

        if not await self.rate_limiter.can_post(platform_name, post_type):
            return False, "Rate limit exceeded"

        if self.platform_retries[platform_name] >= self.max_retries:
            return False, "Maximum retry attempts exceeded"

        return True, None

    async def post_weather(self, weather_data: Dict[str, Any]) -> Dict[str, PostResult]:
        """Post weather update to appropriate platforms."""
        content = self.post_formatter.format_weather(weather_data)
        return await self.post_content(content, 'weather')

    async def post_weather_alert(self, alert_data: Dict[str, Any]) -> Dict[str, PostResult]:
        """Post weather alert to appropriate platforms."""
        content = self.post_formatter.format_weather_alert(alert_data)
        return await self.post_content(content, 'weather')

    async def post_earthquake(self, quake_data: Dict[str, Any]) -> Dict[str, PostResult]:
        """Post earthquake update to appropriate platforms."""
        content = self.post_formatter.format_earthquake(quake_data)
        return await self.post_content(content, 'earthquake')

    async def post_news(self, article_data: Dict[str, Any]) -> Dict[str, PostResult]:
        """Post news update to appropriate platforms."""
        content = self.post_formatter.format_news(article_data)
        return await self.post_content(content, 'news')

    async def close(self) -> None:
        """Clean up resources and close connections."""
        close_tasks = []
        for platform in self.platforms.values():
            if hasattr(platform, 'close'):
                close_tasks.append(platform.close())
        
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        
        await self.rate_limiter.close()
        logger.info("Social media manager shutdown complete")