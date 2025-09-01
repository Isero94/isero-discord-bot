"""Runtime configuration via environment variables.

Pydantic v2 + pydantic-settings.
Tartalmazza a tickets cog által használt mezőket is.
"""

from __future__ import annotations
from typing import Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- schema ---
    ENV_SCHEMA_VERSION: int = 1

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MODEL_HEAVY: str = Field(default="gpt-4o")
    PRECHAT_MSG_CHAR_LIMIT: int = Field(default=300)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=20000)

    # --- Discord környezet / tickets cog igényei ---
    GUILD_ID: int = 0
    CHANNEL_TICKET_HUB: int = 0
    CATEGORY_TICKETS: int = 0
    ARCHIVE_CATEGORY_ID: int = 0
    STAFF_ROLE_ID: int = 0
    TICKET_COOLDOWN_SECONDS: int = 20
    NSFW_ROLE_NAME: str = "NSFW 18+"

    # --- Egyebek / listák nyersen, property-vel parse-oljuk ---
    AGENT_ALLOWED_CHANNELS: str = Field(default="")
    NSFW_CHANNELS: str = Field(default="")

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

# Backwards compatibility constants (régebbi cogoknak)
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
