"""Runtime configuration via environment variables."""

from __future__ import annotations

from typing import Dict, Optional, Set

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pydantic settings loaded from environment variables."""

    ENV_SCHEMA_VERSION: int = 1

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MODEL_HEAVY: str = Field(default="gpt-4o")
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=20000)

    # --- Message limits ---
    MAX_MSG_CHARS: int = Field(default=300)
    BRIEF_MAX_CHARS: int = Field(default=800)
    BRIEF_MAX_IMAGES: int = Field(default=4)

    # --- Channel lists (comma separated) ---
    AGENT_ALLOWED_CHANNELS: Optional[str] = None
    NSFW_CHANNELS: Optional[str] = None

    # --- Discord IDs ---
    GUILD_ID: Optional[int] = None
    OWNER_ID: Optional[int] = None
    CHANNEL_TICKET_HUB: Optional[int] = None
    CHANNEL_BOT_COMMANDS: Optional[int] = None
    CHANNEL_SUGGESTIONS: Optional[int] = None
    CHANNEL_GENERAL_CHAT: Optional[int] = None
    CHANNEL_ANNOUNCEMENTS: Optional[int] = None
    CHANNEL_RULES: Optional[int] = None
    CHANNEL_SERVER_GUIDE: Optional[int] = None
    CHANNEL_MOD_LOGS: Optional[int] = None
    CHANNEL_MOD_QUEUE: Optional[int] = None
    CHANNEL_GENERAL_LOGS: Optional[int] = None
    CATEGORY_TICKETS: Optional[int] = None
    CATEGORY_MEBINU: Optional[int] = None
    CATEGORY_NSFW: Optional[int] = None
    CATEGORY_GAMING: Optional[int] = None
    CATEGORY_ART: Optional[int] = None
    CATEGORY_UTILITIES: Optional[int] = None
    CATEGORY_STAFF: Optional[int] = None
    CATEGORY_SOCIAL: Optional[int] = None
    CATEGORY_INFO: Optional[int] = None
    ARCHIVE_CATEGORY_ID: Optional[int] = None
    STAFF_ROLE_ID: Optional[int] = None
    STAFF_EXTRA_ROLE_IDS: Optional[str] = None
    TICKET_COOLDOWN_SECONDS: int = Field(default=20)
    NSFW_ROLE_NAME: str = Field(default="NSFW 18+")
    OWNER_NL_ENABLED: bool = Field(default=False)
    OWNER_ACTIVATION_PREFIX: str = Field(default="admin:")

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

    @property
    def staff_extra_roles(self) -> Set[int]:
        return {
            int(x)
            for x in (self.STAFF_EXTRA_ROLE_IDS or "").replace(" ", "").split(",")
            if x
        }

    @property
    def channel_registry(self) -> Dict[int, str]:
        return {
            getattr(self, attr): attr
            for attr in dir(self)
            if attr.startswith("CHANNEL_")
            and isinstance(getattr(self, attr), int)
            and getattr(self, attr)
        }

    @property
    def category_registry(self) -> Dict[int, str]:
        return {
            getattr(self, attr): attr
            for attr in dir(self)
            if attr.startswith("CATEGORY_")
            and isinstance(getattr(self, attr), int)
            and getattr(self, attr)
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
MAX_MSG_CHARS = settings.MAX_MSG_CHARS
PRECHAT_MSG_CHAR_LIMIT = settings.MAX_MSG_CHARS  # legacy name
GUILD_ID = settings.GUILD_ID

__all__ = [
    "Settings",
    "settings",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "MAX_MSG_CHARS",
    "PRECHAT_MSG_CHAR_LIMIT",
    "GUILD_ID",
]

