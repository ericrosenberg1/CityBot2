"""Utility classes and functions for CityBot2, including rate limiting, content validation, map generation, and caching."""

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
import matplotlib
matplotlib.use('Agg')  # Set non-interactive backend before other imports
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
            # pylint: disable=broad-exception-caught
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
            # pylint: disable=broad-exception-caught
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
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error cleaning up records: %s", exc, exc_info=True)

    async def close(self) -> None:
        """Close any open resources."""
        # No resources to explicitly close; aiosqlite closes connections automatically
        # pylint: disable=unnecessary-pass
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
        """Validate content for platform-specific requirements."""
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
        """Validate media content."""
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
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                errors.append("Error validating image %s: %s" % (media.image_path, exc))
                logger.exception("Image validation error")

        if media.video_path and not os.path.exists(media.video_path):
            errors.append("Video file not found: %s" % media.video_path)

        if media.link_url and not self._validate_url(media.link_url):
            errors.append("Invalid URL format: %s" % media.link_url)

        return errors

    def _validate_url(self, url: str) -> bool:
        """Validate URL format."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except ValueError:
            return False


class MapGenerator:
    """Generates various maps."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cache_dir = Path("cache/maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def generate_earthquake_map(self, quake_data: Dict[str, Any]) -> Optional[str]:
        """Generate earthquake location map."""
        try:
            return await asyncio.to_thread(self._create_earthquake_map, quake_data)
        except (OSError, ValueError) as exc:
            logger.error("Error generating earthquake map: %s", exc, exc_info=True)
            return None
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error generating earthquake map: %s", exc, exc_info=True)
            return None

    def _create_earthquake_map(self, quake_data: Dict[str, Any]) -> str:
        """Create earthquake map (runs in thread pool)."""
        center_lat = (self.config['coordinates']['latitude'] + float(quake_data['latitude'])) / 2
        center_lon = (self.config['coordinates']['longitude'] + float(quake_data['longitude'])) / 2

        zoom = self._calculate_zoom(quake_data['distance'])
        m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom)

        try:
            folium.Marker(
                [self.config['coordinates']['latitude'],
                 self.config['coordinates']['longitude']],
                popup=self.config.get('city', 'City'),
                icon=folium.Icon(color='blue')
            ).add_to(m)

            folium.Marker(
                [quake_data['latitude'], quake_data['longitude']],
                popup="M%s Earthquake<br>%s" % (
                    quake_data['magnitude'], quake_data['location']
                ),
                icon=folium.Icon(color='red')
            ).add_to(m)

            folium.PolyLine(
                locations=[
                    [self.config['coordinates']['latitude'],
                     self.config['coordinates']['longitude']],
                    [quake_data['latitude'], quake_data['longitude']]
                ],
                weight=2,
                color='red'
            ).add_to(m)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            html_path = self.cache_dir / f"earthquake_map_{timestamp}.html"
            image_path = str(html_path).replace('.html', '.png')

            m.save(str(html_path))
            # Using % formatting instead of f-strings for logging
            cmd = 'cutycapt --url=file://%s --out=%s' % (html_path, image_path)
            os.system(cmd)

            if os.path.exists(html_path):
                os.unlink(html_path)

            return image_path

        except (OSError, ValueError) as exc:
            logger.error("Error creating earthquake map: %s", exc, exc_info=True)
            if 'html_path' in locals() and html_path and os.path.exists(html_path):
                os.unlink(html_path)
            raise
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error creating earthquake map: %s", exc, exc_info=True)
            if 'html_path' in locals() and html_path and os.path.exists(html_path):
                os.unlink(html_path)
            raise

    def _calculate_zoom(self, distance: float) -> int:
        """Calculate appropriate zoom level based on distance."""
        if distance <= 25:
            return 10
        if distance <= 50:
            return 9
        if distance <= 100:
            return 8
        return 7

    async def generate_news_map(self, location_data: Dict[str, Any]) -> Optional[str]:
        """Generate map for news location."""
        try:
            return await asyncio.to_thread(self._create_news_map, location_data)
        except (OSError, ValueError) as exc:
            logger.error("Error generating news map: %s", exc, exc_info=True)
            return None
        # pylint: disable=broad-exception-caught
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
            html_path = self.cache_dir / f"news_map_{timestamp}.html"
            image_path = str(html_path).replace('.html', '.png')

            m.save(str(html_path))
            cmd = 'cutycapt --url=file://%s --out=%s' % (html_path, image_path)
            os.system(cmd)

            if os.path.exists(html_path):
                os.unlink(html_path)

            return image_path

        except (OSError, ValueError) as exc:
            logger.error("Error creating news map: %s", exc, exc_info=True)
            if 'html_path' in locals() and html_path and os.path.exists(html_path):
                os.unlink(html_path)
            raise
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error creating news map: %s", exc, exc_info=True)
            if 'html_path' in locals() and html_path and os.path.exists(html_path):
                os.unlink(html_path)
            raise

    async def cleanup_old_maps(self, days: int = 7) -> None:
        """Clean up old map files."""
        try:
            cutoff = datetime.now() - timedelta(days=days)
            await asyncio.to_thread(self._cleanup_files, cutoff)
        except (OSError, ValueError) as exc:
            logger.error("Error cleaning up maps: %s", exc, exc_info=True)
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error cleaning up maps: %s", exc, exc_info=True)

    def _cleanup_files(self, cutoff: datetime) -> None:
        """Clean up old files (runs in thread pool)."""
        for file_path in self.cache_dir.glob('*'):
            try:
                if datetime.fromtimestamp(file_path.stat().st_mtime) < cutoff:
                    file_path.unlink()
            except (OSError, ValueError) as exc:
                logger.error("Error deleting file %s: %s", file_path, exc, exc_info=True)
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error deleting file %s: %s", file_path, exc, exc_info=True)


