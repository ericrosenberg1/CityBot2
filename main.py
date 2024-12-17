import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any
import os
from pathlib import Path
from dotenv import load_dotenv

from database.operations import DatabaseManager
from monitors.weather import WeatherMonitor
from monitors.earthquake import EarthquakeMonitor
from monitors.news import NewsMonitor
from social_media.manager import SocialMediaManager
from social_media.utils.rate_limiter import RateLimiter
from social_media.utils.image_generator import WeatherMapGenerator
from social_media.utils.map_generator import MapGenerator
from config import load_city_config, get_default_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/citybot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('CityBot2')

class SocialMediaHandler:
    def __init__(self, networks: Dict[str, Any]):
        self.networks = networks
        self.active_networks = {}
        
        for name, config in networks.items():
            try:
                if self._validate_network(name, config):
                    self.active_networks[name] = config
                    logger.info(f"Successfully initialized {name}")
            except Exception as e:
                logger.warning(f"Skipping {name} due to: {str(e)}")
                
    def _validate_network(self, name: str, config: Dict) -> bool:
        validators = {
            "twitter": ["api_key", "api_secret"],
            "facebook": ["page_id", "access_token"],
            "bluesky": ["handle", "password"],
            "linkedin": ["client_id", "client_secret", "access_token"],
            "reddit": ["client_id", "client_secret", "username", "password"],
            "instagram": ["username", "password"]
        }
        return name in validators and all(k in config for k in validators[name])

    async def post_content(self, content: Dict[str, Any]) -> Dict[str, bool]:
        results = {}
        for name, network in self.active_networks.items():
            try:
                success = await self._post_to_network(name, network, content)
                results[name] = success
                logger.info(f"Posted to {name}: {success}")
            except Exception as e:
                logger.error(f"Failed to post to {name}: {str(e)}")
                results[name] = False
        return results

    async def _post_to_network(self, name: str, network: Dict, content: Dict) -> bool:
        # Implement posting logic per network
        pass

