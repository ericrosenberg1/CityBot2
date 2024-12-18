import asyncio
import logging
import math
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import requests
import folium

from social_media.utils import PostContent, MediaContent

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
        lat1 = math.radians(self.city_lat)
        lon1 = math.radians(self.city_lon)
        lat2 = math.radians(lat)
        lon2 = math.radians(lon)

        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

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
                props = feature['properties']
                coords = feature['geometry']['coordinates']
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
            logger.error("Error fetching earthquake data (requests): %s", exc, exc_info=True)
            return []
        except (ValueError, KeyError) as exc:
            logger.error("Error parsing earthquake data: %s", exc, exc_info=True)
            return []
        except Exception as exc:
            logger.error("Unexpected error in get_earthquakes: %s", exc, exc_info=True)
            return []

    def is_significant(self, magnitude: float, distance: float) -> bool:
        """Determine if an earthquake is significant enough to report."""
        if magnitude is None:
            return False
        if magnitude >= 5.0:
            return True
        elif magnitude >= 4.0 and distance <= 50:
            return True
        elif magnitude >= 3.0 and distance <= 25:
            return True
        return False

    async def check_earthquakes(self) -> List[Dict[str, Any]]:
        """Check for significant earthquakes."""
        eqs = await self.get_earthquakes()
        return [quake for quake in eqs if self.is_significant(quake['magnitude'], quake['distance'])]

    def generate_earthquake_map(self, quake_data: Dict[str, Any]) -> Optional[str]:
        """Generate earthquake location map."""
        try:
            center_lat = (self.city_config['coordinates']['latitude'] + float(quake_data['latitude'])) / 2
            center_lon = (self.city_config['coordinates']['longitude'] + float(quake_data['longitude'])) / 2

            zoom = self._calculate_zoom(quake_data['distance'])
            m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom)

            folium.Marker(
                [self.city_config['coordinates']['latitude'],
                 self.city_config['coordinates']['longitude']],
                popup=self.city_config.get('city', 'City'),
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
                    [self.city_config['coordinates']['latitude'],
                     self.city_config['coordinates']['longitude']],
                    [quake_data['latitude'], quake_data['longitude']]
                ],
                weight=2,
                color='red'
            ).add_to(m)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            cache_dir = "cache/maps"
            os.makedirs(cache_dir, exist_ok=True)
            html_path = os.path.join(cache_dir, f"earthquake_map_{timestamp}.html")
            image_path = html_path.replace('.html', '.png')

            m.save(html_path)
            cmd = 'cutycapt --url=file://%s --out=%s' % (html_path, image_path)
            os.system(cmd)

            if os.path.exists(html_path):
                os.unlink(html_path)

            return image_path

        except (OSError, ValueError) as exc:
            logger.error("Error creating earthquake map: %s", exc, exc_info=True)
            return None
        except Exception as exc:
            logger.error("Error creating earthquake map: %s", exc, exc_info=True)
            return None

    def _calculate_zoom(self, distance: float) -> int:
        """Calculate appropriate zoom level based on distance."""
        if distance <= 25:
            return 10
        if distance <= 50:
            return 9
        if distance <= 100:
            return 8
        return 7


def format_earthquake_for_social(quake_data: Dict[str, Any], hashtags: List[str]) -> PostContent:
    """Format earthquake update content into a PostContent object."""
    logger = logging.getLogger('CityBot2.earthquake_formatter')
    try:
        magnitude = quake_data.get('magnitude')
        location = quake_data.get('location')
        depth = quake_data.get('depth')
        distance = quake_data.get('distance')
        city = quake_data.get('city')
        state = quake_data.get('state')
        url = quake_data.get('url')

        if magnitude is None:
            magnitude_emoji = "🟢"
        elif magnitude >= 5.0:
            magnitude_emoji = "🔴"
        elif magnitude >= 4.0:
            magnitude_emoji = "🟡"
        else:
            magnitude_emoji = "🟢"

        hashtag_text = ' '.join(f"#{tag}" for tag in hashtags)
        text = (
            f"{magnitude_emoji} EARTHQUAKE REPORT {magnitude_emoji}\n\n"
            f"Magnitude: {magnitude}\n"
            f"Location: {location}\n"
            f"Depth: {depth:.1f} km\n"
            f"Distance from {city}: {distance:.1f} miles\n\n"
            f"{hashtag_text}"
        )

        # Optionally generate map here using EarthquakeMonitor if you have city_config
        # Skipped for now. If needed, instantiate EarthquakeMonitor with city_config and call generate_earthquake_map.
        map_path = quake_data.get('map_path')

        return PostContent(
            text=text,
            media=MediaContent(
                image_path=map_path,
                link_url=url,
                meta_title=f"M{magnitude} Earthquake near {city}, {state}",
                meta_description=f"Earthquake detected {distance:.1f} miles from {city}"
            )
        )
    except Exception as e:
        logger.error("Error formatting earthquake content: %s", e, exc_info=True)
        raise
