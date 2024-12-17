from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging
from datetime import datetime
from .utils import PostContent, MediaContent

logger = logging.getLogger('CityBot2.formatters')

@dataclass
class HashtagConfig:
    """Configuration for hashtags by post type."""
    weather: List[str]
    earthquake: List[str]
    news: List[str]

class PostFormatter:
    """Formats social media posts for different types of content."""

    def __init__(self, city_config: Dict[str, Any]):
        """Initialize the post formatter with city configuration.
        
        Args:
            city_config: Dictionary containing city name, state, and other settings
        """
        self._validate_config(city_config)
        self.city_config = city_config
        self.hashtags = self._create_hashtag_config(city_config)

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Validate required configuration fields exist."""
        required_fields = ['name', 'state']
        missing_fields = [field for field in required_fields if field not in config]
        if missing_fields:
            raise ValueError(f"Missing required configuration fields: {', '.join(missing_fields)}")

    def _create_hashtag_config(self, config: Dict[str, Any]) -> HashtagConfig:
        """Create hashtag configuration based on city config."""
        try:
            return HashtagConfig(
                weather=[
                    f"{config['name']}Weather",
                    f"{config['name']}{config['state']}",
                    f"{config['state']}Weather"
                ],
                earthquake=[
                    "Earthquake",
                    f"{config['name']}{config['state']}",
                    f"{config['state']}Earthquake"
                ],
                news=[
                    config['name'],
                    f"{config['name']}{config['state']}",
                    "LocalNews"
                ]
            )
        except Exception as e:
            logger.error(f"Error creating hashtag config: {str(e)}")
            raise

    def format_weather(self, weather_data: Dict[str, Any]) -> PostContent:
        """Format weather update content.
        
        Args:
            weather_data: Dictionary containing weather information
                Required keys: temperature, wind_speed, wind_direction, cloud_cover, forecast
                Optional keys: map_path
        
        Returns:
            PostContent object with formatted weather update
        """
        try:
            self._validate_weather_data(weather_data)
            hashtags = ' '.join([f"#{tag}" for tag in self.hashtags.weather])
            
            text = (
                f"Weather Update for {self.city_config['name']}, {self.city_config['state']}\n\n"
                f"🌡️ Temperature: {weather_data['temperature']:.1f}°F\n"
                f"💨 Wind: {weather_data['wind_speed']:.1f}mph {weather_data['wind_direction']}\n"
                f"☁️ Cloud Cover: {weather_data['cloud_cover']}%\n\n"
                f"Forecast: {weather_data['forecast']}\n\n"
                f"{hashtags}"
            )

            return PostContent(
                text=text,
                media=MediaContent(
                    image_path=weather_data.get('map_path'),
                    meta_title=f"{self.city_config['name']}, {self.city_config['state']} Weather Update",
                    meta_description=f"Current conditions: {weather_data['temperature']}°F, "
                                   f"{weather_data['wind_speed']}mph winds"
                )
            )
        except Exception as e:
            logger.error(f"Error formatting weather content: {str(e)}")
            raise

    def format_weather_alert(self, alert_data: Dict[str, Any]) -> PostContent:
        """Format weather alert content.
        
        Args:
            alert_data: Dictionary containing alert information
                Required keys: severity, event, areas, headline, expires, urgency
        
        Returns:
            PostContent object with formatted weather alert
        """
        try:
            self._validate_alert_data(alert_data)
            hashtags = ' '.join([f"#{tag}" for tag in self.hashtags.weather])
            
            severity_emoji = {
                'Extreme': '⛔️',
                'Severe': '🚨',
                'Moderate': '⚠️',
                'Minor': '📢'
            }.get(alert_data['severity'], '⚠️')

            text = (
                f"{severity_emoji} WEATHER ALERT {severity_emoji}\n\n"
                f"Type: {alert_data['event']}\n"
                f"Areas: {alert_data['areas']}\n\n"
                f"{alert_data['headline']}\n\n"
                f"Valid until: {alert_data['expires'].strftime('%I:%M %p %Z')}\n\n"
                f"{hashtags}"
            )

            return PostContent(
                text=text,
                media=None,
                platform_specific={
                    'alert_level': alert_data['severity'],
                    'urgency': alert_data['urgency']
                }
            )
        except Exception as e:
            logger.error(f"Error formatting weather alert: {str(e)}")
            raise

    def format_earthquake(self, quake_data: Dict[str, Any]) -> PostContent:
        """Format earthquake update content.
        
        Args:
            quake_data: Dictionary containing earthquake information
                Required keys: magnitude, location, depth, distance
                Optional keys: map_path, url
        
        Returns:
            PostContent object with formatted earthquake update
        """
        try:
            self._validate_quake_data(quake_data)
            magnitude_emoji = self._get_magnitude_emoji(quake_data['magnitude'])
            hashtags = ' '.join([f"#{tag}" for tag in self.hashtags.earthquake])
            
            text = (
                f"{magnitude_emoji} EARTHQUAKE REPORT {magnitude_emoji}\n\n"
                f"Magnitude: {quake_data['magnitude']}\n"
                f"Location: {quake_data['location']}\n"
                f"Depth: {quake_data['depth']:.1f} km\n"
                f"Distance from {self.city_config['name']}: {quake_data['distance']:.1f} miles\n\n"
                f"{hashtags}"
            )

            return PostContent(
                text=text,
                media=MediaContent(
                    image_path=quake_data.get('map_path'),
                    link_url=quake_data.get('url'),
                    meta_title=f"M{quake_data['magnitude']} Earthquake near {self.city_config['name']}, {self.city_config['state']}",
                    meta_description=f"Earthquake detected {quake_data['distance']:.1f} miles from {self.city_config['name']}"
                )
            )
        except Exception as e:
            logger.error(f"Error formatting earthquake content: {str(e)}")
            raise

    def format_news(self, article_data: Dict[str, Any]) -> PostContent:
        """Format news update content.
        
        Args:
            article_data: Dictionary containing news article information
                Required keys: title, content_snippet, source, url
                Optional keys: map_path
        
        Returns:
            PostContent object with formatted news update
        """
        try:
            self._validate_article_data(article_data)
            hashtags = ' '.join([f"#{tag}" for tag in self.hashtags.news])
            
            text = (
                f"📰 {article_data['title']}\n\n"
                f"{article_data['content_snippet']}\n\n"
                f"Source: {article_data['source']}\n"
                f"{article_data['url']}\n\n"
                f"{hashtags}"
            )

            return PostContent(
                text=text,
                media=MediaContent(
                    image_path=article_data.get('map_path'),
                    link_url=article_data['url'],
                    meta_title=article_data['title'],
                    meta_description=article_data['content_snippet'][:200]
                )
            )
        except Exception as e:
            logger.error(f"Error formatting news content: {str(e)}")
            raise

    def _validate_weather_data(self, data: Dict[str, Any]) -> None:
        """Validate weather data contains required fields."""
        required_fields = ['temperature', 'wind_speed', 'wind_direction', 'cloud_cover', 'forecast']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required weather data fields: {', '.join(missing_fields)}")

    def _validate_alert_data(self, data: Dict[str, Any]) -> None:
        """Validate alert data contains required fields."""
        required_fields = ['severity', 'event', 'areas', 'headline', 'expires', 'urgency']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required alert data fields: {', '.join(missing_fields)}")

    def _validate_quake_data(self, data: Dict[str, Any]) -> None:
        """Validate earthquake data contains required fields."""
        required_fields = ['magnitude', 'location', 'depth', 'distance']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required earthquake data fields: {', '.join(missing_fields)}")

    def _validate_article_data(self, data: Dict[str, Any]) -> None:
        """Validate article data contains required fields."""
        required_fields = ['title', 'content_snippet', 'source', 'url']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required article data fields: {', '.join(missing_fields)}")

    def _get_magnitude_emoji(self, magnitude: float) -> str:
        """Get appropriate emoji for earthquake magnitude."""
        if magnitude >= 5.0:
            return "🔴"
        elif magnitude >= 4.0:
            return "🟡"
        return "🟢"