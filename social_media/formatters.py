from typing import Dict, Any
from dataclasses import dataclass
from .platforms.base import PostContent, MediaContent

@dataclass
class HashtagConfig:
    weather: list[str]
    earthquake: list[str]
    news: list[str]

class PostFormatter:
    def __init__(self, city_config: Dict[str, Any]):
        self.city_config = city_config
        self.hashtags = HashtagConfig(
            weather=[f"{city_config['name']}Weather", f"{city_config['name']}CA", "CaWeather"],
            earthquake=["Earthquake", f"{city_config['name']}CA", "CaliforniaEarthquake"],
            news=[city_config['name'], f"{city_config['name']}CA", "LocalNews"]
        )

    def format_weather(self, weather_data: Dict[str, Any]) -> PostContent:
        """Format weather update content."""
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

    def format_earthquake(self, quake_data: Dict[str, Any]) -> PostContent:
        """Format earthquake update content."""
        magnitude_emoji = "🔴" if quake_data['magnitude'] >= 5.0 else "🟡" if quake_data['magnitude'] >= 4.0 else "🟢"
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

    def format_news(self, article_data: Dict[str, Any]) -> PostContent:
        """Format news update content."""
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