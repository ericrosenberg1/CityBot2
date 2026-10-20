import logging
from typing import ClassVar

from ..utils import PostContent
from .base import SocialPlatform

logger = logging.getLogger(__name__)

THREADS_API_BASE = "https://graph.threads.net/v1.0"


class ThreadsPlatform(SocialPlatform):
    """Threads (by Meta) platform implementation."""

    NAME = "threads"
    # Each field reads from THREADS_<FIELD> when the admin UI has no value.
    CREDENTIAL_FIELDS: ClassVar[tuple[str, ...]] = (
        "access_token",
        "user_id",
    )
    CHAR_LIMIT = 500

    async def initialize_client(self) -> None:
        """Verify Threads credentials."""
        try:
            await self._graph_verify(
                f"{THREADS_API_BASE}/{self.credentials['user_id']}",
                self.credentials["access_token"],
            )
        except Exception:
            logger.exception("Failed to initialize Threads client")
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to Threads (two-step: create container, then publish)."""
        try:
            formatted = self.format_post(content)
            container_params = {
                "media_type": "TEXT",
                "text": formatted.text,
                "access_token": self.credentials["access_token"],
            }

            if formatted.media and formatted.media.image_path:
                if formatted.media.image_path.startswith("http"):
                    container_params["media_type"] = "IMAGE"
                    container_params["image_url"] = formatted.media.image_path
                else:
                    logger.warning(
                        "Threads requires a public URL for images; local path ignored"
                    )

            return await self._graph_create_and_publish(
                f"{THREADS_API_BASE}/{self.credentials['user_id']}",
                "threads",
                "threads_publish",
                container_params,
            )

        except Exception:
            logger.exception("Error posting to Threads")
            return False
