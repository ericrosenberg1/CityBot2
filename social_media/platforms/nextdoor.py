# NOTE: Nextdoor posting requires Nextdoor Agency API partnership access.
# This is not available to individual developers — only approved media organizations.
# The Nextdoor integration is included for completeness but will not function
# without approved API credentials from Nextdoor's partner program.
# See: https://developers.nextdoor.com/

import os
import logging
from typing import Dict, Any, Optional

import aiohttp

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)

NEXTDOOR_API_BASE = "https://nextdoor.com/api/v2"


class NextdoorPlatform(SocialPlatform):
    """Nextdoor platform implementation using the Nextdoor API v2."""

    CREDENTIAL_MAP = {
        'access_token': 'NEXTDOOR_ACCESS_TOKEN',
        'agency_id': 'NEXTDOOR_AGENCY_ID',
    }
    CHAR_LIMIT = 10000

    async def initialize_client(self) -> None:
        """Initialize session with auth headers and verify credentials."""
        try:
            # Nextdoor needs auth headers on the session
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = aiohttp.ClientSession(headers={
                'Authorization': f"Bearer {self.credentials['access_token']}",
                'Content-Type': 'application/json',
            })
            url = f"{NEXTDOOR_API_BASE}/agencies/{self.credentials['agency_id']}"
            async with self._session.get(url) as response:
                if response.status != 200:
                    raise RuntimeError(f"Nextdoor auth failed: {await response.text()}")
                data = await response.json()
                logger.info("Authenticated Nextdoor for agency: %s", data.get('name', 'unknown'))
        except Exception as e:
            logger.error("Failed to initialize Nextdoor client: %s", str(e), exc_info=True)
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to Nextdoor agency feed."""
        try:
            if not self._session or self._session.closed:
                await self.initialize_client()

            formatted = self.format_post(content)
            agency_id = self.credentials['agency_id']
            post_data: Dict[str, Any] = {'body': formatted.text}

            if formatted.media and formatted.media.link_url:
                post_data['link'] = {'url': formatted.media.link_url}

            if formatted.media and formatted.media.image_path:
                image_id = await self._upload_image(formatted.media.image_path)
                if image_id:
                    post_data['media'] = [{'id': image_id}]

            url = f"{NEXTDOOR_API_BASE}/agencies/{agency_id}/posts"
            async with self._session.post(url, json=post_data) as response:
                if response.status not in (200, 201):
                    logger.error("Nextdoor post failed: %s", await response.text())
                    return False

            logger.info("Successfully posted to Nextdoor")
            return True

        except Exception as e:
            logger.error("Error posting to Nextdoor: %s", str(e), exc_info=True)
            return False

    async def _upload_image(self, image_path: str) -> Optional[str]:
        """Upload an image and return the media ID."""
        try:
            agency_id = self.credentials['agency_id']
            upload_url = f"{NEXTDOOR_API_BASE}/agencies/{agency_id}/media"

            if image_path.startswith('http'):
                async with self._session.post(upload_url, json={'url': image_path}) as resp:
                    if resp.status not in (200, 201):
                        logger.error("Nextdoor image upload failed: %s", await resp.text())
                        return None
                    return (await resp.json()).get('id')
            else:
                form = aiohttp.FormData()
                form.add_field('file', open(image_path, 'rb'),
                               filename=os.path.basename(image_path),
                               content_type='image/jpeg')
                headers = {'Authorization': f"Bearer {self.credentials['access_token']}"}
                async with aiohttp.ClientSession() as upload_session:
                    async with upload_session.post(upload_url, data=form, headers=headers) as resp:
                        if resp.status not in (200, 201):
                            logger.error("Nextdoor image upload failed: %s", await resp.text())
                            return None
                        return (await resp.json()).get('id')
        except Exception as e:
            logger.error("Error uploading image to Nextdoor: %s", str(e), exc_info=True)
            return None
