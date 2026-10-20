import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from database.models import Announcement, Earthquake, PostHistory, PostQueue
from monitors.news import NewsArticleContent
from monitors.weather import WeatherAlert, WeatherData
from posting.queue_manager import QueueManager
from social_media.social_media_manager import PostResult


class FakeSocial:
    def __init__(self, results):
        self.results = results
        self.posted = []

    async def post_content(self, content, post_type):
        self.posted.append((post_type, content))
        return self.results


@pytest.fixture
def make_queue(db, city_config):
    def make(results=None):
        return QueueManager(db, FakeSocial(results or {}), city_config)

    return make


def quake(**extra):
    return {
        "magnitude": 4.2,
        "location": "5 km W of Ventura",
        "depth": -0.4,
        "distance": 3.0,
        "timestamp": datetime.now(UTC),
        "url": "https://usgs/ev1",
        "city": "Ventura",
        "state": "CA",
        **extra,
    }


def test_earthquake_enqueues_once_and_is_recorded(db, make_queue):
    # json.dumps choked on the quake's datetime, so no earthquake was ever queued.
    queue = make_queue()
    assert queue.enqueue("earthquake", quake()) is not None
    assert queue.enqueue("earthquake", quake()) is None
    with db.Session() as session:
        assert session.query(PostQueue).count() == 1
        record = session.query(Earthquake).one()
        assert record.depth == 0  # negative depth would break the CHECK constraint


def test_news_and_alerts_dedupe_by_link(db, make_queue):
    queue = make_queue()
    article = NewsArticleContent(
        title="Ventura harbor dredging",
        source="VC Star",
        url="https://n/1",
        content_snippet="...",
        published_date=datetime.now(UTC),
        relevance_score=0.9,
    )
    alert = WeatherAlert(
        event="Wind Advisory",
        headline="h",
        description="d",
        severity="Moderate",
        urgency="Expected",
        areas="Ventura",
        onset=None,
        expires=None,
        city="Ventura",
        state="CA",
        alert_id="urn:alert:1",
    )
    for _ in range(2):
        queue.enqueue("news", article)
        queue.enqueue("weather_alert", alert)
    with db.Session() as session:
        assert session.query(PostQueue).count() == 2


def test_weather_replaces_the_pending_post_for_its_slot(db, make_queue):
    queue = make_queue()
    for temp in (60.0, 64.0):
        queue.enqueue(
            "weather",
            WeatherData(
                temperature=temp,
                wind_speed=3.0,
                wind_direction="W",
                cloud_cover=0,
                forecast="Sunny",
                timestamp=datetime.now(UTC),
                city="Ventura",
                state="CA",
            ),
        )
    with db.Session() as session:
        items = session.query(PostQueue).filter_by(content_type="weather").all()
    assert len(items) == 1
    assert "64°F" in items[0].content_text


def test_quiet_hours_use_city_time(make_queue):
    queue = make_queue()
    # 01:00 UTC is 6pm in Ventura: not quiet. It used to compare UTC hours.
    assert not queue._in_quiet_hours(datetime(2026, 7, 1, 1, 0))
    # 09:00 UTC is 2am in Ventura: quiet.
    assert queue._in_quiet_hours(datetime(2026, 7, 1, 9, 0))


def test_scheduled_weather_time_needs_no_pytz(make_queue):
    # pytz wasn't installed, so every weather enqueue raised ImportError.
    when = make_queue()._next_scheduled_time("weather")
    assert when.tzinfo is None and when > datetime.now(UTC).replace(tzinfo=None)


def run_drip_item(db, queue):
    queue.enqueue("earthquake", quake(magnitude=3.1))
    with db.Session() as session:
        item = session.query(PostQueue).one()
        session.expunge(item)
    asyncio.run(queue._post_item(item))
    with db.Session() as session:
        return session.get(PostQueue, item.id)


def test_rate_limited_post_stays_pending_without_spending_a_retry(db, make_queue):
    queue = make_queue(
        {
            "bluesky": PostResult(
                success=False, error="Rate limit exceeded", skipped=True
            )
        }
    )
    item = run_drip_item(db, queue)
    assert item.status == "pending" and item.retry_count == 0


def test_platform_failure_spends_a_retry(db, make_queue):
    queue = make_queue({"bluesky": PostResult(success=False, error="boom")})
    item = run_drip_item(db, queue)
    assert item.status == "pending" and item.retry_count == 1


def test_success_writes_post_history(db, make_queue):
    queue = make_queue(
        {"bluesky": PostResult(success=True), "twitter": PostResult(success=True)}
    )
    item = run_drip_item(db, queue)
    assert item.status == "posted"
    with db.Session() as session:
        rows = session.query(PostHistory).all()
        assert {r.platform for r in rows} == {"bluesky", "twitter"}
        assert all(r.earthquake_id == item.earthquake_id for r in rows)


def test_announcements_are_queued_when_due_and_closed_when_posted(db, make_queue):
    queue = make_queue({"bluesky": PostResult(success=True)})
    with db.Session() as session:
        session.add(Announcement(title="Cleanup day", body="Saturday at the pier"))
        session.add(
            Announcement(
                title="Later",
                body="x",
                scheduled_for=datetime.now() + timedelta(days=2),
            )
        )
        session.commit()

    assert queue.enqueue_due_announcements() == 1
    assert queue.enqueue_due_announcements() == 0

    with db.Session() as session:
        item = session.query(PostQueue).one()
        session.expunge(item)
    asyncio.run(queue._post_item(item))
    with db.Session() as session:
        posted = session.query(Announcement).filter_by(title="Cleanup day").one()
        assert posted.posted and posted.posted_at


def test_prune_keeps_pending_items(db, make_queue):
    queue = make_queue()
    queue.enqueue("earthquake", quake())
    queue.enqueue("earthquake", quake(url="https://usgs/ev2"))
    with db.Session() as session:
        items = session.query(PostQueue).all()
        for item in items:
            item.created_at = datetime(2020, 1, 1)
        items[0].status = "posted"
        session.commit()
    assert queue.prune_finished() == 1
