import tweepy
import logging
from typing import Dict, Any, Optional, Tuple

from .base import SocialPlatform
from ..utils import PostContent, MediaContent

logger = logging.getLogger(__name__)


class TwitterPlatform(SocialPlatform):
    """X.com (Twitter) platform implementation."""

    CREDENTIAL_MAP = {
        'api_key': 'TWITTER_API_KEY',
        'api_secret': 'TWITTER_API_SECRET',
        'access_token': 'TWITTER_ACCESS_TOKEN',
        'access_secret': 'TWITTER_ACCESS_SECRET',
    }
    CHAR_LIMIT = 280

    def __init__(self, platform_config: Dict[str, Any], city_config: Dict[str, Any]):
        super().__init__(platform_config, city_config)
        self._api = None

    @staticmethod
    def validate_config(config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate Twitter platform configuration."""
        required_fields = ['api_key', 'api_secret', 'access_token', 'access_secret']
        credentials = config.get('credentials', {})
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
                self.credentials['api_key'],
                self.credentials['api_secret']
            )
            auth.set_access_token(
                self.credentials['access_token'],
                self.credentials['access_secret']
            )
            self._api = tweepy.API(auth)
            self._client = tweepy.Client(
                consumer_key=self.credentials['api_key'],
                consumer_secret=self.credentials['api_secret'],
                access_token=self.credentials['access_token'],
                access_token_secret=self.credentials['access_secret'],
                wait_on_rate_limit=True
            )
            logger.info("Successfully initialized Twitter client")
        except Exception as e:
            logger.error("Failed to initialize Twitter client: %s", str(e), exc_info=True)
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post a tweet to X/Twitter."""
        try:
            if not self._client or not self._api:
                await self.initialize_client()

            media_ids = []
            if content.media and content.media.image_path:
                try:
                    upload = self._api.media_upload(filename=content.media.image_path)
                    media_ids.append(upload.media_id)
                    logger.info("Successfully uploaded media to Twitter")
                except Exception as media_err:
                    logger.error("Error uploading media to X: %s", str(media_err), exc_info=True)
                    return False

            tweet_response = self._client.create_tweet(
                text=content.text,
                media_ids=media_ids if media_ids else None
            )

            if tweet_response and hasattr(tweet_response, 'data') and tweet_response.data:
                logger.info("Successfully posted tweet")
                return True
            else:
                logger.error("Unexpected response when creating tweet")
                return False

        except Exception as e:
            logger.error("Error posting to X: %s", str(e), exc_info=True)
            return False
