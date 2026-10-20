import logging
from typing import ClassVar

from ..utils import PostContent
from .base import GRAPH_API_BASE, SocialPlatform

logger = logging.getLogger(__name__)


class InstagramPlatform(SocialPlatform):
    """Instagram platform implementation using the Instagram Graph API."""

    CREDENTIAL_MAP: ClassVar[dict[str, str]] = {
        "access_token": "INSTAGRAM_ACCESS_TOKEN",
        "business_account_id": "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    }
    CHAR_LIMIT = 2200

    async def initialize_client(self) -> None:
        """Verify Instagram credentials."""
        try:
            await self._graph_verify(
                f"{GRAPH_API_BASE}/{self.credentials['business_account_id']}",
                self.credentials["access_token"],
            )
        except Exception:
            logger.exception("Failed to initialize Instagram client")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to Instagram (requires a publicly accessible image URL)."""
        try:
            formatted = self.format_post(content)

            if not formatted.media or not formatted.media.image_path:
                logger.warning("Instagram requires an image for every post; skipping")
                return False

            image_url = formatted.media.image_path
            if not image_url.startswith("http"):
                logger.error(
                    "Instagram Graph API requires a public image URL, got: %s",
                    image_url,
                )
                return False

            return await self._graph_create_and_publish(
                f"{GRAPH_API_BASE}/{self.credentials['business_account_id']}",
                "media",
                "media_publish",
                {
                    "image_url": image_url,
                    "caption": formatted.text,
                    "access_token": self.credentials["access_token"],
                },
            )

        except Exception:
            logger.exception("Error posting to Instagram")
            return False
