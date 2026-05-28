import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from database.operations import DatabaseManager
from database.models import PostQueue
from social_media.social_media_manager import SocialMediaManager
from social_media.formatters import (
    format_weather_for_social, format_weather_alert_for_social,
    format_earthquake_for_social, format_news_for_social,
    format_announcement_for_social,
)
from social_media.utils import PostContent

logger = logging.getLogger('CityBot2.queue')


class QueueManager:
    def __init__(self, db: DatabaseManager, social_media: SocialMediaManager, city_config: dict):
        self.db = db
        self.social_media = social_media
        self.city_config = city_config
        self.max_drip_per_hour = 3
        self.min_drip_interval = 15  # minutes
        self.quiet_hours = (23, 6)  # don't drip between 11pm-6am
        self.weather_schedule = ['07:00', '12:00', '18:00']
        self.tz_name = city_config.get('timezone', 'America/Los_Angeles')

    def enqueue(self, content_type: str, data: Any, force_priority: str = None):
        """Add content to the post queue. Auto-classifies priority."""
        priority = force_priority or self._classify_priority(content_type, data)
        title, text, media_path, link_url, image_url, source_name = self._extract_fields(content_type, data)

        scheduled_for = None
        earliest_post = None
        expires_at = datetime.utcnow() + timedelta(hours=48)

        if priority == 'scheduled':
            scheduled_for = self._next_scheduled_time(content_type)
            expires_at = scheduled_for + timedelta(hours=6) if scheduled_for else expires_at
        elif priority == 'immediate':
            expires_at = datetime.utcnow() + timedelta(hours=6)
        elif priority == 'drip':
            earliest_post = datetime.utcnow()  # can post anytime from now

        item = PostQueue(
            content_type=content_type,
            priority=priority,
            status='pending',
            title=title,
            content_text=text,
            content_json=json.dumps(data) if isinstance(data, dict) else None,
            media_path=media_path,
            link_url=link_url,
            image_url=image_url,
            source_name=source_name,
            scheduled_for=scheduled_for,
            earliest_post=earliest_post,
            expires_at=expires_at,
            is_public=True,
        )

        with self.db.Session() as session:
            session.add(item)
            session.commit()
            logger.info("Enqueued %s item (priority=%s): %s", content_type, priority, title or text[:50])

    async def process_queue(self):
        """Process the posting queue. Call this every 30-60 seconds."""
        now = datetime.utcnow()

        # Expire old items
        self._expire_old_items(now)

        # 1. Process immediate items
        for item in self._get_items('immediate', now):
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
            # Build PostContent from the stored data
            hashtags = self._get_hashtags(item.content_type)
            if item.content_json:
                data = json.loads(item.content_json)
                content = self._format_content(item.content_type, data, hashtags)
            else:
                content = PostContent(text=item.content_text)

            results = await self.social_media.post_content(content, item.content_type)

            any_success = any(r.success for r in results.values())

            with self.db.Session() as session:
                db_item = session.query(PostQueue).get(item.id)
                if any_success:
                    db_item.status = 'posted'
                    db_item.posted_at = datetime.utcnow()
                    logger.info("Posted queue item %d: %s", item.id, item.title or item.content_type)
                else:
                    db_item.retry_count += 1
                    errors = '; '.join(f"{k}: {r.error}" for k, r in results.items() if not r.success)
                    db_item.error_message = errors
                    if db_item.retry_count >= db_item.max_retries:
                        db_item.status = 'failed'
                        logger.error("Queue item %d failed permanently: %s", item.id, errors)
                    else:
                        logger.warning("Queue item %d attempt %d failed: %s", item.id, db_item.retry_count, errors)
                session.commit()

        except Exception as e:
            logger.error("Error posting queue item %d: %s", item.id, str(e), exc_info=True)
            with self.db.Session() as session:
                db_item = session.query(PostQueue).get(item.id)
                db_item.retry_count += 1
                db_item.error_message = str(e)
                if db_item.retry_count >= db_item.max_retries:
                    db_item.status = 'failed'
                session.commit()

    def _classify_priority(self, content_type: str, data: Any) -> str:
        if content_type == 'weather_alert':
            severity = getattr(data, 'severity', '') if hasattr(data, 'severity') else data.get('severity', '')
            if severity in ('Extreme', 'Severe'):
                return 'immediate'
            return 'drip'
        if content_type == 'earthquake':
            mag = data.get('magnitude', 0) if isinstance(data, dict) else 0
            dist = data.get('distance', 999) if isinstance(data, dict) else 999
            if mag >= 5.0 or (mag >= 4.0 and dist <= 50):
                return 'immediate'
            return 'drip'
        if content_type == 'weather':
            return 'scheduled'
        return 'drip'  # news, announcements

    def _extract_fields(self, content_type, data):
        """Extract title, text, media, link, image, source from data."""
        title = text = media_path = link_url = image_url = source_name = None
        hashtags = self._get_hashtags(content_type)

        if content_type == 'weather':
            title = f"Weather Update: {getattr(data, 'city', '')}, {getattr(data, 'state', '')}"
            content = format_weather_for_social(data, hashtags)
            text = content.text
            media_path = getattr(data, 'map_path', None)
            source_name = 'National Weather Service'
        elif content_type == 'weather_alert':
            title = f"Weather Alert: {getattr(data, 'event', 'Alert')}"
            content = format_weather_alert_for_social(data, hashtags)
            text = content.text
            source_name = 'National Weather Service'
        elif content_type == 'earthquake':
            d = data if isinstance(data, dict) else {}
            title = f"M{d.get('magnitude', '?')} Earthquake near {d.get('city', '')}"
            content = format_earthquake_for_social(d, hashtags)
            text = content.text
            media_path = d.get('map_path')
            link_url = d.get('url')
            source_name = 'USGS'
        elif content_type == 'news':
            title = getattr(data, 'title', 'News')
            content = format_news_for_social(data, hashtags)
            text = content.text
            link_url = getattr(data, 'url', None)
            source_name = getattr(data, 'source', None)
            image_url = getattr(data, 'image_url', None)
        elif content_type == 'announcement':
            d = data if isinstance(data, dict) else {}
            title = d.get('title', 'Announcement')
            content = format_announcement_for_social(d, hashtags)
            text = content.text

        return title, text, media_path, link_url, image_url, source_name

    def _get_hashtags(self, content_type):
        category = 'weather' if content_type in ('weather', 'weather_alert') else content_type
        return self.city_config.get('social', {}).get('hashtags', {}).get(category, [])

    def _format_content(self, content_type, data, hashtags):
        """Re-create PostContent from stored JSON data."""
        if content_type == 'earthquake':
            return format_earthquake_for_social(data, hashtags)
        if content_type == 'announcement':
            return format_announcement_for_social(data, hashtags)
        # For weather/news, just use the stored text
        return PostContent(text=data.get('text', ''))

    def _next_scheduled_time(self, content_type):
        """Get the next scheduled post time."""
        import pytz
        try:
            tz = pytz.timezone(self.tz_name)
        except Exception:
            tz = pytz.UTC
        now_local = datetime.now(tz)

        if content_type == 'weather':
            for time_str in self.weather_schedule:
                h, m = map(int, time_str.split(':'))
                candidate = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate > now_local:
                    return candidate.astimezone(pytz.UTC).replace(tzinfo=None)
            # All times passed today, use first time tomorrow
            h, m = map(int, self.weather_schedule[0].split(':'))
            candidate = (now_local + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
            return candidate.astimezone(pytz.UTC).replace(tzinfo=None)
        return None

    def _get_items(self, priority, now):
        with self.db.Session() as session:
            items = session.query(PostQueue).filter(
                PostQueue.priority == priority,
                PostQueue.status == 'pending',
            ).order_by(PostQueue.created_at).all()
            session.expunge_all()
            return items

    def _get_scheduled_due(self, now):
        with self.db.Session() as session:
            items = session.query(PostQueue).filter(
                PostQueue.priority == 'scheduled',
                PostQueue.status == 'pending',
                PostQueue.scheduled_for <= now,
            ).order_by(PostQueue.scheduled_for).all()
            session.expunge_all()
            return items

    def _get_next_drip(self, now):
        with self.db.Session() as session:
            item = session.query(PostQueue).filter(
                PostQueue.priority == 'drip',
                PostQueue.status == 'pending',
            ).order_by(PostQueue.created_at).first()
            if item:
                session.expunge(item)
            return item

    def _can_drip_now(self, now):
        hour = now.hour
        quiet_start, quiet_end = self.quiet_hours
        if quiet_start > quiet_end:  # wraps midnight
            if hour >= quiet_start or hour < quiet_end:
                return False
        elif quiet_start <= hour < quiet_end:
            return False

        cutoff = now - timedelta(hours=1)
        with self.db.Session() as session:
            recent_count = session.query(PostQueue).filter(
                PostQueue.priority == 'drip',
                PostQueue.status == 'posted',
                PostQueue.posted_at >= cutoff,
            ).count()
            if recent_count >= self.max_drip_per_hour:
                return False

            last_drip = session.query(PostQueue).filter(
                PostQueue.priority == 'drip',
                PostQueue.status == 'posted',
            ).order_by(PostQueue.posted_at.desc()).first()
            if last_drip and last_drip.posted_at:
                elapsed = (now - last_drip.posted_at).total_seconds() / 60
                if elapsed < self.min_drip_interval:
                    return False
        return True

    def _expire_old_items(self, now):
        with self.db.Session() as session:
            expired = session.query(PostQueue).filter(
                PostQueue.status == 'pending',
                PostQueue.expires_at < now,
            ).all()
            for item in expired:
                item.status = 'expired'
                logger.info("Expired queue item %d: %s", item.id, item.title)
            session.commit()
