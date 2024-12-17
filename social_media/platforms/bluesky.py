import logging
import asyncio
from blueskysocial import Client, Post, Image
from typing import Dict, Any, Optional
from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger('CityBot2.social.bluesky')

class BlueSkyPlatform(SocialPlatform):
    """Bluesky platform implementation."""
    
    def __init__(self, platform_config: Dict[str, Any], city_config: Dict[str, Any]):
        """
        Initialize Bluesky platform.
        
        Args:
            platform_config: Dictionary containing platform configuration and credentials
            city_config: Configuration for the city
        """
        super().__init__(platform_config)
        self.city_config = city_config
        self._client: Optional[Client] = None
        
        # Validate credentials on initialization
        if not self.validate_credentials():
            raise ValueError("Invalid or missing Bluesky credentials")
        
        logger.debug(f"BlueSky platform initialized for {city_config.get('name', 'Unknown City')}")

    def validate_credentials(self) -> bool:
        """Validate that required credentials are present."""
        required_fields = ['handle', 'password']
        
        if not hasattr(self, 'credentials'):
            logger.error("No credentials dictionary found")
            return False
            
        for field in required_fields:
            if not self.credentials.get(field):
                logger.error(f"Missing required credential: {field}")
                return False
                
        logger.debug(f"Credentials validated for handle: {self.credentials.get('handle')}")
        return True

    async def initialize_client(self) -> None:
        """Initialize Bluesky client."""
        try:
            logger.debug("Creating new Bluesky client instance")
            self._client = Client()
            
            logger.debug(f"Attempting authentication for handle: {self.credentials['handle']}")
            await asyncio.to_thread(
                self._client.authenticate,
                self.credentials['handle'],
                self.credentials['password']
            )
            logger.info(f"Successfully authenticated Bluesky client for {self.credentials['handle']}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Bluesky client: {str(e)}")
            self._client = None
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to Bluesky."""
        try:
            # Ensure client is initialized
            if not self._client:
                await self.initialize_client()
                if not self._client:
                    raise RuntimeError("Failed to initialize Bluesky client")

            # Format post content
            formatted_content = self.format_post(content)
            
            # Create post directly with the text as first argument
            if formatted_content.media and formatted_content.media.image_path:
                try:
                    image = Image(
                        formatted_content.media.image_path,
                        alt_text=formatted_content.text[:100]
                    )
                    post = Post(formatted_content.text, with_attachments=[image])
                except Exception as img_err:
                    logger.warning(f"Could not attach image: {img_err}")
                    post = Post(formatted_content.text)
            else:
                post = Post(formatted_content.text)
            
            logger.debug("Sending post to Bluesky")
            result = await asyncio.to_thread(self._client.post, post)
            
            if result:
                logger.info("Successfully posted to Bluesky")
                return True
            else:
                logger.warning("Post to Bluesky returned no result")
                return False

        except Exception as e:
            logger.error(f"Error posting to Bluesky: {str(e)}")
            return False

    def format_post(self, content: PostContent) -> PostContent:
        """
        Format content for Bluesky, respecting platform constraints.
        
        Args:
            content: Original post content
        
        Returns:
            PostContent: Formatted post content
        """
        try:
            # Bluesky has a 300 character limit
            text = content.text
            if len(text) > 300:
                text = text[:297] + "..."
                logger.debug(f"Truncated post text to {len(text)} characters")
            
            # Handle URLs in text - Bluesky supports markdown-style links
            # If we need to add URL handling in the future, it would go here
            
            return PostContent(
                text=text,
                media=content.media,
                platform_specific=content.platform_specific
            )
            
        except Exception as e:
            logger.error(f"Error formatting post: {str(e)}")
            # Return original content if formatting fails
            return content

    async def cleanup(self) -> None:
        """Cleanup any resources used by the platform."""
        try:
            self._client = None
            logger.debug("Bluesky platform cleanup completed")
        except Exception as e:
            logger.error(f"Error during Bluesky platform cleanup: {str(e)}")