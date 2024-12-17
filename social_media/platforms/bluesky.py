import logging
import asyncio
from blueskysocial import Client, Post, Image
from typing import Dict, Any
from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)

class BlueSkyPlatform(SocialPlatform):
    """Bluesky platform implementation."""
    
    def __init__(self, credentials: Dict[str, Any], city_config: Dict[str, Any]):
        """
        Initialize Bluesky platform.
        
        :param credentials: Dictionary containing authentication credentials
        :param city_config: Configuration for the city
        """
        super().__init__({'credentials': credentials})
        self.city_config = city_config
        self._client = None

    async def initialize_client(self) -> None:
        """Initialize Bluesky client."""
        try:
            # Create a new client instance
            self._client = Client()
            
            # Authenticate the client
            # Note: This uses blocking method, so we use to_thread
            await asyncio.to_thread(
                self._client.authenticate, 
                self.credentials['handle'], 
                self.credentials['password']
            )
        except Exception as e:
            logger.error(f"Failed to initialize Bluesky client: {str(e)}")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to Bluesky."""
        try:
            # Ensure client is initialized
            if not self._client:
                await self.initialize_client()

            # Prepare post parameters
            post_params = {
                'text': content.text
            }

            # Handle media attachment
            if content.media and content.media.image_path:
                try:
                    # Create an Image object for the attachment
                    image = Image(
                        content.media.image_path, 
                        alt_text=content.text[:100]  # truncate for alt text
                    )
                    post_params['with_attachments'] = [image]
                except Exception as img_err:
                    logger.warning(f"Could not attach image: {img_err}")

            # Create and post the post
            post = Post(**post_params)
            
            # Use to_thread to handle blocking post method
            result = await asyncio.to_thread(self._client.post, post)
            
            return bool(result)

        except Exception as e:
            logger.error(f"Error posting to Bluesky: {str(e)}")
            return False

    def format_post(self, content: PostContent) -> PostContent:
        """
        Format content for Bluesky, respecting the 300 character limit.
        
        :param content: Original post content
        :return: Formatted post content
        """
        # Bluesky has a 300 character limit
        text = content.text
        if len(text) > 300:
            text = text[:297] + "..."
        
        return PostContent(
            text=text,
            media=content.media,
            platform_specific=content.platform_specific
        )