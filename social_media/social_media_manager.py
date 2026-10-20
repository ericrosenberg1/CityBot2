import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from social_media.utils import ContentValidator, PostContent, RateLimiter

from .platforms.base import SocialPlatform
from .platforms.bluesky import BlueSkyPlatform
from .platforms.facebook import FacebookPlatform
from .platforms.instagram import InstagramPlatform
from .platforms.linkedin import LinkedInPlatform
from .platforms.nextdoor import NextdoorPlatform
from .platforms.reddit import RedditPlatform
from .platforms.threads import ThreadsPlatform
from .platforms.twitter import TwitterPlatform

logger = logging.getLogger("CityBot2.social.manager")

PLATFORM_CLASSES = {
    "bluesky": BlueSkyPlatform,
    "twitter": TwitterPlatform,
    "facebook": FacebookPlatform,
    "linkedin": LinkedInPlatform,
    "reddit": RedditPlatform,
    "threads": ThreadsPlatform,
    "instagram": InstagramPlatform,
    "nextdoor": NextdoorPlatform,
}


@dataclass
class PostResult:
    """Result of a social media post attempt."""

    success: bool
    error: str | None = None
    platform_response: dict[str, Any] | None = None
    # True when the post wasn't attempted (rate limited or post type off),
    # so the queue should hold the item rather than spend a retry on it.
    skipped: bool = False


class SocialMediaManager:
    """Manages posting to multiple social media platforms."""

    def __init__(self, config: dict[str, Any], city_config: dict[str, Any]):
        if "platforms" not in config:
            raise ValueError("Configuration must include 'platforms' section")
        for f in ("name", "state", "coordinates"):
            if f not in city_config:
                raise ValueError(f"Missing required city config field: {f}")

        self.config = config
        self.city_config = city_config
        self.platforms: dict[str, SocialPlatform] = {}
        self.rate_limiter = RateLimiter(config=config.get("rate_limits"))
        self.content_validator = ContentValidator()
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay", 5)

        self._initialize_platforms()

    def _initialize_platforms(self) -> None:
        """Initialize configured social media platforms.

        Each platform's base class validates its own credentials via
        CREDENTIAL_FIELDS, so no separate validation dict is needed here.
        """
        for name, cls in PLATFORM_CLASSES.items():
            platform_config = self.config["platforms"].get(name, {})
            if not platform_config.get("enabled", False):
                continue
            try:
                self.platforms[name] = cls(platform_config, self.city_config)
                logger.info("Initialized %s platform", name)
            except Exception:
                logger.exception("Failed to initialize %s", name)

    # ── posting pipeline ─────────────────────────────────────────────

    async def post_content(
        self, content: PostContent, post_type: str
    ) -> dict[str, PostResult]:
        """Post content to all enabled platforms."""
        results: dict[str, PostResult] = {}
        tasks = {}

        for name, platform in self.platforms.items():
            can, reason = await self._can_post(name, post_type)
            if not can:
                results[name] = PostResult(success=False, error=reason, skipped=True)
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
        """Retry a post that raised, with backoff. A platform that reports a
        clean failure isn't retried here: the post queue retries it later."""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._post_single(name, platform, content, post_type)
            except Exception as e:
                last_error = str(e)
                logger.exception("Error posting to %s (attempt %d)", name, attempt)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2 ** (attempt - 1)))
        return PostResult(
            success=False, error=f"Max retries exceeded. Last error: {last_error}"
        )

    async def _post_single(self, name, platform, content, post_type) -> PostResult:
        formatted = platform.format_post(content)
        errors = self.content_validator.validate_content(formatted, name)
        if errors:
            return PostResult(
                success=False, error=f"Validation failed: {', '.join(errors)}"
            )

        success = await platform.post_update(formatted)
        if success:
            await self.rate_limiter.record_post(name, post_type, content.text[:100])
            logger.info("Successfully posted to %s", name)
            return PostResult(success=True)
        return PostResult(success=False, error="Platform post update failed")

    async def _can_post(self, name: str, post_type: str) -> tuple[bool, str | None]:
        cfg = self.config["platforms"].get(name, {})
        if not cfg.get("enabled", False):
            return False, "Platform not enabled"
        if post_type not in cfg.get("post_types", []):
            return False, f"Post type '{post_type}' not enabled"
        if not await self.rate_limiter.can_post(name, post_type):
            return False, "Rate limit exceeded"
        return True, None

    async def close(self) -> None:
        close_tasks = [
            p.close() for p in self.platforms.values() if hasattr(p, "close")
        ]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        await self.rate_limiter.close()
        logger.info("Social media manager shutdown complete")
