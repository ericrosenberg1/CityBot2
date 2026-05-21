import logging
from typing import Dict, Any

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)

THREADS_API_BASE = "https://graph.threads.net/v1.0"


class ThreadsPlatform(SocialPlatform):
    """Threads (by Meta) platform implementation."""

    CREDENTIAL_MAP = {
        'access_token': 'THREADS_ACCESS_TOKEN',
        'user_id': 'THREADS_USER_ID',
    }
    CHAR_LIMIT = 500

    async def initialize_client(self) -> None:
        """Verify Threads credentials."""
        try:
            session = await self._ensure_session()
            url = f"{THREADS_API_BASE}/{self.credentials['user_id']}"
            params = {
                'fields': 'id,username',
                'access_token': self.credentials['access_token'],
            }
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise RuntimeError(
                        f"Failed to verify Threads credentials: "
                        f"{error_data.get('error', {}).get('message', 'Unknown error')}"
                    )
                data = await response.json()
                logger.info("Authenticated Threads client for @%s", data.get('username', 'unknown'))
        except Exception as e:
            logger.error("Failed to initialize Threads client: %s", str(e), exc_info=True)
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to Threads (two-step: create container, then publish)."""
        try:
            session = await self._ensure_session()
            formatted = self.format_post(content)
            user_id = self.credentials['user_id']
            access_token = self.credentials['access_token']

            container_params = {
                'media_type': 'TEXT',
                'text': formatted.text,
                'access_token': access_token,
            }

            if formatted.media and formatted.media.image_path:
                if formatted.media.image_path.startswith('http'):
                    container_params['media_type'] = 'IMAGE'
                    container_params['image_url'] = formatted.media.image_path
                else:
                    logger.warning("Threads requires a public URL for images; local path ignored")

            async with session.post(f"{THREADS_API_BASE}/{user_id}/threads", data=container_params) as resp:
                if resp.status != 200:
                    error = await resp.json()
                    logger.error("Threads container error: %s", error.get('error', {}).get('message'))
                    return False
                container_id = (await resp.json()).get('id')

            if not container_id:
                return False

            publish_params = {'creation_id': container_id, 'access_token': access_token}
            async with session.post(f"{THREADS_API_BASE}/{user_id}/threads_publish", data=publish_params) as resp:
                if resp.status != 200:
                    error = await resp.json()
                    logger.error("Threads publish error: %s", error.get('error', {}).get('message'))
                    return False

            logger.info("Successfully posted to Threads")
            return True

        except Exception as e:
            logger.error("Error posting to Threads: %s", str(e), exc_info=True)
            return False
