import folium
import requests
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
import os

logger = logging.getLogger('CityBot2.map_generator')

class MapGenerator:
    def __init__(self, cache_dir: str = "cache/maps", config: Dict = None):
        self.cache_dir = cache_dir
        self.config = config or {}
        os.makedirs(cache_dir, exist_ok=True)
        
        # City coordinates
        self.city_center = (
            self.config.get('latitude', 34.2805),
            self.config.get('longitude', -119.2945)
        )
        self.city_name = self.config.get('city', 'City')
        self.zoom_level = self.config.get('zoom_level', 11)

    def generate_earthquake_map(self, quake_data: Dict) -> Optional[str]:
        """Generate a map showing earthquake location relative to city."""
        try:
            # Create map centered between city and earthquake
            quake_lat = float(quake_data['latitude'])
            quake_lon = float(quake_data['longitude'])
            
            center_lat = (self.city_center[0] + quake_lat) / 2
            center_lon = (self.city_center[1] + quake_lon) / 2
            
            # Create the map
            m = folium.Map(location=[center_lat, center_lon], 
                          zoom_start=self.calculate_zoom_level(quake_data['distance']))

            # Add city marker
            folium.Marker(
                self.city_center,
                popup=f'{self.city_name}',
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(m)

            # Add earthquake marker
            magnitude = float(quake_data['magnitude'])
            color = self.get_magnitude_color(magnitude)
            
            folium.Marker(
                [quake_lat, quake_lon],
                popup=f"M{magnitude} Earthquake<br>{quake_data['location']}<br>"
                      f"Depth: {quake_data['depth']}km",
                icon=folium.Icon(color=color, icon='warning-sign')
            ).add_to(m)

            # Add line connecting points
            folium.PolyLine(
                locations=[self.city_center, [quake_lat, quake_lon]],
                weight=2,
                color='red',
                opacity=0.8
            ).add_to(m)

            # Add distance circle
            folium.Circle(
                radius=quake_data['distance'] * 1609.34,  # Convert miles to meters
                location=self.city_center,
                popup=f"{quake_data['distance']:.1f} miles",
                color="red",
                fill=True,
                opacity=0.2
            ).add_to(m)

            # Save map
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = os.path.join(self.cache_dir, 
                                     f"earthquake_map_{timestamp}.html")
            m.save(output_path)

            # Convert to image
            image_path = self.html_to_image(output_path)
            return image_path

        except Exception as e:
            logger.error(f"Error generating earthquake map: {str(e)}")
            return None

    def calculate_zoom_level(self, distance: float) -> int:
        """Calculate appropriate zoom level based on distance."""
        if distance <= 25:
            return 10
        elif distance <= 50:
            return 9
        elif distance <= 100:
            return 8
        else:
            return 7

    def get_magnitude_color(self, magnitude: float) -> str:
        """Determine marker color based on earthquake magnitude."""
        if magnitude >= 5.0:
            return 'red'
        elif magnitude >= 4.0:
            return 'orange'
        else:
            return 'yellow'

    def html_to_image(self, html_path: str) -> Optional[str]:
        """Convert HTML map to image using cutycapt or similar tool."""
        try:
            image_path = html_path.replace('.html', '.png')
            os.system(f'cutycapt --url=file://{html_path} --out={image_path}')
            return image_path
        except Exception as e:
            logger.error(f"Error converting map to image: {str(e)}")
            return None

    def generate_news_map(self, location_data: Dict) -> Optional[str]:
        """Generate a map for news events with specific locations."""
        try:
            m = folium.Map(location=self.city_center, zoom_start=self.zoom_level)

            # Add event location marker
            folium.Marker(
                [location_data['latitude'], location_data['longitude']],
                popup=location_data['description'],
                icon=folium.Icon(color='red', icon='info-sign')
            ).add_to(m)

            # Add city center marker for reference
            folium.Marker(
                self.city_center,
                popup=self.city_name,
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(m)

            # Save map
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = os.path.join(self.cache_dir, 
                                     f"news_map_{timestamp}.html")
            m.save(output_path)

            # Convert to image
            return self.html_to_image(output_path)

        except Exception as e:
            logger.error(f"Error generating news map: {str(e)}")
            return None