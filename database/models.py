from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class WeatherReport(Base):
    __tablename__ = 'weather_reports'
    
    id = Column(Integer, primary_key=True)
    temperature = Column(Float)
    wind_speed = Column(Float)
    wind_direction = Column(String(10))
    cloud_cover = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    forecast = Column(Text)
    posted = Column(Boolean, default=False)
    map_path = Column(String(255), nullable=True)

class WeatherAlert(Base):
    __tablename__ = 'weather_alerts'
    
    id = Column(Integer, primary_key=True)
    event = Column(String(100))
    headline = Column(String(255))
    description = Column(Text)
    severity = Column(String(50))
    urgency = Column(String(50))
    areas = Column(Text)
    onset = Column(DateTime)
    expires = Column(DateTime)
    posted = Column(Boolean, default=False)

class Earthquake(Base):
    __tablename__ = 'earthquakes'
    
    id = Column(Integer, primary_key=True)
    magnitude = Column(Float)
    location = Column(String(255))
    depth = Column(Float)
    timestamp = Column(DateTime)
    distance = Column(Float)
    posted = Column(Boolean, default=False)

class NewsArticle(Base):
    __tablename__ = 'news_articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    source = Column(String(100))
    url = Column(String(512), unique=True)
    published_date = Column(DateTime)
    content_snippet = Column(Text)
    posted = Column(Boolean, default=False)
    relevance_score = Column(Float)