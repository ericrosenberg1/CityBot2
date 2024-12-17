import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from urllib.parse import urlparse
from PIL import Image
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import folium
import requests
from io import BytesIO

logger = logging.getLogger('CityBot2.utils')

@dataclass
class MediaContent:
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    link_url: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None

@dataclass
class PostContent:
    text: str
    media: Optional[MediaContent] = None
    platform_specific: Dict[str, Any] = None

class RateLimiter:
    def __init__(self, db_path: str = "data/rate_limits.db"):
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        """Initialize the rate limiting database."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    post_type TEXT NOT NULL,
                    timestamp DATETIME NOT NULL
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_platform_type_timestamp 
                ON post_history(platform, post_type, timestamp)
            ''')

    def can_post(self, platform: str, post_type: str) -> bool:
        """Check if posting is allowed based on rate limits."""
        now = datetime.now()
        hourly_limit = self._get_limit(platform, 'hourly')
        daily_limit = self._get_limit(platform, 'daily')
        min_interval = self._get_limit(platform, 'interval')

        with sqlite3.connect(self.db_path) as conn:
            # Check minimum interval
            last_post = conn.execute('''
                SELECT timestamp FROM post_history
                WHERE platform = ? AND post_type = ?
                ORDER BY timestamp DESC LIMIT 1
            ''', (platform, post_type)).fetchone()

            if last_post:
                last_time = datetime.fromisoformat(last_post[0])
                if (now - last_time).total_seconds() < min_interval:
                    return False

            # Check hourly limit
            hourly_count = conn.execute('''
                SELECT COUNT(*) FROM post_history
                WHERE platform = ? AND post_type = ?
                AND timestamp > ?
            ''', (platform, post_type, (now - timedelta(hours=1)).isoformat())).fetchone()[0]

            if hourly_count >= hourly_limit:
                return False

            # Check daily limit
            daily_count = conn.execute('''
                SELECT COUNT(*) FROM post_history
                WHERE platform = ? AND post_type = ?
                AND timestamp > ?
            ''', (platform, post_type, (now - timedelta(days=1)).isoformat())).fetchone()[0]

            return daily_count < daily_limit

    def _get_limit(self, platform: str, limit_type: str) -> int:
        """Get rate limit for platform and type."""
        limits = {
            'twitter': {'hourly': 10, 'daily': 24, 'interval': 300},
            'bluesky': {'hourly': 10, 'daily': 24, 'interval': 300},
            'facebook': {'hourly': 10, 'daily': 24, 'interval': 300},
            'linkedin': {'hourly': 10, 'daily': 24, 'interval': 300},
            'reddit': {'hourly': 10, 'daily': 24, 'interval': 300}
        }
        return limits.get(platform, {'hourly': 10, 'daily': 24, 'interval': 300})[limit_type]

    def record_post(self, platform: str, post_type: str):
        """Record a successful post."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO post_history (platform, post_type, timestamp)
                VALUES (?, ?, ?)
            ''', (platform, post_type, datetime.now().isoformat()))

    def cleanup_old_records(self, days: int = 7):
        """Clean up records older than specified days."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                DELETE FROM post_history
                WHERE timestamp < ?
            ''', ((datetime.now() - timedelta(days=days)).isoformat(),))

