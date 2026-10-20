import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database.models import (
    Announcement,
    Earthquake,
    NewsArticle,
    PostHistory,
    PostQueue,
    WeatherAlert,
    WeatherReport,
)
from database.operations import DatabaseManager
from social_media.formatters import (
    format_announcement_for_social,
    format_earthquake_for_social,
    format_news_for_social,
    format_weather_alert_for_social,
    format_weather_for_social,
)
from social_media.social_media_manager import SocialMediaManager
from social_media.utils import MediaContent, PostContent

logger = logging.getLogger("CityBot2.queue")

# Queue items in these states never post again, so maintenance can prune them.
FINISHED_STATUSES = ("posted", "failed", "expired", "cancelled")


def _utcnow() -> datetime:
    """Naive UTC now, matching what the DateTime columns store."""
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Convert an aware datetime to naive UTC for storage. Naive values pass through."""
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


class QueueManager:
    def __init__(
        self, db: DatabaseManager, social_media: SocialMediaManager, city_config: dict
    ):
        self.db = db
        self.social_media = social_media
        self.city_config = city_config
        self.max_drip_per_hour = 3
        self.min_drip_interval = 15  # minutes
        self.quiet_hours = (23, 6)  # don't drip between 11pm-6am, city local time
        self.weather_schedule = ["07:00", "12:00", "18:00"]
        try:
            self.tz = ZoneInfo(city_config.get("timezone") or "America/Los_Angeles")
        except (ZoneInfoNotFoundError, ValueError):
            self.tz = UTC

    def enqueue(
        self, content_type: str, data: Any, force_priority: str | None = None
    ) -> int | None:
        """Add content to the post queue. Auto-classifies priority.

        Skips content that's already queued (same link for news, earthquakes
        and alerts) and replaces a still-pending weather update for the same
        time slot, so repeated polling never posts the same thing twice.
        Returns the queue item id, or None when nothing new was queued.
        """
        priority = force_priority or self._classify_priority(content_type, data)
        title, text, media_path, link_url, image_url, source_name = (
            self._extract_fields(content_type, data)
        )

        scheduled_for = None
        earliest_post = None
        now = _utcnow()
        expires_at = now + timedelta(hours=48)

        if priority == "scheduled":
            scheduled_for = self._next_scheduled_time(content_type)
            expires_at = (
                scheduled_for + timedelta(hours=6) if scheduled_for else expires_at
            )
        elif priority == "immediate":
            expires_at = now + timedelta(hours=6)
        elif priority == "drip":
            earliest_post = now  # can post anytime from now

        with self.db.Session() as session:
            if (
                link_url
                and session.query(PostQueue.id)
                .filter_by(content_type=content_type, link_url=link_url)
                .first()
            ):
                return None

            if content_type == "weather" and scheduled_for:
                pending = (
                    session.query(PostQueue)
                    .filter_by(
                        content_type="weather",
                        status="pending",
                        scheduled_for=scheduled_for,
                    )
                    .first()
                )
                if pending:
                    pending.content_text = text
                    pending.media_path = media_path
                    session.commit()
                    return pending.id

            item = PostQueue(
                content_type=content_type,
                priority=priority,
                status="pending",
                title=title,
                content_text=text,
                content_json=json.dumps(data, default=str)
                if isinstance(data, dict)
                else None,
                media_path=media_path,
                link_url=link_url,
                image_url=image_url,
                source_name=source_name,
                scheduled_for=scheduled_for,
                earliest_post=earliest_post,
                expires_at=expires_at,
                is_public=True,
            )
            self._record_source(session, item, content_type, data)
            session.add(item)
            session.commit()
            logger.info(
                "Enqueued %s item (priority=%s): %s",
                content_type,
                priority,
                title or text[:50],
            )
            return item.id

    def _record_source(
        self, session, item: PostQueue, content_type: str, data: Any
    ) -> None:
        """Save the monitored data the item came from, for the dashboard and RSS feed."""
        if content_type == "weather":
            record = WeatherReport(
                temperature=data.temperature,
                wind_speed=data.wind_speed,
                wind_direction=data.wind_direction,
                cloud_cover=data.cloud_cover,
                forecast=data.forecast,
                map_path=data.map_path,
            )
            session.add(record)
            session.flush()
            item.weather_report_id = record.id
        elif content_type == "weather_alert":
            session.add(
                WeatherAlert(
                    event=data.event,
                    headline=data.headline,
                    description=data.description,
                    severity=data.severity,
                    urgency=data.urgency,
                    areas=data.areas,
                    onset=_naive_utc(data.onset),
                    expires=_naive_utc(data.expires),
                )
            )
        elif content_type == "earthquake":
            record = Earthquake(
                magnitude=data.get("magnitude"),
                location=data.get("location"),
                # USGS reports quakes above sea level with a negative depth.
                depth=max(data.get("depth") or 0, 0),
                distance=data.get("distance"),
                timestamp=_naive_utc(data.get("timestamp")),
                map_path=data.get("map_path"),
            )
            session.add(record)
            session.flush()
            item.earthquake_id = record.id
        elif content_type == "news":
            record = session.query(NewsArticle).filter_by(url=data.url).first()
            if record is None:
                record = NewsArticle(
                    title=data.title,
                    source=data.source,
                    url=data.url,
                    published_date=_naive_utc(data.published_date),
                    content_snippet=data.content_snippet,
                    relevance_score=data.relevance_score,
                )
                session.add(record)
                session.flush()
            item.news_article_id = record.id
        elif content_type == "announcement" and isinstance(data, dict):
            item.announcement_id = data.get("id")

    def enqueue_due_announcements(self) -> int:
        """Queue announcements whose scheduled time has come. Returns how many were queued."""
        # The admin form takes scheduled_for in the city's local time.
        now_local = datetime.now(self.tz).replace(tzinfo=None)
        with self.db.Session() as session:
            queued_ids = {
                row[0]
                for row in session.query(PostQueue.announcement_id).filter(
                    PostQueue.announcement_id.isnot(None)
                )
            }
            due = [
                {"id": a.id, "title": a.title, "body": a.body}
                for a in session.query(Announcement).filter_by(posted=False)
                if a.id not in queued_ids
                and (a.scheduled_for is None or a.scheduled_for <= now_local)
            ]
        for announcement in due:
            self.enqueue("announcement", announcement)
        return len(due)

    async def process_queue(self):
        """Process the posting queue. Call this every 30-60 seconds."""
        now = _utcnow()

        # Expire old items
        self._expire_old_items(now)

        # 1. Process immediate items
        for item in self._get_items("immediate", now):
            await self._post_item(item)

        # 2. Process scheduled items that are due
        for item in self._get_scheduled_due(now):
            await self._post_item(item)

        # 3. Process one drip item if rate allows
        if self._can_drip_now(now):
            item = self._get_next_drip(now)
            if item:
                await self._post_item(item)

    async def _post_item(self, item: PostQueue):
        """Post a queue item to social media."""
        try:
            media = None
            if item.media_path or item.link_url:
                media = MediaContent(
                    image_path=item.media_path,
                    link_url=item.link_url,
                    meta_title=item.title,
                )
            content = PostContent(text=item.content_text, media=media)

            results = await self.social_media.post_content(content, item.content_type)

            posted_to = [name for name, r in results.items() if r.success]
            # Nothing attempted (rate limited, or no platform takes this type):
            # leave the item pending without spending a retry.
            held = not posted_to and all(r.skipped for r in results.values())

            with self.db.Session() as session:
                db_item = session.get(PostQueue, item.id)
                if posted_to:
                    db_item.status = "posted"
                    db_item.posted_at = _utcnow()
                    db_item.error_message = None
                    self._record_history(session, db_item, posted_to)
                    logger.info(
                        "Posted queue item %d to %s: %s",
                        item.id,
                        ", ".join(posted_to),
                        item.title or item.content_type,
                    )
                elif held:
                    logger.debug(
                        "Queue item %d held: %s",
                        item.id,
                        "; ".join(f"{k}: {r.error}" for k, r in results.items())
                        or "no platforms",
                    )
                else:
                    errors = "; ".join(
                        f"{k}: {r.error}" for k, r in results.items() if not r.success
                    )
                    self._record_failure(db_item, errors)
                session.commit()

        except Exception as e:
            logger.exception("Error posting queue item %d", item.id)
            with self.db.Session() as session:
                db_item = session.get(PostQueue, item.id)
                self._record_failure(db_item, str(e))
                session.commit()

    @staticmethod
    def _record_failure(db_item: PostQueue, error: str) -> None:
        db_item.retry_count += 1
        db_item.error_message = error
        if db_item.retry_count >= db_item.max_retries:
            db_item.status = "failed"
            logger.error("Queue item %d failed permanently: %s", db_item.id, error)
        else:
            logger.warning(
                "Queue item %d attempt %d failed: %s",
                db_item.id,
                db_item.retry_count,
                error,
            )

    @staticmethod
    def _record_history(session, db_item: PostQueue, platforms: list) -> None:
        """Log one PostHistory row per platform, and close out a posted announcement."""
        for platform in platforms:
            session.add(
                PostHistory(
                    platform=platform,
                    item_type=db_item.content_type,
                    content_preview=(db_item.title or db_item.content_text)[:100],
                    weather_report_id=db_item.weather_report_id,
                    earthquake_id=db_item.earthquake_id,
                    news_article_id=db_item.news_article_id,
                )
            )
        if db_item.announcement_id:
            announcement = session.get(Announcement, db_item.announcement_id)
            if announcement:
                announcement.posted = True
                announcement.posted_at = db_item.posted_at

    def _classify_priority(self, content_type: str, data: Any) -> str:
        if content_type == "weather_alert":
            severity = (
                getattr(data, "severity", "")
                if hasattr(data, "severity")
                else data.get("severity", "")
            )
            if severity in ("Extreme", "Severe"):
                return "immediate"
            return "drip"
        if content_type == "earthquake":
            mag = data.get("magnitude", 0) if isinstance(data, dict) else 0
            dist = data.get("distance", 999) if isinstance(data, dict) else 999
            if mag >= 5.0 or (mag >= 4.0 and dist <= 50):
                return "immediate"
            return "drip"
        if content_type == "weather":
            return "scheduled"
        return "drip"  # news, announcements

    def _extract_fields(self, content_type, data):
        """Extract title, text, media, link, image, source from data."""
        title = text = media_path = link_url = image_url = source_name = None
        hashtags = self._get_hashtags(content_type)

        if content_type == "weather":
            title = f"Weather Update: {getattr(data, 'city', '')}, {getattr(data, 'state', '')}"
            content = format_weather_for_social(data, hashtags)
            text = content.text
            media_path = getattr(data, "map_path", None)
            source_name = "National Weather Service"
        elif content_type == "weather_alert":
            title = f"Weather Alert: {getattr(data, 'event', 'Alert')}"
            content = format_weather_alert_for_social(data, hashtags, self.tz)
            text = content.text
            link_url = getattr(data, "alert_id", None)
            source_name = "National Weather Service"
        elif content_type == "earthquake":
            d = data if isinstance(data, dict) else {}
            title = f"M{d.get('magnitude', '?')} Earthquake near {d.get('city', '')}"
            content = format_earthquake_for_social(d, hashtags)
            text = content.text
            media_path = d.get("map_path")
            link_url = d.get("url")
            source_name = "USGS"
        elif content_type == "news":
            title = getattr(data, "title", "News")
            content = format_news_for_social(data, hashtags)
            text = content.text
            link_url = getattr(data, "url", None)
            source_name = getattr(data, "source", None)
            image_url = getattr(data, "image_url", None)
        elif content_type == "announcement":
            d = data if isinstance(data, dict) else {}
            title = d.get("title", "Announcement")
            content = format_announcement_for_social(d, hashtags)
            text = content.text

        return title, text, media_path, link_url, image_url, source_name

    def _get_hashtags(self, content_type):
        category = (
            "weather" if content_type in ("weather", "weather_alert") else content_type
        )
        return self.city_config.get("social", {}).get("hashtags", {}).get(category, [])

    def _next_scheduled_time(self, content_type):
        """Get the next scheduled post time as naive UTC."""
        if content_type != "weather":
            return None
        now_local = datetime.now(self.tz)
        for day in (0, 1):
            for time_str in self.weather_schedule:
                h, m = map(int, time_str.split(":"))
                candidate = (now_local + timedelta(days=day)).replace(
                    hour=h, minute=m, second=0, microsecond=0
                )
                if candidate > now_local:
                    return _naive_utc(candidate)
        return None

    def _get_items(self, priority, now):
        with self.db.Session() as session:
            items = (
                session.query(PostQueue)
                .filter(
                    PostQueue.priority == priority,
                    PostQueue.status == "pending",
                )
                .order_by(PostQueue.created_at)
                .all()
            )
            session.expunge_all()
            return items

    def _get_scheduled_due(self, now):
        with self.db.Session() as session:
            items = (
                session.query(PostQueue)
                .filter(
                    PostQueue.priority == "scheduled",
                    PostQueue.status == "pending",
                    PostQueue.scheduled_for <= now,
                )
                .order_by(PostQueue.scheduled_for)
                .all()
            )
            session.expunge_all()
            return items

    def _get_next_drip(self, now):
        with self.db.Session() as session:
            item = (
                session.query(PostQueue)
                .filter(
                    PostQueue.priority == "drip",
                    PostQueue.status == "pending",
                )
                .order_by(PostQueue.created_at)
                .first()
            )
            if item:
                session.expunge(item)
            return item

    def _in_quiet_hours(self, now: datetime) -> bool:
        """Quiet hours are in city time. `now` is naive UTC."""
        hour = now.replace(tzinfo=UTC).astimezone(self.tz).hour
        quiet_start, quiet_end = self.quiet_hours
        if quiet_start > quiet_end:  # wraps midnight
            return hour >= quiet_start or hour < quiet_end
        return quiet_start <= hour < quiet_end

    def _can_drip_now(self, now):
        if self._in_quiet_hours(now):
            return False

        cutoff = now - timedelta(hours=1)
        with self.db.Session() as session:
            recent_count = (
                session.query(PostQueue)
                .filter(
                    PostQueue.priority == "drip",
                    PostQueue.status == "posted",
                    PostQueue.posted_at >= cutoff,
                )
                .count()
            )
            if recent_count >= self.max_drip_per_hour:
                return False

            last_drip = (
                session.query(PostQueue)
                .filter(
                    PostQueue.priority == "drip",
                    PostQueue.status == "posted",
                )
                .order_by(PostQueue.posted_at.desc())
                .first()
            )
            if last_drip and last_drip.posted_at:
                elapsed = (now - last_drip.posted_at).total_seconds() / 60
                if elapsed < self.min_drip_interval:
                    return False
        return True

    def _expire_old_items(self, now):
        with self.db.Session() as session:
            expired = (
                session.query(PostQueue)
                .filter(
                    PostQueue.status == "pending",
                    PostQueue.expires_at < now,
                )
                .all()
            )
            for item in expired:
                item.status = "expired"
                logger.info("Expired queue item %d: %s", item.id, item.title)
            session.commit()

    def prune_finished(self, days: int = 30) -> int:
        """Delete finished queue items older than `days`. Returns the count removed.

        Finished items double as the dedupe ledger, so keep them long enough
        to outlast any feed that still lists an old story.
        """
        cutoff = _utcnow() - timedelta(days=days)
        with self.db.Session() as session:
            removed = (
                session.query(PostQueue)
                .filter(
                    PostQueue.status.in_(FINISHED_STATUSES),
                    PostQueue.created_at < cutoff,
                )
                .delete(synchronize_session=False)
            )
            session.commit()
        return removed
