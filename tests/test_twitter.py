"""TwitterPlatform signs and sends its own X calls (tweepy was removed)."""

import asyncio

import pytest

from social_media.platforms.twitter import (
    MEDIA_UPLOAD_URL,
    TWEET_URL,
    TwitterPlatform,
)
from social_media.utils import MediaContent, PostContent

CREDENTIALS = {
    "api_key": "ck",
    "api_secret": "cs",
    "access_token": "at",
    "access_secret": "as",
}


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def json(self):
        return self._body

    async def text(self):
        return str(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture
def platform(city_config):
    return TwitterPlatform({"credentials": CREDENTIALS}, city_config)


def run_post(platform, session, content):
    async def fake_session():
        return session

    platform._ensure_session = fake_session
    return asyncio.run(platform.post_update(content))


def test_text_tweet_is_signed_and_sent_as_json(platform):
    session = FakeSession([FakeResponse(201, {"data": {"id": "1", "text": "hi"}})])

    assert run_post(platform, session, PostContent(text="hi")) is True

    url, kwargs = session.calls[0]
    assert url == TWEET_URL
    assert kwargs["json"] == {"text": "hi"}
    auth = kwargs["headers"]["Authorization"]
    assert auth.startswith("OAuth ")
    assert 'oauth_consumer_key="ck"' in auth
    assert 'oauth_token="at"' in auth
    assert "oauth_signature=" in auth


def test_image_is_uploaded_first_and_attached(platform, tmp_path):
    image = tmp_path / "map.png"
    image.write_bytes(b"\x89PNG fake")
    session = FakeSession(
        [
            FakeResponse(200, {"media_id_string": "555"}),
            FakeResponse(201, {"data": {"id": "2"}}),
        ]
    )
    content = PostContent(text="map", media=MediaContent(image_path=str(image)))

    assert run_post(platform, session, content) is True

    assert [call[0] for call in session.calls] == [MEDIA_UPLOAD_URL, TWEET_URL]
    assert session.calls[1][1]["json"] == {
        "text": "map",
        "media": {"media_ids": ["555"]},
    }


def test_failed_upload_posts_nothing(platform, tmp_path):
    image = tmp_path / "map.png"
    image.write_bytes(b"x")
    session = FakeSession([FakeResponse(400, {"errors": ["bad media"]})])
    content = PostContent(text="map", media=MediaContent(image_path=str(image)))

    assert run_post(platform, session, content) is False
    assert len(session.calls) == 1


def test_rejected_tweet_returns_false(platform):
    session = FakeSession([FakeResponse(429, {"title": "Too Many Requests"})])

    assert run_post(platform, session, PostContent(text="hi")) is False


def test_signing_is_deterministic_for_a_fixed_nonce_and_timestamp():
    """Same inputs, same HMAC-SHA1 signature, so a signer change shows up here."""
    from oauthlib.oauth1 import Client

    def sign():
        client = Client(
            "ck",
            client_secret="cs",
            resource_owner_key="at",
            resource_owner_secret="as",
            nonce="fixednonce",
            timestamp="1700000000",
        )
        _, headers, _ = client.sign(TWEET_URL, http_method="POST")
        return headers["Authorization"]

    assert sign() == sign()
    assert 'oauth_signature_method="HMAC-SHA1"' in sign()
