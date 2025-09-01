"""Tests for the Pydantic Settings helper."""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.config import Settings


def test_allowed_channels_parsing(monkeypatch):
    monkeypatch.setenv("AGENT_ALLOWED_CHANNELS", "1, 2,3")
    cfg = Settings()
    assert cfg.allowed_channels == {1, 2, 3}


def test_nsfw_channels_empty(monkeypatch):
    monkeypatch.delenv("NSFW_CHANNELS", raising=False)
    cfg = Settings()
    assert cfg.nsfw_channels == set()


def test_token_limit_validation(monkeypatch):
    monkeypatch.setenv("AGENT_DAILY_TOKEN_LIMIT", "-1")
    try:
        Settings()
    except ValueError:
        pass
    else:
        raise AssertionError("negative token limit should raise")