class ContentValidator:
    def __init__(self):
        self.platform_limits = {
            'bluesky': {'text': 300, 'images': 4},
            'twitter': {'text': 280, 'images': 4},
            'facebook': {'text': 63206, 'images': 10},
            'linkedin': {'text': 3000, 'images': 9},
            'reddit': {'text': 40000, 'images': 20}
        }
        
        self.image_requirements = {
            'max_size': 5 * 1024 * 1024,  # 5MB
            'min_dimensions': (200, 200),
            'max_dimensions': (4096, 4096),
            'allowed_formats': {'JPEG', 'PNG', 'GIF'}
        }

    def validate_content(self, content: PostContent, platform: str) -> List[str]:
        """Validate content for platform-specific requirements."""
        errors = []
        if not content.text.strip():
            errors.append("Text content cannot be empty")

        limits = self.platform_limits.get(platform, {})
        if len(content.text) > limits.get('text', float('inf')):
            errors.append(f"Text exceeds {platform} limit")

        if content.media:
            errors.extend(self._validate_media(content.media))

        return errors

    def _validate_media(self, media: MediaContent) -> List[str]:
        """Validate media content."""
        errors = []
        if media.image_path and not self._validate_image(media.image_path):
            errors.append("Invalid image file")
        if media.link_url and not self._validate_url(media.link_url):
            errors.append("Invalid URL")
        return errors

    def _validate_image(self, image_path: str) -> bool:
        """Validate image file."""
        try:
            with Image.open(image_path) as img:
                return (
                    os.path.getsize(image_path) <= self.image_requirements['max_size']
                    and img.format in self.image_requirements['allowed_formats']
                    and all(self.image_requirements['min_dimensions'][i] <= img.size[i] <= self.image_requirements['max_dimensions'][i] for i in range(2))
                )
        except Exception:
            return False

    def _validate_url(self, url: str) -> bool:
        """Validate URL."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except Exception:
            return False

class WeatherMapGenerator:
    def __init__(self, config: Dict):
        self.config = config
        self.cache_dir = "cache/weather_maps"
        os.makedirs(self.cache_dir, exist_ok=True)

    def generate_weather_map(self, weather_data: Dict) -> Optional[str]:
        """Generate weather map with current conditions."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = os.path.join(self.cache_dir, f"weather_map_{timestamp}.png")

            fig = plt.figure(figsize=(12, 8))
            ax = plt.axes(projection=ccrs.PlateCarree())

            # Set map extent
            center_lat = self.config['coordinates']['latitude']
            center_lon = self.config['coordinates']['longitude']
            ax.set_extent([
                center_lon - 1.5,
                center_lon + 1.5,
                center_lat - 1.5,
                center_lat + 1.5
            ])

            # Add map features
            ax.add_feature(cfeature.COASTLINE)
            ax.add_feature(cfeature.STATES)
            ax.add_feature(cfeature.LAND, facecolor='lightgray')
            ax.add_feature(cfeature.OCEAN, facecolor='lightblue')

            # Add weather info
            plt.title(f"Weather Conditions for {self.config.get('city', 'City')}")
            info_text = (
                f"Temperature: {weather_data['temperature']}°F\n"
                f"Wind: {weather_data['wind_speed']}mph {weather_data['wind_direction']}\n"
                f"Cloud Cover: {weather_data['cloud_cover']}%"
            )
            plt.text(0.02, 0.98, info_text, transform=ax.transAxes, 
                    bbox=dict(facecolor='white', alpha=0.7),
                    verticalalignment='top')

            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()

            return output_path

        except Exception as e:
            logger.error(f"Error generating weather map: {str(e)}")
            return None

class MapGenerator:
    def __init__(self, config: Dict):
        self.config = config
        self.cache_dir = "cache/maps"
        os.makedirs(self.cache_dir, exist_ok=True)

    def generate_earthquake_map(self, quake_data: Dict) -> Optional[str]:
        """Generate earthquake location map."""
        try:
            center_lat = (self.config['coordinates']['latitude'] + float(quake_data['latitude'])) / 2
            center_lon = (self.config['coordinates']['longitude'] + float(quake_data['longitude'])) / 2

            m = folium.Map(location=[center_lat, center_lon], 
                          zoom_start=self._calculate_zoom(quake_data['distance']))

            # Add markers
            folium.Marker(
                [self.config['coordinates']['latitude'], 
                 self.config['coordinates']['longitude']],
                popup=self.config.get('city', 'City'),
                icon=folium.Icon(color='blue')
            ).add_to(m)

            folium.Marker(
                [quake_data['latitude'], quake_data['longitude']],
                popup=f"M{quake_data['magnitude']} Earthquake<br>{quake_data['location']}",
                icon=folium.Icon(color='red')
            ).add_to(m)

            # Add connecting line
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
            html_path = os.path.join(self.cache_dir, f"earthquake_map_{timestamp}.html")
            m.save(html_path)

            # Convert to image
            image_path = html_path.replace('.html', '.png')
            os.system(f'cutycapt --url=file://{html_path} --out={image_path}')
            
            return image_path

        except Exception as e:
            logger.error(f"Error generating earthquake map: {str(e)}")
            return None

    def _calculate_zoom(self, distance: float) -> int:
        """Calculate appropriate zoom level based on distance."""
        if distance <= 25:
            return 10
        elif distance <= 50:
            return 9
        elif distance <= 100:
            return 8
        else:
            return 7

    def generate_news_map(self, location_data: Dict) -> Optional[str]:
        """Generate map for news location."""
        try:
            m = folium.Map(
                location=[self.config['coordinates']['latitude'],
                         self.config['coordinates']['longitude']],
                zoom_start=12
            )

            folium.Marker(
                [location_data['latitude'], location_data['longitude']],
                popup=location_data.get('description', 'News Location'),
                icon=folium.Icon(color='red')
            ).add_to(m)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            html_path = os.path.join(self.cache_dir, f"news_map_{timestamp}.html")
            m.save(html_path)

            # Convert to image
            image_path = html_path.replace('.html', '.png')
            os.system(f'cutycapt --url=file://{html_path} --out={image_path}')
            
            return image_path

        except Exception as e:
            logger.error(f"Error generating news map: {str(e)}")
            return None