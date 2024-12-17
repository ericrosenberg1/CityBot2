from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import func
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.pool import Pool
from typing import List, Optional, Dict, Any, TypeVar, Type
from datetime import datetime, timedelta
from pathlib import Path
import logging
import sqlite3

from .models import (
    Base,
    WeatherReport,
    WeatherAlert, 
    Earthquake,
    NewsArticle,
    PostHistory
)

logger = logging.getLogger('CityBot2.database')

T = TypeVar('T')

class DatabaseManager:
    """Manages database operations for CityBot2."""
    
    def __init__(self, db_url: str = None):
        """Initialize database manager.
        
        Args:
            db_url: Database connection URL. Defaults to SQLite database in data directory.
        """
        if db_url is None:
            data_dir = Path('data')
            data_dir.mkdir(exist_ok=True)
            db_url = f"sqlite:///{data_dir}/citybot.db"

        try:
            self.engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            # Register event listeners
            event.listen(Pool, 'connect', self._on_connect)
            event.listen(Pool, 'checkout', self._on_checkout)
            
            # Create tables
            self._initialize_database()
            
            # Create session factory
            session_factory = sessionmaker(bind=self.engine)
            self.Session = scoped_session(session_factory)
            
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            raise

    def _initialize_database(self):
        """Create database tables if they don't exist."""
        try:
            Base.metadata.create_all(self.engine)
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            raise

    @staticmethod
    def _on_connect(dbapi_connection, connection_record):
        """Configure SQLite connection."""
        if isinstance(dbapi_connection, sqlite3.Connection):
            dbapi_connection.execute('PRAGMA journal_mode=WAL')
            dbapi_connection.execute('PRAGMA synchronous=NORMAL')

    @staticmethod
    def _on_checkout(dbapi_connection, connection_record, connection_proxy):
        """Validate connection on checkout."""
        if isinstance(dbapi_connection, sqlite3.Connection):
            try:
                dbapi_connection.execute('SELECT 1')
            except sqlite3.Error:
                logger.error("Invalid database connection, reconnecting...")
                raise OperationalError("Invalid connection")

    def _get_unposted_items(self, model: Type[T], **filters) -> List[T]:
        """Generic method to get unposted items of any type."""
        try:
            with self.Session() as session:
                query = session.query(model).filter_by(posted=False)
                
                # Apply additional filters
                for key, value in filters.items():
                    if hasattr(model, key):
                        query = query.filter(getattr(model, key) == value)
                
                # Add timestamp order if available
                if hasattr(model, 'timestamp'):
                    query = query.order_by(model.timestamp.desc())
                
                return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving {model.__name__} items: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error retrieving {model.__name__} items: {str(e)}")
            return []

    def get_unposted_weather(self) -> Optional[WeatherReport]:
        """Get most recent unposted weather report."""
        return self._get_unposted_items(WeatherReport, limit=1)

    def get_unposted_alerts(self) -> List[WeatherAlert]:
        """Get active unposted weather alerts."""
        try:
            with self.Session() as session:
                return session.query(WeatherAlert)\
                    .filter_by(posted=False)\
                    .filter(WeatherAlert.expires > datetime.utcnow())\
                    .all()
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving weather alerts: {str(e)}")
            return []

    def get_unposted_earthquakes(self) -> List[Earthquake]:
        """Get unposted earthquakes."""
        return self._get_unposted_items(Earthquake)

    def get_unposted_news(self, min_relevance: float = 0.7) -> List[NewsArticle]:
        """Get unposted news articles above relevance threshold."""
        try:
            with self.Session() as session:
                return session.query(NewsArticle)\
                    .filter_by(posted=False)\
                    .filter(NewsArticle.relevance_score >= min_relevance)\
                    .order_by(NewsArticle.published_date.desc())\
                    .all()
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving news articles: {str(e)}")
            return []

    def add_item(self, item: Any) -> bool:
        """Add a new item to the database."""
        try:
            with self.Session() as session:
                session.add(item)
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(f"Database error adding {type(item).__name__}: {str(e)}")
            return False

    def mark_posted(self, item: Any, platform: str) -> bool:
        """Mark an item as posted and record posting history."""
        if not platform:
            logger.error("Platform must be specified when marking item as posted")
            return False

        try:
            with self.Session() as session:
                if isinstance(item, (WeatherReport, WeatherAlert, Earthquake, NewsArticle)):
                    # Update item status
                    session.merge(item)
                    item.posted = True
                    
                    # Create post history entry with appropriate foreign key
                    history = PostHistory(
                        platform=platform,
                        item_type=type(item).__name__
                    )
                    
                    # Set the appropriate relationship
                    if isinstance(item, WeatherReport):
                        history.weather_report = item
                    elif isinstance(item, WeatherAlert):
                        history.weather_alert = item
                    elif isinstance(item, Earthquake):
                        history.earthquake = item
                    elif isinstance(item, NewsArticle):
                        history.news_article = item
                    
                    session.add(history)
                    session.commit()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error(f"Database error marking item as posted: {str(e)}")
            session.rollback()
            return False

    def cleanup_old_records(self, days: int = 7) -> bool:
        """Remove records older than specified days."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            with self.Session() as session:
                for model in [WeatherReport, WeatherAlert, Earthquake, NewsArticle, PostHistory]:
                    deleted = session.query(model)\
                        .filter(model.timestamp < cutoff)\
                        .delete(synchronize_session=False)
                    logger.info(f"Deleted {deleted} old {model.__name__} records")
                session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Database error during cleanup: {str(e)}")
            return False

    def get_posting_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get posting statistics for the specified time period."""
        try:
            with self.Session() as session:
                stats = {
                    'total_posts': 0,
                    'platform_breakdown': {},
                    'type_breakdown': {},
                    'daily_average': 0
                }
                
                cutoff = datetime.utcnow() - timedelta(days=days)
                
                # Get basic counts
                total = session.query(func.count(PostHistory.id))\
                    .filter(PostHistory.timestamp >= cutoff)\
                    .scalar()
                stats['total_posts'] = total or 0
                
                # Platform breakdown
                platform_counts = session.query(
                    PostHistory.platform,
                    func.count(PostHistory.id)
                ).filter(
                    PostHistory.timestamp >= cutoff
                ).group_by(
                    PostHistory.platform
                ).all()
                
                stats['platform_breakdown'] = dict(platform_counts)
                
                # Type breakdown
                type_counts = session.query(
                    PostHistory.item_type,
                    func.count(PostHistory.id)
                ).filter(
                    PostHistory.timestamp >= cutoff
                ).group_by(
                    PostHistory.item_type
                ).all()
                
                stats['type_breakdown'] = dict(type_counts)
                
                # Calculate daily average
                stats['daily_average'] = stats['total_posts'] / days if days > 0 else 0
                
                return stats
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving posting stats: {str(e)}")
            return {}

    def close(self):
        """Close database connections."""
        try:
            self.Session.remove()
            self.engine.dispose()
        except Exception as e:
            logger.error(f"Error closing database connections: {str(e)}")