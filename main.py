import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any
import os
from pathlib import Path

from database.operations import DatabaseManager
from monitors.weather import WeatherMonitor
from monitors.earthquake import EarthquakeMonitor
from monitors.news import NewsMonitor
from social_media import SocialMediaManager
from social_media.utils import RateLimiter, WeatherMapGenerator, MapGenerator
from config import ConfigurationManager

# Set up logging
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
        """Initialize CityBot with configuration and components."""
        try:
            # Initialize configuration
            self.config_manager = ConfigurationManager()
            
            # Get configurations
            self.city_config = self.config_manager.city_config
            self.enabled_networks = self.config_manager.get_enabled_networks()
            
            # Log initialization
            logger.info(f"Initialized CityBot for {self.city_config['name']}, {self.city_config['state']}")
            logger.info(f"Enabled social networks: {', '.join(self.enabled_networks)}")

            # Get social network configurations
            self.social_config = {}
            for network in self.enabled_networks:
                network_config = self.config_manager.get_social_network_config(network)
                if network_config:
                    self.social_config[network] = network_config.credentials

            # Get update intervals
            self.post_intervals = {
                'news': self.config_manager.get_interval('news'),
                'weather': self.config_manager.get_interval('weather'),
                'earthquake': self.config_manager.get_interval('earthquake'),
                'maintenance': self.config_manager.get_interval('maintenance')
            }

            # Initialize components
            self._initialize_components()
            
            # Set up signal handlers
            signal.signal(signal.SIGINT, self._shutdown_handler)
            signal.signal(signal.SIGTERM, self._shutdown_handler)
            self.tasks = []
            self.running = True

        except Exception as e:
            logger.error(f"Error initializing CityBot: {str(e)}")
            raise

    def _initialize_components(self):
        """Initialize all component systems."""
        try:
            # Initialize database
            self.db = DatabaseManager()

            # Initialize monitors with configurations from config manager
            self.weather_monitor = WeatherMonitor(
                self.config_manager.get_config('weather'),
                self.city_config
            )
            
            self.earthquake_monitor = EarthquakeMonitor(
                self.config_manager.get_config('earthquake'),
                self.city_config
            )
            
            self.news_monitor = NewsMonitor(
                self.config_manager.get_config('news'),
                self.city_config
            )

            # Initialize social media manager with configurations
            self.social_media = SocialMediaManager(
                {
                    'platforms': {
                        network: {
                            'enabled': True,
                            'credentials': credentials,
                            'post_types': ['weather', 'earthquake', 'news']
                        }
                        for network, credentials in self.social_config.items()
                    }
                },
                self.city_config
            )

            # Initialize utilities
            self.rate_limiter = RateLimiter()
            self.weather_map_generator = WeatherMapGenerator(
                self.config_manager.get_config('weather')
            )
            self.map_generator = MapGenerator(
                {'coordinates': self.city_config['coordinates']}
            )

        except Exception as e:
            logger.error(f"Error initializing components: {str(e)}")
            raise

    async def weather_task(self):
        """Handle weather monitoring and posting."""
        while self.running:
            try:
                # Get current conditions
                conditions = await self.weather_monitor.get_current_conditions()
                if conditions:
                    if self.rate_limiter.can_post('weather', 'regular'):
                        map_path = self.weather_map_generator.generate_weather_map(conditions)
                        if map_path:
                            conditions['map_path'] = map_path
                        
                        success = await self.social_media.post_weather(conditions)
                        if success:
                            self.rate_limiter.record_post('weather', 'regular')
                            logger.info("Posted weather update successfully")

                # Check alerts
                alerts = await self.weather_monitor.get_alerts()
                for alert in alerts:
                    if self.rate_limiter.can_post('weather', 'alert'):
                        success = await self.social_media.post_weather_alert(alert)
                        if success:
                            self.rate_limiter.record_post('weather', 'alert')
                            logger.info(f"Posted weather alert: {alert['event']}")

            except Exception as e:
                logger.error(f"Error in weather task: {str(e)}")

            await asyncio.sleep(self.post_intervals['weather'])

    async def earthquake_task(self):
        """Handle earthquake monitoring and posting."""
        while self.running:
            try:
                earthquakes = await self.earthquake_monitor.check_earthquakes()
                for quake in earthquakes:
                    if self.rate_limiter.can_post('earthquake', 'alert'):
                        map_path = self.map_generator.generate_earthquake_map(quake)
                        if map_path:
                            quake['map_path'] = map_path
                        
                        success = await self.social_media.post_earthquake(quake)
                        if success:
                            self.rate_limiter.record_post('earthquake', 'alert')
                            logger.info(f"Posted earthquake update: M{quake['magnitude']}")

            except Exception as e:
                logger.error(f"Error in earthquake task: {str(e)}")

            await asyncio.sleep(self.post_intervals['earthquake'])

    async def news_task(self):
        """Handle news monitoring and posting."""
        while self.running:
            try:
                articles = await self.news_monitor.check_news()
                for article in articles:
                    if self.rate_limiter.can_post('news', 'regular'):
                        if 'location_data' in article:
                            map_path = self.map_generator.generate_news_map(article['location_data'])
                            if map_path:
                                article['map_path'] = map_path
                        
                        success = await self.social_media.post_news(article)
                        if success:
                            self.rate_limiter.record_post('news', 'regular')
                            logger.info(f"Posted news article: {article['title']}")

            except Exception as e:
                logger.error(f"Error in news task: {str(e)}")

            await asyncio.sleep(self.post_intervals['news'])

    async def maintenance_task(self):
        """Handle system maintenance."""
        while self.running:
            try:
                self._cleanup()
            except Exception as e:
                logger.error(f"Error in maintenance task: {str(e)}")
            await asyncio.sleep(self.post_intervals['maintenance'])

    def _cleanup(self):
        """Perform system cleanup."""
        try:
            self.db.cleanup_old_records()
            self.rate_limiter.cleanup_old_records()
            
            # Clean up old map files
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

    def _shutdown_handler(self, signum, frame):
        """Handle system shutdown."""
        logger.info("Shutdown signal received. Cleaning up...")
        self.running = False
        for task in self.tasks:
            task.cancel()
        self._cleanup()
        logger.info("Shutdown complete.")
        sys.exit(0)

    async def run(self):
        """Run the main bot loop."""
        logger.info(f"Starting CityBot for {self.city_config['name']}...")
        try:
            # Initialize weather monitor
            await self.weather_monitor.initialize()
            
            # Create tasks
            self.tasks = [
                asyncio.create_task(self.weather_task()),
                asyncio.create_task(self.earthquake_task()),
                asyncio.create_task(self.news_task()),
                asyncio.create_task(self.maintenance_task())
            ]
            
            # Run all tasks
            await asyncio.gather(*self.tasks)
            
        except asyncio.CancelledError:
            logger.info("Bot tasks cancelled")
        except Exception as e:
            logger.error(f"Error running bot: {str(e)}")
            raise
        finally:
            self._cleanup()

def main():
    """Main entry point for the application."""
    # Create necessary directories
    for directory in ['logs', 'data', 'cache/weather_maps', 'cache/maps']:
        os.makedirs(directory, exist_ok=True)

    # Start the bot
    try:
        bot = CityBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()