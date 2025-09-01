"""Runtime configuration via environment variables.

This module exposes a :class:`Settings` object based on Pydantic's
``BaseSettings``. It parses values from the process environment and provides
helpers for CSV → ``set[int]`` conversions. The legacy constants
(`OPENAI_API_KEY`, `OPENAI_MODEL` and `PRECHAT_MSG_CHAR_LIMIT`) are kept for
backwards compatibility with existing cogs.
"""

from __future__ import annotations

from typing import Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pydantic settings loaded from environment variables."""

    # schema
    ENV_SCHEMA_VERSION: int = 1

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MODEL_HEAVY: str = Field(default="gpt-4o")
    PRECHAT_MSG_CHAR_LIMIT: int = Field(default=300)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=20000)

    # --- Channel lists (comma separated) ---
    # keep them as raw strings, convert with properties below
    AGENT_ALLOWED_CHANNELS: str = Field(default="")   # e.g. "123,456"
    NSFW_CHANNELS: str = Field(default="")            # e.g. "111,222"

    # ---- Parsed helpers -----------------------------------------------------

    @property
    def allowed_channels(self) -> Set[int]:
        raw = (self.AGENT_ALLOWED_CHANNELS or "").replace(" ", "")
        return {int(x) for x in raw.split(",") if x}

    @property
    def nsfw_channels(self) -> Set[int]:
        raw = (self.NSFW_CHANNELS or "").replace(" ", "")
        return {int(x) for x in raw.split(",") if x}

    # ---- Validators ---------------------------------------------------------

    @field_validator("AGENT_DAILY_TOKEN_LIMIT")
    @classmethod
    def _cap_tokens(cls, v: int) -> int:
        if v <= 0 or v > 2_000_000:
            raise ValueError("AGENT_DAILY_TOKEN_LIMIT out of range")
        return v

    # Pydantic v2 config
    model_config = {
        "case_sensitive": False,
        "env_file_encoding": "utf-8",
    }


# Instantiate once for app-wide use
settings = Settings()

# Backwards compatibility constants ---------------------------------------
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_MODEL = settings.OPENAI_MODEL
PRECHAT_MSG_CHAR_LIMIT = settings.PRECHAT_MSG_CHAR_LIMIT

__all__ = [
    "Settings",
    "settings",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "PRECHAT_MSG_CHAR_LIMIT",
]
