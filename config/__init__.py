import json
import os
from typing import Dict

def load_city_config(city_name: str) -> Dict:
    """Load configuration for a specific city."""
    config_path = os.path.join(os.path.dirname(__file__), 'cities', f'{city_name}.json')
    
    if not os.path.exists(config_path):
        raise ValueError(f"No configuration found for city: {city_name}")
    
    with open(config_path) as f:
        return json.load(f)