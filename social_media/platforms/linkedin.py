import asyncio
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

from linkedin_v2 import linkedin

from ..utils import PostContent
from .base import SocialPlatform

logger = logging.getLogger(__name__)


class LinkedInPlatform(SocialPlatform):
    """LinkedIn platform implementation."""

    NAME = "linkedin"
    # Each field reads from LINKEDIN_<FIELD> when the admin UI has no value.
    CREDENTIAL_FIELDS: ClassVar[tuple[str, ...]] = (
        "client_id",
        "client_secret",
        "access_token",
    )
    CHAR_LIMIT = 3000

    async def initialize_client(self) -> None:
        """Initialize LinkedIn client."""
        try:
            self._client = linkedin.LinkedInApplication(
                token=self.credentials["access_token"]
            )
        except Exception as e:
            logger.error("Failed to initialize LinkedIn client: %s", str(e))
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post to LinkedIn."""
        try:
            if not self._client:
                await self.initialize_client()

            post_data = {
                "author": f"urn:li:person:{self.credentials['client_id']}",
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": content.text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }

            if content.media and content.media.image_path:
                image_data = await self._upload_image(content.media.image_path)
                if image_data:
                    share = post_data["specificContent"][
                        "com.linkedin.ugc.ShareContent"
                    ]
                    share["shareMediaCategory"] = "IMAGE"
                    share["media"] = [image_data]

            result = await asyncio.to_thread(
                self._client.make_request,
                "POST",
                "/v2/ugcPosts",
                data=json.dumps(post_data),
            )
            return bool(result)

        except Exception:
            logger.exception("Error posting to LinkedIn")
            return False

    async def _upload_image(self, image_path: str) -> dict[str, Any] | None:
        """Upload image to LinkedIn."""
        try:
            register_response = await asyncio.to_thread(
                self._client.make_request,
                "POST",
                "/v2/assets?action=registerUpload",
                data=json.dumps(
                    {
                        "registerUploadRequest": {
                            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                            "owner": f"urn:li:person:{self.credentials['client_id']}",
                            "serviceRelationships": [
                                {
                                    "relationshipType": "OWNER",
                                    "identifier": "urn:li:userGeneratedContent",
                                }
                            ],
                        }
                    }
                ),
            )

            upload_url = register_response["value"]["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            image_bytes = await asyncio.to_thread(Path(image_path).read_bytes)
            await asyncio.to_thread(
                self._client.make_request,
                "POST",
                upload_url,
                data=image_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )

            return {"status": "READY", "media": register_response["value"]["asset"]}
        except Exception:
            logger.exception("Error uploading image to LinkedIn")
            return None
