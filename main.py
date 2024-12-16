import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any
import json
import os
from pathlib import Path

from database.operations import DatabaseManager
from monitors.weather import WeatherMonitor
from monitors.earthquake import EarthquakeMonitor
from monitors.news import NewsMonitor
from social_media.manager import SocialMediaManager
from social_media.utils.rate_limiter import RateLimiter
from social_media.utils.image_generator import WeatherMapGenerator
from social_media.utils.map_generator import MapGenerator
from config import load_city_config

# Configure logging
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
        if name == "twitter":
            return all(k in config for k in ["api_key", "api_secret"])
        elif name == "facebook":
            return all(k in config for k in ["access_token"])
        return False

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
        # Implement actual posting logic here
        pass

class CityBot:
    def __init__(self, city_name: str = "ventura"):
        """Initialize the bot and its components."""
        try:
            # Load configurations
            with open('config/config.json') as f:
                self.config = json.load(f)

            with open('config/social_config.json') as f:
                self.social_config = json.load(f)

            # Load city-specific configuration
            self.city_config = load_city_config(city_name)
            logger.info(f"Loaded configuration for {self.city_config['name']}, {self.city_config['state']}")

            # Initialize components with city configuration
            self.db = DatabaseManager()
            self.weather_monitor = WeatherMonitor(self.config['weather'], self.city_config)
            self.earthquake_monitor = EarthquakeMonitor(self.config['earthquake'], self.city_config)
            self.news_monitor = NewsMonitor(self.config['news'], self.city_config)
            
            # Initialize social media components with error handling
            self.social_handler = SocialMediaHandler(self.social_config)
            self.social_media = SocialMediaManager(self.social_config, self.city_config)
            self.rate_limiter = RateLimiter()
            self.weather_map_generator = WeatherMapGenerator(config=self.city_config)
            self.map_generator = MapGenerator(config=self.city_config)

            # Set up shutdown handler
            signal.signal(signal.SIGINT, self.shutdown_handler)
            signal.signal(signal.SIGTERM, self.shutdown_handler)

            # Initialize task tracking
            self.tasks = []
            self.running = True

            logger.info(f"CityBot initialized successfully for {self.city_config['name']}")

        except Exception as e:
            logger.error(f"Error initializing CityBot: {str(e)}")
            raise

    def shutdown_handler(self, signum, frame):
        """Handle graceful shutdown."""
        logger.info("Shutdown signal received. Cleaning up...")
        self.running = False
        for task in self.tasks:
            task.cancel()
        
        # Perform cleanup
        self.cleanup()
        
        logger.info("Shutdown complete.")
        sys.exit(0)

    def cleanup(self):
        """Perform cleanup operations."""
        try:
            # Clean up old records
            self.db.cleanup_old_records()
            self.rate_limiter.cleanup_old_records()
            
            # Clean up old maps and images
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
        """Regular weather updates task."""
        while self.running:
            try:
                conditions = await self.weather_monitor.get_current_conditions()
                if conditions:
                    map_path = self.weather_map_generator.generate_weather_map(conditions)
                    if map_path:
                        conditions['map_path'] = map_path
                    
                    if self.rate_limiter.can_post('weather', 'regular'):
                        post_results = await self.social_handler.post_content({
                            'type': 'weather',
                            'data': conditions
                        })
                        self.rate_limiter.record_post('weather', 'regular')
                        logger.info(f"Weather update post results: {post_results}")

                alerts = await self.weather_monitor.get_alerts()
                for alert in alerts:
                    if self.rate_limiter.can_post('weather', 'alert'):
                        post_results = await self.social_handler.post_content({
                            'type': 'weather_alert',
                            'data': alert
                        })
                        self.rate_limiter.record_post('weather', 'alert')
                        logger.info(f"Weather alert post results: {post_results}")

            except Exception as e:
                logger.error(f"Error in weather task: {str(e)}")

            await asyncio.sleep(self.config['weather']['update_interval'])

    async def earthquake_task(self):
        """Earthquake monitoring task."""
        while self.running:
            try:
                earthquakes = await self.earthquake_monitor.get_earthquakes()
                for quake in earthquakes:
                    if self.rate_limiter.can_post('earthquake', 'alert'):
                        map_path = self.map_generator.generate_earthquake_map(quake)
                        if map_path:
                            quake['map_path'] = map_path
                        
                        post_results = await self.social_handler.post_content({
                            'type': 'earthquake',
                            'data': quake
                        })
                        self.rate_limiter.record_post('earthquake', 'alert')
                        logger.info(f"Earthquake alert post results: {post_results}")

            except Exception as e:
                logger.error(f"Error in earthquake task: {str(e)}")

            await asyncio.sleep(self.config['earthquake']['check_interval'])

    async def news_task(self):
        """News monitoring task."""
        while self.running:
            try:
                articles = await self.news_monitor.check_news()
                for article in articles:
                    if self.rate_limiter.can_post('news', 'regular'):
                        if 'location_data' in article:
                            map_path = self.map_generator.generate_news_map(article['location_data'])
                            if map_path:
                                article['map_path'] = map_path
                        
                        post_results = await self.social_handler.post_content({
                            'type': 'news',
                            'data': article
                        })
                        self.rate_limiter.record_post('news', 'regular')
                        logger.info(f"News article post results: {post_results}")

            except Exception as e:
                logger.error(f"Error in news task: {str(e)}")

            await asyncio.sleep(self.config['news']['check_interval'])

    async def maintenance_task(self):
        """Regular maintenance task."""
        while self.running:
            try:
                self.cleanup()
            except Exception as e:
                logger.error(f"Error in maintenance task: {str(e)}")

            await asyncio.sleep(self.config['maintenance']['cleanup_interval'])

    async def run(self):
        """Start the bot."""
        logger.info(f"Starting CityBot for {self.city_config['name']}...")
        
        try:
            # Initialize monitors
            await self.weather_monitor.initialize()
            
            # Create tasks
            self.tasks = [
                asyncio.create_task(self.weather_task()),
                asyncio.create_task(self.earthquake_task()),
                asyncio.create_task(self.news_task()),
                asyncio.create_task(self.maintenance_task())
            ]
            
            # Wait for tasks
            await asyncio.gather(*self.tasks)
            
        except asyncio.CancelledError:
            logger.info("Bot tasks cancelled")
        except Exception as e:
            logger.error(f"Error running bot: {str(e)}")
            raise

if __name__ == "__main__":
    # Ensure required directories exist
    for directory in ['logs', 'data', 'cache/weather_maps', 'cache/maps']:
        os.makedirs(directory, exist_ok=True)

    # Get city name from environment variable or use default
    city_name = os.getenv('CITYBOT_CITY', 'ventura')

    # Start the bot
    bot = CityBot(city_name)
    asyncio.run(bot.run())