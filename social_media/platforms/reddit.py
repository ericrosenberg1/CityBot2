import logging
from typing import Dict, Any
import praw
from .base import SocialPlatform, PostContent

logger = logging.getLogger('CityBot2.social.reddit')

class RedditPlatform(SocialPlatform):
    def initialize(self):
        try:
            self.client = praw.Reddit(
                client_id=self.config['client_id'],
                client_secret=self.config['client_secret'],
                username=self.config['username'],
                password=self.config['password'],
                user_agent="CityBot2/1.0"
            )
            self.subreddits = self.config.get('subreddits', [])
            logger.info("Successfully initialized Reddit client")
        except Exception as e:
            logger.error(f"Failed to initialize Reddit client: {str(e)}")
            raise

    def format_post(self, content: PostContent) -> PostContent:
        # Reddit has a 40,000 character limit
        formatted_text = content.text
        
        # Add formatting for Reddit markdown
        formatted_text = formatted_text.replace('\n', '\n\n')  # Double line breaks for paragraphs
        
        # Add source attribution if it's a news post
        if content.media and content.media.link_url:
            formatted_text += f"\n\n---\nSource: {content.media.link_url}"
        
        formatted_text += "\n\n^(Posted by CityBot2)"

        return PostContent(
            text=formatted_text,
            media=content.media
        )

    async def post_update(self, content: PostContent) -> bool:
        try:
            formatted = self.format_post(content)
            success = True
            
            for subreddit_name in self.subreddits:
                try:
                    subreddit = self.client.subreddit(subreddit_name)
                    
                    # Determine post type
                    if formatted.media and formatted.media.image_path:
                        submission = subreddit.submit_image(
                            title=formatted.media.meta_title or "City Update",
                            image_path=formatted.media.image_path,
                            flair_id=self.config.get('flair_id'),
                        )
                        # Add comment with additional information
                        submission.reply(formatted.text)
                    else:
                        # Text post
                        submission = subreddit.submit(
                            title=formatted.media.meta_title if formatted.media else "City Update",
                            selftext=formatted.text,
                            flair_id=self.config.get('flair_id'),
                        )
                    
                    logger.info(f"Successfully posted to r/{subreddit_name}")
                except Exception as e:
                    logger.error(f"Error posting to r/{subreddit_name}: {str(e)}")
                    success = False
            
            return success
            
        except Exception as e:
            logger.error(f"Error posting to Reddit: {str(e)}")
            return False