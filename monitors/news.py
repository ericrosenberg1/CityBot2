from datetime import datetime, timezone
import logging
from typing import List, Dict, Optional, Any
import feedparser
import aiohttp
from bs4 import BeautifulSoup
import re
from dataclasses import dataclass
from pathlib import Path
from social_media.utils import PostContent, MediaContent

logger = logging.getLogger('CityBot2.news')

@dataclass
class NewsArticleContent:
    """Structured news content for social media posts."""
    title: str
    source: str
    url: str
    content_snippet: str
    published_date: datetime
    relevance_score: float
    location_data: Optional[Dict[str, Any]] = None
    map_path: Optional[str] = None

    def format_for_social(self, hashtags: List[str]) -> PostContent:
        """Format news article for social media posting.
        
        Args:
            hashtags: List of hashtags to append to the post
            
        Returns:
            PostContent object ready for social media posting
        """
        try:
            hashtag_text = ' '.join([f"#{tag}" for tag in hashtags])
            
            text = (
                f"📰 {self.title}\n\n"
                f"{self.content_snippet}\n\n"
                f"Source: {self.source}\n"
                f"{self.url}\n\n"
                f"{hashtag_text}"
            )

            return PostContent(
                text=text,
                media=MediaContent(
                    image_path=self.map_path,
                    link_url=self.url,
                    meta_title=self.title,
                    meta_description=self.content_snippet[:200]
                )
            )
        except Exception as e:
            logger.error(f"Error formatting news content: {str(e)}")
            raise

class NewsMonitor:
    """Monitors RSS feeds for local news."""
    
    def __init__(self, config: Dict[str, Any], city_config: Dict[str, Any]):
        """Initialize the news monitor.
        
        Args:
            config: News configuration dictionary
            city_config: City-specific configuration
        """
        self.config = config
        self.city_config = city_config
        self.rss_feeds = city_config['news']['rss_feeds']
        self.location_keywords = city_config['news']['location_keywords']
        self.cache_dir = Path("cache/maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _extract_location_data(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract location information from article text.
        
        Args:
            text: Article text to analyze
            
        Returns:
            Dictionary containing location data if found, None otherwise
        """
        location_data = {
            'latitude': self.city_config['coordinates']['latitude'],
            'longitude': self.city_config['coordinates']['longitude'],
            'description': None
        }

        locations = self.location_keywords['at_least_one']
        for location in locations:
            if location.lower() in text.lower():
                location_data['description'] = location.title()
                return location_data

        return None

    def calculate_relevance_score(self, title: str, content: str) -> float:
        """Calculate relevance score for article.
        
        Args:
            title: Article title
            content: Article content or summary
            
        Returns:
            Float between 0 and 1 indicating relevance
        """
        text = f"{title.lower()} {content.lower()}"
        score = 0.0
        
        # Must include required terms
        if not any(term.lower() in text for term in self.location_keywords['must_include']):
            return 0.0
        
        # Check for specific location mentions
        for term in self.location_keywords['at_least_one']:
            if term.lower() in text:
                score += 0.3
                break  # Only count once
        
        # Check for exclusion terms
        for term in self.location_keywords['exclude']:
            if term.lower() in text:
                score -= 0.2
        
        # Bonus for city-specific mentions
        city_name = self.city_config['name'].lower()
        city_patterns = [
            f'\\b{city_name} city\\b',
            f'\\bcity of {city_name}\\b',
            f'\\bdowntown {city_name}\\b'
        ]
        for pattern in city_patterns:
            if re.search(pattern, text):
                score += 0.2
                break  # Only count once

        return min(max(score, 0.0), 1.0)

    async def extract_article_content(self, url: str) -> str:
        """Extract article content for relevance checking.
        
        Args:
            url: Article URL to fetch
            
        Returns:
            Extracted text content from the article
        """
        try:
            headers = {
                'User-Agent': 'CityBot2/1.0 (News Aggregator)',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Remove unwanted elements
                        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                            tag.decompose()
                        
                        # Look for article content
                        article = soup.find('article') or soup.find(class_=re.compile(r'article|content|story'))
                        if article:
                            text = article.get_text(strip=True)
                        else:
                            # Fallback to paragraphs
                            text = ' '.join(p.get_text(strip=True) for p in soup.find_all('p'))
                        
                        return text[:1000]  # Limit content length
                    
                    return ""
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {str(e)}")
            return ""

    def parse_date(self, entry: feedparser.FeedParserDict) -> datetime:
        """Parse publication date from feed entry.
        
        Args:
            entry: Feed entry from feedparser
            
        Returns:
            Parsed datetime object
        """
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            return datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error parsing date: {str(e)}")
            return datetime.now(timezone.utc)

    async def check_news(self) -> List[NewsArticleContent]:
        """Check RSS feeds for relevant news articles.
        
        Returns:
            List of NewsArticleContent objects sorted by publication date
        """
        articles = []
        min_relevance = self.config.get('minimum_relevance_score', 0.7)
        
        for source, feed_info in self.rss_feeds.items():
            try:
                feed = feedparser.parse(feed_info['url'])
                
                for entry in feed.entries:
                    # Get initial content
                    content = entry.get('summary', '')
                    
                    # For high-priority sources, fetch full content
                    if feed_info['priority'] == 1:
                        additional_content = await self.extract_article_content(entry.link)
                        content = f"{content} {additional_content}"
                    
                    # Calculate relevance score
                    score = self.calculate_relevance_score(entry.title, content)
                    
                    if score >= min_relevance:
                        # Extract location data
                        location_data = self._extract_location_data(f"{entry.title} {content}")
                        
                        article = NewsArticleContent(
                            title=entry.title,
                            source=source,
                            url=entry.link,
                            content_snippet=content[:300] + '...',
                            published_date=self.parse_date(entry),
                            relevance_score=score,
                            location_data=location_data
                        )
                        articles.append(article)
            
            except Exception as e:
                logger.error(f"Error processing feed {source}: {str(e)}")
                continue
        
        # Sort by publication date
        articles.sort(key=lambda x: x.published_date, reverse=True)
        return articles

    async def cleanup(self) -> None:
        """Cleanup any resources."""
        pass