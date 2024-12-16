import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, List
import logging

logger = logging.getLogger('CityBot2.weather')

class WeatherMonitor:
    def __init__(self, config: Dict):
        self.config = config
        self.latitude = 34.2805
        self.longitude = -119.2945
        self.base_url = "https://api.weather.gov"
        self.headers = {
            "User-Agent": "CityBot2/1.0",
            "Accept": "application/geo+json"
        }
        self.grid_info = None

    async def initialize(self):
        """Initialize grid coordinates for location."""
        if not self.grid_info:
            self.grid_info = await self._get_grid_coordinates()

    async def _get_grid_coordinates(self) -> Dict:
        """Get grid coordinates from NWS API."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/points/{self.latitude},{self.longitude}"
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'gridId': data['properties']['gridId'],
                        'gridX': data['properties']['gridX'],
                        'gridY': data['properties']['gridY']
                    }
                else:
                    raise Exception(f"Error getting grid coordinates: {response.status}")

    async def get_current_conditions(self) -> Optional[Dict]:
        """Get current weather conditions."""
        if not self.grid_info:
            await self.initialize()

        async with aiohttp.ClientSession() as session:
            # Get forecast data
            forecast_url = (f"{self.base_url}/gridpoints/"
                          f"{self.grid_info['gridId']}/"
                          f"{self.grid_info['gridX']},"
                          f"{self.grid_info['gridY']}/forecast/hourly")
            
            try:
                async with session.get(forecast_url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        current = data['properties']['periods'][0]

                        # Get observations from nearest station
                        stations_url = (f"{self.base_url}/gridpoints/"
                                      f"{self.grid_info['gridId']}/"
                                      f"{self.grid_info['gridX']},"
                                      f"{self.grid_info['gridY']}/stations")
                        
                        async with session.get(stations_url, headers=self.headers) as station_response:
                            if station_response.status == 200:
                                stations_data = await station_response.json()
                                station_id = stations_data['features'][0]['properties']['stationIdentifier']
                                
                                obs_url = f"{self.base_url}/stations/{station_id}/observations/latest"
                                async with session.get(obs_url, headers=self.headers) as obs_response:
                                    if obs_response.status == 200:
                                        obs_data = await obs_response.json()
                                        return {
                                            'temperature': obs_data['properties']['temperature']['value'] * 9/5 + 32,
                                            'wind_speed': obs_data['properties']['windSpeed']['value'] * 2.237,
                                            'wind_direction': obs_data['properties']['windDirection']['value'],
                                            'cloud_cover': obs_data['properties'].get('cloudLayers', [{}])[0].get('amount', 0),
                                            'forecast': current['shortForecast'],
                                            'timestamp': datetime.now(timezone.utc)
                                        }
            
            except Exception as e:
                logger.error(f"Error fetching weather data: {str(e)}")
                return None

    async def get_alerts(self) -> List[Dict]:
        """Get active weather alerts."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/alerts/active/zone/CAZ039"  # Ventura County Coast
            
            try:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        alerts = []
                        
                        for feature in data['features']:
                            props = feature['properties']
                            alerts.append({
                                'event': props['event'],
                                'headline': props['headline'],
                                'description': props['description'],
                                'severity': props['severity'],
                                'urgency': props['urgency'],
                                'areas': props['areaDesc'],
                                'onset': datetime.fromisoformat(props['onset'].replace('Z', '+00:00')),
                                'expires': datetime.fromisoformat(props['expires'].replace('Z', '+00:00'))
                            })
                        
                        return alerts
            
            except Exception as e:
                logger.error(f"Error fetching weather alerts: {str(e)}")
                return []