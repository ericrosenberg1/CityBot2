import asyncio
import asyncio.exceptions
import logging
import signal
import sys
from datetime import datetime, timedelta
import os

from database.operations import DatabaseManager
from monitors.weather import WeatherMonitor
from monitors.earthquake import EarthquakeMonitor
from monitors.news import NewsMonitor
from social_media import SocialMediaManager
from social_media.utils import RateLimiter, MapGenerator
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
    """A city-focused bot that posts weather, earthquake, and news updates."""

    def __init__(self):
        """Initialize CityBot with configuration and components."""
        self.running = False
        self.tasks = []
        self.shutdown_event = asyncio.Event()
        
        try:
            self.config_manager = ConfigurationManager()
            self.city_config = self.config_manager.city_config
            self.enabled_networks = self.config_manager.get_enabled_networks()

            logger.info("Initialized CityBot for %s, %s",
                       self.city_config['name'], self.city_config['state'])
            enabled_networks_str = ", ".join(self.enabled_networks)
            logger.info("Enabled social networks: %s", enabled_networks_str)

            self.social_config = {}
            for network in self.enabled_networks:
                network_config = self.config_manager.get_social_network_config(network)
                if network_config:
                    self.social_config[network] = network_config.credentials

            self.post_intervals = {
                'news': self.config_manager.get_interval('news'),
                'weather': self.config_manager.get_interval('weather'),
                'earthquake': self.config_manager.get_interval('earthquake'),
                'maintenance': self.config_manager.get_interval('maintenance')
            }

            self._initialize_components()
            
            # Initialize signal handlers
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

        except Exception as e:
            logger.error("Critical error initializing CityBot: %s", e, exc_info=True)
            raise

    def _initialize_components(self):
        """Initialize all component systems."""
        try:
            self.db = DatabaseManager()

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

            platforms = {
                network: {
                    'enabled': True,
                    'credentials': creds,
                    'post_types': ['weather', 'earthquake', 'news']
                }
                for network, creds in self.social_config.items()
            }

            self.social_media = SocialMediaManager(
                {'platforms': platforms},
                self.city_config
            )

            self.rate_limiter = RateLimiter()

            self.map_generator = MapGenerator(
                {'coordinates': self.city_config['coordinates']}
            )

        except Exception as e:
            logger.error("Critical error initializing components: %s", e, exc_info=True)
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}")
        if self.running:
            asyncio.create_task(self.shutdown())

    async def run(self):
        """Main run loop for the bot."""
        try:
            self.running = True
            logger.info("Starting CityBot tasks...")
            
            # Create all tasks
            self.tasks = [
                asyncio.create_task(self.weather_task()),
                asyncio.create_task(self.earthquake_task()),
                asyncio.create_task(self.news_task()),
                asyncio.create_task(self.maintenance_task())
            ]
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
            # Wait for all tasks to complete
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
                
        except Exception as e:
            logger.error("Error in main run loop: %s", e, exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def shutdown(self):
        """Handle graceful shutdown."""
        if not self.running:
            return
            
        logger.info("Initiating shutdown...")
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        # Signal shutdown
        self.shutdown_event.set()

    async def cleanup(self):
        """Clean up resources during shutdown."""
        logger.info("Cleaning up resources...")
        try:
            # Close social media connections
            await self.social_media.close()
            
            # Close weather monitor
            await self.weather_monitor.cleanup()
            
            # Close rate limiter
            await self.rate_limiter.close()
            
            # Close database connection
            self.db.close()
            
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error("Error during cleanup: %s", e, exc_info=True)

    async def weather_task(self):
        """Handle weather monitoring and posting."""
        try:
            while self.running:
                try:
                    weather_data = await self.weather_monitor.get_current_conditions()
                    if weather_data is None:
                        logger.warning("No weather conditions received. Skipping weather post.")
                        await asyncio.sleep(self.post_intervals['weather'])
                        continue

                    if await self.rate_limiter.can_post('weather', 'regular'):
                        results = await self.social_media.post_weather(weather_data)
                        if any(result.success for result in results.values()):
                            await self.rate_limiter.record_post('weather', 'regular')
                            logger.info("Posted weather update successfully")
                        else:
                            logger.error("Failed to post weather update to social media")

                    alerts = await self.weather_monitor.get_alerts()
                    for alert in alerts:
                        if await self.rate_limiter.can_post('weather', 'alert'):
                            results = await self.social_media.post_weather_alert(alert)
                            if any(result.success for result in results.values()):
                                await self.rate_limiter.record_post('weather', 'alert')
                                logger.info("Posted weather alert: %s", alert.event)
                            else:
                                logger.error("Failed to post weather alert: %s", alert.event)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Error in weather task: %s", e, exc_info=True)

                await asyncio.sleep(self.post_intervals['weather'])
        except asyncio.CancelledError:
            logger.info("Weather task canceled cleanly.")

    async def earthquake_task(self):
        """Handle earthquake monitoring and posting."""
        try:
            while self.running:
                try:
                    earthquakes = await self.earthquake_monitor.check_earthquakes()
                    for quake in earthquakes:
                        if await self.rate_limiter.can_post('earthquake', 'alert'):
                            map_path = await self.map_generator.generate_earthquake_map(quake)
                            if map_path:
                                quake['map_path'] = str(map_path)
                            results = await self.social_media.post_earthquake(quake)
                            if any(result.success for result in results.values()):
                                await self.rate_limiter.record_post('earthquake', 'alert')
                                magnitude = quake.get('magnitude', 'Unknown')
                                logger.info("Posted earthquake update: M%s", magnitude)
                            else:
                                magnitude = quake.get('magnitude', 'Unknown')
                                logger.error("Failed to post earthquake update: M%s", magnitude)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Error in earthquake task: %s", e, exc_info=True)

                await asyncio.sleep(self.post_intervals['earthquake'])
        except asyncio.CancelledError:
            logger.info("Earthquake task canceled cleanly.")

    async def news_task(self):
        """Handle news monitoring and posting."""
        try:
            while self.running:
                try:
                    articles = await self.news_monitor.check_news()
                    for article in articles:
                        if await self.rate_limiter.can_post('news', 'regular'):
                            results = await self.social_media.post_news(article)
                            if any(result.success for result in results.values()):
                                await self.rate_limiter.record_post('news', 'regular')
                                logger.info("Posted news article: %s", article.title)
                            else:
                                logger.error("Failed to post news article: %s", article.title)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Error in news task: %s", e, exc_info=True)

                await asyncio.sleep(self.post_intervals['news'])
        except asyncio.CancelledError:
            logger.info("News task canceled cleanly.")

    async def maintenance_task(self):
        """Handle system maintenance."""
        try:
            while self.running:
                try:
                    await self.rate_limiter.cleanup_old_records()
                    self.db.cleanup_old_records()

                    cleanup_time = datetime.now() - timedelta(days=7)
                    for directory in ['cache/weather_maps', 'cache/maps']:
                        if os.path.exists(directory):
                            for file in os.listdir(directory):
                                file_path = os.path.join(directory, file)
                                try:
                                    if datetime.fromtimestamp(os.path.getctime(file_path)) < cleanup_time:
                                        os.remove(file_path)
                                except Exception as e:
                                    logger.warning("Could not remove file %s: %s", file_path, e)

                    logger.info("Maintenance task completed successfully")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Error in maintenance task: %s", e, exc_info=True)

                await asyncio.sleep(self.post_intervals['maintenance'])
        except asyncio.CancelledError:
            logger.info("Maintenance task canceled cleanly.")


async def async_main():
    """Async entry point for the application."""
    for directory in ['logs', 'data', 'cache/weather_maps', 'cache/maps']:
        os.makedirs(directory, exist_ok=True)

    bot = None
    try:
        bot = CityBot()
        await bot.run()
    except Exception as e:
        logger.error("Critical application error: %s", e, exc_info=True)
        if bot:
            await bot.shutdown()
    finally:
        if bot:
            await bot.cleanup()


def main():
    """Main entry point for the application."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()