import logging
from typing import Dict, Any, List, Type, Optional
from dataclasses import dataclass, field
import asyncio

from .platforms.base import SocialPlatform, PostContent, MediaContent
from .platforms.bluesky import BlueSkyPlatform
from .platforms.twitter import TwitterPlatform
from .platforms.facebook import FacebookPlatform
from .platforms.linkedin import LinkedInPlatform
from .platforms.reddit import RedditPlatform
from .utils.rate_limiter import RateLimiter
from .utils.content_validator import ContentValidator

logger = logging.getLogger('CityBot2.social.manager')

@dataclass
class PlatformConfig:
    enabled: bool = False
    post_types: List[str] = field(default_factory=list)
    credentials: Dict[str, str] = field(default_factory=dict)

class SocialMediaManager:
    def __init__(self, config: Dict[str, Any], city_config: Dict[str, Any]):
        """Initialize the social media manager.
        
        Args:
            config: Dictionary containing platform configurations
            city_config: Dictionary containing city-specific settings
        """
        self.config = config
        self.city_config = city_config
        self.platforms: Dict[str, SocialPlatform] = {}
        self.rate_limiter = RateLimiter()
        self.content_validator = ContentValidator()
        
        # Initialize hashtags
        self.hashtags = {
            'weather': [
                f"{city_config['name']}Weather",
                f"{city_config['name']}CA",
                "CaWeather"
            ],
            'earthquake': [
                "Earthquake",
                f"{city_config['name']}CA",
                "CaliforniaEarthquake"
            ],
            'news': [
                city_config['name'],
                f"{city_config['name']}CA",
                "LocalNews"
            ]
        }
        
        self.initialize_platforms()

    def initialize_platforms(self) -> None:
        """Initialize all enabled social media platforms."""
        platform_classes = {
            'bluesky': BlueSkyPlatform,
            'twitter': TwitterPlatform,
            'facebook': FacebookPlatform,
            'linkedin': LinkedInPlatform,
            'reddit': RedditPlatform
        }

        for platform_name, platform_class in platform_classes.items():
            platform_config = self.config['platforms'].get(platform_name, {})
            if not platform_config.get('enabled', False):
                continue

            try:
                self.platforms[platform_name] = platform_class(platform_config)
                logger.info(f"Initialized {platform_name} platform")
            except Exception as e:
                logger.error(f"Failed to initialize {platform_name}: {str(e)}")

    async def post_content(self, content: PostContent, post_type: str) -> Dict[str, bool]:
        """Post content to all enabled and appropriate platforms.
        
        Args:
            content: The content to post
            post_type: Type of post (weather, earthquake, news)
            
        Returns:
            Dictionary mapping platform names to posting success status
        """
        results = {}
        tasks = []

        for platform_name, platform in self.platforms.items():
            if not self._can_post_to_platform(platform_name, post_type):
                continue

            tasks.append(self._post_to_platform(platform_name, platform, content))

        if tasks:
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
            results.update({
                platform: result if not isinstance(result, Exception) else False
                for platform, result in zip(self.platforms.keys(), completed_tasks)
            })

        return results

    async def _post_to_platform(self, platform_name: str, platform: SocialPlatform,
                              content: PostContent) -> bool:
        """Post to a specific platform with error handling."""
        try:
            # Validate content for platform
            formatted_content = platform.format_post(content)
            if not self.content_validator.validate_content(formatted_content, platform_name):
                logger.warning(f"Content validation failed for {platform_name}")
                return False

            # Post content
            success = await platform.post_update(formatted_content)
            if success:
                self.rate_limiter.record_post(platform_name, content)
                logger.info(f"Successfully posted to {platform_name}")
            return success

        except Exception as e:
            logger.error(f"Error posting to {platform_name}: {str(e)}")
            return False

    def _can_post_to_platform(self, platform_name: str, post_type: str) -> bool:
        """Check if posting is allowed for the platform and type."""
        platform_config = self.config['platforms'].get(platform_name, {})
        return (
            platform_config.get('enabled', False) and
            post_type in platform_config.get('post_types', []) and
            self.rate_limiter.can_post(platform_name, post_type)
        )

    def _format_weather_text(self, weather_data: Dict[str, Any]) -> str:
        """Format weather update text."""
        hashtags = ' '.join([f"#{tag}" for tag in self.hashtags['weather']])
        return (
            f"Weather Update for {self.city_config['name']}, {self.city_config['state']}\n\n"
            f"🌡️ Temperature: {weather_data['temperature']:.1f}°F\n"
            f"💨 Wind: {weather_data['wind_speed']:.1f}mph {weather_data['wind_direction']}\n"
            f"☁️ Cloud Cover: {weather_data['cloud_cover']}%\n\n"
            f"Forecast: {weather_data['forecast']}\n\n"
            f"{hashtags}"
        )

    def _format_earthquake_text(self, quake_data: Dict[str, Any]) -> str:
        """Format earthquake update text."""
        magnitude_emoji = "🔴" if quake_data['magnitude'] >= 5.0 else "🟡" if quake_data['magnitude'] >= 4.0 else "🟢"
        hashtags = ' '.join([f"#{tag}" for tag in self.hashtags['earthquake']])
        
        return (
            f"{magnitude_emoji} EARTHQUAKE REPORT {magnitude_emoji}\n\n"
            f"Magnitude: {quake_data['magnitude']}\n"
            f"Location: {quake_data['location']}\n"
            f"Depth: {quake_data['depth']:.1f} km\n"
            f"Distance from {self.city_config['name']}: {quake_data['distance']:.1f} miles\n\n"
            f"{hashtags}"
        )

    def _format_news_text(self, article_data: Dict[str, Any]) -> str:
        """Format news update text."""
        hashtags = ' '.join([f"#{tag}" for tag in self.hashtags['news']])
        
        return (
            f"📰 {article_data['title']}\n\n"
            f"{article_data['content_snippet']}\n\n"
            f"Source: {article_data['source']}\n"
            f"{article_data['url']}\n\n"
            f"{hashtags}"
        )

    async def post_weather(self, weather_data: Dict[str, Any]) -> Dict[str, bool]:
        """Post weather update to appropriate platforms."""
        content = PostContent(
            text=self._format_weather_text(weather_data),
            media=MediaContent(
                image_path=weather_data.get('map_path'),
                meta_title=f"{self.city_config['name']}, {self.city_config['state']} Weather Update",
                meta_description=f"Current conditions: {weather_data['temperature']}°F, "
                               f"{weather_data['wind_speed']}mph winds"
            )
        )
        return await self.post_content(content, 'weather')

    async def post_earthquake(self, quake_data: Dict[str, Any]) -> Dict[str, bool]:
        """Post earthquake update to appropriate platforms."""
        content = PostContent(
            text=self._format_earthquake_text(quake_data),
            media=MediaContent(
                image_path=quake_data.get('map_path'),
                link_url=quake_data.get('url'),
                meta_title=f"M{quake_data['magnitude']} Earthquake near {self.city_config['name']}, {self.city_config['state']}",
                meta_description=f"Earthquake detected {quake_data['distance']:.1f} miles from {self.city_config['name']}"
            )
        )
        return await self.post_content(content, 'earthquake')

    async def post_news(self, article_data: Dict[str, Any]) -> Dict[str, bool]:
        """Post news update to appropriate platforms."""
        content = PostContent(
            text=self._format_news_text(article_data),
            media=MediaContent(
                image_path=article_data.get('map_path'),
                link_url=article_data['url'],
                meta_title=article_data['title'],
                meta_description=article_data['content_snippet'][:200]
            )
        )
        return await self.post_content(content, 'news')