class CityBot:
    def __init__(self):
        try:
            load_dotenv('credentials.env')
            
            cities_dir = Path('config/cities')
            city_files = list(cities_dir.glob('*.json'))
            if not city_files:
                raise FileNotFoundError("No city configuration files found")
            
            city_name = city_files[0].stem
            
            self.config = get_default_config()
            self.city_config = load_city_config(city_name)
            logger.info(f"Loaded configuration for {self.city_config['name']}, {self.city_config['state']}")

            self.social_config = {}
            platforms = {
                'bluesky': ['BLUESKY_HANDLE', 'BLUESKY_PASSWORD'],
                'twitter': ['TWITTER_API_KEY', 'TWITTER_API_SECRET', 'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_SECRET'],
                'facebook': ['FACEBOOK_PAGE_ID', 'FACEBOOK_ACCESS_TOKEN'],
                'linkedin': ['LINKEDIN_CLIENT_ID', 'LINKEDIN_CLIENT_SECRET', 'LINKEDIN_ACCESS_TOKEN'],
                'reddit': ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET', 'REDDIT_USERNAME', 'REDDIT_PASSWORD'],
                'instagram': ['INSTAGRAM_USERNAME', 'INSTAGRAM_PASSWORD']
            }
            
            for platform, keys in platforms.items():
                if all(os.getenv(key) for key in keys):
                    self.social_config[platform] = {
                        k.lower().split('_')[-1]: os.getenv(key) 
                        for k, key in zip(['handle', 'password', 'api_key', 'api_secret', 
                                         'access_token', 'access_token_secret', 'page_id', 
                                         'client_id', 'client_secret', 'username'], keys)
                    }

            self.post_intervals = {
                'news': int(os.getenv('NEWS_POST_INTERVAL', 3600)),
                'weather': int(os.getenv('WEATHER_POST_INTERVAL', 21600)),
                'minimum': int(os.getenv('MINIMUM_POST_INTERVAL', 300))
            }

            self._initialize_components()

        except Exception as e:
            logger.error(f"Error initializing CityBot: {str(e)}")
            raise

    def _initialize_components(self):
        weather_config = {
            **self.config['weather'],
            'coordinates': self.city_config['coordinates'],
            'radar_station': self.city_config['weather']['radar_station'],
            'zone_code': self.city_config['weather']['zone_code'],
            'description': self.city_config['weather']['description']
        }
        
        earthquake_config = {
            **self.config['earthquake'],
            'coordinates': self.city_config['coordinates']
        }
        
        news_config = {
            **self.config['news'],
            'rss_feeds': self.city_config['news']['rss_feeds'],
            'location_keywords': self.city_config['news']['location_keywords']
        }
        
        self.db = DatabaseManager()
        self.weather_monitor = WeatherMonitor(weather_config, self.city_config)
        self.earthquake_monitor = EarthquakeMonitor(earthquake_config, self.city_config)
        self.news_monitor = NewsMonitor(news_config, self.city_config)
        
        self.social_handler = SocialMediaHandler(self.social_config)
        self.social_media = SocialMediaManager(
            {'platforms': self.social_config}, 
            {'name': self.city_config['name'], 'state': self.city_config['state']}
        )

        self.rate_limiter = RateLimiter()
        
        # Use radar settings from env or city config
        self.weather_map_generator = WeatherMapGenerator(
            config={
                'coordinates': self.city_config['coordinates'],
                'radar_zoom': int(os.getenv('RADAR_ZOOM_LEVEL', 8)),
                'radar_lat': float(os.getenv('RADAR_CENTER_LAT', self.city_config['coordinates']['latitude'])),
                'radar_lon': float(os.getenv('RADAR_CENTER_LON', self.city_config['coordinates']['longitude']))
            }
        )
        self.map_generator = MapGenerator(config={'coordinates': self.city_config['coordinates']})
        
        signal.signal(signal.SIGINT, self.shutdown_handler)
        signal.signal(signal.SIGTERM, self.shutdown_handler)
        self.tasks = []
        self.running = True

    def shutdown_handler(self, signum, frame):
        logger.info("Shutdown signal received. Cleaning up...")
        self.running = False
        for task in self.tasks:
            task.cancel()
        self.cleanup()
        logger.info("Shutdown complete.")
        sys.exit(0)

    def cleanup(self):
        try:
            self.db.cleanup_old_records()
            self.rate_limiter.cleanup_old_records()
            
            cleanup_time = datetime.now() - timedelta(days=7)
            for directory in ['cache/weather_maps', 'cache/maps']:
                if os.path.exists(directory):
                    for file in os.listdir(directory):
                        file_path = os.path.join(directory, file)
                        if datetime.fromtimestamp(os.path.getctime(file_path)) < cleanup_time:
                            os.remove(file_path)
            
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def weather_task(self):
        while self.running:
            try:
                conditions = await self.weather_monitor.get_current_conditions()
                if conditions:
                    map_path = self.weather_map_generator.generate_weather_map(conditions)
                    if map_path:
                        conditions['map_path'] = map_path
                    
                    if self.rate_limiter.can_post('weather', 'regular'):
                        await self.social_handler.post_content({
                            'type': 'weather',
                            'data': conditions
                        })
                        self.rate_limiter.record_post('weather', 'regular')

                alerts = await self.weather_monitor.get_alerts()
                for alert in alerts:
                    if self.rate_limiter.can_post('weather', 'alert'):
                        await self.social_handler.post_content({
                            'type': 'weather_alert',
                            'data': alert
                        })
                        self.rate_limiter.record_post('weather', 'alert')

            except Exception as e:
                logger.error(f"Error in weather task: {str(e)}")

            await asyncio.sleep(self.config['weather']['update_interval'])

    async def earthquake_task(self):
        while self.running:
            try:
                earthquakes = await self.earthquake_monitor.get_earthquakes()
                for quake in earthquakes:
                    if self.rate_limiter.can_post('earthquake', 'alert'):
                        map_path = self.map_generator.generate_earthquake_map(quake)
                        if map_path:
                            quake['map_path'] = map_path
                        await self.social_handler.post_content({
                            'type': 'earthquake',
                            'data': quake
                        })
                        self.rate_limiter.record_post('earthquake', 'alert')

            except Exception as e:
                logger.error(f"Error in earthquake task: {str(e)}")

            await asyncio.sleep(self.config['earthquake']['check_interval'])

    async def news_task(self):
        while self.running:
            try:
                articles = await self.news_monitor.check_news()
                for article in articles:
                    if self.rate_limiter.can_post('news', 'regular'):
                        if 'location_data' in article:
                            map_path = self.map_generator.generate_news_map(article['location_data'])
                            if map_path:
                                article['map_path'] = map_path
                        await self.social_handler.post_content({
                            'type': 'news',
                            'data': article
                        })
                        self.rate_limiter.record_post('news', 'regular')

            except Exception as e:
                logger.error(f"Error in news task: {str(e)}")

            await asyncio.sleep(self.config['news']['check_interval'])

    async def maintenance_task(self):
        while self.running:
            try:
                self.cleanup()
            except Exception as e:
                logger.error(f"Error in maintenance task: {str(e)}")
            await asyncio.sleep(self.config['maintenance']['cleanup_interval'])

    async def run(self):
        logger.info(f"Starting CityBot for {self.city_config['name']}...")
        try:
            await self.weather_monitor.initialize()
            self.tasks = [
                asyncio.create_task(self.weather_task()),
                asyncio.create_task(self.earthquake_task()),
                asyncio.create_task(self.news_task()),
                asyncio.create_task(self.maintenance_task())
            ]
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            logger.info("Bot tasks cancelled")
        except Exception as e:
            logger.error(f"Error running bot: {str(e)}")
            raise

if __name__ == "__main__":
    for directory in ['logs', 'data', 'cache/weather_maps', 'cache/maps']:
        os.makedirs(directory, exist_ok=True)

    bot = CityBot()
    asyncio.run(bot.run())