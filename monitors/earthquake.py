from datetime import datetime, timedelta
import requests
import logging
from typing import List, Dict, Optional
from math import sin, cos, sqrt, atan2, radians

logger = logging.getLogger('CityBot2.earthquake')

class EarthquakeMonitor:
    def __init__(self, config: Dict, city_config: Dict):
        self.config = config
        self.city_config = city_config
        self.city_lat = city_config['coordinates']['latitude']
        self.city_lon = city_config['coordinates']['longitude']
        self.base_url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
        self.radius_km = self.config.get('radius_miles', 100) * 1.60934  # Convert miles to km

    def calculate_distance(self, lat: float, lon: float) -> float:
        """Calculate distance in miles from city to earthquake location."""
        R = 3959.87433  # Earth's radius in miles

        lat1 = radians(self.city_lat)
        lon1 = radians(self.city_lon)
        lat2 = radians(lat)
        lon2 = radians(lon)

        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        return R * c

    async def get_earthquakes(self) -> List[Dict]:
        """Get recent earthquakes within specified radius."""
        try:
            # Calculate time 24 hours ago
            start_time = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            
            params = {
                "format": "geojson",
                "latitude": self.city_lat,
                "longitude": self.city_lon,
                "maxradiuskm": self.radius_km,
                "minmagnitude": self.config.get('minimum_magnitude', 3.0),
                "starttime": start_time,
                "orderby": "time"
            }
            
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            earthquakes = []
            for feature in data['features']:
                props = feature['properties']
                coords = feature['geometry']['coordinates']
                
                # Calculate distance from city
                distance = self.calculate_distance(coords[1], coords[0])
                
                earthquakes.append({
                    'magnitude': props['mag'],
                    'location': props['place'],
                    'depth': coords[2],
                    'timestamp': datetime.fromtimestamp(props['time'] / 1000),
                    'distance': distance,
                    'url': props['url'],
                    'felt': props.get('felt', 0),
                    'alert': props.get('alert', None),
                    'status': props.get('status', 'automatic'),
                    'latitude': coords[1],
                    'longitude': coords[0],
                    'city': self.city_config['name'],
                    'state': self.city_config['state']
                })
            
            return earthquakes
            
        except Exception as e:
            logger.error(f"Error fetching earthquake data: {str(e)}")
            return []

    def is_significant(self, magnitude: float, distance: float) -> bool:
        """Determine if an earthquake is significant enough to report."""
        if magnitude >= 5.0:  # Major earthquakes always reported
            return True
        elif magnitude >= 4.0 and distance <= 50:  # Moderate earthquakes within 50 miles
            return True
        elif magnitude >= 3.0 and distance <= 25:  # Minor earthquakes within 25 miles
            return True
        return False

    async def check_earthquakes(self) -> List[Dict]:
        """Check for significant earthquakes."""
        earthquakes = await self.get_earthquakes()
        return [quake for quake in earthquakes 
                if self.is_significant(quake['magnitude'], quake['distance'])]