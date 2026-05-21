"""Consolidated social media formatters for CityBot2."""

import logging
from typing import List, Dict, Any, Optional

from social_media.utils import PostContent, MediaContent

logger = logging.getLogger('CityBot2.formatters')


def _build_hashtag_text(hashtags: List[str]) -> str:
    """Build a hashtag string from a list of hashtag words (without '#' prefix)."""
    return ' '.join(f"#{tag}" for tag in hashtags)


def format_weather_for_social(weather_data: Any, hashtags: List[str]) -> PostContent:
    """Format weather data for social media posting.

    Args:
        weather_data: A WeatherData instance (or any object with temperature,
            wind_speed, wind_direction, cloud_cover, forecast, city, state, map_path).
        hashtags: List of hashtag words.
    """
    hashtag_text = _build_hashtag_text(hashtags)

    if weather_data.temperature is not None:
        temp_str = f"{int(round(weather_data.temperature))}°F"
    else:
        temp_str = "N/A"

    if weather_data.wind_speed is not None:
        wind_str = f"{int(round(weather_data.wind_speed))}mph {weather_data.wind_direction}"
    else:
        wind_str = f"N/A {weather_data.wind_direction}"

    text = (
        f"Weather Update for {weather_data.city}, {weather_data.state}\n\n"
        f"\U0001f321\ufe0f Temperature: {temp_str}\n"
        f"\U0001f4a8 Wind: {wind_str}\n"
        f"\u2601\ufe0f Cloud Cover: {weather_data.cloud_cover}%\n\n"
        f"Forecast: {weather_data.forecast}\n\n"
        f"{hashtag_text}"
    )

    return PostContent(
        text=text,
        media=MediaContent(
            image_path=weather_data.map_path,
            meta_title=f"{weather_data.city}, {weather_data.state} Weather Update",
            meta_description=f"Current conditions: {temp_str}, {wind_str}"
        )
    )


def format_weather_alert_for_social(alert: Any, hashtags: List[str]) -> PostContent:
    """Format weather alert for social media posting.

    Args:
        alert: A WeatherAlert instance (or any object with event, headline,
            severity, urgency, areas, expires).
        hashtags: List of hashtag words.
    """
    hashtag_text = _build_hashtag_text(hashtags)

    severity_emoji = {
        'Extreme': '\u26d4\ufe0f',
        'Severe': '\U0001f6a8',
        'Moderate': '\u26a0\ufe0f',
        'Minor': '\U0001f4e2'
    }.get(alert.severity, '\u26a0\ufe0f')

    text = (
        f"{severity_emoji} WEATHER ALERT {severity_emoji}\n\n"
        f"Type: {alert.event}\n"
        f"Areas: {alert.areas}\n\n"
        f"{alert.headline}\n\n"
        f"Valid until: {alert.expires.strftime('%I:%M %p %Z')}\n\n"
        f"{hashtag_text}"
    )

    return PostContent(
        text=text,
        media=None,
        platform_specific={
            'alert_level': alert.severity,
            'urgency': alert.urgency
        }
    )


def format_earthquake_for_social(quake_data: Dict[str, Any], hashtags: List[str]) -> PostContent:
    """Format earthquake update content into a PostContent object."""
    try:
        magnitude = quake_data.get('magnitude')
        location = quake_data.get('location')
        depth = quake_data.get('depth')
        distance = quake_data.get('distance')
        city = quake_data.get('city')
        state = quake_data.get('state')
        url = quake_data.get('url')

        if magnitude is None:
            magnitude_emoji = "\U0001f7e2"
        elif magnitude >= 5.0:
            magnitude_emoji = "\U0001f534"
        elif magnitude >= 4.0:
            magnitude_emoji = "\U0001f7e1"
        else:
            magnitude_emoji = "\U0001f7e2"

        hashtag_text = _build_hashtag_text(hashtags)
        text = (
            f"{magnitude_emoji} EARTHQUAKE REPORT {magnitude_emoji}\n\n"
            f"Magnitude: {magnitude}\n"
            f"Location: {location}\n"
            f"Depth: {depth:.1f} km\n"
            f"Distance from {city}: {distance:.1f} miles\n\n"
            f"{hashtag_text}"
        )

        map_path = quake_data.get('map_path')

        return PostContent(
            text=text,
            media=MediaContent(
                image_path=map_path,
                link_url=url,
                meta_title=f"M{magnitude} Earthquake near {city}, {state}",
                meta_description=f"Earthquake detected {distance:.1f} miles from {city}"
            )
        )
    except Exception as e:
        logger.error("Error formatting earthquake content: %s", e, exc_info=True)
        raise


def format_news_for_social(article: Any, hashtags: List[str]) -> PostContent:
    """Format news article for social media posting.

    Args:
        article: A NewsArticleContent instance (or any object with title,
            content_snippet, source, url, map_path).
        hashtags: List of hashtag words.
    """
    try:
        hashtag_text = _build_hashtag_text(hashtags)
        text = (
            f"\U0001f4f0 {article.title}\n\n"
            f"{article.content_snippet}\n\n"
            f"Source: {article.source}\n"
            f"{article.url}\n\n"
            f"{hashtag_text}"
        )

        return PostContent(
            text=text,
            media=MediaContent(
                image_path=article.map_path,
                link_url=article.url,
                meta_title=article.title,
                meta_description=article.content_snippet[:200]
            )
        )
    except (ValueError, OSError) as exc:
        logger.error("Error formatting news content: %s", exc, exc_info=True)
        raise
    except (TypeError, AttributeError) as exc:
        logger.error("Error formatting news content: %s", exc, exc_info=True)
        raise


def format_announcement_for_social(announcement: Dict[str, Any], hashtags: List[str]) -> PostContent:
    """Format an announcement for social media posting.

    Args:
        announcement: Dict with keys 'title', 'body', and optionally
            'url', 'image_path'.
        hashtags: List of hashtag words.
    """
    hashtag_text = _build_hashtag_text(hashtags)

    title = announcement.get('title', 'Announcement')
    body = announcement.get('body', '')
    url = announcement.get('url')
    image_path = announcement.get('image_path')

    text = (
        f"\U0001f4e3 {title}\n\n"
        f"{body}\n\n"
        f"{hashtag_text}"
    )

    media = None
    if image_path or url:
        media = MediaContent(
            image_path=image_path,
            link_url=url,
            meta_title=title,
            meta_description=body[:200] if body else None
        )

    return PostContent(
        text=text,
        media=media
    )
