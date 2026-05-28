"""Monitor earthquakes via the USGS API."""

import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger('CityBot2.earthquake')


class EarthquakeMonitor:
    """Monitor recent earthquakes via the USGS API."""

    def __init__(self, config: Dict[str, Any], city_config: Dict[str, Any]):
        self.config = config
        self.city_config = city_config
        self.city_lat = city_config['coordinates']['latitude']
        self.city_lon = city_config['coordinates']['longitude']
        self.base_url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
        self.radius_km = self.config.get('radius_miles', 100) * 1.60934

    def calculate_distance(self, lat: float, lon: float) -> float:
        """Calculate distance in miles from the city to the earthquake location."""
        R = 3959.87433
        lat1, lon1 = math.radians(self.city_lat), math.radians(self.city_lon)
        lat2, lon2 = math.radians(lat), math.radians(lon)
        dlat, dlon = lat2 - lat1, lon2 - lon1

        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    async def get_earthquakes(self) -> List[Dict[str, Any]]:
        """Get recent earthquakes within the specified radius."""
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

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(requests.get, self.base_url, params=params),
                timeout=15.0
            )
            response.raise_for_status()
            data = response.json()

            earthquakes = []
            for feature in data.get('features', []):
                props = feature.get('properties', {})
                coords = feature.get('geometry', {}).get('coordinates', [0, 0, 0])
                distance = self.calculate_distance(coords[1], coords[0])

                earthquakes.append({
                    'magnitude': props.get('mag'),
                    'location': props.get('place'),
                    'depth': coords[2],
                    'timestamp': datetime.fromtimestamp(props['time'] / 1000),
                    'distance': distance,
                    'url': props.get('url'),
                    'felt': props.get('felt', 0),
                    'alert': props.get('alert'),
                    'status': props.get('status', 'automatic'),
                    'latitude': coords[1],
                    'longitude': coords[0],
                    'city': self.city_config['name'],
                    'state': self.city_config['state']
                })
            return earthquakes

        except asyncio.CancelledError:
            logger.info("Earthquake fetch task canceled.")
            return []
        except asyncio.TimeoutError:
            logger.warning("Timeout while fetching earthquake data.")
            return []
        except requests.RequestException as exc:
            logger.error("Error fetching earthquake data: %s", exc, exc_info=True)
            return []
        except (ValueError, KeyError) as exc:
            logger.error("Error parsing earthquake data: %s", exc, exc_info=True)
            return []

    def is_significant(self, magnitude: float, distance: float) -> bool:
        """Determine if an earthquake is significant enough to report."""
        if magnitude is None:
            return False
        if magnitude >= 5.0:
            return True
        if magnitude >= 4.0 and distance <= 50:
            return True
        if magnitude >= 3.0 and distance <= 25:
            return True
        return False

    async def check_earthquakes(self) -> List[Dict[str, Any]]:
        """Check for significant earthquakes."""
        eqs = await self.get_earthquakes()
        return [q for q in eqs if self.is_significant(q['magnitude'], q['distance'])]
