"""Main entry point and event loop management for CityBot2."""

import asyncio
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

            signal.signal(signal.SIGINT, self._shutdown_handler)
            signal.signal(signal.SIGTERM, self._shutdown_handler)
            self.tasks = []
            self.running = True

        except (ValueError, FileNotFoundError, OSError) as exc:
            logger.error("Critical error initializing CityBot: %s", exc, exc_info=True)
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

        except (ValueError, FileNotFoundError, OSError) as exc:
            logger.error("Critical error initializing components: %s", exc, exc_info=True)
            raise

    async def weather_task(self):
        """Handle weather monitoring and posting."""
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

            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("Error in weather task: %s", exc, exc_info=True)
                # pylint: disable=broad-exception-caught
            except Exception as exc:  # Catch-all for unexpected exceptions
                logger.error("Error in weather task: %s", exc, exc_info=True)

            await asyncio.sleep(self.post_intervals['weather'])

    async def earthquake_task(self):
        """Handle earthquake monitoring and posting."""
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
                            magnitude = quake.get('magnitude', 'Unknown')
                            logger.info("Posted earthquake update: M%s", magnitude)
                            await self.rate_limiter.record_post('earthquake', 'alert')
                        else:
                            magnitude = quake.get('magnitude', 'Unknown')
                            logger.error("Failed to post earthquake update: M%s", magnitude)

            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("Error in earthquake task: %s", exc, exc_info=True)
                # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error in earthquake task: %s", exc, exc_info=True)

            await asyncio.sleep(self.post_intervals['earthquake'])

    async def news_task(self):
        """Handle news monitoring and posting."""
        while self.running:
            try:
                articles = await self.news_monitor.check_news()
                for article in articles:
                    if await self.rate_limiter.can_post('news', 'regular'):
                        results = await self.social_media.post_news(article)
                        if any(result.success for result in results.values()):
                            logger.info("Posted news article: %s", article.title)
                            await self.rate_limiter.record_post('news', 'regular')
                        else:
                            logger.error("Failed to post news article: %s", article.title)

            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("Error in news task: %s", exc, exc_info=True)
                # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error in news task: %s", exc, exc_info=True)

            await asyncio.sleep(self.post_intervals['news'])

    async def maintenance_task(self):
        """Handle system maintenance."""
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
                            except OSError as exc:
                                logger.warning("Could not remove file %s: %s", file_path, exc)

                logger.info("Maintenance task completed successfully")
            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("Error in maintenance task: %s", exc, exc_info=True)
                # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error in maintenance task: %s", exc, exc_info=True)

            await asyncio.sleep(self.post_intervals['maintenance'])

    def _shutdown_handler(self, _signum, _frame):
        """Handle system shutdown."""
        logger.info("Shutdown signal received. Cleaning up...")
        self.running = False

        loop = asyncio.get_event_loop()

        async def shutdown_tasks():
            """Perform shutdown tasks asynchronously."""
            try:
                for task in self.tasks:
                    if not task.done():
                        task.cancel()

                await asyncio.gather(*self.tasks, return_exceptions=True)

                await self.db.close()
                await self.social_media.close()
                await self.weather_monitor.cleanup()

                logger.info("All tasks and connections closed successfully")
            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("Error during shutdown tasks: %s", exc, exc_info=True)
                # pylint: disable=broad-exception-caught
            except Exception as exc:
                logger.error("Error during shutdown tasks: %s", exc, exc_info=True)

        try:
            if loop.is_running():
                loop.create_task(shutdown_tasks())
            else:
                loop.run_until_complete(shutdown_tasks())
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Error in shutdown handler: %s", exc, exc_info=True)
            # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Error in shutdown handler: %s", exc, exc_info=True)
        finally:
            logger.info("Shutdown complete.")
            sys.exit(0)

    async def run(self):
        """Run the main bot loop."""
        logger.info("Starting CityBot for %s...", self.city_config['name'])
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
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Critical error running bot: %s", exc, exc_info=True)
            raise
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            logger.error("Critical error running bot: %s", exc, exc_info=True)
            raise


def main():
    """Main entry point for the application."""
    for directory in ['logs', 'data', 'cache/weather_maps', 'cache/maps']:
        os.makedirs(directory, exist_ok=True)

    try:
        bot = CityBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("Critical application error: %s", exc, exc_info=True)
        sys.exit(1)
    # pylint: disable=broad-exception-caught
    except Exception as exc:
        logger.error("Critical application error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
