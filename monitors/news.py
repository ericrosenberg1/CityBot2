"""News monitoring module for CityBot2, handling RSS feeds and relevance scoring."""

import asyncio
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import feedparser
from bs4 import BeautifulSoup

logger = logging.getLogger("CityBot2.news")


@dataclass
class NewsArticleContent:
    """Structured news content."""

    title: str
    source: str
    url: str
    content_snippet: str
    published_date: datetime
    relevance_score: float
    location_data: dict[str, Any] | None = None
    map_path: str | None = None


class NewsMonitor:
    """Monitors RSS feeds for local news."""

    # How many evaluated URLs to remember. Feeds list at most 50 entries each,
    # so this covers every live entry across dozens of feeds.
    SEEN_URL_LIMIT = 5000
    # Skip entries older than this. They were either seen before a restart or
    # are stale, and the queue's dedupe ledger only reaches back 30 days.
    MAX_ARTICLE_AGE = timedelta(days=3)
    # Feeds fetched at once.
    FEED_CONCURRENCY = 4

    def __init__(self, config: dict[str, Any], city_config: dict[str, Any]):
        self.config = config
        self.city_config = city_config
        self.rss_feeds = city_config["news"]["rss_feeds"]
        self.location_keywords = city_config["news"]["location_keywords"]
        # Every URL already scored, relevant or not, so an off-topic link (or
        # one that isn't a web page) is fetched once instead of every cycle.
        self._seen_urls: OrderedDict[str, None] = OrderedDict()

    def set_sources(self, rss_feeds: dict[str, dict[str, Any]]) -> None:
        """Replace the feed list, e.g. with the sources managed in the admin UI.

        Each feed is {"url", "priority"} plus an optional "location_keywords"
        dict that overrides the city-wide keywords for that feed.
        """
        self.rss_feeds = rss_feeds

    def _remember(self, url: str) -> None:
        self._seen_urls[url] = None
        while len(self._seen_urls) > self.SEEN_URL_LIMIT:
            self._seen_urls.popitem(last=False)

    def _extract_location_data(self, text: str) -> dict[str, Any] | None:
        """Extract location information from article text."""
        location_data = {
            "latitude": self.city_config["coordinates"]["latitude"],
            "longitude": self.city_config["coordinates"]["longitude"],
            "description": None,
        }

        for location in self.location_keywords["at_least_one"]:
            if location.lower() in text.lower():
                location_data["description"] = location.title()
                return location_data

        return None

    def calculate_relevance_score(
        self, title: str, content: str, keywords: dict[str, list[str]] | None = None
    ) -> float:
        """Score 0-1 for how local an article is. The default minimum is 0.7.

        A place-name match is worth 0.7 on its own, a "city of X" style phrase
        adds 0.2, and each excluded term takes off 0.4. When must_include has
        terms, an article needs one of them to score at all.
        """
        keywords = keywords or self.location_keywords
        combined_text = f"{title.lower()} {content.lower()}"

        must_include = keywords.get("must_include", [])
        if must_include and not any(
            term.lower() in combined_text for term in must_include
        ):
            return 0.0

        score = 0.0
        if any(
            term.lower() in combined_text for term in keywords.get("at_least_one", [])
        ):
            score += 0.7

        for term in keywords.get("exclude", []):
            if term.lower() in combined_text:
                score -= 0.4

        city_name = re.escape(self.city_config["name"].lower())
        city_patterns = [
            rf"\b{city_name} city\b",
            rf"\bcity of {city_name}\b",
            rf"\bdowntown {city_name}\b",
        ]
        if any(re.search(pattern, combined_text) for pattern in city_patterns):
            score += 0.2

        return min(max(score, 0.0), 1.0)

    async def extract_article_content(
        self, session: aiohttp.ClientSession, url: str
    ) -> str:
        """Extract article content for relevance checking."""
        headers = {
            "User-Agent": "CityBot2/1.0 (News Aggregator)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Non-200 response (%d) fetching article: %s",
                        response.status,
                        url,
                    )
                    return ""
                # Some feeds link to PDFs or video (the city's agenda feed does),
                # which can't be read as text.
                if "html" not in response.content_type:
                    logger.debug(
                        "Skipping non-HTML article %s (%s)", url, response.content_type
                    )
                    return ""
                html = await response.text(errors="replace")
        except (TimeoutError, aiohttp.ClientError, OSError, ValueError) as exc:
            logger.warning("Error fetching article %s: %s", url, exc)
            return ""

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        article = soup.find("article") or soup.find(
            class_=re.compile(r"article|content|story")
        )
        if article:
            text = article.get_text(strip=True)
        else:
            text = " ".join(p.get_text(strip=True) for p in soup.find_all("p"))
        return text[:1000]

    def parse_date(self, entry: feedparser.FeedParserDict) -> datetime:
        """Parse publication date from feed entry."""
        try:
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                return datetime(*entry.published_parsed[:6], tzinfo=UTC)
            if hasattr(entry, "updated_parsed") and entry.updated_parsed:
                return datetime(*entry.updated_parsed[:6], tzinfo=UTC)
            return datetime.now(UTC)
        except (ValueError, TypeError, AttributeError):
            logger.exception("Error parsing date")
            return datetime.now(UTC)

    async def check_news(self) -> list[NewsArticleContent]:
        """Check RSS feeds for relevant news articles."""
        semaphore = asyncio.Semaphore(self.FEED_CONCURRENCY)

        async def limited(session, source, feed_info):
            async with semaphore:
                return await self._check_feed(session, source, feed_info)

        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *(
                    limited(session, source, info)
                    for source, info in self.rss_feeds.items()
                )
            )

        articles = [article for feed_articles in results for article in feed_articles]
        articles.sort(key=lambda x: x.published_date, reverse=True)
        logger.info("Total relevant articles found: %d", len(articles))
        return articles

    async def _check_feed(
        self, session: aiohttp.ClientSession, source: str, feed_info: dict[str, Any]
    ) -> list[NewsArticleContent]:
        """Fetch one feed and return its new, relevant articles."""
        min_relevance = self.config.get("minimum_relevance_score", 0.7)
        keywords = feed_info.get("location_keywords")
        oldest = datetime.now(UTC) - self.MAX_ARTICLE_AGE
        articles = []
        try:
            # feedparser.parse() does a blocking network fetch with no
            # built-in timeout, which would otherwise stall the whole
            # event loop (and every other monitor/post) on a slow or
            # hanging RSS server. Run it off-thread with a hard timeout,
            # the same pattern used for the earthquake/weather HTTP calls.
            feed = await asyncio.wait_for(
                asyncio.to_thread(feedparser.parse, feed_info["url"]),
                timeout=20.0,
            )
            logger.info("Fetched feed from %s, entries: %d", source, len(feed.entries))

            for entry in feed.entries[:50]:
                url = getattr(entry, "link", None)
                if not url or url in self._seen_urls:
                    continue
                self._remember(url)

                published = self.parse_date(entry)
                if published < oldest:
                    continue

                title = entry.get("title", "")
                content = entry.get("summary", "")
                if feed_info.get("priority") == 1:
                    additional_content = await self.extract_article_content(
                        session, url
                    )
                    content = f"{content} {additional_content}"

                score = self.calculate_relevance_score(title, content, keywords)
                if score < min_relevance:
                    continue

                articles.append(
                    NewsArticleContent(
                        title=title,
                        source=source,
                        url=url,
                        content_snippet=f"{content[:300]}...",
                        published_date=published,
                        relevance_score=score,
                        location_data=self._extract_location_data(f"{title} {content}"),
                    )
                )
        except (TimeoutError, OSError, ValueError, AttributeError, TypeError, KeyError):
            logger.exception("Error processing feed %s", source)
        return articles
