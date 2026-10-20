import logging
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import scoped_session, sessionmaker

from .models import (
    Base,
    Earthquake,
    NewsArticle,
    PostHistory,
    WeatherAlert,
    WeatherReport,
    _utcnow,
)

logger = logging.getLogger("CityBot2.database")

T = TypeVar("T")


class DatabaseManager:
    """Manages database operations for CityBot2."""

    def __init__(self, db_url: str | None = None):
        """Initialize database manager.

        Args:
            db_url: Database connection URL. Defaults to SQLite database in data directory.
        """
        if db_url is None:
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            db_url = f"sqlite:///{data_dir}/citybot.db"

        try:
            self.engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)

            # Listen on this engine only. Listening on the Pool class registered
            # the hooks process-wide, once more for every DatabaseManager built.
            # pool_pre_ping already checks each connection on checkout.
            event.listen(self.engine, "connect", self._on_connect)

            # Create tables
            self._initialize_database()

            # Create session factory
            session_factory = sessionmaker(bind=self.engine)
            self.Session = scoped_session(session_factory)

            logger.info("Database initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing database: {e!s}")
            raise

    def _initialize_database(self):
        """Create database tables if they don't exist."""
        try:
            Base.metadata.create_all(self.engine)
        except Exception as e:
            logger.error(f"Error creating database tables: {e!s}")
            raise

    @staticmethod
    def _on_connect(dbapi_connection, connection_record):
        """Configure SQLite connection."""
        if isinstance(dbapi_connection, sqlite3.Connection):
            dbapi_connection.execute("PRAGMA journal_mode=WAL")
            dbapi_connection.execute("PRAGMA synchronous=NORMAL")

    def cleanup_old_records(self, days: int = 7) -> bool:
        """Remove records older than specified days."""
        try:
            cutoff = _utcnow() - timedelta(days=days)
            with self.Session() as session:
                for model in [
                    WeatherReport,
                    WeatherAlert,
                    Earthquake,
                    NewsArticle,
                    PostHistory,
                ]:
                    deleted = (
                        session.query(model)
                        .filter(model.timestamp < cutoff)
                        .delete(synchronize_session=False)
                    )
                    logger.info(f"Deleted {deleted} old {model.__name__} records")
                session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Database error during cleanup: {e!s}")
            return False

    def close(self):
        """Close database connections."""
        try:
            self.Session.remove()
            self.engine.dispose()
        except Exception:
            logger.exception("Error closing database connections")
