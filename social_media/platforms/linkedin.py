from linkedin_v2 import linkedin
import json
import asyncio
import logging
from typing import Dict, Any
from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)

class LinkedInPlatform(SocialPlatform):
    """LinkedIn platform implementation."""
    
    def __init__(self, credentials: Dict[str, Any], city_config: Dict[str, Any]):
        """
        Initialize LinkedIn platform.
        
        :param credentials: Dictionary containing authentication credentials
        :param city_config: Configuration for the city
        """
        super().__init__({'credentials': credentials})
        self.city_config = city_config
        self._client = None

    async def initialize_client(self) -> None:
        """Initialize LinkedIn client."""
        try:
            self._client = linkedin.LinkedInApplication(
                token=self.credentials['access_token']
            )
        except Exception as e:
            logger.error(f"Failed to initialize LinkedIn client: {str(e)}")
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
                        'shareCommentary': {
                            'text': content.text
                        },
                        'shareMediaCategory': 'NONE'
                    }
                },
                'visibility': {
                    'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
                }
            }

            if content.media and content.media.image_path:
                # Handle image upload
                image_data = await self._upload_image(content.media.image_path)
                if image_data:
                    post_data['specificContent']['com.linkedin.ugc.ShareContent']['shareMediaCategory'] = 'IMAGE'
                    post_data['specificContent']['com.linkedin.ugc.ShareContent']['media'] = [image_data]

            result = await asyncio.to_thread(
                self._client.make_request,
                'POST',
                '/v2/ugcPosts',
                data=json.dumps(post_data)
            )
            return bool(result)

        except Exception as e:
            logger.error(f"Error posting to LinkedIn: {str(e)}")
            return False

    async def _upload_image(self, image_path: str) -> Dict[str, Any]:
        """Upload image to LinkedIn."""
        try:
            # Register image upload
            register_response = await asyncio.to_thread(
                self._client.make_request,
                'POST',
                '/v2/assets?action=registerUpload',
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

            # Upload image binary
            with open(image_path, 'rb') as image:
                upload_response = await asyncio.to_thread(
                    self._client.make_request,
                    'POST',
                    register_response['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl'],
                    data=image.read(),
                    headers={'Content-Type': 'application/octet-stream'}
                )

            return {
                'status': 'READY',
                'media': register_response['value']['asset']
            }

        except Exception as e:
            logger.error(f"Error uploading image to LinkedIn: {str(e)}")
            return None

    def format_post(self, content: PostContent) -> PostContent:
        """Format content for LinkedIn."""
        # LinkedIn has a 3000 character limit
        text = content.text
        if len(text) > 3000:
            text = text[:2997] + "..."
        
        return PostContent(
            text=text,
            media=content.media,
            platform_specific=content.platform_specific
        )