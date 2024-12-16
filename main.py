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

class CityBot:
    def __init__(self):
        """Initialize the bot and its components."""
        try:
            # Load configuration
            with open('config/config.json') as f:
                self.config = json.load(f)

            # Load social media configuration
            with open('config/social_config.json') as f:
                self.social_config = json.load(f)

            # Initialize components
            self.db = DatabaseManager()
            self.weather_monitor = WeatherMonitor(self.config['weather'])
            self.earthquake_monitor = EarthquakeMonitor(self.config['earthquake'])
            self.news_monitor = NewsMonitor(self.config['news'])
            self.social_media = SocialMediaManager(self.social_config)
            self.rate_limiter = RateLimiter()
            self.weather_map_generator = WeatherMapGenerator(config=self.config['weather'])
            self.map_generator = MapGenerator(config=self.config['weather'])

            # Set up shutdown handler
            signal.signal(signal.SIGINT, self.shutdown_handler)
            signal.signal(signal.SIGTERM, self.shutdown_handler)

            # Initialize task tracking
            self.tasks = []
            self.running = True

            logger.info("CityBot initialized successfully")

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
                # Get current conditions
                conditions = await self.weather_monitor.get_current_conditions()
                if conditions:
                    # Generate weather map
                    map_path = self.weather_map_generator.generate_weather_map(conditions)
                    if map_path:
                        conditions['map_path'] = map_path
                    
                    # Post to social media if rate limits allow
                    if self.rate_limiter.can_post('weather', 'regular'):
                        await self.social_media.post_weather(conditions)
                        self.rate_limiter.record_post('weather', 'regular')
                        logger.info("Posted weather update successfully")

                # Check for alerts
                alerts = await self.weather_monitor.get_alerts()
                for alert in alerts:
                    if self.rate_limiter.can_post('weather', 'alert'):
                        await self.social_media.post_weather_alert(alert)
                        self.rate_limiter.record_post('weather', 'alert')
                        logger.info(f"Posted weather alert: {alert['event']}")

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
                        # Generate earthquake map
                        map_path = self.map_generator.generate_earthquake_map(quake)
                        if map_path:
                            quake['map_path'] = map_path
                        
                        await self.social_media.post_earthquake(quake)
                        self.rate_limiter.record_post('earthquake', 'alert')
                        logger.info(f"Posted earthquake alert: M{quake['magnitude']}")

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
                        # Check if article has location data for map
                        if 'location_data' in article:
                            map_path = self.map_generator.generate_news_map(article['location_data'])
                            if map_path:
                                article['map_path'] = map_path
                        
                        await self.social_media.post_news(article)
                        self.rate_limiter.record_post('news', 'regular')
                        logger.info(f"Posted news article: {article['title']}")

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
        logger.info("Starting CityBot...")
        
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

    # Start the bot
    bot = CityBot()
    asyncio.run(bot.run())