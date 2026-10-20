import logging
import os
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import aiohttp

from ..utils import PostContent

logger = logging.getLogger("CityBot2.platforms")

# Meta supports each Graph API version for about two years. v23.0 shipped May 2025.
GRAPH_API_BASE = "https://graph.facebook.com/v23.0"


async def graph_error(response: aiohttp.ClientResponse) -> str:
    """Error message from a failed Meta Graph API response."""
    try:
        return (await response.json()).get("error", {}).get("message", "Unknown error")
    except (aiohttp.ContentTypeError, ValueError):
        return await response.text()


class SocialPlatform(ABC):
    """Base class for all social media platforms."""

    NAME: ClassVar[str] = ""
    # Credential field names. Each can come from the admin UI or from the
    # env var {NAME}_{FIELD}, e.g. ("access_token",) reads THREADS_ACCESS_TOKEN.
    CREDENTIAL_FIELDS: ClassVar[tuple[str, ...]] = ()
    CHAR_LIMIT: int = 5000

    def __init__(self, platform_config: dict[str, Any], city_config: dict[str, Any]):
        self.config = platform_config
        self.city_config = city_config
        self._client = None
        self._session: aiohttp.ClientSession | None = None
        self.credentials = self._load_credentials(platform_config)

    @classmethod
    def credential_env_vars(cls) -> dict[str, str]:
        """Credential field -> the env var it falls back to."""
        return {
            field: f"{cls.NAME.upper()}_{field.upper()}"
            for field in cls.CREDENTIAL_FIELDS
        }

    def _load_credentials(self, config: dict[str, Any]) -> dict[str, str]:
        """Load credentials from the config dict, falling back to env vars."""
        creds = config.get("credentials", {})
        credentials = {}
        missing = []

        for key, env_var in self.credential_env_vars().items():
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

    async def _graph_verify(self, url: str, access_token: str) -> dict:
        """Check Meta Graph credentials by reading the account's id and username."""
        session = await self._ensure_session()
        params = {"fields": "id,username", "access_token": access_token}
        async with session.get(url, params=params) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Failed to verify {self.__class__.__name__} credentials: {await graph_error(response)}"
                )
            data = await response.json()
        logger.info(
            "Authenticated %s for @%s",
            self.__class__.__name__,
            data.get("username", "unknown"),
        )
        return data

    async def _graph_create_and_publish(
        self,
        account_url: str,
        container_edge: str,
        publish_edge: str,
        params: dict[str, Any],
    ) -> bool:
        """Meta's two-step publish (Threads, Instagram): create a media
        container, then publish it."""
        session = await self._ensure_session()
        name = self.__class__.__name__
        async with session.post(f"{account_url}/{container_edge}", data=params) as resp:
            if resp.status != 200:
                logger.error("%s container error: %s", name, await graph_error(resp))
                return False
            container_id = (await resp.json()).get("id")
        if not container_id:
            return False

        publish_params = {
            "creation_id": container_id,
            "access_token": params["access_token"],
        }
        async with session.post(
            f"{account_url}/{publish_edge}", data=publish_params
        ) as resp:
            if resp.status != 200:
                logger.error("%s publish error: %s", name, await graph_error(resp))
                return False
        logger.info("Successfully posted to %s", name)
        return True

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
                if hasattr(self._client, "close"):
                    await self._client.close()
                elif hasattr(self._client, "logout"):
                    await self._client.logout()
                logger.info("%s: Client closed successfully", self.__class__.__name__)
        except Exception:
            logger.exception("%s: Error closing client", self.__class__.__name__)
        finally:
            self._client = None
            self._session = None
