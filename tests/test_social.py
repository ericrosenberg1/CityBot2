import asyncio
from datetime import UTC, datetime

import pytest

from social_media.formatters import format_weather_alert_for_social
from social_media.social_media_manager import SocialMediaManager
from social_media.utils import PostContent, RateLimiter
from utils.maps import LocationMapGenerator


def test_rate_limiter_reads_per_platform_limits(tmp_path):
    # The limits were looked up one level too deep, so config never applied.
    limiter = RateLimiter(
        str(tmp_path / "rl.db"), {"bluesky": {"hourly": 1, "interval": 0}}
    )

    async def scenario():
        assert await limiter.can_post("bluesky", "news")
        await limiter.record_post("bluesky", "news", "x")
        assert not await limiter.can_post("bluesky", "news")  # hourly cap of 1
        assert await limiter.can_post("twitter", "news")  # defaults elsewhere

    asyncio.run(scenario())


def test_rate_limiter_enforces_interval(tmp_path):
    limiter = RateLimiter(str(tmp_path / "rl.db"), {})

    async def scenario():
        await limiter.record_post("twitter", "news", "x")
        return await limiter.can_post("twitter", "news")

    assert asyncio.run(scenario()) is False


class FlakyPlatform:
    CHAR_LIMIT = 300

    def __init__(self):
        self.calls = 0

    def format_post(self, content):
        return content

    async def post_update(self, content):
        self.calls += 1
        raise RuntimeError("network down")


@pytest.fixture
def manager(tmp_path, city_config, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = SocialMediaManager({"platforms": {}, "retry_delay": 0}, city_config)
    mgr.platforms["bluesky"] = FlakyPlatform()
    mgr.config["platforms"]["bluesky"] = {"enabled": True, "post_types": ["news"]}
    return mgr


def test_failures_never_lock_a_platform_out(manager):
    # Three exceptions used to block the platform until the bot restarted.
    for _ in range(3):
        result = asyncio.run(manager.post_content(PostContent(text="hi"), "news"))
        assert result["bluesky"].success is False
        assert result["bluesky"].skipped is False
    assert manager.platforms["bluesky"].calls == 3 * manager.max_retries


def test_disabled_post_type_is_skipped(manager):
    result = asyncio.run(manager.post_content(PostContent(text="hi"), "weather_alert"))
    assert result["bluesky"].skipped is True


class Alert:
    event = "Wind Advisory"
    headline = "Gusts to 50 mph"
    severity = "Moderate"
    urgency = "Expected"
    areas = "Ventura County Coast"

    def __init__(self, expires):
        self.expires = expires


def test_alert_without_expiry_formats():
    assert "Valid until" not in format_weather_alert_for_social(Alert(None), []).text


def test_alert_expiry_shows_city_time():
    from zoneinfo import ZoneInfo

    expires = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
    text = format_weather_alert_for_social(
        Alert(expires), [], ZoneInfo("America/Los_Angeles")
    ).text
    assert "12:00 PM PST" in text


def test_location_map_is_none_without_cutycapt(tmp_path, monkeypatch):
    # It returned the PNG path even though no PNG existed, and every platform
    # then rejected the earthquake post as "Image file not found".
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("utils.maps.shutil.which", lambda name: None)
    maps = LocationMapGenerator(
        {"coordinates": {"latitude": 34.28, "longitude": -119.29}}
    )
    assert (
        asyncio.run(maps.generate_location_map({"latitude": 34.3, "longitude": -119.3}))
        is None
    )
