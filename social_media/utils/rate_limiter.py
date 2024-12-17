import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3
from typing import Dict, Optional
import os
from dotenv import load_dotenv

logger = logging.getLogger('CityBot2.rate_limiter')

@dataclass
class RateLimit:
    platform: str
    post_type: str
    posts_per_hour: int
    posts_per_day: int
    minimum_interval: int  # seconds

class RateLimiter:
    def __init__(self, db_path: str = "data/rate_limits.db"):
        self.db_path = db_path
        load_dotenv('credentials.env')
        self.initialize_db()
        self.load_limits()

    def initialize_db(self):
        """Initialize the rate limiting database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    post_type TEXT NOT NULL,
                    timestamp DATETIME NOT NULL
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_platform_type_timestamp 
                ON post_history(platform, post_type, timestamp)
            ''')

    def load_limits(self):
        """Load rate limits from environment variables."""
        try:
            self.limits = {}
            platforms = os.getenv('PLATFORMS', 'twitter').split(',')
            
            for platform in platforms:
                post_types = os.getenv(f'{platform.upper()}_POST_TYPES', 'tweet').split(',')
                for post_type in post_types:
                    self.limits[f"{platform}_{post_type}"] = RateLimit(
                        platform=platform,
                        post_type=post_type,
                        posts_per_hour=int(os.getenv(f'{platform.upper()}_POSTS_PER_HOUR', 10)),
                        posts_per_day=int(os.getenv(f'{platform.upper()}_POSTS_PER_DAY', 24)),
                        minimum_interval=int(os.getenv(f'{platform.upper()}_MINIMUM_INTERVAL', 300))
                    )
        except Exception as e:
            logger.error(f"Error loading rate limits: {str(e)}")
            raise

    def can_post(self, platform: str, post_type: str) -> bool:
        """Check if a post is allowed based on rate limits."""
        limit_key = f"{platform}_{post_type}"
        if limit_key not in self.limits:
            logger.warning(f"No rate limit configuration found for {limit_key}")
            return False

        limit = self.limits[limit_key]
        now = datetime.now()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Check minimum interval
            cursor.execute('''
                SELECT timestamp FROM post_history
                WHERE platform = ? AND post_type = ?
                ORDER BY timestamp DESC LIMIT 1
            ''', (platform, post_type))
            
            last_post = cursor.fetchone()
            if last_post:
                last_post_time = datetime.fromisoformat(last_post[0])
                if (now - last_post_time).total_seconds() < limit.minimum_interval:
                    logger.debug(f"Minimum interval not met for {platform}_{post_type}")
                    return False

            # Check hourly limit
            cursor.execute('''
                SELECT COUNT(*) FROM post_history
                WHERE platform = ? AND post_type = ?
                AND timestamp > ?
            ''', (platform, post_type, (now - timedelta(hours=1)).isoformat()))
            
            hourly_count = cursor.fetchone()[0]
            if hourly_count >= limit.posts_per_hour:
                logger.debug(f"Hourly limit reached for {platform}_{post_type}")
                return False

            # Check daily limit
            cursor.execute('''
                SELECT COUNT(*) FROM post_history
                WHERE platform = ? AND post_type = ?
                AND timestamp > ?
            ''', (platform, post_type, (now - timedelta(days=1)).isoformat()))
            
            daily_count = cursor.fetchone()[0]
            if daily_count >= limit.posts_per_day:
                logger.debug(f"Daily limit reached for {platform}_{post_type}")
                return False

        return True

    def record_post(self, platform: str, post_type: str):
        """Record a successful post."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO post_history (platform, post_type, timestamp)
                    VALUES (?, ?, ?)
                ''', (platform, post_type, datetime.now().isoformat()))
            logger.debug(f"Recorded post for {platform}_{post_type}")
        except Exception as e:
            logger.error(f"Error recording post: {str(e)}")

    def cleanup_old_records(self, days: int = 7):
        """Clean up records older than specified days."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    DELETE FROM post_history
                    WHERE timestamp < ?
                ''', ((datetime.now() - timedelta(days=days)).isoformat(),))
            logger.info(f"Cleaned up post history older than {days} days")
        except Exception as e:
            logger.error(f"Error cleaning up records: {str(e)}")