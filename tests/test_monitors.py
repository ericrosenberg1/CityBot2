import asyncio
import time
from types import SimpleNamespace

import feedparser

from monitors.news import NewsMonitor
from monitors.weather import WeatherMonitor


def news_monitor(city_config):
    return NewsMonitor({"minimum_relevance_score": 0.7}, city_config)


def test_one_place_match_clears_the_default_threshold(city_config):
    # With an empty must_include list every article scored 0, and even a
    # perfect match topped out at 0.5, under the 0.7 threshold.
    monitor = news_monitor(city_config)
    assert monitor.calculate_relevance_score("New cafe at Ventura Harbor", "") >= 0.7
    assert monitor.calculate_relevance_score("Weather in Phoenix", "") == 0.0


def test_excluded_place_sinks_the_score(city_config):
    monitor = news_monitor(city_config)
    assert (
        monitor.calculate_relevance_score("Ventura County news", "Oxnard council votes")
        < 0.7
    )


def test_must_include_still_gates_when_set(city_config):
    monitor = news_monitor(city_config)
    keywords = {"must_include": ["harbor"], "at_least_one": ["ventura"], "exclude": []}
    assert monitor.calculate_relevance_score("Ventura budget", "", keywords) == 0.0
    assert (
        monitor.calculate_relevance_score("Ventura harbor budget", "", keywords) >= 0.7
    )


class FakeResponse:
    def __init__(self, status=200, content_type="text/html", body=b""):
        self.status = status
        self.content_type = content_type
        self.body = body

    async def text(self, errors="strict"):
        return self.body.decode("utf-8", errors=errors)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.response


def test_pdf_links_are_skipped_not_decoded(city_config):
    # The city's agenda feed links to PDFs. Decoding them as UTF-8 raised and
    # logged a traceback for each one, every cycle.
    monitor = news_monitor(city_config)
    session = FakeSession(
        FakeResponse(content_type="application/pdf", body=b"%PDF-\xe2\x00")
    )
    assert (
        asyncio.run(monitor.extract_article_content(session, "https://x/agenda")) == ""
    )


def test_bad_bytes_in_html_are_replaced(city_config):
    monitor = news_monitor(city_config)
    session = FakeSession(FakeResponse(body=b"<p>Ventura \xff harbor</p>"))
    assert "Ventura" in asyncio.run(
        monitor.extract_article_content(session, "https://x/a")
    )


def test_irrelevant_links_are_fetched_once(city_config, monkeypatch):
    monitor = news_monitor(city_config)
    entry = feedparser.FeedParserDict(
        link="https://x/off-topic",
        title="Phoenix zoning",
        summary="",
        published_parsed=time.gmtime(),
    )
    monkeypatch.setattr(
        feedparser, "parse", lambda url: SimpleNamespace(entries=[entry])
    )
    session = FakeSession(FakeResponse(body=b"<p>nothing local</p>"))
    feed = {"url": "https://x/rss", "priority": 1}

    for _ in range(3):
        assert asyncio.run(monitor._check_feed(session, "Test", feed)) == []
    assert session.calls == 1


def test_old_entries_are_skipped(city_config, monkeypatch):
    monitor = news_monitor(city_config)
    entry = feedparser.FeedParserDict(
        link="https://x/old",
        title="Ventura harbor story",
        summary="",
        published_parsed=time.gmtime(time.time() - 10 * 86400),
    )
    monkeypatch.setattr(
        feedparser, "parse", lambda url: SimpleNamespace(entries=[entry])
    )
    feed = {"url": "https://x/rss", "priority": 2}
    assert (
        asyncio.run(monitor._check_feed(FakeSession(FakeResponse()), "Test", feed))
        == []
    )


def test_cloud_cover_and_wind_direction_are_human_readable(city_config):
    monitor = WeatherMonitor({}, city_config)
    # NWS sends codes like "BKN", which used to print as "Cloud Cover: BKN%".
    assert monitor._get_cloud_cover([{"amount": "FEW"}, {"amount": "BKN"}]) == 75
    assert monitor._get_cloud_cover([]) == 0
    # And degrees, which printed as "Wind: 5mph 270".
    assert monitor._compass_direction(270) == "W"
    assert monitor._compass_direction(None) == "Unknown"
