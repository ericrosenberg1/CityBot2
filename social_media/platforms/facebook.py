import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import aiohttp

from ..utils import PostContent
from .base import GRAPH_API_BASE, SocialPlatform, graph_error

logger = logging.getLogger(__name__)


class FacebookPlatform(SocialPlatform):
    """Facebook Page platform implementation using the Graph API directly.

    This replaces facebook-sdk, which hasn't had a release since 2019 and
    can't target any Graph API version newer than 3.1.
    """

    CREDENTIAL_MAP: ClassVar[dict[str, str]] = {
        "page_id": "FACEBOOK_PAGE_ID",
        "access_token": "FACEBOOK_ACCESS_TOKEN",
    }
    CHAR_LIMIT = 63206

    async def initialize_client(self) -> None:
        """Facebook needs no client object. Posts go over the shared session."""
        await self._ensure_session()

    async def post_update(self, content: PostContent) -> bool:
        """Post to the Facebook Page: a photo post when there's an image,
        otherwise a feed post (with its link preview when there's a link)."""
        try:
            session = await self._ensure_session()
            page_url = f"{GRAPH_API_BASE}/{self.credentials['page_id']}"
            media = content.media

            if media and media.image_path:
                image_bytes = await asyncio.to_thread(Path(media.image_path).read_bytes)
                form = aiohttp.FormData()
                form.add_field("caption", content.text)
                form.add_field("access_token", self.credentials["access_token"])
                form.add_field("source", image_bytes, filename="image.png")
                request = session.post(f"{page_url}/photos", data=form)
            else:
                data = {
                    "message": content.text,
                    "access_token": self.credentials["access_token"],
                }
                if media and media.link_url:
                    data["link"] = media.link_url
                request = session.post(f"{page_url}/feed", data=data)

            async with request as response:
                if response.status != 200:
                    logger.error(
                        "Error posting to Facebook: %s", await graph_error(response)
                    )
                    return False
            return True

        except Exception:
            logger.exception("Error posting to Facebook")
            return False
