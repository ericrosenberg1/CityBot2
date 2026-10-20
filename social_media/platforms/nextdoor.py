# NOTE: Nextdoor posting requires Nextdoor Agency API partnership access.
# This is not available to individual developers — only approved media organizations.
# The Nextdoor integration is included for completeness but will not function
# without approved API credentials from Nextdoor's partner program.
# See: https://developers.nextdoor.com/

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, ClassVar

import aiohttp

from ..utils import PostContent
from .base import SocialPlatform

logger = logging.getLogger(__name__)

NEXTDOOR_API_BASE = "https://nextdoor.com/api/v2"


class NextdoorPlatform(SocialPlatform):
    """Nextdoor platform implementation using the Nextdoor API v2."""

    NAME = "nextdoor"
    # Each field reads from NEXTDOOR_<FIELD> when the admin UI has no value.
    CREDENTIAL_FIELDS: ClassVar[tuple[str, ...]] = (
        "access_token",
        "agency_id",
    )
    CHAR_LIMIT = 10000

    async def initialize_client(self) -> None:
        """Initialize session with auth headers and verify credentials."""
        try:
            # Nextdoor needs auth headers on the session
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.credentials['access_token']}",
                    "Content-Type": "application/json",
                }
            )
            url = f"{NEXTDOOR_API_BASE}/agencies/{self.credentials['agency_id']}"
            async with self._session.get(url) as response:
                if response.status != 200:
                    raise RuntimeError(f"Nextdoor auth failed: {await response.text()}")
                data = await response.json()
                logger.info(
                    "Authenticated Nextdoor for agency: %s", data.get("name", "unknown")
                )
        except Exception:
            logger.exception("Failed to initialize Nextdoor client")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to Nextdoor agency feed."""
        try:
            if not self._session or self._session.closed:
                await self.initialize_client()

            formatted = self.format_post(content)
            agency_id = self.credentials["agency_id"]
            post_data: dict[str, Any] = {"body": formatted.text}

            if formatted.media and formatted.media.link_url:
                post_data["link"] = {"url": formatted.media.link_url}

            if formatted.media and formatted.media.image_path:
                image_id = await self._upload_image(formatted.media.image_path)
                if image_id:
                    post_data["media"] = [{"id": image_id}]

            url = f"{NEXTDOOR_API_BASE}/agencies/{agency_id}/posts"
            async with self._session.post(url, json=post_data) as response:
                if response.status not in (200, 201):
                    logger.error("Nextdoor post failed: %s", await response.text())
                    return False

            logger.info("Successfully posted to Nextdoor")
            return True

        except Exception:
            logger.exception("Error posting to Nextdoor")
            return False

    async def _upload_image(self, image_path: str) -> str | None:
        """Upload an image and return the media ID."""
        try:
            agency_id = self.credentials["agency_id"]
            upload_url = f"{NEXTDOOR_API_BASE}/agencies/{agency_id}/media"

            if image_path.startswith("http"):
                async with self._session.post(
                    upload_url, json={"url": image_path}
                ) as resp:
                    if resp.status not in (200, 201):
                        logger.error(
                            "Nextdoor image upload failed: %s", await resp.text()
                        )
                        return None
                    return (await resp.json()).get("id")
            else:
                # Read the bytes up front: passing an open file left the handle
                # open after every upload.
                image_bytes = await asyncio.to_thread(Path(image_path).read_bytes)
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    image_bytes,
                    filename=os.path.basename(image_path),
                    content_type="image/png"
                    if image_path.lower().endswith(".png")
                    else "image/jpeg",
                )
                # The shared session's JSON Content-Type header would break the multipart body.
                headers = {
                    "Authorization": f"Bearer {self.credentials['access_token']}"
                }
                async with (
                    aiohttp.ClientSession() as upload_session,
                    upload_session.post(upload_url, data=form, headers=headers) as resp,
                ):
                    if resp.status not in (200, 201):
                        logger.error(
                            "Nextdoor image upload failed: %s", await resp.text()
                        )
                        return None
                    return (await resp.json()).get("id")
        except Exception:
            logger.exception("Error uploading image to Nextdoor")
            return None
