"""Configuration management module for CityBot2."""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from dotenv import load_dotenv

from social_media.social_media_manager import PLATFORM_CLASSES

logger = logging.getLogger("CityBot2.config")


@dataclass
class SocialNetworkConfig:
    """Configuration for a social network."""

    enabled: bool
    credentials: dict[str, str]
    post_types: list[str]
    rate_limits: dict[str, int]


class ConfigurationManager:
    """Manages all application configuration."""

    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "weather": {
            "update_interval": 21600,  # 6 hours
            "alert_check_interval": 900,  # 15 minutes
            "radar_update_interval": 900,  # 15 minutes
            "default_hashtags": ["Weather", "CaWeather"],
        },
        "earthquake": {
            "check_interval": 300,  # 5 minutes
            "minimum_magnitude": 3.0,
            "radius_miles": 100,
            "default_hashtags": ["Earthquake", "CaliforniaEarthquake"],
        },
        "news": {
            "check_interval": 1800,  # 30 minutes
            "max_daily_posts": 24,
            "minimum_relevance_score": 0.7,
            "default_hashtags": ["LocalNews", "California"],
        },
        "maintenance": {
            "cleanup_interval": 86400,  # 24 hours
            "retention_days": 7,
        },
        "cache": {
            "weather_maps_dir": "cache/weather_maps",
            "maps_dir": "cache/maps",
            "max_age_days": 7,
        },
        "rate_limits": {
            "default": {
                "posts_per_hour": 10,
                "posts_per_day": 24,
                "minimum_interval": 300,
            }
        },
    }

    def __init__(self, env_file: str = "credentials.env"):
        """Initialize configuration manager."""
        self._load_environment(env_file)
        self.city_config = self._load_city_config()
        self.social_networks = self._initialize_social_networks()
        self._validate_all_configs()

    def _load_environment(self, env_file: str) -> None:
        """Load environment variables from file."""
        env_path = Path("config") / env_file
        if not env_path.exists():
            raise FileNotFoundError(f"Environment file not found: {env_path}")
        load_dotenv(env_path)

    def _load_city_config(self) -> dict:
        """Load city configuration based on CITY_NAME environment variable."""
        city_name = os.getenv("CITY_NAME")
        if not city_name:
            raise ValueError("CITY_NAME environment variable not set")

        config_path = Path("config/cities") / f"{city_name}.json"
        if not config_path.exists():
            raise FileNotFoundError(f"City configuration not found: {config_path}")

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
            self._validate_city_config(config)
            return self._merge_with_defaults(config)

    def _merge_with_defaults(self, config: dict) -> dict:
        """Merge city-specific config with default values."""
        merged = config.copy()
        hashtags = merged.setdefault("social", {}).setdefault("hashtags", {})

        # Hashtags can't contain spaces, so "San Diego" becomes #SanDiegoWeather.
        city_tag = merged["name"].replace(" ", "")
        for category in ["weather", "earthquake", "news"]:
            hashtags[category] = [
                f"{city_tag}{category.capitalize()}",
                f"{city_tag}{merged['state']}",
            ] + self.DEFAULT_CONFIG[category]["default_hashtags"]

        return merged

    def _validate_city_config(self, config: dict) -> None:
        """Validate required city configuration fields."""
        required = {
            "name": str,
            "state": str,
            "coordinates": {"latitude": (float, int), "longitude": (float, int)},
            "weather": {"radar_station": str, "zone_code": str, "description": str},
            "news": {
                "rss_feeds": dict,
                "location_keywords": {
                    "must_include": list,
                    "at_least_one": list,
                    "exclude": list,
                },
            },
        }

        self._validate_structure(config, required)

    def _validate_structure(self, data: dict, structure: dict, path: str = "") -> None:
        """Recursively validate configuration structure."""
        for key, expected_type in structure.items():
            if key not in data:
                raise ValueError(f"Missing required field: {path}{key}")

            if isinstance(expected_type, dict):
                if not isinstance(data[key], dict):
                    raise TypeError(f"Invalid type for {path}{key}: expected dict")
                self._validate_structure(data[key], expected_type, f"{path}{key}.")
            else:
                valid_types = (
                    expected_type
                    if isinstance(expected_type, tuple)
                    else (expected_type,)
                )
                if not isinstance(data[key], valid_types):
                    raise TypeError(
                        f"Invalid type for {path}{key}: expected {valid_types}, got {type(data[key])}"
                    )

    def _initialize_social_networks(self) -> dict[str, SocialNetworkConfig]:
        """Initialize configuration for each social network."""
        networks = {}

        for network, platform_cls in PLATFORM_CLASSES.items():
            # Check if this platform is enabled
            enabled = os.getenv(f"{network.upper()}_ENABLED", "false").lower() == "true"
            if not enabled:
                continue

            env_vars = platform_cls.credential_env_vars()
            missing_vars = [var for var in env_vars.values() if not os.getenv(var)]
            if missing_vars:
                logger.warning(
                    f"{network.capitalize()} is enabled but missing required environment variables: {missing_vars}"
                )
                continue

            credentials = {field: os.getenv(var) for field, var in env_vars.items()}

            networks[network] = SocialNetworkConfig(
                enabled=True,
                credentials=credentials,
                post_types=list(self.POST_TYPES),
                rate_limits=self.get_rate_limits(network),
            )

        return networks

    # Every content type the post queue can hold.
    POST_TYPES = ("weather", "weather_alert", "earthquake", "news", "announcement")

    def get_rate_limits(self, network: str) -> dict[str, int]:
        """Posting limits for a network in the shape RateLimiter reads.

        {NETWORK}_POSTS_PER_HOUR, _POSTS_PER_DAY and _MINIMUM_INTERVAL override
        the defaults.
        """
        defaults = self.DEFAULT_CONFIG["rate_limits"]["default"]
        limits = {}
        for key, setting in (
            ("hourly", "posts_per_hour"),
            ("daily", "posts_per_day"),
            ("interval", "minimum_interval"),
        ):
            value = (os.getenv(f"{network.upper()}_{setting.upper()}") or "").strip()
            limits[key] = int(value) if value.isdigit() else defaults[setting]
        return limits

    def _validate_all_configs(self) -> None:
        """Validate all configurations are consistent."""
        for network, config in self.social_networks.items():
            if not all(config.credentials.values()):
                raise ValueError(f"Invalid credentials for {network}")

    def get_social_network_config(self, network: str) -> SocialNetworkConfig | None:
        """Get configuration for a specific social network."""
        return self.social_networks.get(network)

    def get_enabled_networks(self) -> list[str]:
        """Get list of enabled social networks."""
        return [name for name, config in self.social_networks.items() if config.enabled]

    def get_config(self, section: str) -> dict:
        """Get configuration for a specific section."""
        return self.DEFAULT_CONFIG.get(section, {})

    # task type -> (env var documented in credentials.env.example, DEFAULT_CONFIG section, key)
    INTERVAL_SETTINGS: ClassVar[dict[str, tuple[str, str, str]]] = {
        "weather": ("WEATHER_UPDATE_INTERVAL", "weather", "update_interval"),
        "weather_alert": ("WEATHER_ALERT_INTERVAL", "weather", "alert_check_interval"),
        "earthquake": ("EARTHQUAKE_CHECK_INTERVAL", "earthquake", "check_interval"),
        "news": ("NEWS_CHECK_INTERVAL", "news", "check_interval"),
        "maintenance": ("MAINTENANCE_INTERVAL", "maintenance", "cleanup_interval"),
    }

    def get_interval(self, task_type: str) -> int:
        """Get the polling interval in seconds for a task type.

        Reads the env var named in credentials.env.example, then the older
        {TASK}_UPDATE_INTERVAL spelling, then the DEFAULT_CONFIG value.
        """
        env_var, section, key = self.INTERVAL_SETTINGS.get(
            task_type, (None, task_type, "update_interval")
        )
        for var in filter(None, (env_var, f"{task_type.upper()}_UPDATE_INTERVAL")):
            value = (os.getenv(var) or "").strip()
            if value.isdigit() and int(value) > 0:
                return int(value)
        return self.DEFAULT_CONFIG.get(section, {}).get(key, 3600)
