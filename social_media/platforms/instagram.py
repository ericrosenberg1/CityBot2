import logging
from typing import Dict, Any

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)

INSTAGRAM_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramPlatform(SocialPlatform):
    """Instagram platform implementation using the Instagram Graph API."""

    CREDENTIAL_MAP = {
        'access_token': 'INSTAGRAM_ACCESS_TOKEN',
        'business_account_id': 'INSTAGRAM_BUSINESS_ACCOUNT_ID',
    }
    CHAR_LIMIT = 2200

    async def initialize_client(self) -> None:
        """Verify Instagram credentials."""
        try:
            session = await self._ensure_session()
            account_id = self.credentials['business_account_id']
            url = f"{INSTAGRAM_API_BASE}/{account_id}"
            params = {'fields': 'id,username', 'access_token': self.credentials['access_token']}

            async with session.get(url, params=params) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise RuntimeError(
                        f"Failed to verify Instagram credentials: "
                        f"{error_data.get('error', {}).get('message', 'Unknown error')}"
                    )
                data = await response.json()
                logger.info("Authenticated Instagram client for @%s", data.get('username', 'unknown'))
        except Exception as e:
            logger.error("Failed to initialize Instagram client: %s", str(e), exc_info=True)
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to Instagram (requires a publicly accessible image URL)."""
        try:
            session = await self._ensure_session()
            formatted = self.format_post(content)

            if not formatted.media or not formatted.media.image_path:
                logger.warning("Instagram requires an image for every post; skipping")
                return False

            image_url = formatted.media.image_path
            if not image_url.startswith('http'):
                logger.error("Instagram Graph API requires a public image URL, got: %s", image_url)
                return False

            account_id = self.credentials['business_account_id']
            access_token = self.credentials['access_token']

            # Step 1: Create media container
            create_url = f"{INSTAGRAM_API_BASE}/{account_id}/media"
            container_params = {
                'image_url': image_url,
                'caption': formatted.text,
                'access_token': access_token,
            }
            async with session.post(create_url, data=container_params) as resp:
                if resp.status != 200:
                    error = await resp.json()
                    logger.error("Instagram container error: %s", error.get('error', {}).get('message'))
                    return False
                container_id = (await resp.json()).get('id')

            if not container_id:
                return False

            # Step 2: Publish
            publish_url = f"{INSTAGRAM_API_BASE}/{account_id}/media_publish"
            publish_params = {'creation_id': container_id, 'access_token': access_token}
            async with session.post(publish_url, data=publish_params) as resp:
                if resp.status != 200:
                    error = await resp.json()
                    logger.error("Instagram publish error: %s", error.get('error', {}).get('message'))
                    return False

            logger.info("Successfully posted to Instagram")
            return True

        except Exception as e:
            logger.error("Error posting to Instagram: %s", str(e), exc_info=True)
            return False
