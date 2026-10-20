"""Utility classes and functions for CityBot2, including rate limiting, content validation, and caching."""

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import urlparse

import aiosqlite
from PIL import Image

logger = logging.getLogger("CityBot2.utils")


@dataclass
class MediaContent:
    """Media content for social media posts."""

    image_path: str | None = None
    video_path: str | None = None
    link_url: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None


@dataclass
class PostContent:
    """Content for social media posts."""

    text: str
    media: MediaContent | None = None
    platform_specific: dict[str, Any] | None = None


class RateLimiter:
    """Rate limiter with async support."""

    def __init__(
        self, db_path: str = "data/rate_limits.db", config: dict[str, Any] | None = None
    ):
        self.db_path = db_path
        self.config = config or {}
        self.lock = asyncio.Lock()
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Initialize the rate limiting database."""
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    post_type TEXT NOT NULL,
                    content_preview TEXT,
                    timestamp DATETIME NOT NULL
                )
            """)
            conn.execute("DROP INDEX IF EXISTS idx_platform_type_timestamp")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_platform_type_timestamp
                ON post_history(platform, post_type, timestamp)
            """)

    DEFAULT_LIMITS: ClassVar[dict[str, int]] = {
        "hourly": 10,
        "daily": 24,
        "interval": 300,
    }

    def _get_limits(self, platform: str) -> dict[str, int]:
        """Get rate limits for platform: per-platform config over the defaults."""
        return {**self.DEFAULT_LIMITS, **self.config.get(platform, {})}

    async def can_post(self, platform: str, post_type: str) -> bool:
        """Check if posting is allowed based on rate limits."""
        async with self.lock:
            now = datetime.now()
            limits = self._get_limits(platform)
            hour_ago = (now - timedelta(hours=1)).isoformat()
            day_ago = (now - timedelta(days=1)).isoformat()
            # One query covers all three checks. The interval check only needs the
            # last day's posts, since any interval longer than that is never configured.
            query = """
                SELECT MAX(timestamp), COALESCE(SUM(timestamp > ?), 0), COUNT(*)
                FROM post_history
                WHERE platform = ? AND post_type = ? AND timestamp > ?
            """
            try:
                async with (
                    aiosqlite.connect(self.db_path) as db,
                    db.execute(
                        query, (hour_ago, platform, post_type, day_ago)
                    ) as cursor,
                ):
                    last_post, hourly_count, daily_count = await cursor.fetchone()
            except (sqlite3.Error, ValueError, OSError):
                logger.exception("Error checking rate limits")
                return False

            if (
                last_post
                and (now - datetime.fromisoformat(last_post)).total_seconds()
                < limits["interval"]
            ):
                return False
            return hourly_count < limits["hourly"] and daily_count < limits["daily"]

    async def record_post(
        self, platform: str, post_type: str, content_preview: str = ""
    ) -> None:
        """Record a successful post."""
        async with self.lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    query = """
                        INSERT INTO post_history (platform, post_type, content_preview, timestamp)
                        VALUES (?, ?, ?, ?)
                    """
                    await db.execute(
                        query,
                        (
                            platform,
                            post_type,
                            content_preview[:100],
                            datetime.now().isoformat(),
                        ),
                    )
                    await db.commit()
            except (sqlite3.Error, OSError, ValueError):
                logger.exception("Error recording post")

    async def cleanup_old_records(self, days: int = 7) -> None:
        """Clean up records older than specified days."""
        async with self.lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    query = """
                        DELETE FROM post_history
                        WHERE timestamp < ?
                    """
                    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                    await db.execute(query, (cutoff,))
                    await db.commit()
            except (sqlite3.Error, OSError, ValueError):
                logger.exception("Error cleaning up records")

    async def close(self) -> None:
        """Close any open resources."""


class ContentValidator:
    """Validates content for different platforms."""

    def __init__(self):
        self.platform_limits = {
            "bluesky": {"text": 300, "images": 4},
            "twitter": {"text": 280, "images": 4},
            "facebook": {"text": 63206, "images": 10},
            "linkedin": {"text": 3000, "images": 9},
            "reddit": {"text": 40000, "images": 1},
            "threads": {"text": 500, "images": 1},
            "instagram": {"text": 2200, "images": 1},
            "nextdoor": {"text": 10000, "images": 1},
        }

        self.image_requirements = {
            "twitter": {
                "max_size": 5 * 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (4096, 4096),
                "allowed_formats": {"JPEG", "PNG", "GIF"},
            },
            "facebook": {
                "max_size": 4 * 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (8192, 8192),
                "allowed_formats": {"JPEG", "PNG"},
            },
            "linkedin": {
                "max_size": 5 * 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (4096, 4096),
                "allowed_formats": {"JPEG", "PNG"},
            },
            "bluesky": {
                "max_size": 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (2048, 2048),
                "allowed_formats": {"JPEG", "PNG"},
            },
            "reddit": {
                "max_size": 20 * 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (4096, 4096),
                "allowed_formats": {"JPEG", "PNG", "GIF"},
            },
            "threads": {
                "max_size": 8 * 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (4096, 4096),
                "allowed_formats": {"JPEG", "PNG"},
            },
            "instagram": {
                "max_size": 8 * 1024 * 1024,
                "min_dimensions": (320, 320),
                "max_dimensions": (4096, 4096),
                "allowed_formats": {"JPEG", "PNG"},
            },
            "nextdoor": {
                "max_size": 10 * 1024 * 1024,
                "min_dimensions": (200, 200),
                "max_dimensions": (4096, 4096),
                "allowed_formats": {"JPEG", "PNG", "GIF"},
            },
        }

    def validate_content(self, content: PostContent, platform: str) -> list[str]:
        errors = []

        if not content.text or not content.text.strip():
            errors.append("Text content cannot be empty")
            return errors

        limits = self.platform_limits.get(platform, {})
        if len(content.text) > limits.get("text", float("inf")):
            errors.append(
                f"Text exceeds {platform} limit of {limits['text']} characters"
            )

        if content.media:
            errors.extend(self._validate_media(content.media, platform))

        return errors

    def _validate_media(self, media: MediaContent, platform: str) -> list[str]:
        errors = []

        if media.image_path:
            try:
                if not isinstance(media.image_path, (str, bytes, os.PathLike)):
                    errors.append(f"Invalid image path type: {type(media.image_path)}")
                    return errors

                if not os.path.exists(media.image_path):
                    errors.append(f"Image file not found: {media.image_path}")
                    return errors

                platform_reqs = self.image_requirements.get(platform)
                if not platform_reqs:
                    errors.append(
                        f"No image requirements defined for platform: {platform}"
                    )
                    return errors

                with Image.open(media.image_path) as img:
                    file_size = os.path.getsize(media.image_path)
                    max_size_mb = platform_reqs["max_size"] / (1024 * 1024)
                    current_size_mb = file_size / (1024 * 1024)
                    if file_size > platform_reqs["max_size"]:
                        errors.append(
                            f"Image size ({current_size_mb:.1f}MB) exceeds platform limit of {max_size_mb:.1f}MB"
                        )

                    width, height = img.size
                    min_w, min_h = platform_reqs["min_dimensions"]
                    max_w, max_h = platform_reqs["max_dimensions"]

                    if width < min_w or height < min_h:
                        errors.append(
                            f"Image dimensions ({width}x{height}) below minimum requirement of {min_w}x{min_h}"
                        )
                    elif width > max_w or height > max_h:
                        errors.append(
                            f"Image dimensions ({width}x{height}) exceed maximum allowed {max_w}x{max_h}"
                        )

                    if img.format not in platform_reqs["allowed_formats"]:
                        allowed = ", ".join(platform_reqs["allowed_formats"])
                        errors.append(
                            f"Image format {img.format} not supported. Allowed: {allowed}"
                        )

            except Exception as exc:
                errors.append(f"Error validating image {media.image_path}: {exc}")
                logger.exception("Image validation error")

        if media.video_path and not os.path.exists(media.video_path):
            errors.append(f"Video file not found: {media.video_path}")

        if media.link_url and not self._validate_url(media.link_url):
            errors.append(f"Invalid URL format: {media.link_url}")

        return errors

    def _validate_url(self, url: str) -> bool:
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in [
                "http",
                "https",
            ]
        except ValueError:
            return False


class AsyncCache:
    """Async-compatible cache for temporary data storage."""
