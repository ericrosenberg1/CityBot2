import logging
from typing import Dict, Any
import tweepy
from .base import SocialPlatform, PostContent

logger = logging.getLogger('CityBot2.social.twitter')

class TwitterPlatform(SocialPlatform):
    def initialize(self):
        try:
            auth = tweepy.OAuthHandler(
                self.config['api_key'],
                self.config['api_secret']
            )
            auth.set_access_token(
                self.config['access_token'],
                self.config['access_secret']
            )
            self.client = tweepy.Client(
                consumer_key=self.config['api_key'],
                consumer_secret=self.config['api_secret'],
                access_token=self.config['access_token'],
                access_token_secret=self.config['access_secret']
            )
            self.auth_api = tweepy.API(auth)
            logger.info("Successfully initialized Twitter client")
        except Exception as e:
            logger.error(f"Failed to initialize Twitter client: {str(e)}")
            raise

    def format_post(self, content: PostContent) -> PostContent:
        # Format text (280 character limit)
        formatted_text = content.text
        if len(formatted_text) > 280:
            # Leave room for media URL if present
            limit = 257 if content.media and content.media.link_url else 277
            formatted_text = formatted_text[:limit] + "..."

        return PostContent(
            text=formatted_text,
            media=content.media
        )

    async def post_update(self, content: PostContent) -> bool:
        try:
            formatted = self.format_post(content)
            media_ids = []

            # Handle media
            if formatted.media and formatted.media.image_path:
                media = self.auth_api.media_upload(formatted.media.image_path)
                media_ids.append(media.media_id)

            # Create tweet
            self.client.create_tweet(
                text=formatted.text,
                media_ids=media_ids if media_ids else None
            )
            
            logger.info("Successfully posted to Twitter")
            return True
            
        except Exception as e:
            logger.error(f"Error posting to Twitter: {str(e)}")
            return False