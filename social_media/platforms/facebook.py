import facebook
import asyncio
import logging
from typing import Dict, Any

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)


class FacebookPlatform(SocialPlatform):
    """Facebook platform implementation."""

    CREDENTIAL_MAP = {
        'page_id': 'FACEBOOK_PAGE_ID',
        'access_token': 'FACEBOOK_ACCESS_TOKEN',
    }
    CHAR_LIMIT = 63206

    async def initialize_client(self) -> None:
        """Initialize Facebook client."""
        try:
            self._client = facebook.GraphAPI(
                access_token=self.credentials['access_token'],
                version="3.1"
            )
        except Exception as e:
            logger.error("Failed to initialize Facebook client: %s", str(e))
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to Facebook."""
        try:
            if not self._client:
                await self.initialize_client()

            post_args = {'message': content.text}

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
            logger.error("Error posting to Facebook: %s", str(e))
            return False
