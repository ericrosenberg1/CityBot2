"""Consolidated map generators for CityBot2."""

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import folium
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

logger = logging.getLogger('CityBot2.maps')


class WeatherMapGenerator:
    """Generates weather maps using matplotlib and cartopy."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cache_dir = Path("cache/weather_maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def generate_map(self, weather_data: Dict[str, Any]) -> Optional[str]:
        """Generate weather map with current conditions."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = self.cache_dir / f"weather_map_{timestamp}.png"
            return await asyncio.to_thread(self._create_map, weather_data, str(output_path))
        except (OSError, RuntimeError) as exc:
            logger.error("Error generating weather map: %s", exc)
            return None

    def _create_map(self, weather_data: Dict[str, Any], output_path: str) -> Optional[str]:
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


class LocationMapGenerator:
    """Generates folium-based location maps for earthquakes and news events.

    Uses a unified pattern: folium map with city marker + event marker + optional
    connecting line, rendered to PNG via cutycapt.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cache_dir = Path("cache/maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def generate_location_map(self, location_data: Dict[str, Any]) -> Optional[str]:
        """Generate a location map for any event type (earthquake, news, etc.).

        Args:
            location_data: Dict containing at minimum 'latitude' and 'longitude'
                for the event location. Optional keys:
                - 'description': popup text for event marker (default: 'Event Location')
                - 'magnitude': if present, used for earthquake-style popup
                - 'location': text description used in earthquake popup
                - 'distance': distance from city, used to calculate zoom
                - 'color': marker color for event (default: 'red')
                - 'show_line': whether to draw a line from city to event (default: True)
                - 'map_prefix': filename prefix (default: 'location_map')

        Returns:
            Path to the generated PNG image, or None on failure.
        """
        try:
            return await asyncio.to_thread(self._create_location_map, location_data)
        except (OSError, ValueError) as exc:
            logger.error("Error generating location map: %s", exc, exc_info=True)
            return None
        except Exception as exc:
            logger.error("Error generating location map: %s", exc, exc_info=True)
            return None

    def _create_location_map(self, location_data: Dict[str, Any]) -> Optional[str]:
        """Create a folium location map (runs in thread pool)."""
        city_lat = self.config['coordinates']['latitude']
        city_lon = self.config['coordinates']['longitude']
        event_lat = float(location_data['latitude'])
        event_lon = float(location_data['longitude'])

        # Calculate center and zoom
        center_lat = (city_lat + event_lat) / 2
        center_lon = (city_lon + event_lon) / 2
        distance = location_data.get('distance')
        zoom = self._calculate_zoom(distance) if distance else 12

        m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom)

        # City marker
        folium.Marker(
            [city_lat, city_lon],
            popup=self.config.get('city', self.config.get('name', 'City')),
            icon=folium.Icon(color='blue')
        ).add_to(m)

        # Event marker
        popup_text = self._build_popup(location_data)
        marker_color = location_data.get('color', 'red')
        folium.Marker(
            [event_lat, event_lon],
            popup=popup_text,
            icon=folium.Icon(color=marker_color)
        ).add_to(m)

        # Optional connecting line
        show_line = location_data.get('show_line', True)
        if show_line:
            folium.PolyLine(
                locations=[[city_lat, city_lon], [event_lat, event_lon]],
                weight=2,
                color='red'
            ).add_to(m)

        # Save and convert
        map_prefix = location_data.get('map_prefix', 'location_map')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        html_path = str(self.cache_dir / f"{map_prefix}_{timestamp}.html")
        image_path = html_path.replace('.html', '.png')

        try:
            m.save(html_path)
            if shutil.which('cutycapt'):
                subprocess.run(
                    ['cutycapt', f'--url=file://{html_path}', f'--out={image_path}'],
                    timeout=30, check=False
                )
            else:
                logger.warning("cutycapt not installed, skipping map image generation")

            if os.path.exists(html_path):
                os.unlink(html_path)

            return image_path

        except (OSError, ValueError) as exc:
            logger.error("Error creating location map: %s", exc, exc_info=True)
            if os.path.exists(html_path):
                os.unlink(html_path)
            return None
        except Exception as exc:
            logger.error("Error creating location map: %s", exc, exc_info=True)
            if os.path.exists(html_path):
                os.unlink(html_path)
            return None

    @staticmethod
    def _build_popup(location_data: Dict[str, Any]) -> str:
        """Build popup text based on available data."""
        if 'magnitude' in location_data:
            return "M%s Earthquake<br>%s" % (
                location_data['magnitude'],
                location_data.get('location', 'Unknown')
            )
        return location_data.get('description', 'Event Location')

    @staticmethod
    def _calculate_zoom(distance: Optional[float]) -> int:
        """Calculate appropriate zoom level based on distance in miles."""
        if distance is None:
            return 12
        if distance <= 25:
            return 10
        if distance <= 50:
            return 9
        if distance <= 100:
            return 8
        return 7
