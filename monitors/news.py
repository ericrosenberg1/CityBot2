import feedparser
import aiohttp
from bs4 import BeautifulSoup
import logging
from typing import List, Dict, Set
import re
from datetime import datetime, timezone
import time
from urllib.parse import urlparse

logger = logging.getLogger('CityBot2.news')

class NewsMonitor:
    def __init__(self, config: Dict, city_config: Dict):
        self.config = config
        self.city_config = city_config
        self.rss_feeds = city_config['news']['rss_feeds']
        self.location_keywords = city_config['news']['location_keywords']

    def calculate_relevance_score(self, title: str, content: str) -> float:
        """Calculate relevance score for article."""
        text = f"{title.lower()} {content.lower()}"
        score = 0.0
        
        # Check for must-include terms
        if not any(term in text for term in self.location_keywords['must_include']):
            return 0.0
        
        # Check for specific location mentions
        for term in self.location_keywords['at_least_one']:
            if term in text:
                score += 0.3
        
        # Check for exclusion terms
        for term in self.location_keywords['exclude']:
            if term in text:
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
        
        return min(max(score, 0.0), 1.0)

    async def extract_article_content(self, url: str) -> str:
        """Extract article content for relevance checking."""
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
        """Parse publication date from feed entry."""
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            return datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error parsing date: {str(e)}")
            return datetime.now(timezone.utc)

    async def check_news(self) -> List[Dict]:
        """Check RSS feeds for relevant news articles."""
        articles = []
        
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
                    
                    if score >= self.config.get('minimum_relevance_score', 0.7):
                        articles.append({
                            'title': entry.title,
                            'source': source,
                            'url': entry.link,
                            'published_date': self.parse_date(entry),
                            'content_snippet': content[:300] + '...',
                            'relevance_score': score
                        })
            
            except Exception as e:
                logger.error(f"Error processing feed {source}: {str(e)}")
                continue
        
        # Sort by publication date
        articles.sort(key=lambda x: x['published_date'], reverse=True)
        return articles