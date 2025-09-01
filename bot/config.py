"""Runtime configuration via environment variables.

This module exposes a :class:`Settings` object based on Pydantic's BaseSettings.
It parses values from the process environment and provides handy helpers.
Legacy constants (OPENAI_* and PRECHAT_MSG_CHAR_LIMIT) are kept for backwards
compatibility with existing cogs.
"""

from __future__ import annotations

from typing import Set
from pydantic import Field
from pydantic.alias_generators import to_snake
from pydantic.settings import BaseSettings
from pydantic import AliasChoices

class Settings(BaseSettings):
    # --- schema ---
    ENV_SCHEMA_VERSION: int = 1

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MODEL_HEAVY: str = Field(default="gpt-4o")
    PRECHAT_MSG_CHAR_LIMIT: int = Field(default=300)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=20000)

    # --- Agent / channels (raw CSV, majd property konvertál) ---
    AGENT_ALLOWED_CHANNELS: str = Field(default="")   # "123,456"
    NSFW_CHANNELS: str = Field(default="")            # "111,222"

    # --- Discord / tickets / roles / categories ---
    # Elfogadjuk mindkét ENV nevet aliasokkal:
    CHANNEL_TICKET_HUB: int = Field(
        default=0,
        validation_alias=AliasChoices("CHANNEL_TICKET_HUB", "TICKET_HUB_CHANNEL_ID"),
    )
    CATEGORY_TICKETS: int = Field(
        default=0,
        validation_alias=AliasChoices("CATEGORY_TICKETS", "TICKETS_CATEGORY_ID"),
    )
    ARCHIVE_CATEGORY_ID: int = Field(default=0)

    STAFF_ROLE_ID: int = Field(default=0)
    STAFF_CHANNEL_ID: int = Field(default=0)
    STAFF_EXTRA_ROLE_IDS: str = Field(default="")  # CSV, ha kell később

    # Ticket cooldown
    TICKET_COOLDOWN_SECONDS: int = Field(default=20)

    # Egy gyakran hiányzó érték a cogban – adjunk biztonságos defaultot:
    NSFW_ROLE_NAME: str = Field(default="NSFW 18+")

    # Egyéb (ha kell máshol)
    GUILD_ID: int = Field(default=0)
    OWNER_ID: int = Field(default=0)

    # ---- Parsed helpers -----------------------------------------------------
    @property
    def allowed_channels(self) -> Set[int]:
        raw = (self.AGENT_ALLOWED_CHANNELS or "").replace(" ", "")
        return {int(x) for x in raw.split(",") if x}

    @property
    def nsfw_channels(self) -> Set[int]:
        raw = (self.NSFW_CHANNELS or "").replace(" ", "")
        return {int(x) for x in raw.split(",") if x}

    # ---- Pydantic v2 config -------------------------------------------------
    model_config = {
        "case_sensitive": False,
        "env_file_encoding": "utf-8",
        "alias_generator": to_snake,
    }

# Instantiate once for app-wide use
settings = Settings()

# Backwards compatibility constants -----------------------------------------
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
