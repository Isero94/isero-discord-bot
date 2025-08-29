import os
from dataclasses import dataclass

# Canonical category labels (single source of truth)
CATEGORIES = ["Mebinu", "Commission", "NSFW 18+", "General Help"]

# Channels (extend with new names/IDs at any time)
GUILD_ID = int(os.getenv("GUILD_ID", "0")) or None
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0")) or None
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0")) or None
ARCHIVES_CHANNEL_ID = int(os.getenv("ARCHIVES_CHANNEL_ID", "0")) or None
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0")) or None

# Limits (env-overridable)
PRECHAT_TURNS = int(os.getenv("PRECHAT_TURNS", "10"))
PRECHAT_MSG_CHAR_LIMIT = int(os.getenv("PRECHAT_MSG_CHAR_LIMIT", "300"))
TICKET_TEXT_MAXLEN = int(os.getenv("TICKET_TEXT_MAXLEN", "800"))
TICKET_IMG_MAX = int(os.getenv("TICKET_IMG_MAX", "4"))

# Feature flags
FEATURES = {
    "ticket_hub": os.getenv("FEATURE_TICKET_HUB", "true").lower() == "true",
    "ranks": os.getenv("FEATURE_RANKS", "true").lower() == "true",
    "staff_assistant": os.getenv("FEATURE_STAFF_ASSISTANT", "true").lower() == "true",
    "public_assistant": os.getenv("FEATURE_PUBLIC_ASSISTANT", "true").lower() == "true",
    "guardian": os.getenv("FEATURE_GUARDIAN", "true").lower() == "true",
    "deviantart": os.getenv("FEATURE_DEVIANTART", "false").lower() == "true",
}

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# NSFW policy
NSFW_AGEGATE_REQUIRED = True

@dataclass(frozen=True)
class Limits:
    PRECHAT_TURNS: int = PRECHAT_TURNS
    PRECHAT_MSG_CHAR_LIMIT: int = PRECHAT_MSG_CHAR_LIMIT
    TICKET_TEXT_MAXLEN: int = TICKET_TEXT_MAXLEN
    TICKET_IMG_MAX: int = TICKET_IMG_MAX
