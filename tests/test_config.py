import json

import pytest


def test_bot_entry_point_imports():
    """main.py imported ConfigurationManager from `config`, which resolved to
    the config/ package instead of config.py, so the bot couldn't start."""
    import main

    assert main.ConfigurationManager.__name__ == "ConfigurationManager"


@pytest.fixture
def manager(tmp_path, monkeypatch, city_config):
    from config import ConfigurationManager

    (tmp_path / "config" / "cities").mkdir(parents=True)
    (tmp_path / "config" / "credentials.env").write_text("CITY_NAME=testcity\n")
    city_config = {**city_config, "name": "San Buenaventura"}
    city_config.pop("social")
    (tmp_path / "config" / "cities" / "testcity.json").write_text(
        json.dumps(city_config)
    )
    monkeypatch.chdir(tmp_path)
    for var in (
        "EARTHQUAKE_CHECK_INTERVAL",
        "EARTHQUAKE_UPDATE_INTERVAL",
        "NEWS_CHECK_INTERVAL",
        "TWITTER_POSTS_PER_HOUR",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CITY_NAME", "testcity")
    return ConfigurationManager()


def test_interval_defaults_follow_each_tasks_own_setting(manager):
    # These all fell back to 3600 because only "update_interval" was read.
    assert manager.get_interval("earthquake") == 300
    assert manager.get_interval("news") == 1800
    assert manager.get_interval("weather_alert") == 900
    assert manager.get_interval("maintenance") == 86400
    assert manager.get_interval("weather") == 21600


def test_interval_reads_documented_env_names(manager, monkeypatch):
    monkeypatch.setenv("EARTHQUAKE_CHECK_INTERVAL", "120")
    assert manager.get_interval("earthquake") == 120
    monkeypatch.delenv("EARTHQUAKE_CHECK_INTERVAL")
    monkeypatch.setenv("EARTHQUAKE_UPDATE_INTERVAL", "90")
    assert manager.get_interval("earthquake") == 90


def test_hashtags_drop_spaces_and_survive_missing_social(manager):
    tags = manager.city_config["social"]["hashtags"]["weather"]
    assert tags[0] == "SanBuenaventuraWeather"


def test_rate_limits_use_ratelimiter_keys(manager, monkeypatch):
    monkeypatch.setenv("TWITTER_POSTS_PER_HOUR", "2")
    assert manager.get_rate_limits("twitter") == {
        "hourly": 2,
        "daily": 24,
        "interval": 300,
    }
