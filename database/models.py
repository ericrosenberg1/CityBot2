from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime, 
    Boolean, Text, ForeignKey, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from datetime import datetime, timedelta
import logging
import os

logger = logging.getLogger('CityBot2.database')
Base = declarative_base()

class WeatherReport(Base):
    __tablename__ = 'weather_reports'
    
    id = Column(Integer, primary_key=True)
    temperature = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    wind_direction = Column(String(10), nullable=True)
    cloud_cover = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    forecast = Column(Text, nullable=True)
    posted = Column(Boolean, default=False)
    map_path = Column(String(255), nullable=True)
    
    post_history = relationship('PostHistory', back_populates='weather_report')

    def __repr__(self):
        return (f"<WeatherReport(id={self.id}, "
                f"temperature={self.temperature}, "
                f"timestamp={self.timestamp})>")

class WeatherAlert(Base):
    __tablename__ = 'weather_alerts'
    
    id = Column(Integer, primary_key=True)
    event = Column(String(100), nullable=True)
    headline = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    severity = Column(String(50), nullable=True)
    urgency = Column(String(50), nullable=True)
    areas = Column(Text, nullable=True)
    onset = Column(DateTime, nullable=True)
    expires = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    posted = Column(Boolean, default=False)
    
    post_history = relationship('PostHistory', back_populates='weather_alert')

    def __repr__(self):
        return (f"<WeatherAlert(id={self.id}, "
                f"event='{self.event}', "
                f"severity='{self.severity}', "
                f"timestamp={self.timestamp})>")

class Earthquake(Base):
    __tablename__ = 'earthquakes'
    
    id = Column(Integer, primary_key=True)
    magnitude = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    depth = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=True, index=True)
    distance = Column(Float, nullable=True)
    posted = Column(Boolean, default=False)
    map_path = Column(String(255), nullable=True)
    
    __table_args__ = (
        CheckConstraint('magnitude >= 0', name='check_magnitude_non_negative'),
        CheckConstraint('depth >= 0', name='check_depth_non_negative')
    )
    
    post_history = relationship('PostHistory', back_populates='earthquake')

    def __repr__(self):
        return (f"<Earthquake(id={self.id}, "
                f"magnitude={self.magnitude}, "
                f"location='{self.location}', "
                f"timestamp={self.timestamp})>")

class NewsArticle(Base):
    __tablename__ = 'news_articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=True)
    source = Column(String(100), nullable=True)
    url = Column(String(512), unique=True, nullable=True)
    published_date = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    content_snippet = Column(Text, nullable=True)
    posted = Column(Boolean, default=False)
    relevance_score = Column(Float, nullable=True)
    map_path = Column(String(255), nullable=True)
    
    post_history = relationship('PostHistory', back_populates='news_article')

    def __repr__(self):
        return (f"<NewsArticle(id={self.id}, "
                f"title='{self.title}', "
                f"source='{self.source}')>")

class PostHistory(Base):
    """Model for tracking social media post history."""
    __tablename__ = 'post_history'

    id = Column(Integer, primary_key=True)
    platform = Column(String(50), nullable=False, index=True)
    item_type = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Foreign keys to related items
    weather_report_id = Column(Integer, ForeignKey('weather_reports.id'), nullable=True)
    weather_alert_id = Column(Integer, ForeignKey('weather_alerts.id'), nullable=True)
    earthquake_id = Column(Integer, ForeignKey('earthquakes.id'), nullable=True)
    news_article_id = Column(Integer, ForeignKey('news_articles.id'), nullable=True)
    
    # Relationships
    weather_report = relationship('WeatherReport', back_populates='post_history')
    weather_alert = relationship('WeatherAlert', back_populates='post_history')
    earthquake = relationship('Earthquake', back_populates='post_history')
    news_article = relationship('NewsArticle', back_populates='post_history')

    def __repr__(self):
        return (f"<PostHistory(id={self.id}, "
                f"platform='{self.platform}', "
                f"item_type='{self.item_type}', "
                f"timestamp={self.timestamp})>")

def create_database(database_url: str):
    """
    Create database engine and session factory.
    
    :param database_url: SQLAlchemy database connection URL
    :return: Tuple of (engine, SessionLocal)
    """
    try:
        engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return engine, SessionLocal
    except Exception as e:
        logger.error(f"Error creating database: {str(e)}")
        raise

def cleanup_old_records(session: Session, days: int = 7):
    """
    Clean up old records across different tables.
    
    :param session: SQLAlchemy session
    :param days: Number of days to keep records
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # Cleanup WeatherReports
        deleted_weather = session.query(WeatherReport).filter(WeatherReport.timestamp < cutoff).delete(synchronize_session=False)
        
        # Cleanup WeatherAlerts
        deleted_alerts = session.query(WeatherAlert).filter(WeatherAlert.timestamp < cutoff).delete(synchronize_session=False)
        
        # Cleanup Earthquakes
        deleted_earthquakes = session.query(Earthquake).filter(Earthquake.timestamp < cutoff).delete(synchronize_session=False)
        
        # Cleanup NewsArticles - use either published_date or timestamp
        deleted_news = session.query(NewsArticle).filter(
            (NewsArticle.published_date < cutoff) | (NewsArticle.timestamp < cutoff)
        ).delete(synchronize_session=False)
        
        # Cleanup PostHistory
        deleted_history = session.query(PostHistory).filter(PostHistory.timestamp < cutoff).delete(synchronize_session=False)
        
        session.commit()
        logger.info(f"Cleaned up records older than {days} days: "
                    f"Weather Reports: {deleted_weather}, "
                    f"Weather Alerts: {deleted_alerts}, "
                    f"Earthquakes: {deleted_earthquakes}, "
                    f"News Articles: {deleted_news}, "
                    f"Post History: {deleted_history}")
    except Exception as e:
        session.rollback()
        logger.error(f"Error cleaning up old records: {str(e)}")

def add_weather_report(session: Session, **kwargs):
    """
    Add a new weather report to the database.
    
    :param session: SQLAlchemy session
    :param kwargs: Keyword arguments for WeatherReport
    :return: Added WeatherReport instance
    """
    try:
        report = WeatherReport(**kwargs)
        session.add(report)
        session.commit()
        session.refresh(report)
        return report
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding weather report: {str(e)}")
        raise

def record_post(session: Session, platform: str, item_type: str, related_item):
    """
    Record a social media post in the database.
    
    :param session: SQLAlchemy session
    :param platform: Social media platform name
    :param item_type: Type of item being posted
    :param related_item: Related database model instance
    :return: Added PostHistory instance
    """
    try:
        post_history = PostHistory(
            platform=platform,
            item_type=item_type,
            weather_report=(related_item if isinstance(related_item, WeatherReport) else None),
            weather_alert=(related_item if isinstance(related_item, WeatherAlert) else None),
            earthquake=(related_item if isinstance(related_item, Earthquake) else None),
            news_article=(related_item if isinstance(related_item, NewsArticle) else None)
        )
        session.add(post_history)
        session.commit()
        session.refresh(post_history)
        return post_history
    except Exception as e:
        session.rollback()
        logger.error(f"Error recording post history: {str(e)}")
        raise