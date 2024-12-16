import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
from datetime import datetime
import os
import logging
from typing import Dict, Optional

logger = logging.getLogger('CityBot2.image_generator')

class WeatherMapGenerator:
    def __init__(self, cache_dir: str = "cache/weather_maps", config: Dict = None):
        self.cache_dir = cache_dir
        self.config = config or {}
        os.makedirs(cache_dir, exist_ok=True)
        
        # Get coordinates from config or use defaults
        self.center_lat = self.config.get('latitude', 34.2805)
        self.center_lon = self.config.get('longitude', -119.2945)
        
        # Map boundaries (roughly 100 mile radius)
        self.lat_range = 1.5  # degrees
        self.lon_range = 1.5  # degrees
        
        # Load custom fonts if available
        self.font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'OpenSans-Regular.ttf')
        if not os.path.exists(self.font_path):
            self.font_path = None

    def generate_weather_map(self, weather_data: Dict[str, any]) -> Optional[str]:
        """Generate weather map with current conditions."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = os.path.join(self.cache_dir, f"weather_map_{timestamp}.png")

            # Create the map
            fig = plt.figure(figsize=(12, 8))
            ax = plt.axes(projection=ccrs.PlateCarree())

            # Set map extent
            ax.set_extent([
                self.center_lon - self.lon_range,
                self.center_lon + self.lon_range,
                self.center_lat - self.lat_range,
                self.center_lat + self.lat_range
            ])

            # Add map features
            ax.add_feature(cfeature.COASTLINE)
            ax.add_feature(cfeature.STATES)
            ax.add_feature(cfeature.LAND, facecolor='lightgray')
            ax.add_feature(cfeature.OCEAN, facecolor='lightblue')
            ax.add_feature(cfeature.LAKES, alpha=0.5)
            
            # Add weather radar overlay
            self._add_radar_overlay(ax)
            
            # Add city marker
            ax.plot(self.center_lon, self.center_lat, 'ro', markersize=10, 
                   transform=ccrs.PlateCarree(), label=self.config.get('city', 'City'))
            
            # Add weather info
            info_text = (
                f"Temperature: {weather_data['temperature']}°F\n"
                f"Wind: {weather_data['wind_speed']}mph {weather_data['wind_direction']}\n"
                f"Cloud Cover: {weather_data['cloud_cover']}%\n"
                f"{weather_data['forecast']}"
            )
            plt.text(0.02, 0.98, info_text, transform=ax.transAxes, 
                    bbox=dict(facecolor='white', alpha=0.7),
                    verticalalignment='top')

            # Add timestamp and attribution
            plt.text(0.98, 0.02, 
                    f"Generated: {timestamp}\nData: National Weather Service",
                    transform=ax.transAxes, 
                    horizontalalignment='right',
                    bbox=dict(facecolor='white', alpha=0.7))

            # Add legend
            plt.legend(loc='upper right')

            # Save the map
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()

            # Add post-processing effects
            self._enhance_image(output_path)

            logger.info(f"Generated