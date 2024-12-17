import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import logging
from pathlib import Path
import matplotlib
matplotlib.use('Agg')  # Set non-interactive backend before other imports
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

logger = logging.getLogger('CityBot2.weather')

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

            # Run matplotlib operations in a thread pool
            return await asyncio.to_thread(self._create_map,
                                         weather_data,
                                         str(output_path))

        except Exception as e:
            logger.error(f"Error generating weather map: {str(e)}")
            return None

    def _create_map(self, weather_data: Dict, output_path: str) -> Optional[str]:
        """Create the weather map (runs in thread pool)."""
        fig = plt.figure(figsize=(12, 8))
        try:
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
            plt.close(fig)
            return output_path
            
        except Exception as e:
            logger.error(f"Error creating weather map: {str(e)}")
            plt.close(fig)
            return None

    async def cleanup_old_maps(self, days: int = 7) -> None:
        """Clean up old weather map files."""
        try:
            cutoff = datetime.now() - timedelta(days=days)
            for file_path in self.cache_dir.glob('*.png'):
                try:
                    if datetime.fromtimestamp(file_path.stat().st_mtime) < cutoff:
                        file_path.unlink()
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Error cleaning up weather maps: {str(e)}")

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
        except KeyError as e:
            logger.error(f"Missing required grid coordinate field: {e}")
            return None

    async def _fetch_data(self, url: str) -> Optional[Dict]:
        """Fetch data from the weather service."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        return await response.json()
                    logger.error(f"Failed to fetch data: {url}, Status: {response.status}")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching {url}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {str(e)}")
            return None

    def _convert_temperature(self, celsius_value: Optional[float]) -> Optional[float]:
        """Convert temperature from Celsius to Fahrenheit."""
        if celsius_value is None:
            return None
        try:
            return (celsius_value * 9/5) + 32
        except (TypeError, ValueError) as e:
            logger.error(f"Error converting temperature: {e}")
            return None

    def _convert_wind_speed(self, mps_value: Optional[float]) -> Optional[float]:
        """Convert wind speed from meters per second to miles per hour."""
        if mps_value is None:
            return None
        try:
            return mps_value * 2.237
        except (TypeError, ValueError) as e:
            logger.error(f"Error converting wind speed: {e}")
            return None

    def _get_cloud_cover(self, cloud_layers: List[Dict]) -> int:
        """Extract cloud cover percentage from cloud layers."""
        try:
            for layer in cloud_layers:
                if 'amount' in layer:
                    return layer['amount']
            return 0
        except Exception as e:
            logger.error(f"Error processing cloud cover: {e}")
            return 0

    async def get_current_conditions(self) -> Optional[Dict]:
        """Get current weather conditions with optional map."""
        if not self.grid_info:
            await self.initialize()
        if not self.grid_info:
            logger.error("Grid coordinates not initialized.")
            return None

        conditions = await self._get_current_conditions()
        if conditions:
            # Generate map if conditions are available
            map_path = await self.map_generator.generate_map(conditions)
            if map_path:
                conditions['map_path'] = str(map_path)
        return conditions

    async def _get_current_conditions(self) -> Optional[Dict]:
        """Get current weather conditions."""
        # Fetch forecast data
        forecast_url = (f"{self.base_url}/gridpoints/"
                       f"{self.grid_info['gridId']}/"
                       f"{self.grid_info['gridX']},"
                       f"{self.grid_info['gridY']}/forecast/hourly")
        forecast_data = await self._fetch_data(forecast_url)
        if not forecast_data or 'properties' not in forecast_data:
            logger.error("Failed to fetch forecast data or invalid format")
            return None

        # Fetch stations data
        stations_url = (f"{self.base_url}/gridpoints/"
                       f"{self.grid_info['gridId']}/"
                       f"{self.grid_info['gridX']},"
                       f"{self.grid_info['gridY']}/stations")
        stations_data = await self._fetch_data(stations_url)
        if not stations_data or not stations_data.get('features'):
            logger.error("No weather stations found in grid area")
            return None

        # Get observation data
        station_id = stations_data['features'][0]['properties']['stationIdentifier']
        obs_url = f"{self.base_url}/stations/{station_id}/observations/latest"
        obs_data = await self._fetch_data(obs_url)
        if not obs_data or 'properties' not in obs_data:
            logger.error("Failed to fetch observation data or invalid format")
            return None

        try:
            properties = obs_data['properties']
            
            # Safely extract and convert values
            temp_value = properties.get('temperature', {}).get('value')
            wind_speed_value = properties.get('windSpeed', {}).get('value')
            wind_direction_value = properties.get('windDirection', {}).get('value')
            cloud_layers = properties.get('cloudLayers', [])

            return {
                'temperature': self._convert_temperature(temp_value),
                'wind_speed': self._convert_wind_speed(wind_speed_value),
                'wind_direction': wind_direction_value or 'Unknown',
                'cloud_cover': self._get_cloud_cover(cloud_layers),
                'forecast': forecast_data['properties']['periods'][0].get('shortForecast', 'No forecast available'),
                'timestamp': datetime.now(timezone.utc),
                'city': self.city_config['name'],
                'state': self.city_config['state']
            }
        except Exception as e:
            logger.error(f"Error processing weather data: {e}")
            return None

    async def get_alerts(self) -> List[Dict]:
        """Get active weather alerts."""
        url = f"{self.base_url}/alerts/active/zone/{self.zone_code}"
        data = await self._fetch_data(url)
        if not data:
            return []

        alerts = []
        for feature in data.get('features', []):
            try:
                props = feature['properties']
                alerts.append({
                    'event': props.get('event', 'Unknown Event'),
                    'headline': props.get('headline', 'No headline'),
                    'description': props.get('description', ''),
                    'severity': props.get('severity', 'Unknown'),
                    'urgency': props.get('urgency', 'Unknown'),
                    'areas': props.get('areaDesc', 'Unknown'),
                    'onset': datetime.fromisoformat(props['onset'].replace('Z', '+00:00')) 
                            if props.get('onset') else None,
                    'expires': datetime.fromisoformat(props['expires'].replace('Z', '+00:00')) 
                            if props.get('expires') else None,
                    'city': self.city_config['name'],
                    'state': self.city_config['state']
                })
            except Exception as e:
                logger.error(f"Error processing alert data: {e}")
                continue
        return alerts

    async def cleanup(self) -> None:
        """Cleanup weather-related resources."""
        await self.map_generator.cleanup_old_maps()