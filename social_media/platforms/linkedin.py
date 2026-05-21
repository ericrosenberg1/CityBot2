import json
import asyncio
import logging
from typing import Dict, Any, Optional

from linkedin_v2 import linkedin

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)


class LinkedInPlatform(SocialPlatform):
    """LinkedIn platform implementation."""

    CREDENTIAL_MAP = {
        'client_id': 'LINKEDIN_CLIENT_ID',
        'client_secret': 'LINKEDIN_CLIENT_SECRET',
        'access_token': 'LINKEDIN_ACCESS_TOKEN',
    }
    CHAR_LIMIT = 3000

    async def initialize_client(self) -> None:
        """Initialize LinkedIn client."""
        try:
            self._client = linkedin.LinkedInApplication(
                token=self.credentials['access_token']
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
                'author': f"urn:li:person:{self.credentials['client_id']}",
                'lifecycleState': 'PUBLISHED',
                'specificContent': {
                    'com.linkedin.ugc.ShareContent': {
                        'shareCommentary': {'text': content.text},
                        'shareMediaCategory': 'NONE'
                    }
                },
                'visibility': {
                    'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
                }
            }

            if content.media and content.media.image_path:
                image_data = await self._upload_image(content.media.image_path)
                if image_data:
                    share = post_data['specificContent']['com.linkedin.ugc.ShareContent']
                    share['shareMediaCategory'] = 'IMAGE'
                    share['media'] = [image_data]

            result = await asyncio.to_thread(
                self._client.make_request,
                'POST', '/v2/ugcPosts',
                data=json.dumps(post_data)
            )
            return bool(result)

        except Exception as e:
            logger.error("Error posting to LinkedIn: %s", str(e))
            return False

    async def _upload_image(self, image_path: str) -> Optional[Dict[str, Any]]:
        """Upload image to LinkedIn."""
        try:
            register_response = await asyncio.to_thread(
                self._client.make_request,
                'POST', '/v2/assets?action=registerUpload',
                data=json.dumps({
                    'registerUploadRequest': {
                        'recipes': ['urn:li:digitalmediaRecipe:feedshare-image'],
                        'owner': f"urn:li:person:{self.credentials['client_id']}",
                        'serviceRelationships': [{
                            'relationshipType': 'OWNER',
                            'identifier': 'urn:li:userGeneratedContent'
                        }]
                    }
                })
            )

            with open(image_path, 'rb') as image:
                upload_url = register_response['value']['uploadMechanism'][
                    'com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
                await asyncio.to_thread(
                    self._client.make_request,
                    'POST', upload_url,
                    data=image.read(),
                    headers={'Content-Type': 'application/octet-stream'}
                )

            return {
                'status': 'READY',
                'media': register_response['value']['asset']
            }
        except Exception as e:
            logger.error("Error uploading image to LinkedIn: %s", str(e))
            return None
