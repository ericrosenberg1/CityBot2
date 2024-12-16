import logging
from typing import Dict, Any, List
import asyncio
from .platforms.base import PostContent, MediaContent
from .platforms.bluesky import BlueSkyPlatform
from .platforms.twitter import TwitterPlatform
from .platforms.facebook import FacebookPlatform
from .platforms.linkedin import LinkedInPlatform
from .platforms.reddit import RedditPlatform
from .utils.rate_limiter import RateLimiter
from .utils.content_validator import ContentValidator
from .utils.image_generator import WeatherMapGenerator
from .utils.map_generator import MapGenerator

logger = logging.getLogger('CityBot2.social.manager')

class SocialMediaManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.platforms = {}
        self.rate_limiter = RateLimiter()
        self.content_validator = ContentValidator()
        self.initialize_platforms()

    def initialize_platforms(self):
        """Initialize all enabled social media platforms."""
        platform_classes = {
            'bluesky': BlueSkyPlatform,
            'twitter': TwitterPlatform,
            'facebook': FacebookPlatform,
            'linkedin': LinkedInPlatform,
            'reddit': RedditPlatform
        }

        for platform_name, platform_config in self.config['platforms'].items():
            if platform_config.get('enabled', False):
                try:
                    platform_class = platform_classes.get(platform_name)
                    if platform_class:
                        self.platforms[platform_name] = platform_class(platform_config)
                        logger.info(f"Initialized {platform_name} platform")
                except Exception as e:
                    logger.error(f"Failed to initialize {platform_name} platform: {str(e)}")

    async def post_content(self, content: PostContent, post_type: str) -> Dict[str, bool]:
        """Post content to all enabled and appropriate platforms."""
        results = {}
        tasks = []

        for platform_name, platform in self.platforms.items():
            platform_config = self.config['platforms'][platform_name]
            
            # Check if this post type is enabled for this platform
            if post_type in platform_config.get('post_types', []):
                # Validate content for platform
                errors = self.content_validator.validate_content(content, platform_name)
                if errors:
                    logger.warning(f"Content validation failed for {platform_name}: {errors}")
                    results[platform_name] = False
                    continue

                # Check rate limits
                if self.rate_limiter.can_post(platform_name, post_type):
                    tasks.append(self._post_to_platform(platform_name, platform, content))
                else:
                    logger.info(f"Rate limit reached for {platform_name} - {post_type}")
                    results[platform_name] = False

        # Wait for all posts to complete
        if tasks:
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
            results.update({platform: result for platform, result in zip(self.platforms.keys(), completed_tasks)})

        return results

    async def _post_to_platform(self, platform_name: str, platform: Any, content: PostContent) -> bool:
        """Post to a specific platform with error handling and rate limit recording."""
        try:
            success = await platform.post_update(content)
            if success:
                self.rate_limiter.record_post(platform_name, content)
                logger.info(f"Successfully posted to {platform_name}")
            return success
        except Exception as e:
            logger.error(f"Error posting to {platform_name}: {str(e)}")
            return False

    def _format_weather_text(self, weather_data: Dict[str, Any]) -> str:
        """Format weather update text."""
        return (
            f"Weather Update for {self.config.get('city_name', 'City')}\n\n"
            f"🌡️ Temperature: {weather_data['temperature']:.1f}°F\n"
            f"💨 Wind: {weather_data['wind_speed']:.1f}mph {weather_data['wind_direction']}\n"
            f"☁️ Cloud Cover: {weather_data['cloud_cover']}%\n\n"
            f"Forecast: {weather_data['forecast']}\n\n"
            f"#{self.config.get('city_hashtag', 'City')}Weather #Weather"
        )

    def _format_earthquake_text(self, quake_data: Dict[str, Any]) -> str:
        """Format earthquake update text."""
        magnitude_emoji = "🔴" if quake_data['magnitude'] >= 5.0 else "🟡" if quake_data['magnitude'] >= 4.0 else "🟢"
        
        return (
            f"{magnitude_emoji} EARTHQUAKE REPORT {magnitude_emoji}\n\n"
            f"Magnitude: {quake_data['magnitude']}\n"
            f"Location: {quake_data['location']}\n"
            f"Depth: {quake_data['depth']:.1f} km\n"
            f"Distance from {self.config.get('city_name', 'City')}: {quake_data['distance']:.1f} miles\n\n"
            f"#Earthquake #{self.config.get('city_hashtag', 'City')} #Earthquake"
        )

    def _format_news_text(self, article_data: Dict[str, Any]) -> str:
        """Format news update text."""
        return (
            f"📰 {article_data['title']}\n\n"
            f"{article_data['content_snippet']}\n\n"
            f"Source: {article_data['source']}\n"
            f"{article_data['url']}\n\n"
            f"#{self.config.get('city_hashtag', 'City')}News #News"
        )

    async def post_weather(self, weather_data: Dict[str, Any]) -> Dict[str, bool]:
        """Post weather update to appropriate platforms."""
        content = PostContent(
            text=self._format_weather_text(weather_data),
            media=MediaContent(
                image_path=weather_data.get('map_path'),
                meta_title=f"{self.config.get('city_name', 'City')} Weather Update",
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
                meta_title=f"M{quake_data['magnitude']} Earthquake near {self.config.get('city_name', 'City')}",
                meta_description=f"Earthquake detected {quake_data['distance']:.1f} miles from {self.config.get('city_name', 'City')}"
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