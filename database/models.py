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
    content_preview = Column(String(100), nullable=True)  # Added this column
    
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


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(100))
    role = Column(String(20), nullable=False, default='editor')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    invited_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    invite_token = Column(String(100), nullable=True, unique=True)
    invite_expires = Column(DateTime, nullable=True)


class SocialAccount(Base):
    __tablename__ = 'social_accounts'
    id = Column(Integer, primary_key=True)
    platform = Column(String(50), nullable=False)
    account_name = Column(String(255))
    auth_method = Column(String(20), nullable=False, default='api_key')
    credentials_json = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    connected_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)


class Announcement(Base):
    __tablename__ = 'announcements'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    scheduled_for = Column(DateTime, nullable=True)
    posted = Column(Boolean, default=False)
    posted_at = Column(DateTime, nullable=True)


class EmailSubscriber(Base):
    __tablename__ = 'email_subscribers'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    confirmed = Column(Boolean, default=False)
    confirm_token = Column(String(100), unique=True)
    unsubscribe_token = Column(String(100), unique=True)
    preferences = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)


class DataSource(Base):
    __tablename__ = 'data_sources'
    id = Column(Integer, primary_key=True)
    source_type = Column(String(50), nullable=False)  # 'rss', 'weather', 'earthquake'
    name = Column(String(255), nullable=False)
    url = Column(String(512), nullable=True)
    is_enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=2)  # 1=high, 2=normal, 3=low
    check_interval = Column(Integer, default=1800)
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    last_checked = Column(DateTime, nullable=True)


class KeywordFilter(Base):
    __tablename__ = 'keyword_filters'
    id = Column(Integer, primary_key=True)
    data_source_id = Column(Integer, ForeignKey('data_sources.id', ondelete='CASCADE'), nullable=False)
    keyword = Column(String(255), nullable=False)
    filter_type = Column(String(20), nullable=False)  # 'must_include', 'at_least_one', 'exclude'
    data_source = relationship('DataSource', backref='keyword_filters')


class PostQueue(Base):
    __tablename__ = 'post_queue'
    id = Column(Integer, primary_key=True)
    content_type = Column(String(50), nullable=False, index=True)
    priority = Column(String(20), nullable=False, index=True)  # 'immediate', 'scheduled', 'drip'
    status = Column(String(20), nullable=False, default='pending', index=True)
    title = Column(String(500), nullable=True)
    content_text = Column(Text, nullable=False)
    content_json = Column(Text, nullable=True)
    media_path = Column(String(512), nullable=True)
    link_url = Column(String(512), nullable=True)
    image_url = Column(String(512), nullable=True)
    source_name = Column(String(255), nullable=True)
    scheduled_for = Column(DateTime, nullable=True)
    earliest_post = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    posted_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    is_public = Column(Boolean, default=True)
    weather_report_id = Column(Integer, ForeignKey('weather_reports.id'), nullable=True)
    earthquake_id = Column(Integer, ForeignKey('earthquakes.id'), nullable=True)
    news_article_id = Column(Integer, ForeignKey('news_articles.id'), nullable=True)
    announcement_id = Column(Integer, ForeignKey('announcements.id'), nullable=True)


def create_database(database_url: str):
    """
    Create database engine and session factory.

    Args:
        database_url: SQLAlchemy database connection URL
    Returns:
        Tuple of (engine, SessionLocal)
    """
    try:
        engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return engine, SessionLocal
    except Exception as e:
        logger.error(f"Error creating database: {str(e)}")
        raise