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


def test_ticket_ids(monkeypatch):
    monkeypatch.setenv("CHANNEL_TICKET_HUB", "123")
    monkeypatch.setenv("CATEGORY_TICKETS", "456")
    monkeypatch.delenv("TICKET_COOLDOWN_SECONDS", raising=False)
    cfg = Settings()
    assert cfg.CHANNEL_TICKET_HUB == 123
    assert cfg.CATEGORY_TICKETS == 456
    assert cfg.TICKET_COOLDOWN_SECONDS == 20


def test_channel_registry(monkeypatch):
    monkeypatch.setenv("CHANNEL_GENERAL_CHAT", "111")
    cfg = Settings()
    assert cfg.channel_registry[111] == "CHANNEL_GENERAL_CHAT"


def test_msg_limits(monkeypatch):
    monkeypatch.delenv("MAX_MSG_CHARS", raising=False)
    monkeypatch.delenv("BRIEF_MAX_CHARS", raising=False)
    monkeypatch.delenv("BRIEF_MAX_IMAGES", raising=False)
    cfg = Settings()
    assert cfg.MAX_MSG_CHARS == 300
    assert cfg.BRIEF_MAX_CHARS == 800
    assert cfg.BRIEF_MAX_IMAGES == 4

