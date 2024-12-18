"""Monitor and retrieve weather data, generate maps, and format weather updates."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from pathlib import Path
from dataclasses import dataclass

import aiohttp
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from social_media.utils import PostContent, MediaContent

logger = logging.getLogger('CityBot2.weather')

@dataclass
class WeatherData:
    """Weather data container with social media formatting."""
    temperature: Optional[float]
    wind_speed: Optional[float]
    wind_direction: str
    cloud_cover: int
    forecast: str
    timestamp: datetime
    city: str
    state: str
    map_path: Optional[str] = None

    def format_for_social(self, hashtags: List[str]) -> PostContent:
        """Format weather data for social media posting."""
        hashtag_text = ' '.join('#' + tag for tag in hashtags)

        # Round temperature and wind speed to whole numbers if they are not None
        if self.temperature is not None:
            temp_str = f"{int(round(self.temperature))}°F"
        else:
            temp_str = "N/A"

        if self.wind_speed is not None:
            wind_str = f"{int(round(self.wind_speed))}mph {self.wind_direction}"
        else:
            wind_str = f"N/A {self.wind_direction}"

        text = (
            f"Weather Update for {self.city}, {self.state}\n\n"
            f"🌡️ Temperature: {temp_str}\n"
            f"💨 Wind: {wind_str}\n"
            f"☁️ Cloud Cover: {self.cloud_cover}%\n\n"
            f"Forecast: {self.forecast}\n\n"
            f"{hashtag_text}"
        )

        return PostContent(
            text=text,
            media=MediaContent(
                image_path=self.map_path,
                meta_title=f"{self.city}, {self.state} Weather Update",
                meta_description=(
                    f"Current conditions: {temp_str}, {wind_str}"
                )
            )
        )

@dataclass
class WeatherAlert:
    """Weather alert container with social media formatting."""
    event: str
    headline: str
    description: str
    severity: str
    urgency: str
    areas: str
    onset: Optional[datetime]
    expires: datetime
    city: str
    state: str

    def format_for_social(self, hashtags: List[str]) -> PostContent:
        """Format weather alert for social media posting."""
        hashtag_text = ' '.join('#' + tag for tag in hashtags)

        severity_emoji = {
            'Extreme': '⛔️',
            'Severe': '🚨',
            'Moderate': '⚠️',
            'Minor': '📢'
        }.get(self.severity, '⚠️')

        text = (
            f"{severity_emoji} WEATHER ALERT {severity_emoji}\n\n"
            f"Type: {self.event}\n"
            f"Areas: {self.areas}\n\n"
            f"{self.headline}\n\n"
            f"Valid until: {self.expires.strftime('%I:%M %p %Z')}\n\n"
            f"{hashtag_text}"
        )

        return PostContent(
            text=text,
            media=None,
            platform_specific={
                'alert_level': self.severity,
                'urgency': self.urgency
            }
        )

class WeatherMapGenerator:
    """Generates weather maps."""
    def __init__(self, config: Dict):
        self.config = config
        self.cache_dir = Path("cache/weather_maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def generate_map(self, weather_data: Dict) -> Optional[str]:
        """Generate weather map with current conditions."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = self.cache_dir / f"weather_map_{timestamp}.png"

            return await asyncio.to_thread(self._create_map, weather_data, str(output_path))
        except (OSError, RuntimeError) as exc:
            logger.error("Error generating weather map: %s", exc)
            return None

    def _create_map(self, weather_data: Dict, output_path: str) -> Optional[str]:
        """Create the weather map (runs in thread pool)."""
        fig = plt.figure(figsize=(12, 8))
        try:
            ax = plt.axes(projection=ccrs.PlateCarree())

            center_lat = self.config['coordinates']['latitude']
            center_lon = self.config['coordinates']['longitude']
            ax.set_extent([
                center_lon - 1.5,
                center_lon + 1.5,
                center_lat - 1.5,
                center_lat + 1.5
            ])

            ax.add_feature(cfeature.COASTLINE)
            ax.add_feature(cfeature.STATES)
            ax.add_feature(cfeature.LAND, facecolor='lightgray')
            ax.add_feature(cfeature.OCEAN, facecolor='lightblue')

            temperature = weather_data.get('temperature')
            wind_speed = weather_data.get('wind_speed')
            wind_direction = weather_data.get('wind_direction', 'Unknown')
            cloud_cover = weather_data.get('cloud_cover', 0)

            if temperature is not None:
                temp_str = f"{int(round(temperature))}°F"
            else:
                temp_str = "N/A"

            if wind_speed is not None:
                wind_str = f"{int(round(wind_speed))}mph {wind_direction}"
            else:
                wind_str = f"N/A {wind_direction}"

            info_text = (
                f"Temperature: {temp_str}\n"
                f"Wind: {wind_str}\n"
                f"Cloud Cover: {cloud_cover}%"
            )

            plt.title(f"Weather Conditions for {self.config['name']}")
            plt.text(
                0.02, 0.98, info_text, transform=ax.transAxes,
                bbox=dict(facecolor='white', alpha=0.7),
                verticalalignment='top'
            )

            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close(fig)
            return output_path
        except (OSError, RuntimeError) as exc:
            logger.error("Error creating weather map: %s", exc)
            plt.close(fig)
            return None

    async def cleanup_old_maps(self, days: int = 7) -> None:
        """Clean up old weather map files."""
        cutoff = datetime.now() - timedelta(days=days)
        for file_path in self.cache_dir.glob('*.png'):
            try:
                if datetime.fromtimestamp(file_path.stat().st_mtime) < cutoff:
                    file_path.unlink()
            except OSError as exc:
                logger.warning("Error deleting file %s: %s", file_path, exc)

