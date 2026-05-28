import os
import asyncpraw
import logging
from typing import Dict, Any, List

from .base import SocialPlatform
from ..utils import PostContent

logger = logging.getLogger(__name__)


class RedditPlatform(SocialPlatform):
    """Reddit platform implementation using asyncpraw."""

    CREDENTIAL_MAP = {
        'client_id': 'REDDIT_CLIENT_ID',
        'client_secret': 'REDDIT_CLIENT_SECRET',
        'username': 'REDDIT_USERNAME',
        'password': 'REDDIT_PASSWORD',
    }
    CHAR_LIMIT = 40000

    def __init__(self, platform_config: Dict[str, Any], city_config: Dict[str, Any]):
        super().__init__(platform_config, city_config)
        # user_agent is optional — provide a default if missing
        if 'user_agent' not in self.credentials:
            ua_env = os.getenv('REDDIT_USER_AGENT')
            self.credentials['user_agent'] = ua_env or (
                f"CityBot2/1.0 (by /u/{self.credentials.get('username', 'citybot')})"
            )
        self.subreddits = self._load_subreddits(platform_config)

    def _load_subreddits(self, config: Dict[str, Any]) -> List[str]:
        """Load target subreddits from config or environment."""
        subreddits = config.get('subreddits', [])
        if not subreddits:
            env_subs = os.getenv('REDDIT_SUBREDDITS', '')
            if env_subs:
                subreddits = [s.strip() for s in env_subs.split(',') if s.strip()]
        if not subreddits:
            logger.warning("No subreddits configured for Reddit platform")
        return subreddits

    async def initialize_client(self) -> None:
        """Initialize async Reddit client."""
        try:
            self._client = asyncpraw.Reddit(
                client_id=self.credentials['client_id'],
                client_secret=self.credentials['client_secret'],
                username=self.credentials['username'],
                password=self.credentials['password'],
                user_agent=self.credentials['user_agent'],
            )
            user = await self._client.user.me()
            logger.info("Successfully authenticated Reddit client as /u/%s", user.name)
        except Exception as e:
            logger.error("Failed to initialize Reddit client: %s", str(e), exc_info=True)
            self._client = None
            raise

    async def post_update(self, content: PostContent) -> bool:
        """Post content to configured subreddits."""
        try:
            if not self._client:
                await self.initialize_client()

            formatted_content = self.format_post(content)
            success = False

            for subreddit_name in self.subreddits:
                try:
                    subreddit = await self._client.subreddit(subreddit_name)
                    title = self._extract_title(formatted_content)
                    link_url = None
                    if formatted_content.media and formatted_content.media.link_url:
                        link_url = formatted_content.media.link_url

                    if link_url:
                        submission = await subreddit.submit(title=title, url=link_url)
                    else:
                        submission = await subreddit.submit(title=title, selftext=formatted_content.text)

                    logger.info("Successfully posted to r/%s: %s", subreddit_name, submission.id)
                    success = True
                except Exception as sub_err:
                    logger.error("Error posting to r/%s: %s", subreddit_name, str(sub_err), exc_info=True)

            return success

        except Exception as e:
            logger.error("Error posting to Reddit: %s", str(e), exc_info=True)
            return False

    def _extract_title(self, content: PostContent) -> str:
        """Extract a title from post content (first line, max 300 chars)."""
        first_line = content.text.strip().split('\n')[0].strip()
        if len(first_line) > 300:
            first_line = first_line[:297] + "..."
        return first_line

    def format_post(self, content: PostContent) -> PostContent:
        """Format for Reddit — truncate via base, then extract title."""
        return super().format_post(content)

    async def close(self) -> None:
        """Clean up Reddit client resources."""
        try:
            if self._client is not None:
                await self._client.close()
                logger.info("Reddit client closed successfully")
        except Exception as e:
            logger.error("Error closing Reddit client: %s", str(e))
        finally:
            self._client = None
