"""Utility classes and functions for CityBot2, including rate limiting, content validation, and caching."""

import logging
import os
import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from urllib.parse import urlparse
from pathlib import Path

import aiosqlite
from PIL import Image
import folium

logger = logging.getLogger('CityBot2.utils')

@dataclass
class MediaContent:
    """Media content for social media posts."""
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    link_url: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None

@dataclass
class PostContent:
    """Content for social media posts."""
    text: str
    media: Optional[MediaContent] = None
    platform_specific: Optional[Dict[str, Any]] = None

class RateLimiter:
    """Rate limiter with async support."""

    def __init__(self, db_path: str = "data/rate_limits.db", config: Optional[Dict[str, Any]] = None):
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
            conn.execute('''
                CREATE TABLE IF NOT EXISTS post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    post_type TEXT NOT NULL,
                    content_preview TEXT,
                    timestamp DATETIME NOT NULL
                )
            ''')
            conn.execute('DROP INDEX IF EXISTS idx_platform_type_timestamp')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_platform_type_timestamp
                ON post_history(platform, post_type, timestamp)
            ''')

    def _get_limits(self, platform: str) -> Dict[str, int]:
        """Get rate limits for platform."""
        default_limits = {'hourly': 10, 'daily': 24, 'interval': 300}

        if platform in self.config.get('rate_limits', {}):
            return self.config['rate_limits'][platform]

        platform_defaults = {
            'twitter': {'hourly': 10, 'daily': 24, 'interval': 300},
            'bluesky': {'hourly': 10, 'daily': 24, 'interval': 300},
            'facebook': {'hourly': 10, 'daily': 24, 'interval': 300},
            'linkedin': {'hourly': 10, 'daily': 24, 'interval': 300},
        }

        return platform_defaults.get(platform, default_limits)

    async def can_post(self, platform: str, post_type: str) -> bool:
        """Check if posting is allowed based on rate limits."""
        async with self.lock:
            now = datetime.now()
            limits = self._get_limits(platform)
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    # Check minimum interval
                    query = '''
                        SELECT timestamp FROM post_history
                        WHERE platform = ? AND post_type = ?
                        ORDER BY timestamp DESC LIMIT 1
                    '''
                    async with db.execute(query, (platform, post_type)) as cursor:
                        last_post = await cursor.fetchone()
                        if last_post:
                            last_time = datetime.fromisoformat(last_post[0])
                            if (now - last_time).total_seconds() < limits['interval']:
                                return False

                    # Check hourly limit
                    query = '''
                        SELECT COUNT(*) FROM post_history
                        WHERE platform = ? AND post_type = ?
                        AND timestamp > ?
                    '''
                    hour_ago = (now - timedelta(hours=1)).isoformat()
                    async with db.execute(query, (platform, post_type, hour_ago)) as cursor:
                        hourly_count = (await cursor.fetchone())[0]
                        if hourly_count >= limits['hourly']:
                            return False

                    # Check daily limit
                    query = '''
                        SELECT COUNT(*) FROM post_history
                        WHERE platform = ? AND post_type = ?
                        AND timestamp > ?
                    '''
                    day_ago = (now - timedelta(days=1)).isoformat()
                    async with db.execute(query, (platform, post_type, day_ago)) as cursor:
                        daily_count = (await cursor.fetchone())[0]
                        return daily_count < limits['daily']

            except (sqlite3.Error, ValueError, OSError) as exc:
                logger.error("Error checking rate limits: %s", exc, exc_info=True)
                return False
            except Exception as exc:
                logger.error("Error checking rate limits: %s", exc, exc_info=True)
                return False

    async def record_post(self, platform: str, content_preview: str) -> None:
        """Record a successful post."""
        async with self.lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    query = '''
                        INSERT INTO post_history (platform, post_type, content_preview, timestamp)
                        VALUES (?, ?, ?, ?)
                    '''
                    await db.execute(query, (platform, 'post', content_preview[:100],
                                             datetime.now().isoformat()))
                    await db.commit()
            except (sqlite3.Error, OSError, ValueError) as exc:
                logger.error("Error recording post: %s", exc, exc_info=True)
            except Exception as exc:
                logger.error("Error recording post: %s", exc, exc_info=True)

    async def cleanup_old_records(self, days: int = 7) -> None:
        """Clean up records older than specified days."""
        async with self.lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    query = '''
                        DELETE FROM post_history
                        WHERE timestamp < ?
                    '''
                    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                    await db.execute(query, (cutoff,))
                    await db.commit()
            except (sqlite3.Error, OSError, ValueError) as exc:
                logger.error("Error cleaning up records: %s", exc, exc_info=True)
            except Exception as exc:
                logger.error("Error cleaning up records: %s", exc, exc_info=True)

    async def close(self) -> None:
        """Close any open resources."""
        pass


class ContentValidator:
    """Validates content for different platforms."""

    def __init__(self):
        self.platform_limits = {
            'bluesky': {'text': 300, 'images': 4},
            'twitter': {'text': 280, 'images': 4},
            'facebook': {'text': 63206, 'images': 10},
            'linkedin': {'text': 3000, 'images': 9},
        }

        self.image_requirements = {
            'twitter': {
                'max_size': 5 * 1024 * 1024,
                'min_dimensions': (200, 200),
                'max_dimensions': (4096, 4096),
                'allowed_formats': {'JPEG', 'PNG', 'GIF'}
            },
            'facebook': {
                'max_size': 4 * 1024 * 1024,
                'min_dimensions': (200, 200),
                'max_dimensions': (8192, 8192),
                'allowed_formats': {'JPEG', 'PNG'}
            },
            'linkedin': {
                'max_size': 5 * 1024 * 1024,
                'min_dimensions': (200, 200),
                'max_dimensions': (4096, 4096),
                'allowed_formats': {'JPEG', 'PNG'}
            },
            'bluesky': {
                'max_size': 1024 * 1024,
                'min_dimensions': (200, 200),
                'max_dimensions': (2048, 2048),
                'allowed_formats': {'JPEG', 'PNG'}
            },
        }

    def validate_content(self, content: PostContent, platform: str) -> List[str]:
        errors = []

        if not content.text or not content.text.strip():
            errors.append("Text content cannot be empty")
            return errors

        limits = self.platform_limits.get(platform, {})
        if len(content.text) > limits.get('text', float('inf')):
            errors.append(f"Text exceeds {platform} limit of {limits['text']} characters")

        if content.media:
            errors.extend(self._validate_media(content.media, platform))

        return errors

    def _validate_media(self, media: MediaContent, platform: str) -> List[str]:
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
                    errors.append(f"No image requirements defined for platform: {platform}")
                    return errors

                with Image.open(media.image_path) as img:
                    file_size = os.path.getsize(media.image_path)
                    max_size_mb = platform_reqs['max_size'] / (1024 * 1024)
                    current_size_mb = file_size / (1024 * 1024)
                    if file_size > platform_reqs['max_size']:
                        errors.append(
                            "Image size (%.1fMB) exceeds platform limit of %.1fMB"
                            % (current_size_mb, max_size_mb)
                        )

                    width, height = img.size
                    min_w, min_h = platform_reqs['min_dimensions']
                    max_w, max_h = platform_reqs['max_dimensions']

                    if width < min_w or height < min_h:
                        errors.append(
                            "Image dimensions (%dx%d) below minimum requirement of %dx%d"
                            % (width, height, min_w, min_h)
                        )
                    elif width > max_w or height > max_h:
                        errors.append(
                            "Image dimensions (%dx%d) exceed maximum allowed %dx%d"
                            % (width, height, max_w, max_h)
                        )

                    if img.format not in platform_reqs['allowed_formats']:
                        allowed = ', '.join(platform_reqs['allowed_formats'])
                        errors.append(
                            "Image format %s not supported. Allowed: %s" % (img.format, allowed)
                        )

            except (OSError, ValueError) as exc:
                errors.append("Error validating image %s: %s" % (media.image_path, exc))
                logger.exception("Image validation error")
            except Exception as exc:
                errors.append("Error validating image %s: %s" % (media.image_path, exc))
                logger.exception("Image validation error")

        if media.video_path and not os.path.exists(media.video_path):
            errors.append("Video file not found: %s" % media.video_path)

        if media.link_url and not self._validate_url(media.link_url):
            errors.append("Invalid URL format: %s" % media.link_url)

        return errors

    def _validate_url(self, url: str) -> bool:
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except ValueError:
            return False


class AsyncCache:
    """Async-compatible cache for temporary data storage."""
    # ... Unchanged ...


class MapGenerator:
    """Generates various maps (if needed for weather/news)."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cache_dir = Path("cache/maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def generate_news_map(self, location_data: Dict[str, Any]) -> Optional[str]:
        """Generate map for news location."""
        try:
            return await asyncio.to_thread(self._create_news_map, location_data)
        except (OSError, ValueError) as exc:
            logger.error("Error generating news map: %s", exc, exc_info=True)
            return None
        except Exception as exc:
            logger.error("Error generating news map: %s", exc, exc_info=True)
            return None

    def _create_news_map(self, location_data: Dict[str, Any]) -> str:
        """Create news map (runs in thread pool)."""
        m = folium.Map(
            location=[self.config['coordinates']['latitude'], self.config['coordinates']['longitude']],
            zoom_start=12
        )

        try:
            folium.Marker(
                [location_data['latitude'], location_data['longitude']],
                popup=location_data.get('description', 'News Location'),
                icon=folium.Icon(color='red')
            ).add_to(m)

            folium.Marker(
                [self.config['coordinates']['latitude'], self.config['coordinates']['longitude']],
                popup=self.config.get('city', 'City Center'),
                icon=folium.Icon(color='blue')
            ).add_to(m)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            html_path = str(self.cache_dir / f"news_map_{timestamp}.html")
            image_path = html_path.replace('.html', '.png')

            m.save(html_path)
            cmd = 'cutycapt --url=file://%s --out=%s' % (html_path, image_path)
            os.system(cmd)

            if os.path.exists(html_path):
                os.unlink(html_path)

            return image_path

        except (OSError, ValueError) as exc:
            logger.error("Error creating news map: %s", exc, exc_info=True)
            if os.path.exists(html_path):
                os.unlink(html_path)
            raise
        except Exception as exc:
            logger.error("Error creating news map: %s", exc, exc_info=True)
            if os.path.exists(html_path):
                os.unlink(html_path)
            raise
