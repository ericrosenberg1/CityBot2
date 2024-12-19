import logging
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
import asyncio
from datetime import datetime

from .platforms.base import SocialPlatform
from .platforms.twitter import TwitterPlatform
from .platforms.bluesky import BlueSkyPlatform
from .platforms.facebook import FacebookPlatform
from .platforms.linkedin import LinkedInPlatform
from social_media.utils import RateLimiter, ContentValidator, PostContent
from monitors.earthquake import format_earthquake_for_social

if TYPE_CHECKING:
    from monitors.weather import WeatherData, WeatherAlert

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
        """Initialize the social media manager."""
        self._validate_config(config, city_config)
        self.config = config
        self.city_config = city_config
        self.platforms: Dict[str, SocialPlatform] = {}
        self.rate_limiter = RateLimiter(config=config.get('rate_limits'))
        self.content_validator = ContentValidator()
        self.platform_retries: Dict[str, int] = {}
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 60)
        
        self.initialize_platforms()

    def _validate_config(self, config: Dict[str, Any], city_config: Dict[str, Any]) -> None:
        """Validate the configuration."""
        if 'platforms' not in config:
            raise ValueError("Configuration must include 'platforms' section")
            
        required_city_fields = ['name', 'state', 'coordinates']
        missing_fields = [field for field in required_city_fields if field not in city_config]
        if missing_fields:
            raise ValueError(f"Missing required city configuration fields: {', '.join(missing_fields)}")

    def initialize_platforms(self) -> None:
        """Initialize configured social media platforms."""
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
                logger.debug("Initializing %s with credentials: %s", 
                           platform_name, 
                           list(platform_config.get('credentials', {}).keys()))
                
                if platform_name == 'twitter':
                    # Let TwitterPlatform handle validation
                    is_valid, error = TwitterPlatform.validate_config(platform_config)
                    if not is_valid:
                        logger.error("Invalid Twitter configuration: %s", error)
                        continue
                elif not self._validate_platform_config(platform_name, platform_config):
                    continue

                self.platforms[platform_name] = platform_class(platform_config, self.city_config)
                self.platform_retries[platform_name] = 0
                logger.info("Initialized %s platform", platform_name)

            except Exception as e:
                logger.error("Failed to initialize %s: %s", platform_name, str(e))

    def _validate_platform_config(self, platform: str, config: Dict) -> bool:
        """Validate platform-specific configuration."""
        required_credentials = {
            'bluesky': ['handle', 'password'],
            'facebook': ['page_id', 'access_token'],
            'linkedin': ['client_id', 'client_secret', 'access_token'],
        }

        if platform not in required_credentials:
            logger.error("Unknown platform: %s", platform)
            return False

        credentials = config.get('credentials', {})
        if not credentials:
            logger.error("No credentials provided for %s", platform)
            return False

        missing = [cred for cred in required_credentials[platform] if not credentials.get(cred)]
        if missing:
            logger.error("Missing credentials for %s: %s", platform, ', '.join(missing))
            return False

        return True

    async def post_content(self, content: PostContent, post_type: str) -> Dict[str, PostResult]:
        """Post content to all enabled platforms."""
        results: Dict[str, PostResult] = {}
        tasks = []

        for platform_name, platform in self.platforms.items():
            can_post, reason = await self._can_post_to_platform(platform_name, post_type)
            if not can_post:
                results[platform_name] = PostResult(success=False, error=reason)
                continue

            tasks.append(self._post_to_platform_with_retry(platform_name, platform, content))

        if tasks:
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
            for platform_name, result in zip(self.platforms.keys(), completed_tasks):
                if isinstance(result, Exception):
                    results[platform_name] = PostResult(success=False, error=str(result))
                else:
                    results[platform_name] = result

        return results

    async def _post_to_platform_with_retry(
        self,
        platform_name: str,
        platform: SocialPlatform,
        content: PostContent
    ) -> PostResult:
        """Attempt to post to a platform with retries."""
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
                logger.error("Error posting to %s (attempt %d): %s",
                           platform_name, retries + 1, last_error)
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
        """Post content to a specific platform."""
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
                logger.info("Successfully posted to %s", platform_name)
                return PostResult(success=True)
            
            return PostResult(success=False, error="Platform post update failed")

        except Exception as e:
            logger.error("Error posting to %s: %s", platform_name, str(e), exc_info=True)
            raise

    async def _can_post_to_platform(
        self,
        platform_name: str,
        post_type: str
    ) -> Tuple[bool, Optional[str]]:
        """Check if posting is allowed for the platform and type."""
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

    async def post_weather(self, weather_data: 'WeatherData') -> Dict[str, PostResult]:
        """Post weather update."""
        hashtags = self.city_config.get('social', {}).get('hashtags', {}).get('weather', [])
        content = weather_data.format_for_social(hashtags)
        return await self.post_content(content, 'weather')

    async def post_weather_alert(self, alert: 'WeatherAlert') -> Dict[str, PostResult]:
        """Post weather alert."""
        hashtags = self.city_config.get('social', {}).get('hashtags', {}).get('weather', [])
        content = alert.format_for_social(hashtags)
        return await self.post_content(content, 'weather')

    async def post_earthquake(self, quake_data: Dict[str, Any]) -> Dict[str, PostResult]:
        """Post earthquake update."""
        hashtags = self.city_config.get('social', {}).get('hashtags', {}).get('earthquake', [])
        content = format_earthquake_for_social(quake_data, hashtags)
        return await self.post_content(content, 'earthquake')

    async def post_news(self, article: Any) -> Dict[str, PostResult]:
        """Post news article."""
        hashtags = self.city_config.get('social', {}).get('hashtags', {}).get('news', [])
        try:
            content = article.format_for_social(hashtags)
        except AttributeError:
            return await self.post_content(article, 'news')
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