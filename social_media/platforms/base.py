import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

import aiohttp

from ..utils import PostContent

logger = logging.getLogger('CityBot2.platforms')


class SocialPlatform(ABC):
    """Base class for all social media platforms."""

    CREDENTIAL_MAP: Dict[str, str] = {}
    CHAR_LIMIT: int = 5000

    def __init__(self, platform_config: Dict[str, Any], city_config: Dict[str, Any]):
        self.config = platform_config
        self.city_config = city_config
        self._client = None
        self._session: Optional[aiohttp.ClientSession] = None
        self.credentials = self._load_credentials(platform_config)

    def _load_credentials(self, config: Dict[str, Any]) -> Dict[str, str]:
        """Load credentials from config dict or env vars using CREDENTIAL_MAP."""
        creds = config.get('credentials', {})
        credentials = {}
        missing = []

        for key, env_var in self.CREDENTIAL_MAP.items():
            value = creds.get(key) or os.getenv(env_var)
            if value:
                credentials[key] = value
            else:
                missing.append(key)

        if missing:
            raise ValueError(
                f"Missing {self.__class__.__name__} credentials: {', '.join(missing)}"
            )
        return credentials

    def format_post(self, content: PostContent) -> PostContent:
        """Truncate text to CHAR_LIMIT."""
        text = content.text
        if len(text) > self.CHAR_LIMIT:
            text = text[: self.CHAR_LIMIT - 3] + "..."
        return PostContent(
            text=text,
            media=content.media,
            platform_specific=content.platform_specific,
        )

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Return a reusable aiohttp.ClientSession, creating one if needed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @abstractmethod
    async def initialize_client(self) -> None:
        pass

    @abstractmethod
    async def post_update(self, content: PostContent) -> bool:
        pass

    async def close(self) -> None:
        """Clean up resources."""
        try:
            if self._session and not self._session.closed:
                await self._session.close()
            if self._client is not None:
                if hasattr(self._client, 'close'):
                    await self._client.close()
                elif hasattr(self._client, 'logout'):
                    await self._client.logout()
                logger.info("%s: Client closed successfully", self.__class__.__name__)
        except Exception as e:
            logger.error("%s: Error closing client - %s", self.__class__.__name__, str(e))
        finally:
            self._client = None
            self._session = None
