import logging
import asyncio
from typing import Dict, Any

from blueskysocial import Client, Post, Image

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger('CityBot2.social.bluesky')


class BlueSkyPlatform(SocialPlatform):
    """Bluesky platform implementation."""

    CREDENTIAL_MAP = {
        'handle': 'BLUESKY_HANDLE',
        'password': 'BLUESKY_PASSWORD',
    }
    CHAR_LIMIT = 300

    async def initialize_client(self) -> None:
        """Initialize Bluesky client."""
        try:
            self._client = Client()
            await asyncio.to_thread(
                self._client.authenticate,
                self.credentials['handle'],
                self.credentials['password']
            )
            logger.info("Successfully authenticated Bluesky client for %s", self.credentials['handle'])
        except Exception as e:
            logger.error("Failed to initialize Bluesky client: %s", str(e))
            self._client = None
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to Bluesky."""
        try:
            if not self._client:
                await self.initialize_client()
                if not self._client:
                    raise RuntimeError("Failed to initialize Bluesky client")

            formatted_content = self.format_post(content)

            if formatted_content.media and formatted_content.media.image_path:
                try:
                    image = Image(
                        formatted_content.media.image_path,
                        alt_text=formatted_content.text[:100]
                    )
                    post = Post(formatted_content.text, with_attachments=[image])
                except Exception as img_err:
                    logger.warning("Could not attach image: %s", img_err)
                    post = Post(formatted_content.text)
            else:
                post = Post(formatted_content.text)

            result = await asyncio.to_thread(self._client.post, post)

            if result:
                logger.info("Successfully posted to Bluesky")
                return True
            else:
                logger.warning("Post to Bluesky returned no result")
                return False

        except Exception as e:
            logger.error("Error posting to Bluesky: %s", str(e))
            return False
