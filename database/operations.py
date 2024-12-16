from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from typing import List, Optional
from datetime import datetime, timedelta
from .models import Base, WeatherReport, WeatherAlert, Earthquake, NewsArticle
import logging

logger = logging.getLogger('CityBot2.database')

class DatabaseManager:
    def __init__(self, db_url: str = "sqlite:///data/ventura_news.db"):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def get_unposted_weather(self) -> Optional[WeatherReport]:
        with self.Session() as session:
            return session.query(WeatherReport)\
                .filter_by(posted=False)\
                .order_by(WeatherReport.timestamp.desc())\
                .first()

    def get_unposted_alerts(self) -> List[WeatherAlert]:
        with self.Session() as session:
            return session.query(WeatherAlert)\
                .filter_by(posted=False)\
                .filter(WeatherAlert.expires > datetime.utcnow())\
                .all()

    def get_unposted_earthquakes(self) -> List[Earthquake]:
        with self.Session() as session:
            return session.query(Earthquake)\
                .filter_by(posted=False)\
                .order_by(Earthquake.timestamp.desc())\
                .all()

    def get_unposted_news(self) -> List[NewsArticle]:
        with self.Session() as session:
            return session.query(NewsArticle)\
                .filter_by(posted=False)\
                .filter(NewsArticle.relevance_score >= 0.7)\
                .order_by(NewsArticle.published_date.desc())\
                .all()

    def mark_posted(self, item, item_type: str):
        with self.Session() as session:
            if isinstance(item, (WeatherReport, WeatherAlert, Earthquake, NewsArticle)):
                session.merge(item)
                item.posted = True
                session.commit()

    def cleanup_old_records(self, days: int = 7):
        """Remove records older than specified days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self.Session() as session:
            for model in [WeatherReport, WeatherAlert, Earthquake, NewsArticle]:
                session.query(model)\
                    .filter(model.timestamp < cutoff)\
                    .delete()
            session.commit()