class AsyncCache:
    """Async-compatible cache for temporary data storage."""

    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()

    async def set(self, key: str, value: Any, expiry: int = 3600) -> None:
        """Set cache value with expiry in seconds."""
        async with self.lock:
            try:
                cache_file = self.cache_dir / f"{key}.cache"
                data = {
                    'value': value,
                    'expires': (datetime.now() + timedelta(seconds=expiry)).isoformat()
                }
                await asyncio.to_thread(self._write_cache, cache_file, data)
            except (OSError, ValueError) as exc:
                logger.error("Error setting cache for %s: %s", key, exc, exc_info=True)
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error setting cache for %s: %s", key, exc, exc_info=True)

    async def get(self, key: str) -> Optional[Any]:
        """Get cache value if not expired."""
        async with self.lock:
            try:
                cache_file = self.cache_dir / f"{key}.cache"
                if not cache_file.exists():
                    return None

                data = await asyncio.to_thread(self._read_cache, cache_file)
                if not data:
                    return None

                expires = datetime.fromisoformat(data['expires'])
                if datetime.now() > expires:
                    await asyncio.to_thread(cache_file.unlink)
                    return None

                return data['value']
            except (OSError, ValueError) as exc:
                logger.error("Error reading cache for %s: %s", key, exc, exc_info=True)
                return None
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error reading cache for %s: %s", key, exc, exc_info=True)
                return None

    def _write_cache(self, cache_file: Path, data: Dict[str, Any]) -> None:
        """Write cache file (runs in thread pool)."""
        try:
            with cache_file.open('w', encoding='utf-8') as f:
                json.dump(data, f)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Error writing cache file %s: %s", cache_file, exc, exc_info=True)
            raise
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error writing cache file %s: %s", cache_file, exc, exc_info=True)
            raise

    def _read_cache(self, cache_file: Path) -> Optional[Dict[str, Any]]:
        """Read cache file (runs in thread pool)."""
        try:
            with cache_file.open('r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Error reading cache file %s: %s", cache_file, exc, exc_info=True)
            return None
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error reading cache file %s: %s", cache_file, exc, exc_info=True)
            return None

    async def cleanup(self, max_age_days: int = 7) -> None:
        """Clean up expired cache files."""
        async with self.lock:
            try:
                cutoff = datetime.now() - timedelta(days=max_age_days)
                await asyncio.to_thread(self._cleanup_files, cutoff)
            except (OSError, ValueError) as exc:
                logger.error("Error cleaning up cache: %s", exc, exc_info=True)
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error cleaning up cache: %s", exc, exc_info=True)

    def _cleanup_files(self, cutoff: datetime) -> None:
        """Clean up old cache files (runs in thread pool)."""
        for cache_file in self.cache_dir.glob('*.cache'):
            try:
                if datetime.fromtimestamp(cache_file.stat().st_mtime) < cutoff:
                    cache_file.unlink()
            except (OSError, ValueError) as exc:
                logger.error("Error deleting cache file %s: %s", cache_file, exc, exc_info=True)
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error deleting cache file %s: %s", cache_file, exc, exc_info=True)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/citybot.log'),
        logging.StreamHandler()
    ]
)