class WeatherMonitor:
    """Monitors weather conditions and generates weather maps."""
    def __init__(self, config: Dict, city_config: Dict):
        self.config = config
        self.city_config = city_config
        self.latitude = city_config['coordinates']['latitude']
        self.longitude = city_config['coordinates']['longitude']
        self.base_url = "https://api.weather.gov"
        self.headers = {
            "User-Agent": "CityBot2/1.0",
            "Accept": "application/geo+json"
        }
        self.grid_info = None
        self.zone_code = city_config['weather']['zone_code']
        self.map_generator = WeatherMapGenerator(city_config)

    async def initialize(self) -> None:
        """Initialize the weather monitor."""
        if not self.grid_info:
            self.grid_info = await self.get_grid_coordinates()

    async def get_grid_coordinates(self) -> Optional[Dict]:
        """Get grid coordinates for the location."""
        url = f"{self.base_url}/points/{self.latitude},{self.longitude}"
        data = await self._fetch_data(url)
        if not data or 'properties' not in data:
            logger.error("Failed to get grid coordinates or invalid response format")
            return None
        try:
            return {
                'gridId': data['properties']['gridId'],
                'gridX': data['properties']['gridX'],
                'gridY': data['properties']['gridY']
            }
        except KeyError as exc:
            logger.error("Missing required grid coordinate field: %s", exc)
            return None

    async def _fetch_data(self, url: str) -> Optional[Dict]:
        """Fetch data from the weather service."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        return await response.json()
                    logger.error("Failed to fetch data from %s, Status: %d", url, response.status)
                    return None
        except aiohttp.ClientError as exc:
            logger.error("Network error fetching %s: %s", url, exc)
            return None

    def _convert_temperature(self, celsius_value: Optional[float]) -> Optional[float]:
        """Convert temperature from Celsius to Fahrenheit."""
        if celsius_value is None:
            return None
        try:
            return (celsius_value * 9 / 5) + 32
        except (TypeError, ValueError) as exc:
            logger.error("Error converting temperature: %s", exc)
            return None

    def _convert_wind_speed(self, mps_value: Optional[float]) -> Optional[float]:
        """Convert wind speed from meters per second to miles per hour."""
        if mps_value is None:
            return None
        try:
            return mps_value * 2.237
        except (TypeError, ValueError) as exc:
            logger.error("Error converting wind speed: %s", exc)
            return None

    def _get_cloud_cover(self, cloud_layers: List[Dict]) -> int:
        """Extract cloud cover percentage from cloud layers."""
        try:
            for layer in cloud_layers:
                if 'amount' in layer:
                    return layer['amount']
            return 0
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Error processing cloud cover: %s", exc)
            return 0

    async def get_current_conditions(self) -> Optional[WeatherData]:
        """Get current weather conditions with optional map."""
        if not self.grid_info:
            await self.initialize()
        if not self.grid_info:
            logger.error("Grid coordinates not initialized.")
            return None

        conditions = await self._get_current_conditions()
        if conditions:
            map_path = await self.map_generator.generate_map(conditions)
            if map_path:
                conditions['map_path'] = str(map_path)

            return WeatherData(
                temperature=conditions['temperature'],
                wind_speed=conditions['wind_speed'],
                wind_direction=conditions['wind_direction'],
                cloud_cover=conditions['cloud_cover'],
                forecast=conditions['forecast'],
                timestamp=conditions['timestamp'],
                city=self.city_config['name'],
                state=self.city_config['state'],
                map_path=conditions.get('map_path')
            )
        return None

    async def _get_current_conditions(self) -> Optional[Dict]:
        """Get current weather conditions."""
        if not self.grid_info:
            return None

        forecast_url = (
            f"{self.base_url}/gridpoints/{self.grid_info['gridId']}/"
            f"{self.grid_info['gridX']},{self.grid_info['gridY']}/forecast/hourly"
        )
        forecast_data = await self._fetch_data(forecast_url)
        if not forecast_data or 'properties' not in forecast_data:
            logger.error("Failed to fetch forecast data or invalid format")
            return None

        stations_url = (
            f"{self.base_url}/gridpoints/{self.grid_info['gridId']}/"
            f"{self.grid_info['gridX']},{self.grid_info['gridY']}/stations"
        )
        stations_data = await self._fetch_data(stations_url)
        if not stations_data or not stations_data.get('features'):
            logger.error("No weather stations found in grid area")
            return None

        station_id = stations_data['features'][0]['properties']['stationIdentifier']
        obs_url = f"{self.base_url}/stations/{station_id}/observations/latest"
        obs_data = await self._fetch_data(obs_url)
        if not obs_data or 'properties' not in obs_data:
            logger.error("Failed to fetch observation data or invalid format")
            return None

        try:
            properties = obs_data['properties']

            temp_value = properties.get('temperature', {}).get('value')
            wind_speed_value = properties.get('windSpeed', {}).get('value')
            wind_direction_value = properties.get('windDirection', {}).get('value')
            cloud_layers = properties.get('cloudLayers', [])

            return {
                'temperature': self._convert_temperature(temp_value),
                'wind_speed': self._convert_wind_speed(wind_speed_value),
                'wind_direction': wind_direction_value or 'Unknown',
                'cloud_cover': self._get_cloud_cover(cloud_layers),
                'forecast': forecast_data['properties']['periods'][0].get(
                    'shortForecast', 'No forecast available'
                ),
                'timestamp': datetime.now(timezone.utc),
                'city': self.city_config['name'],
                'state': self.city_config['state']
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Error processing weather data: %s", exc)
            return None

    async def get_alerts(self) -> List[WeatherAlert]:
        """Get active weather alerts."""
        url = f"{self.base_url}/alerts/active/zone/{self.zone_code}"
        data = await self._fetch_data(url)
        if not data:
            return []

        alerts = []
        for feature in data.get('features', []):
            try:
                props = feature['properties']
                onset_str = props.get('onset')
                expires_str = props.get('expires')
                onset_dt = None
                if onset_str:
                    onset_dt = datetime.fromisoformat(onset_str.replace('Z', '+00:00'))
                expires_dt = None
                if expires_str:
                    expires_dt = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))

                alert = WeatherAlert(
                    event=props.get('event', 'Unknown Event'),
                    headline=props.get('headline', 'No headline'),
                    description=props.get('description', ''),
                    severity=props.get('severity', 'Unknown'),
                    urgency=props.get('urgency', 'Unknown'),
                    areas=props.get('areaDesc', 'Unknown'),
                    onset=onset_dt,
                    expires=expires_dt,
                    city=self.city_config['name'],
                    state=self.city_config['state']
                )
                alerts.append(alert)
            except (KeyError, TypeError, ValueError) as exc:
                logger.error("Error processing alert data: %s", exc)
                continue
        return alerts

    async def cleanup(self) -> None:
        """Cleanup weather-related resources."""
        await self.map_generator.cleanup_old_maps()
