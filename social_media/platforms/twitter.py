import asyncio
import logging
from typing import Any, ClassVar

import tweepy

from ..utils import PostContent
from .base import SocialPlatform

logger = logging.getLogger(__name__)


class TwitterPlatform(SocialPlatform):
    """X.com (Twitter) platform implementation."""

    CREDENTIAL_MAP: ClassVar[dict[str, str]] = {
        "api_key": "TWITTER_API_KEY",
        "api_secret": "TWITTER_API_SECRET",
        "access_token": "TWITTER_ACCESS_TOKEN",
        "access_secret": "TWITTER_ACCESS_SECRET",
    }
    CHAR_LIMIT = 280

    def __init__(self, platform_config: dict[str, Any], city_config: dict[str, Any]):
        super().__init__(platform_config, city_config)
        self._api = None

    @staticmethod
    def validate_config(config: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate Twitter platform configuration."""
        required_fields = ["api_key", "api_secret", "access_token", "access_secret"]
        credentials = config.get("credentials", {})
        if not credentials:
            return False, "No credentials provided"
        missing = [f for f in required_fields if not credentials.get(f)]
        if missing:
            return False, f"Missing required credentials: {', '.join(missing)}"
        return True, None

    async def initialize_client(self) -> None:
        """Initialize X.com (Twitter) client."""
        try:
            auth = tweepy.OAuthHandler(
                self.credentials["api_key"], self.credentials["api_secret"]
            )
            auth.set_access_token(
                self.credentials["access_token"], self.credentials["access_secret"]
            )
            self._api = tweepy.API(auth)
            self._client = tweepy.Client(
                consumer_key=self.credentials["api_key"],
                consumer_secret=self.credentials["api_secret"],
                access_token=self.credentials["access_token"],
                access_token_secret=self.credentials["access_secret"],
                wait_on_rate_limit=True,
            )
            logger.info("Successfully initialized Twitter client")
        except Exception:
            logger.exception("Failed to initialize Twitter client")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post a tweet to X/Twitter."""
        try:
            if not self._client or not self._api:
                await self.initialize_client()

            media_ids = []
            if content.media and content.media.image_path:
                try:
                    upload = await asyncio.to_thread(
                        self._api.media_upload, filename=content.media.image_path
                    )
                    media_ids.append(upload.media_id)
                    logger.info("Successfully uploaded media to Twitter")
                except Exception:
                    logger.exception("Error uploading media to X")
                    return False

            # tweepy.Client is synchronous (uses requests under the hood) and can
            # sleep the whole thread when wait_on_rate_limit kicks in, so run it
            # off the event loop like every other blocking platform client here.
            tweet_response = await asyncio.to_thread(
                self._client.create_tweet,
                text=content.text,
                media_ids=media_ids if media_ids else None,
            )

            if (
                tweet_response
                and hasattr(tweet_response, "data")
                and tweet_response.data
            ):
                logger.info("Successfully posted tweet")
                return True
            else:
                logger.error("Unexpected response when creating tweet")
                return False

        except Exception:
            logger.exception("Error posting to X")
            return False
