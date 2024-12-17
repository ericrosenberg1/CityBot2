import facebook
import asyncio
import logging
from typing import Dict, Any
from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)

class FacebookPlatform(SocialPlatform):
    """Facebook platform implementation."""
    
    def __init__(self, credentials: Dict[str, Any], city_config: Dict[str, Any]):
        """
        Initialize Facebook platform.
        
        :param credentials: Dictionary containing authentication credentials
        :param city_config: Configuration for the city
        """
        super().__init__({'credentials': credentials})
        self.city_config = city_config
        self._client = None

    async def initialize_client(self) -> None:
        """Initialize Facebook client."""
        try:
            self._client = facebook.GraphAPI(
                access_token=self.credentials['access_token'],
                version="3.1"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Facebook client: {str(e)}")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to Facebook."""
        try:
            if not self._client:
                await self.initialize_client()

            post_args = {
                'message': content.text
            }

            if content.media:
                if content.media.image_path:
                    with open(content.media.image_path, 'rb') as image:
                        post_args['image'] = image.read()
                if content.media.link_url:
                    post_args['link'] = content.media.link_url

            result = await asyncio.to_thread(
                self._client.put_object,
                parent_object=self.credentials['page_id'],
                connection_name="feed",
                **post_args
            )
            return bool(result)

        except Exception as e:
            logger.error(f"Error posting to Facebook: {str(e)}")
            return False

    def format_post(self, content: PostContent) -> PostContent:
        """Format content for Facebook."""
        # Facebook has a much higher character limit
        return content