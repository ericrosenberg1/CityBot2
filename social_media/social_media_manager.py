import logging
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
import asyncio

from .platforms.base import SocialPlatform
from .platforms.twitter import TwitterPlatform
from .platforms.bluesky import BlueSkyPlatform
from .platforms.facebook import FacebookPlatform
from .platforms.linkedin import LinkedInPlatform
from .platforms.reddit import RedditPlatform
from .platforms.threads import ThreadsPlatform
from .platforms.instagram import InstagramPlatform
from .platforms.nextdoor import NextdoorPlatform
from social_media.utils import RateLimiter, ContentValidator, PostContent
from social_media.formatters import (
    format_weather_for_social,
    format_weather_alert_for_social,
    format_earthquake_for_social,
    format_news_for_social,
    format_announcement_for_social,
)

if TYPE_CHECKING:
    from monitors.weather import WeatherData, WeatherAlert

logger = logging.getLogger('CityBot2.social.manager')

PLATFORM_CLASSES = {
    'bluesky': BlueSkyPlatform,
    'twitter': TwitterPlatform,
    'facebook': FacebookPlatform,
    'linkedin': LinkedInPlatform,
    'reddit': RedditPlatform,
    'threads': ThreadsPlatform,
    'instagram': InstagramPlatform,
    'nextdoor': NextdoorPlatform,
}


@dataclass
class PostResult:
    """Result of a social media post attempt."""
    success: bool
    error: Optional[str] = None
    platform_response: Optional[Dict[str, Any]] = None


class SocialMediaManager:
    """Manages posting to multiple social media platforms."""

    def __init__(self, config: Dict[str, Any], city_config: Dict[str, Any]):
        if 'platforms' not in config:
            raise ValueError("Configuration must include 'platforms' section")
        for f in ('name', 'state', 'coordinates'):
            if f not in city_config:
                raise ValueError(f"Missing required city config field: {f}")

        self.config = config
        self.city_config = city_config
        self.platforms: Dict[str, SocialPlatform] = {}
        self.rate_limiter = RateLimiter(config=config.get('rate_limits'))
        self.content_validator = ContentValidator()
        self.platform_retries: Dict[str, int] = {}
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 60)

        self._initialize_platforms()

    def _initialize_platforms(self) -> None:
        """Initialize configured social media platforms.

        Each platform's base class validates its own credentials via
        CREDENTIAL_MAP — no separate validation dict needed here.
        """
        for name, cls in PLATFORM_CLASSES.items():
            platform_config = self.config['platforms'].get(name, {})
            if not platform_config.get('enabled', False):
                continue
            try:
                self.platforms[name] = cls(platform_config, self.city_config)
                self.platform_retries[name] = 0
                logger.info("Initialized %s platform", name)
            except Exception as e:
                logger.error("Failed to initialize %s: %s", name, str(e))

    # ── posting pipeline ─────────────────────────────────────────────

    async def post_content(self, content: PostContent, post_type: str) -> Dict[str, PostResult]:
        """Post content to all enabled platforms."""
        results: Dict[str, PostResult] = {}
        tasks = {}

        for name, platform in self.platforms.items():
            can, reason = await self._can_post(name, post_type)
            if not can:
                results[name] = PostResult(success=False, error=reason)
                continue
            tasks[name] = self._post_with_retry(name, platform, content, post_type)

        if tasks:
            completed = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for name, result in zip(tasks.keys(), completed):
                if isinstance(result, Exception):
                    results[name] = PostResult(success=False, error=str(result))
                else:
                    results[name] = result
        return results

    async def _post_with_retry(self, name, platform, content, post_type) -> PostResult:
        retries = 0
        last_error = None
        while retries < self.max_retries:
            try:
                result = await self._post_single(name, platform, content, post_type)
                if result.success:
                    self.platform_retries[name] = 0
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.error("Error posting to %s (attempt %d): %s", name, retries + 1, last_error)
                retries += 1
                self.platform_retries[name] += 1
                if retries < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2 ** retries))
                continue
            break
        return PostResult(success=False, error=f"Max retries exceeded. Last error: {last_error}")

    async def _post_single(self, name, platform, content, post_type) -> PostResult:
        formatted = platform.format_post(content)
        errors = self.content_validator.validate_content(formatted, name)
        if errors:
            return PostResult(success=False, error=f"Validation failed: {', '.join(errors)}")

        success = await platform.post_update(formatted)
        if success:
            await self.rate_limiter.record_post(name, post_type, content.text[:100])
            logger.info("Successfully posted to %s", name)
            return PostResult(success=True)
        return PostResult(success=False, error="Platform post update failed")

    async def _can_post(self, name: str, post_type: str) -> Tuple[bool, Optional[str]]:
        cfg = self.config['platforms'].get(name, {})
        if not cfg.get('enabled', False):
            return False, "Platform not enabled"
        if post_type not in cfg.get('post_types', []):
            return False, f"Post type '{post_type}' not enabled"
        if not await self.rate_limiter.can_post(name, post_type):
            return False, "Rate limit exceeded"
        if self.platform_retries.get(name, 0) >= self.max_retries:
            return False, "Maximum retry attempts exceeded"
        return True, None

    # ── convenience posting methods ──────────────────────────────────

    def _hashtags(self, category: str) -> List[str]:
        return self.city_config.get('social', {}).get('hashtags', {}).get(category, [])

    async def post_weather(self, weather_data: 'WeatherData') -> Dict[str, PostResult]:
        content = format_weather_for_social(weather_data, self._hashtags('weather'))
        return await self.post_content(content, 'weather')

    async def post_weather_alert(self, alert: 'WeatherAlert') -> Dict[str, PostResult]:
        content = format_weather_alert_for_social(alert, self._hashtags('weather'))
        return await self.post_content(content, 'weather')

    async def post_earthquake(self, quake_data: Dict[str, Any]) -> Dict[str, PostResult]:
        content = format_earthquake_for_social(quake_data, self._hashtags('earthquake'))
        return await self.post_content(content, 'earthquake')

    async def post_news(self, article: Any) -> Dict[str, PostResult]:
        content = format_news_for_social(article, self._hashtags('news'))
        return await self.post_content(content, 'news')

    async def post_announcement(self, announcement: Dict[str, Any]) -> Dict[str, PostResult]:
        content = format_announcement_for_social(announcement, self._hashtags('news'))
        return await self.post_content(content, 'announcement')

    async def close(self) -> None:
        close_tasks = [p.close() for p in self.platforms.values() if hasattr(p, 'close')]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        await self.rate_limiter.close()
        logger.info("Social media manager shutdown complete")
