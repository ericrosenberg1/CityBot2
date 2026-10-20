"""Monitor and retrieve weather data and generate weather maps."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

import aiohttp

from utils.maps import WeatherMapGenerator

logger = logging.getLogger("CityBot2.weather")


@dataclass
class WeatherData:
    """Weather data container."""

    temperature: float | None
    wind_speed: float | None
    wind_direction: str
    cloud_cover: int
    forecast: str
    timestamp: datetime
    city: str
    state: str
    map_path: str | None = None


@dataclass
class WeatherAlert:
    """Weather alert container."""

    event: str
    headline: str
    description: str
    severity: str
    urgency: str
    areas: str
    onset: datetime | None
    expires: datetime | None
    city: str
    state: str
    alert_id: str | None = None


class WeatherMonitor:
    """Monitors weather conditions and generates weather maps."""

    def __init__(self, config: dict, city_config: dict):
        self.config = config
        self.city_config = city_config
        self.latitude = city_config["coordinates"]["latitude"]
        self.longitude = city_config["coordinates"]["longitude"]
        self.base_url = "https://api.weather.gov"
        self.headers = {"User-Agent": "CityBot2/1.0", "Accept": "application/geo+json"}
        self.grid_info = None
        self.zone_code = city_config["weather"]["zone_code"]
        self.map_generator = WeatherMapGenerator(city_config)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self):
        """Get or create a reusable aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def initialize(self) -> None:
        """Initialize the weather monitor."""
        if not self.grid_info:
            self.grid_info = await self.get_grid_coordinates()

    async def get_grid_coordinates(self) -> dict | None:
        """Get grid coordinates for the location."""
        url = f"{self.base_url}/points/{self.latitude},{self.longitude}"
        data = await self._fetch_data(url)
        if not data or "properties" not in data:
            logger.error("Failed to get grid coordinates or invalid response format")
            return None
        try:
            return {
                "gridId": data["properties"]["gridId"],
                "gridX": data["properties"]["gridX"],
                "gridY": data["properties"]["gridY"],
            }
        except KeyError as exc:
            logger.error("Missing required grid coordinate field: %s", exc)
            return None

    async def _fetch_data(self, url: str) -> dict | None:
        """Fetch data from the weather service."""
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        try:
            session = await self._get_session()
            async with session.get(
                url, headers=self.headers, timeout=timeout
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(
                    "Failed to fetch data from %s, Status: %d", url, response.status
                )
                return None
        except TimeoutError:
            logger.error("Timeout fetching %s", url)
            return None
        except aiohttp.ClientError as exc:
            logger.error("Network error fetching %s: %s", url, exc)
            return None

    def _convert_temperature(self, celsius_value: float | None) -> float | None:
        """Convert Celsius to Fahrenheit."""
        if celsius_value is None:
            return None
        try:
            return (celsius_value * 9 / 5) + 32
        except (TypeError, ValueError):
            return None

    def _convert_wind_speed(self, mps_value: float | None) -> float | None:
        """Convert m/s to mph."""
        if mps_value is None:
            return None
        try:
            return mps_value * 2.237
        except (TypeError, ValueError):
            return None

    # NWS reports cloud layers as METAR sky-cover codes, measured in eighths
    # of the sky. These are the midpoints of each code's range, as percents.
    CLOUD_AMOUNT_PERCENT: ClassVar[dict[str, int]] = {
        "SKC": 0,
        "CLR": 0,
        "FEW": 19,
        "SCT": 44,
        "BKN": 75,
        "OVC": 100,
        "VV": 100,
    }
    COMPASS_POINTS = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )

    def _get_cloud_cover(self, cloud_layers: list[dict]) -> int:
        """Cloud cover percent from the most-covered layer (0 when clear or unknown)."""
        try:
            return max(
                (
                    self.CLOUD_AMOUNT_PERCENT.get(layer.get("amount"), 0)
                    for layer in cloud_layers
                ),
                default=0,
            )
        except (AttributeError, TypeError):
            return 0

    def _compass_direction(self, degrees) -> str:
        """Turn NWS wind direction degrees into a compass point like 'WSW'."""
        if degrees is None:
            return "Unknown"
        try:
            return self.COMPASS_POINTS[round(float(degrees) / 22.5) % 16]
        except (TypeError, ValueError):
            return "Unknown"

    async def get_current_conditions(self) -> WeatherData | None:
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
                conditions["map_path"] = str(map_path)

            return WeatherData(
                temperature=conditions["temperature"],
                wind_speed=conditions["wind_speed"],
                wind_direction=conditions["wind_direction"],
                cloud_cover=conditions["cloud_cover"],
                forecast=conditions["forecast"],
                timestamp=conditions["timestamp"],
                city=self.city_config["name"],
                state=self.city_config["state"],
                map_path=conditions.get("map_path"),
            )
        return None

    async def _get_current_conditions(self) -> dict | None:
        """Get current weather conditions."""
        if not self.grid_info:
            return None

        forecast_url = (
            f"{self.base_url}/gridpoints/{self.grid_info['gridId']}/"
            f"{self.grid_info['gridX']},{self.grid_info['gridY']}/forecast/hourly"
        )
        forecast_data = await self._fetch_data(forecast_url)
        if not forecast_data or "properties" not in forecast_data:
            return None

        stations_url = (
            f"{self.base_url}/gridpoints/{self.grid_info['gridId']}/"
            f"{self.grid_info['gridX']},{self.grid_info['gridY']}/stations"
        )
        stations_data = await self._fetch_data(stations_url)
        if not stations_data or not stations_data.get("features"):
            return None

        station_id = stations_data["features"][0]["properties"]["stationIdentifier"]
        obs_url = f"{self.base_url}/stations/{station_id}/observations/latest"
        obs_data = await self._fetch_data(obs_url)
        if not obs_data or "properties" not in obs_data:
            return None

        try:
            properties = obs_data["properties"]
            return {
                "temperature": self._convert_temperature(
                    properties.get("temperature", {}).get("value")
                ),
                "wind_speed": self._convert_wind_speed(
                    properties.get("windSpeed", {}).get("value")
                ),
                "wind_direction": self._compass_direction(
                    properties.get("windDirection", {}).get("value")
                ),
                "cloud_cover": self._get_cloud_cover(properties.get("cloudLayers", [])),
                "forecast": forecast_data["properties"]["periods"][0].get(
                    "shortForecast", "No forecast available"
                ),
                "timestamp": datetime.now(UTC),
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Error processing weather data: %s", exc)
            return None

    async def get_alerts(self) -> list[WeatherAlert]:
        """Get active weather alerts."""
        url = f"{self.base_url}/alerts/active/zone/{self.zone_code}"
        data = await self._fetch_data(url)
        if not data:
            return []

        alerts = []
        for feature in data.get("features", []):
            try:
                props = feature["properties"]
                onset_str = props.get("onset")
                expires_str = props.get("expires")
                onset_dt = datetime.fromisoformat(onset_str) if onset_str else None
                expires_dt = (
                    datetime.fromisoformat(expires_str) if expires_str else None
                )

                alerts.append(
                    WeatherAlert(
                        event=props.get("event", "Unknown Event"),
                        headline=props.get("headline", "No headline"),
                        description=props.get("description", ""),
                        severity=props.get("severity", "Unknown"),
                        urgency=props.get("urgency", "Unknown"),
                        areas=props.get("areaDesc", "Unknown"),
                        onset=onset_dt,
                        expires=expires_dt,
                        city=self.city_config["name"],
                        state=self.city_config["state"],
                        alert_id=props.get("id") or feature.get("id"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.error("Error processing alert data: %s", exc)
                continue
        return alerts

    async def cleanup(self) -> None:
        """Cleanup weather-related resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        await self.map_generator.cleanup_old_maps()
