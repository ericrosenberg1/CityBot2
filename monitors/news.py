"""News monitoring module for CityBot2, handling RSS feeds and relevance scoring."""

import logging
import re
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path

import feedparser
import aiohttp
from bs4 import BeautifulSoup

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
        """Format news article for social media posting."""
        try:
            hashtag_text = ' '.join(f"#{tag}" for tag in hashtags)
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
        except (ValueError, OSError) as exc:
            logger.error("Error formatting news content: %s", exc, exc_info=True)
            raise
        except (TypeError, AttributeError) as exc:
            logger.error("Error formatting news content: %s", exc, exc_info=True)
            raise


class NewsMonitor:
    """Monitors RSS feeds for local news."""

    def __init__(self, config: Dict[str, Any], city_config: Dict[str, Any]):
        self.config = config
        self.city_config = city_config
        self.rss_feeds = city_config['news']['rss_feeds']
        self.location_keywords = city_config['news']['location_keywords']
        self.cache_dir = Path("cache/maps")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _extract_location_data(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract location information from article text."""
        location_data = {
            'latitude': self.city_config['coordinates']['latitude'],
            'longitude': self.city_config['coordinates']['longitude'],
            'description': None
        }

        for location in self.location_keywords['at_least_one']:
            if location.lower() in text.lower():
                location_data['description'] = location.title()
                return location_data

        return None

    def calculate_relevance_score(self, title: str, content: str) -> float:
        """Calculate relevance score for article."""
        combined_text = f"{title.lower()} {content.lower()}"
        score = 0.0

        if not any(term.lower() in combined_text for term in self.location_keywords['must_include']):
            return 0.0

        for term in self.location_keywords['at_least_one']:
            if term.lower() in combined_text:
                score += 0.3
                break

        for term in self.location_keywords['exclude']:
            if term.lower() in combined_text:
                score -= 0.2

        city_name = self.city_config['name'].lower()
        city_patterns = [
            fr"\b{city_name} city\b",
            fr"\bcity of {city_name}\b",
            fr"\bdowntown {city_name}\b"
        ]
        for pattern in city_patterns:
            if re.search(pattern, combined_text):
                score += 0.2
                break

        return min(max(score, 0.0), 1.0)

    async def extract_article_content(self, url: str) -> str:
        """Extract article content for relevance checking."""
        headers = {
            'User-Agent': 'CityBot2/1.0 (News Aggregator)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                            tag.decompose()

                        article = (soup.find('article') or
                                   soup.find(class_=re.compile(r'article|content|story')))
                        if article:
                            text = article.get_text(strip=True)
                        else:
                            text = ' '.join(p.get_text(strip=True) for p in soup.find_all('p'))

                        return text[:1000]

                    logger.warning("Non-200 response (%d) fetching article: %s",
                                   response.status, url)
                    return ""
        except (aiohttp.ClientError, OSError, ValueError, AttributeError,
                TypeError, asyncio.TimeoutError) as exc:
            logger.error("Error extracting content from %s: %s", url, exc, exc_info=True)
            return ""

    def parse_date(self, entry: feedparser.FeedParserDict) -> datetime:
        """Parse publication date from feed entry."""
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            return datetime.now(timezone.utc)
        except (ValueError, TypeError, AttributeError) as exc:
            logger.error("Error parsing date: %s", exc, exc_info=True)
            return datetime.now(timezone.utc)

    async def check_news(self) -> List[NewsArticleContent]:
        """Check RSS feeds for relevant news articles."""
        articles = []
        min_relevance = self.config.get('minimum_relevance_score', 0.7)

        for source, feed_info in self.rss_feeds.items():
            try:
                feed = feedparser.parse(feed_info['url'])
                entry_count = len(feed.entries)
                logger.info("Fetched feed from %s, entries: %d",
                            source, entry_count)

                for entry in feed.entries:
                    content = entry.get('summary', '')

                    if feed_info['priority'] == 1:
                        additional_content = await self.extract_article_content(entry.link)
                        content = f"{content} {additional_content}"

                    score = self.calculate_relevance_score(entry.title, content)

                    if score >= min_relevance:
                        combined_text = f"{entry.title} {content}"
                        location_data = self._extract_location_data(combined_text)

                        snippet = f"{content[:300]}..."
                        article = NewsArticleContent(
                            title=entry.title,
                            source=source,
                            url=entry.link,
                            content_snippet=snippet,
                            published_date=self.parse_date(entry),
                            relevance_score=score,
                            location_data=location_data
                        )
                        articles.append(article)
            except (OSError, ValueError, AttributeError, TypeError, KeyError) as exc:
                logger.error("Error processing feed %s: %s", source, exc, exc_info=True)

        articles.sort(key=lambda x: x.published_date, reverse=True)
        logger.info("Total relevant articles found: %d", len(articles))
        return articles
