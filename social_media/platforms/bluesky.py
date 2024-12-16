import logging
from typing import Dict, Any
import asyncio
from atproto import Client
from .base import SocialPlatform, PostContent, MediaContent

logger = logging.getLogger('CityBot2.social.bluesky')

class BlueSkyPlatform(SocialPlatform):
    def initialize(self):
        try:
            self.client = Client()
            self.client.login(
                self.config['handle'],
                self.config['password']
            )
            logger.info("Successfully initialized Bluesky client")
        except Exception as e:
            logger.error(f"Failed to initialize Bluesky client: {str(e)}")
            raise

    def format_post(self, content: PostContent) -> PostContent:
        # Format text (300 character limit)
        formatted_text = content.text
        if len(formatted_text) > 300:
            formatted_text = formatted_text[:297] + "..."

        # Return formatted content
        return PostContent(
            text=formatted_text,
            media=content.media
        )

    async def post_update(self, content: PostContent) -> bool:
        try:
            formatted = self.format_post(content)
            
            # Create post record
            record = {
                "text": formatted.text,
                "$type": "app.bsky.feed.post",
                "createdAt": self.client.get_current_time_iso()
            }

            # Handle media
            if formatted.media:
                if formatted.media.image_path:
                    with open(formatted.media.image_path, 'rb') as f:
                        img_data = f.read()
                        upload = await self.client.upload_blob(img_data)
                        record["embed"] = {
                            "$type": "app.bsky.embed.images",
                            "images": [{"alt": "Ventura Update", "image": upload.blob}]
                        }
                elif formatted.media.link_url:
                    record["embed"] = {
                        "$type": "app.bsky.embed.external",
                        "external": {
                            "uri": formatted.media.link_url,
                            "title": formatted.media.meta_title or "Ventura Update",
                            "description": formatted.media.meta_description or ""
                        }
                    }

            # Create the post
            await self.client.com.atproto.repo.create_record({
                "repo": self.client.me.did,
                "collection": "app.bsky.feed.post",
                "record": record
            })
            
            logger.info("Successfully posted to Bluesky")
            return True
            
        except Exception as e:
            logger.error(f"Error posting to Bluesky: {str(e)}")
            return False