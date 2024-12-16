import logging
from typing import Dict, Any
import facebook
from .base import SocialPlatform, PostContent

logger = logging.getLogger('CityBot2.social.facebook')

class FacebookPlatform(SocialPlatform):
    def initialize(self):
        try:
            self.client = facebook.GraphAPI(self.config['access_token'])
            logger.info("Successfully initialized Facebook client")
        except Exception as e:
            logger.error(f"Failed to initialize Facebook client: {str(e)}")
            raise

    def format_post(self, content: PostContent) -> PostContent:
        # Facebook has a much higher character limit (63,206)
        formatted_text = content.text
        if len(formatted_text) > 63000:
            formatted_text = formatted_text[:62997] + "..."

        return PostContent(
            text=formatted_text,
            media=content.media
        )

    async def post_update(self, content: PostContent) -> bool:
        try:
            formatted = self.format_post(content)
            
            post_args = {
                "message": formatted.text
            }

            # Handle media
            if formatted.media:
                if formatted.media.image_path:
                    with open(formatted.media.image_path, 'rb') as f:
                        self.client.put_photo(
                            image=f.read(),
                            message=formatted.text
                        )
                    return True
                elif formatted.media.link_url:
                    post_args["link"] = formatted.media.link_url
                    if formatted.media.meta_title:
                        post_args["name"] = formatted.media.meta_title
                    if formatted.media.meta_description:
                        post_args["description"] = formatted.media.meta_description

            # Post update
            self.client.put_object(
                parent_object="me",
                connection_name="feed",
                **post_args
            )
            
            logger.info("Successfully posted to Facebook")
            return True
            
        except Exception as e:
            logger.error(f"Error posting to Facebook: {str(e)}")
            return False