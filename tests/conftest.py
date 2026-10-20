"""Shared fixtures. Every test runs against a throwaway database and secret key,
never the real files under data/."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SENTRY_DSN", "")

CITY_CONFIG = {
    "name": "Ventura",
    "state": "CA",
    "timezone": "America/Los_Angeles",
    "coordinates": {"latitude": 34.2805, "longitude": -119.2945},
    "weather": {"radar_station": "VBX", "zone_code": "CAZ039", "description": "Coast"},
    "news": {
        "rss_feeds": {},
        "location_keywords": {
            "must_include": [],
            "at_least_one": ["ventura", "ventura harbor"],
            "exclude": ["oxnard"],
        },
    },
    "social": {"hashtags": {"news": ["VenturaNews"], "weather": [], "earthquake": []}},
}


@pytest.fixture
def city_config():
    return {**CITY_CONFIG, "news": {**CITY_CONFIG["news"]}}


@pytest.fixture
def db(tmp_path):
    from database.operations import DatabaseManager

    manager = DatabaseManager(f"sqlite:///{tmp_path / 'test.db'}")
    yield manager
    manager.close()


@pytest.fixture(autouse=True)
def isolated_secret_key(tmp_path, monkeypatch):
    from web import auth

    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    monkeypatch.setattr(auth, "_serializer", None)
    monkeypatch.setattr(auth, "_fernet", None)
