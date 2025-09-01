"""Runtime configuration via environment variables.

This module exposes a :class:`Settings` object based on Pydantic's
``BaseSettings``.  It parses values from the process environment and provides
handy helpers for CSV → ``set[int]`` conversions.  The legacy constants
(`OPENAI_API_KEY`, ``OPENAI_MODEL`` and ``PRECHAT_MSG_CHAR_LIMIT``) are kept for
backwards compatibility with existing cogs.
"""

from __future__ import annotations


from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pydantic settings loaded from environment variables."""

    ENV_SCHEMA_VERSION: int = 1

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MODEL_HEAVY: str = Field(default="gpt-4o")
    PRECHAT_MSG_CHAR_LIMIT: int = Field(default=300)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=20000)

    # --- Channel lists (comma separated) ---


    @property
    def allowed_channels(self) -> Set[int]:
        return {
            int(x)
            for x in (self.AGENT_ALLOWED_CHANNELS or "").replace(" ", "").split(",")
            if x
        }

    @property
    def nsfw_channels(self) -> Set[int]:
        return {
            int(x)
            for x in (self.NSFW_CHANNELS or "").replace(" ", "").split(",")
            if x
        }

    @validator("AGENT_DAILY_TOKEN_LIMIT")
    def _cap_tokens(cls, v: int) -> int:  # noqa: D401 - simple validation
        if v <= 0 or v > 2_000_000:
            raise ValueError("AGENT_DAILY_TOKEN_LIMIT out of range")
        return v


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

