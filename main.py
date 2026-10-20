import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# =============================================================================
# SENTRY — initialized FIRST so errors during subsequent imports are captured.
# =============================================================================
try:
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=os.getenv(
            "SENTRY_DSN",
            "https://dd5051420c5e14116bdd3addf5d8bb62@o4507525754060800.ingest.us.sentry.io/4511429590188032",
        ),
        environment=os.getenv("APP_ENV", "production"),
        integrations=[
            AsyncioIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2")),
        # Continuous profiling. Transaction-based profiles_sample_rate is deprecated.
        profile_session_sample_rate=float(
            os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.2")
        ),
        profile_lifecycle="trace",
        release=os.getenv("SENTRY_RELEASE"),
    )
except ImportError:
    pass

from config import ConfigurationManager
from database.models import DataSource, KeywordFilter, PostQueue, SocialAccount
from database.operations import DatabaseManager
from monitors.earthquake import EarthquakeMonitor
from monitors.news import NewsMonitor
from monitors.weather import WeatherMonitor
from posting.queue_manager import QueueManager
from social_media import SocialMediaManager
from utils.maps import LocationMapGenerator
from web.auth import decrypt_secret

# Set up logging. Rotate the file: unrotated, it reached 52MB in 2025.
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            "logs/citybot.log", maxBytes=5 * 1024 * 1024, backupCount=3
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("CityBot2")


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

            logger.info(
                "Initialized CityBot for %s, %s",
                self.city_config["name"],
                self.city_config["state"],
            )
            enabled_networks_str = ", ".join(self.enabled_networks)
            logger.info("Social networks enabled in env: %s", enabled_networks_str)

            self.social_config = {}
            for network in self.enabled_networks:
                network_config = self.config_manager.get_social_network_config(network)
                if network_config:
                    self.social_config[network] = network_config.credentials

            self.post_intervals = {
                task: self.config_manager.get_interval(task)
                for task in (
                    "news",
                    "weather",
                    "weather_alert",
                    "earthquake",
                    "maintenance",
                )
            }

            self._loop = None
            self._cleaned_up = False

            self._initialize_components()

        except Exception:
            logger.exception("Critical error initializing CityBot")
            raise

    def _initialize_components(self):
        """Initialize all component systems."""
        try:
            self.db = DatabaseManager()

            # Accounts connected in the admin UI take precedence over env vars.
            self.social_config.update(self._load_db_social_accounts())
            enabled_networks_str = ", ".join(self.social_config) or "none"
            logger.info("Posting to: %s", enabled_networks_str)

            self.weather_monitor = WeatherMonitor(
                self.config_manager.get_config("weather"), self.city_config
            )

            self.earthquake_monitor = EarthquakeMonitor(
                self.config_manager.get_config("earthquake"), self.city_config
            )

            self.news_monitor = NewsMonitor(
                self.config_manager.get_config("news"), self.city_config
            )

            platforms = {
                network: {
                    "enabled": True,
                    "credentials": creds,
                    "post_types": list(ConfigurationManager.POST_TYPES),
                }
                for network, creds in self.social_config.items()
            }
            rate_limits = {
                network: self.config_manager.get_rate_limits(network)
                for network in platforms
            }

            self.social_media = SocialMediaManager(
                {"platforms": platforms, "rate_limits": rate_limits}, self.city_config
            )

            self.map_generator = LocationMapGenerator(
                {"coordinates": self.city_config["coordinates"]}
            )

            self.queue_manager = QueueManager(
                self.db, self.social_media, self.city_config
            )

        except Exception:
            logger.exception("Critical error initializing components")
            raise

    def _load_db_social_accounts(self) -> dict:
        """Credentials for each account connected in the admin UI."""
        accounts = {}
        with self.db.Session() as session:
            for account in session.query(SocialAccount).filter_by(is_active=True):
                plaintext = decrypt_secret(account.credentials_json)
                if not plaintext:
                    logger.warning(
                        "Can't decrypt %s credentials. Reconnect it in the admin UI.",
                        account.platform,
                    )
                    continue
                accounts[account.platform] = json.loads(plaintext)
        return accounts

    def _source_enabled(self, source_type: str) -> bool:
        """Honor the admin UI's on/off switch for weather and earthquake sources."""
        with self.db.Session() as session:
            sources = (
                session.query(DataSource.is_enabled)
                .filter_by(source_type=source_type)
                .all()
            )
        return not sources or any(enabled for (enabled,) in sources)

    def _load_db_news_sources(self):
        """RSS feeds managed in the admin UI, in NewsMonitor's feed format.

        None when the admin UI has no RSS sources at all, so the city JSON
        feeds stay in use until scripts/seed_sources.py (or the UI) adds some.
        """
        feeds = {}
        with self.db.Session() as session:
            sources = session.query(DataSource).filter_by(source_type="rss").all()
            filters = (
                session.query(KeywordFilter)
                .filter(KeywordFilter.data_source_id.in_([src.id for src in sources]))
                .all()
            )
            for src in sources:
                if not src.is_enabled or not src.url:
                    continue
                feeds[src.name] = {"url": src.url, "priority": src.priority}
                own = [f for f in filters if f.data_source_id == src.id]
                if own:
                    keywords = {"must_include": [], "at_least_one": [], "exclude": []}
                    for f in own:
                        keywords.setdefault(f.filter_type, []).append(f.keyword)
                    feeds[src.name]["location_keywords"] = keywords
            has_sources = bool(sources)
        return feeds if has_sources else None

    def _is_queued(self, content_type: str, link_url) -> bool:
        if not link_url:
            return False
        with self.db.Session() as session:
            return (
                session.query(PostQueue.id)
                .filter_by(content_type=content_type, link_url=link_url)
                .first()
                is not None
            )

    def _setup_signal_handlers(self):
        """Set up signal handlers within the running event loop."""
        self._loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._loop.add_signal_handler(sig, self._signal_handler, sig)

    def _signal_handler(self, signum):
        """Handle shutdown signals."""
        logger.info("Received signal %s", signum)
        if self.running and self._loop:
            self._loop.create_task(self.shutdown())

    async def run(self):
        """Main run loop for the bot."""
        try:
            self.running = True
            self._setup_signal_handlers()
            logger.info("Starting CityBot tasks...")

            # Create all tasks
            self.tasks = [
                asyncio.create_task(self.weather_task()),
                asyncio.create_task(self.weather_alert_task()),
                asyncio.create_task(self.earthquake_task()),
                asyncio.create_task(self.news_task()),
                asyncio.create_task(self.queue_processor_task()),
                asyncio.create_task(self.maintenance_task()),
            ]

            # Wait for shutdown signal
            await self.shutdown_event.wait()

            # Wait for all tasks to complete
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)

        except Exception:
            logger.exception("Error in main run loop")
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
        """Clean up resources during shutdown. Safe to call more than once."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        logger.info("Cleaning up resources...")
        try:
            # Close social media connections (also closes its rate limiter)
            await self.social_media.close()

            # Close weather monitor
            await self.weather_monitor.cleanup()

            # Close database connection
            self.db.close()

            logger.info("Cleanup completed successfully")
        except Exception:
            logger.exception("Error during cleanup")

    async def _poll(self, name: str, interval_key: str, check):
        """Run `check` every interval until shutdown, logging (not raising) its errors."""
        try:
            while self.running:
                try:
                    await check()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error in %s task", name)

                await asyncio.sleep(self.post_intervals[interval_key])
        except asyncio.CancelledError:
            logger.info("%s task canceled cleanly.", name.capitalize())

    async def weather_task(self):
        """Fetch current conditions for the scheduled weather posts."""

        async def check():
            if not self._source_enabled("weather"):
                return
            weather_data = await self.weather_monitor.get_current_conditions()
            if weather_data is None:
                logger.warning(
                    "No weather conditions received. Skipping weather enqueue."
                )
            else:
                self.queue_manager.enqueue("weather", weather_data)

        await self._poll("weather", "weather", check)

    async def weather_alert_task(self):
        """Check for alerts on their own, shorter interval than conditions."""

        async def check():
            if not self._source_enabled("weather"):
                return
            for alert in await self.weather_monitor.get_alerts():
                self.queue_manager.enqueue("weather_alert", alert)

        await self._poll("weather alert", "weather_alert", check)

    async def earthquake_task(self):
        """Queue significant earthquakes, drawing a map only for new ones."""

        async def check():
            if not self._source_enabled("earthquake"):
                return
            for quake in await self.earthquake_monitor.check_earthquakes():
                if self._is_queued("earthquake", quake.get("url")):
                    continue
                map_path = await self.map_generator.generate_location_map(quake)
                if map_path:
                    quake["map_path"] = str(map_path)
                self.queue_manager.enqueue("earthquake", quake)

        await self._poll("earthquake", "earthquake", check)

    async def news_task(self):
        """Queue relevant news, using the admin UI's feeds when it has any."""

        async def check():
            db_sources = self._load_db_news_sources()
            if db_sources is not None:
                self.news_monitor.set_sources(db_sources)
            for article in await self.news_monitor.check_news():
                self.queue_manager.enqueue("news", article)

        await self._poll("news", "news", check)

    async def queue_processor_task(self):
        """Process the posting queue on a regular interval."""
        try:
            while self.running:
                try:
                    self.queue_manager.enqueue_due_announcements()
                    await self.queue_manager.process_queue()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error in queue processor task")

                await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("Queue processor task canceled cleanly.")

    async def maintenance_task(self):
        """Prune old records, queue items, rate-limit history and cached maps."""

        async def check():
            self.db.cleanup_old_records()
            pruned = self.queue_manager.prune_finished()
            if pruned:
                logger.info("Pruned %d finished queue items", pruned)
            await self.social_media.rate_limiter.cleanup_old_records()

            cleanup_time = datetime.now() - timedelta(days=7)
            for directory in ["cache/weather_maps", "cache/maps"]:
                if os.path.exists(directory):
                    for file in os.listdir(directory):
                        file_path = os.path.join(directory, file)
                        try:
                            if (
                                os.path.isfile(file_path)
                                and datetime.fromtimestamp(os.path.getctime(file_path))
                                < cleanup_time
                            ):
                                os.remove(file_path)
                        except OSError as e:
                            logger.warning("Could not remove file %s: %s", file_path, e)

            logger.info("Maintenance task completed successfully")

        await self._poll("maintenance", "maintenance", check)


async def async_main():
    """Async entry point for the application."""
    for directory in ["logs", "data", "cache/weather_maps", "cache/maps"]:
        os.makedirs(directory, exist_ok=True)

    bot = None
    try:
        bot = CityBot()
        await bot.run()
    except Exception:
        logger.exception("Critical application error")
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
    except Exception:
        logger.exception("Fatal error")
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
