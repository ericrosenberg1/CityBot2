import logging
from typing import Dict, Any
from linkedin_v2 import linkedin
from .base import SocialPlatform, PostContent

logger = logging.getLogger('CityBot2.social.linkedin')

class LinkedInPlatform(SocialPlatform):
    def initialize(self):
        try:
            self.client = linkedin.LinkedInApplication(
                token=self.config['access_token']
            )
            logger.info("Successfully initialized LinkedIn client")
        except Exception as e:
            logger.error(f"Failed to initialize LinkedIn client: {str(e)}")
            raise

    def format_post(self, content: PostContent) -> PostContent:
        # LinkedIn has a 3000 character limit
        formatted_text = content.text
        if len(formatted_text) > 3000:
            formatted_text = formatted_text[:2997] + "..."

        # Remove excessive emojis for professional tone
        formatted_text = formatted_text.replace(
            "🌤️", "").replace("🌡️", "").replace("💨", "")
        
        return PostContent(
            text=formatted_text,
            media=content.media
        )

    async def post_update(self, content: PostContent) -> bool:
        try:
            formatted = self.format_post(content)
            
            # Create share content
            share_content = {
                "author": f"urn:li:person:{self.config['user_id']}",
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {
                            "text": formatted.text
                        },
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                }
            }

            # Handle media
            if formatted.media:
                if formatted.media.image_path:
                    # Upload image
                    image_data = self.client.upload_image(formatted.media.image_path)
                    
                    share_content["specificContent"]["com.linkedin.ugc.ShareContent"].update({
                        "shareMediaCategory": "IMAGE",
                        "media": [{
                            "status": "READY",
                            "media": image_data["asset"],
                            "title": {
                                "text": formatted.media.meta_title or "City Update"
                            }
                        }]
                    })
                elif formatted.media.link_url:
                    share_content["specificContent"]["com.linkedin.ugc.ShareContent"].update({
                        "shareMediaCategory": "ARTICLE",
                        "media": [{
                            "status": "READY",
                            "originalUrl": formatted.media.link_url,
                            "title": formatted.media.meta_title or "City Update",
                            "description": formatted.media.meta_description or ""
                        }]
                    })

            # Post update
            self.client.submit_share(share_content)
            
            logger.info("Successfully posted to LinkedIn")
            return True
            
        except Exception as e:
            logger.error(f"Error posting to LinkedIn: {str(e)}")
            return False