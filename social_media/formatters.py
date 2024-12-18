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
                ]
            )
        except Exception as e:
            logger.error(f"Error creating hashtag config: {str(e)}")
            raise

    def format_earthquake(self, quake_data: Dict[str, Any]) -> PostContent:
        """Format earthquake update content."""
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

    def _get_magnitude_emoji(self, magnitude: float) -> str:
        """Get appropriate emoji for earthquake magnitude."""
        if magnitude >= 5.0:
            return "🔴"
        elif magnitude >= 4.0:
            return "🟡"
        return "🟢"