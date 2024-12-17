import tweepy
import logging
from typing import Dict, Any
from .base import SocialPlatform
from ..utils import PostContent, MediaContent

logger = logging.getLogger(__name__)

class TwitterPlatform(SocialPlatform):
    """Twitter platform implementation."""
    
    def __init__(self, credentials: Dict[str, Any], city_config: Dict[str, Any]):
        """
        Initialize Twitter platform.
        
        :param credentials: Dictionary containing authentication credentials
        :param city_config: Configuration for the city
        """
        super().__init__({'credentials': credentials})
        self.city_config = city_config
        self._client = None
        self._api = None

    async def initialize_client(self) -> None:
        """Initialize Twitter client."""
        try:
            auth = tweepy.OAuthHandler(
                self.credentials['api_key'],
                self.credentials['api_secret']
            )
            auth.set_access_token(
                self.credentials['access_token'],
                self.credentials['access_secret']
            )
            self._client = tweepy.Client(
                consumer_key=self.credentials['api_key'],
                consumer_secret=self.credentials['api_secret'],
                access_token=self.credentials['access_token'],
                access_token_secret=self.credentials['access_secret']
            )
            self._api = tweepy.API(auth)
        except Exception as e:
            logger.error(f"Failed to initialize Twitter client: {str(e)}")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to Twitter."""
        try:
            if not self._client:
                await self.initialize_client()

            media_ids = []
            if content.media and content.media.image_path:
                media = self._api.media_upload(content.media.image_path)
                media_ids.append(media.media_id)

            tweet = await self._client.create_tweet(
                text=content.text,
                media_ids=media_ids if media_ids else None
            )
            return bool(tweet)

        except Exception as e:
            logger.error(f"Error posting to Twitter: {str(e)}")
            return False

    def format_post(self, content: PostContent) -> PostContent:
        """Format content for Twitter."""
        # Twitter has a 280 character limit
        text = content.text
        if len(text) > 280:
            text = text[:277] + "..."
        
        return PostContent(
            text=text,
            media=content.media,
            platform_specific=content.platform_specific
        )