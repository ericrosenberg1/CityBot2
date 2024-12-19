import tweepy
import logging
import os
from typing import Dict, Any, Optional, Tuple
from .base import SocialPlatform
from ..utils import PostContent, MediaContent

logger = logging.getLogger(__name__)

class TwitterPlatform(SocialPlatform):
    """X.com (Twitter) platform implementation."""
    
    def __init__(self, platform_config: Dict[str, Any], city_config: Dict[str, Any]):
        """Initialize Twitter/X platform."""
        super().__init__(platform_config)
        self.city_config = city_config
        self._client = None
        self._api = None
        
        # Load and validate credentials
        self.credentials = self._load_credentials(platform_config)
        
    def _load_credentials(self, config: Dict[str, Any]) -> Dict[str, str]:
        """Load Twitter credentials from config or environment."""
        # Try to get credentials from config first
        creds = config.get('credentials', {})
        
        # Define the credential mapping
        cred_mapping = {
            'api_key': ('TWITTER_API_KEY', creds.get('api_key')),
            'api_secret': ('TWITTER_API_SECRET', creds.get('api_secret')),
            'access_token': ('TWITTER_ACCESS_TOKEN', creds.get('access_token')),
            'access_secret': ('TWITTER_ACCESS_SECRET', creds.get('access_secret'))
        }
        
        # Build credentials dictionary
        credentials = {}
        missing_creds = []
        
        for key, (env_var, config_value) in cred_mapping.items():
            # Try config value first, then environment variable
            value = config_value if config_value is not None else os.getenv(env_var)
            if value:
                credentials[key] = value
            else:
                missing_creds.append(key)
        
        # Validate credentials
        if missing_creds:
            raise ValueError(f"Missing Twitter credentials: {', '.join(missing_creds)}")
            
        return credentials
    
    @staticmethod
    def validate_config(config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate Twitter platform configuration."""
        required_fields = ['api_key', 'api_secret', 'access_token', 'access_secret']
        
        credentials = config.get('credentials', {})
        if not credentials:
            return False, "No credentials provided"
            
        missing = [field for field in required_fields if not credentials.get(field)]
        if missing:
            return False, f"Missing required credentials: {', '.join(missing)}"
            
        return True, None

    async def initialize_client(self) -> None:
        """Initialize X.com (Twitter) client."""
        try:
            # Use OAuth 1.0a for both v1.1 and v2 endpoints
            auth = tweepy.OAuthHandler(
                self.credentials['api_key'],
                self.credentials['api_secret']
            )
            auth.set_access_token(
                self.credentials['access_token'],
                self.credentials['access_secret']
            )
            
            # Initialize API v1.1 client for media upload
            self._api = tweepy.API(auth)

            # Initialize v2 client for tweets
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
                    # Use v1.1 API for media upload
                    upload = self._api.media_upload(filename=content.media.image_path)
                    media_ids.append(upload.media_id)
                    logger.info("Successfully uploaded media to Twitter")
                except Exception as media_err:
                    logger.error("Error uploading media to X: %s", str(media_err), exc_info=True)
                    return False

            # Use v2 API for posting tweet
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

    def format_post(self, content: PostContent) -> PostContent:
        """Ensure post is <=280 chars."""
        text = content.text
        if len(text) > 280:
            text = text[:277] + "..."

        return PostContent(
            text=text,
            media=content.media,
            platform_specific=content.platform_specific
        )