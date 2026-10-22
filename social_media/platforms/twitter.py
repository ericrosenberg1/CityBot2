import logging
from pathlib import Path
from typing import Any, ClassVar

import aiohttp
from oauthlib.oauth1 import SIGNATURE_TYPE_AUTH_HEADER, Client

from ..utils import PostContent
from .base import SocialPlatform

logger = logging.getLogger(__name__)

TWEET_URL = "https://api.twitter.com/2/tweets"
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
# X answers a create-tweet call with 201 and a media upload with 200.
_OK_STATUSES = (200, 201)


class TwitterPlatform(SocialPlatform):
    """X.com (Twitter) platform implementation.

    Calls the two X endpoints directly and signs them with oauthlib's OAuth1
    client. This replaced tweepy, whose `oauthlib<4` cap kept CityBot2 on an
    oauthlib release with two open advisories.
    """

    NAME = "twitter"
    # Each field reads from TWITTER_<FIELD> when the admin UI has no value.
    CREDENTIAL_FIELDS: ClassVar[tuple[str, ...]] = (
        "api_key",
        "api_secret",
        "access_token",
        "access_secret",
    )
    CHAR_LIMIT = 280

    def __init__(self, platform_config: dict[str, Any], city_config: dict[str, Any]):
        super().__init__(platform_config, city_config)
        self._oauth: Client | None = None

    async def initialize_client(self) -> None:
        """Build the OAuth1 signer for the configured X account."""
        try:
            self._oauth = Client(
                self.credentials["api_key"],
                client_secret=self.credentials["api_secret"],
                resource_owner_key=self.credentials["access_token"],
                resource_owner_secret=self.credentials["access_secret"],
                signature_type=SIGNATURE_TYPE_AUTH_HEADER,
            )
            self._client = self._oauth
            logger.info("Successfully initialized Twitter client")
        except Exception:
            logger.exception("Failed to initialize Twitter client")
            raise

    def _auth_headers(self, url: str, extra: dict[str, str] | None = None) -> dict:
        """OAuth1 Authorization header for a POST to `url`.

        X signs only the URL and the OAuth parameters here. A JSON or multipart
        body is not part of the signature base string, so none is passed in.
        """
        _, headers, _ = self._oauth.sign(url, http_method="POST", headers=extra or {})
        return headers

    async def _upload_media(self, image_path: str) -> str | None:
        """Upload an image and return its media id, or None on failure."""
        session = await self._ensure_session()
        form = aiohttp.FormData()
        form.add_field(
            "media",
            Path(image_path).read_bytes(),
            filename=Path(image_path).name,
            content_type="application/octet-stream",
        )
        async with session.post(
            MEDIA_UPLOAD_URL, data=form, headers=self._auth_headers(MEDIA_UPLOAD_URL)
        ) as response:
            if response.status not in _OK_STATUSES:
                logger.error(
                    "Error uploading media to X: %s %s",
                    response.status,
                    (await response.text())[:300],
                )
                return None
            return (await response.json()).get("media_id_string")

    async def post_update(self, content: PostContent) -> bool:
        """Post a tweet to X/Twitter."""
        try:
            if not self._oauth:
                await self.initialize_client()

            payload: dict[str, Any] = {"text": content.text}
            if content.media and content.media.image_path:
                try:
                    media_id = await self._upload_media(content.media.image_path)
                except Exception:
                    logger.exception("Error uploading media to X")
                    return False
                if not media_id:
                    return False
                payload["media"] = {"media_ids": [media_id]}
                logger.info("Successfully uploaded media to Twitter")

            session = await self._ensure_session()
            async with session.post(
                TWEET_URL,
                json=payload,
                headers=self._auth_headers(TWEET_URL),
            ) as response:
                if response.status not in _OK_STATUSES:
                    logger.error(
                        "Error posting to X: %s %s",
                        response.status,
                        (await response.text())[:300],
                    )
                    return False
                body = await response.json()

            if body.get("data"):
                logger.info("Successfully posted tweet")
                return True
            logger.error("Unexpected response when creating tweet")
            return False

        except Exception:
            logger.exception("Error posting to X")
            return False
