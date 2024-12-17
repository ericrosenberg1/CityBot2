from typing import Dict
import json
import os

DEFAULT_CONFIG = {
    "weather": {
        "update_interval": 21600,
        "alert_check_interval": 900,
        "radar_update_interval": 900
    },
    "earthquake": {
        "check_interval": 300,
        "minimum_magnitude": 3.0,
        "radius_miles": 100
    },
    "news": {
        "check_interval": 1800,
        "max_daily_posts": 24,
        "minimum_relevance_score": 0.7
    },
    "maintenance": {
        "cleanup_interval": 86400,
        "retention_days": 7
    },
    "cache": {
        "weather_maps_dir": "cache/weather_maps",
        "max_cache_age": 604800
    },
    "social": {
        "default_hashtags": {
            "weather": ["Weather", "CaWeather"],
            "earthquake": ["Earthquake", "CaliforniaEarthquake"],
            "news": ["LocalNews", "California"]
        }
    }
}

def get_default_config() -> Dict:
    return DEFAULT_CONFIG

def load_city_config(city_name: str) -> Dict:
    """Load city-specific configuration from file."""
    config_path = os.path.join('config', 'cities', f'{city_name}.json')
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"City configuration not found: {config_path}")
        
    city_config = json.load(open(config_path))
    if 'social' not in city_config:
        city_config['social'] = {'hashtags': {}}
    
    # Merge default hashtags with city-specific ones
    for category in DEFAULT_CONFIG['social']['default_hashtags']:
        city_config['social']['hashtags'][category] = (
            [f"{city_config['name']}Weather", f"{city_config['name']}CA"] + 
            DEFAULT_CONFIG['social']['default_hashtags'][category]
        )
    
    return city_config