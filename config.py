"""Configuration management module for CityBot2."""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass

from dotenv import load_dotenv

logger = logging.getLogger('CityBot2.config')

@dataclass
class SocialNetworkConfig:
    """Configuration for a social network."""
    enabled: bool
    credentials: Dict[str, str]
    post_types: List[str]
    rate_limits: Dict[str, int]


class ConfigurationManager:
    """Manages all application configuration."""

    DEFAULT_CONFIG = {
        "weather": {
            "update_interval": 21600,  # 6 hours
            "alert_check_interval": 900,  # 15 minutes
            "radar_update_interval": 900,  # 15 minutes
            "default_hashtags": ["Weather", "CaWeather"]
        },
        "earthquake": {
            "check_interval": 300,  # 5 minutes
            "minimum_magnitude": 3.0,
            "radius_miles": 100,
            "default_hashtags": ["Earthquake", "CaliforniaEarthquake"]
        },
        "news": {
            "check_interval": 1800,  # 30 minutes
            "max_daily_posts": 24,
            "minimum_relevance_score": 0.7,
            "default_hashtags": ["LocalNews", "California"]
        },
        "maintenance": {
            "cleanup_interval": 86400,  # 24 hours
            "retention_days": 7
        },
        "cache": {
            "weather_maps_dir": "cache/weather_maps",
            "maps_dir": "cache/maps",
            "max_age_days": 7
        },
        "rate_limits": {
            "default": {
                "posts_per_hour": 10,
                "posts_per_day": 24,
                "minimum_interval": 300
            }
        }
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

    def _load_city_config(self) -> Dict:
        """Load city configuration based on CITY_NAME environment variable."""
        city_name = os.getenv("CITY_NAME")
        if not city_name:
            raise ValueError("CITY_NAME environment variable not set")

        config_path = Path("config/cities") / f"{city_name}.json"
        if not config_path.exists():
            raise FileNotFoundError(f"City configuration not found: {config_path}")

        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
            self._validate_city_config(config)
            return self._merge_with_defaults(config)

    def _merge_with_defaults(self, config: Dict) -> Dict:
        """Merge city-specific config with default values."""
        merged = config.copy()

        if 'social' not in merged:
            merged['social'] = {'hashtags': {}}

        for category in ['weather', 'earthquake', 'news']:
            merged['social']['hashtags'][category] = (
                [f"{merged['name']}{category.capitalize()}", f"{merged['name']}{merged['state']}"]
                + self.DEFAULT_CONFIG[category]['default_hashtags']
            )

        return merged

    def _validate_city_config(self, config: Dict) -> None:
        """Validate required city configuration fields."""
        required = {
            "name": str,
            "state": str,
            "coordinates": {
                "latitude": (float, int),
                "longitude": (float, int)
            },
            "weather": {
                "radar_station": str,
                "zone_code": str,
                "description": str
            },
            "news": {
                "rss_feeds": dict,
                "location_keywords": {
                    "must_include": list,
                    "at_least_one": list,
                    "exclude": list
                }
            }
        }

        self._validate_structure(config, required)

    def _validate_structure(self, data: Dict, structure: Dict, path: str = "") -> None:
        """Recursively validate configuration structure."""
        for key, expected_type in structure.items():
            if key not in data:
                raise ValueError(f"Missing required field: {path}{key}")

            if isinstance(expected_type, dict):
                if not isinstance(data[key], dict):
                    raise ValueError(f"Invalid type for {path}{key}: expected dict")
                self._validate_structure(data[key], expected_type, f"{path}{key}.")
            else:
                valid_types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
                if not isinstance(data[key], valid_types):
                    raise ValueError(
                        f"Invalid type for {path}{key}: expected {valid_types}, got {type(data[key])}"
                    )

    def _initialize_social_networks(self) -> Dict[str, SocialNetworkConfig]:
        """Initialize configuration for each social network."""
        networks = {}

        network_configs = {
            'twitter': {
                'required_vars': [
                    'TWITTER_API_KEY',
                    'TWITTER_API_SECRET',
                    'TWITTER_ACCESS_TOKEN',
                    'TWITTER_ACCESS_SECRET'
                ],
                'credentials_map': {
                    'api_key': 'TWITTER_API_KEY',
                    'api_secret': 'TWITTER_API_SECRET',
                    'access_token': 'TWITTER_ACCESS_TOKEN',
                    'access_secret': 'TWITTER_ACCESS_SECRET'
                }
            },
            'bluesky': {
                'required_vars': ['BLUESKY_HANDLE', 'BLUESKY_PASSWORD'],
                'credentials_map': {
                    'handle': 'BLUESKY_HANDLE',
                    'password': 'BLUESKY_PASSWORD'
                }
            },
            'facebook': {
                'required_vars': ['FACEBOOK_PAGE_ID', 'FACEBOOK_ACCESS_TOKEN'],
                'credentials_map': {
                    'page_id': 'FACEBOOK_PAGE_ID',
                    'access_token': 'FACEBOOK_ACCESS_TOKEN'
                }
            },
            'linkedin': {
                'required_vars': [
                    'LINKEDIN_CLIENT_ID',
                    'LINKEDIN_CLIENT_SECRET',
                    'LINKEDIN_ACCESS_TOKEN'
                ],
                'credentials_map': {
                    'client_id': 'LINKEDIN_CLIENT_ID',
                    'client_secret': 'LINKEDIN_CLIENT_SECRET',
                    'access_token': 'LINKEDIN_ACCESS_TOKEN'
                }
            },
            'reddit': {
                'required_vars': [
                    'REDDIT_CLIENT_ID',
                    'REDDIT_CLIENT_SECRET',
                    'REDDIT_USERNAME',
                    'REDDIT_PASSWORD'
                ],
                'credentials_map': {
                    'client_id': 'REDDIT_CLIENT_ID',
                    'client_secret': 'REDDIT_CLIENT_SECRET',
                    'username': 'REDDIT_USERNAME',
                    'password': 'REDDIT_PASSWORD'
                }
            }
        }

        for network, config in network_configs.items():
            if all(os.getenv(var) for var in config['required_vars']):
                credentials = {
                    cred_key: os.getenv(env_var)
                    for cred_key, env_var in config['credentials_map'].items()
                }

                # Get rate limits as strings and convert to int if available, else use defaults
                posts_per_hour_str = os.getenv(f'{network.upper()}_POSTS_PER_HOUR')
                posts_per_hour = int(posts_per_hour_str) if posts_per_hour_str else self.DEFAULT_CONFIG['rate_limits']['default']['posts_per_hour']

                posts_per_day_str = os.getenv(f'{network.upper()}_POSTS_PER_DAY')
                posts_per_day = int(posts_per_day_str) if posts_per_day_str else self.DEFAULT_CONFIG['rate_limits']['default']['posts_per_day']

                minimum_interval_str = os.getenv(f'{network.upper()}_MINIMUM_INTERVAL')
                minimum_interval = int(minimum_interval_str) if minimum_interval_str else self.DEFAULT_CONFIG['rate_limits']['default']['minimum_interval']

                networks[network] = SocialNetworkConfig(
                    enabled=True,
                    credentials=credentials,
                    post_types=['weather', 'earthquake', 'news'],
                    rate_limits={
                        'posts_per_hour': posts_per_hour,
                        'posts_per_day': posts_per_day,
                        'minimum_interval': minimum_interval
                    }
                )

        return networks

    def _validate_all_configs(self) -> None:
        """Validate all configurations are consistent."""
        for network, config in self.social_networks.items():
            if not all(config.credentials.values()):
                raise ValueError(f"Invalid credentials for {network}")

    def get_social_network_config(self, network: str) -> Optional[SocialNetworkConfig]:
        """Get configuration for a specific social network."""
        return self.social_networks.get(network)

    def get_enabled_networks(self) -> List[str]:
        """Get list of enabled social networks."""
        return [name for name, config in self.social_networks.items() if config.enabled]

    def get_config(self, section: str) -> Dict:
        """Get configuration for a specific section."""
        return self.DEFAULT_CONFIG.get(section, {})

    def get_interval(self, task_type: str) -> int:
        """Get update interval for a specific task type."""
        interval_str = os.getenv(
            f'{task_type.upper()}_UPDATE_INTERVAL'
        )
        if interval_str is not None and interval_str.isdigit():
            return int(interval_str)
        return self.DEFAULT_CONFIG.get(task_type, {}).get('update_interval', 3600)


def get_default_config() -> Dict:
    """Get default configuration (for backwards compatibility)."""
    return ConfigurationManager.DEFAULT_CONFIG


def load_city_config(city_name: str = None) -> Dict:
    """Load city configuration (for backwards compatibility)."""
    if city_name is not None:
        os.environ['CITY_NAME'] = city_name
    config_manager = ConfigurationManager()
    return config_manager.city_config
