"""Seed data sources from city JSON config into the database.
Run once after upgrading from JSON-config-based RSS feeds to DB-based sources.

Usage: python -m scripts.seed_sources [city_name]
"""
import sys
import os
import json
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.operations import DatabaseManager
from database.models import DataSource, KeywordFilter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('seed_sources')

def seed(city_name=None):
    if not city_name:
        city_name = os.getenv('CITY_NAME', '')
    if not city_name:
        # Try to find a city config
        cities_dir = Path('config/cities')
        configs = [f.stem for f in cities_dir.glob('*.json') if not f.name.endswith('.example')]
        if configs:
            city_name = configs[0]
        else:
            logger.error("No city name provided and no city configs found")
            sys.exit(1)

    config_path = Path(f'config/cities/{city_name}.json')
    if not config_path.exists():
        logger.error("City config not found: %s", config_path)
        sys.exit(1)

    with open(config_path) as f:
        city_config = json.load(f)

    db = DatabaseManager()

    with db.Session() as session:
        existing = session.query(DataSource).count()
        if existing > 0:
            logger.info("Database already has %d sources, skipping seed", existing)
            return

    # Seed RSS feeds
    rss_feeds = city_config.get('news', {}).get('rss_feeds', {})
    keywords = city_config.get('news', {}).get('location_keywords', {})

    with db.Session() as session:
        # Create built-in sources
        weather_src = DataSource(
            source_type='weather', name='National Weather Service',
            is_enabled=True, priority=1, check_interval=21600
        )
        session.add(weather_src)

        eq_src = DataSource(
            source_type='earthquake', name='USGS Earthquakes',
            is_enabled=True, priority=1, check_interval=300
        )
        session.add(eq_src)

        # Create RSS feed sources with keyword filters
        for feed_name, feed_info in rss_feeds.items():
            src = DataSource(
                source_type='rss',
                name=feed_name,
                url=feed_info.get('url'),
                is_enabled=True,
                priority=feed_info.get('priority', 2),
                check_interval=feed_info.get('update_frequency', 1800),
            )
            session.add(src)
            session.flush()  # get the ID

            # Add keyword filters for each RSS source
            for kw in keywords.get('must_include', []):
                session.add(KeywordFilter(data_source_id=src.id, keyword=kw, filter_type='must_include'))
            for kw in keywords.get('at_least_one', []):
                session.add(KeywordFilter(data_source_id=src.id, keyword=kw, filter_type='at_least_one'))
            for kw in keywords.get('exclude', []):
                session.add(KeywordFilter(data_source_id=src.id, keyword=kw, filter_type='exclude'))

            logger.info("Added source: %s (%s) with %d keyword filters",
                        feed_name, feed_info.get('url', ''),
                        len(keywords.get('must_include', [])) + len(keywords.get('at_least_one', [])) + len(keywords.get('exclude', [])))

        session.commit()

    logger.info("Seeding complete!")

if __name__ == '__main__':
    city = sys.argv[1] if len(sys.argv) > 1 else None
    seed(city)
