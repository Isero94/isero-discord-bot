# config.py
import os
from typing import Optional, List

def _csv(name: str) -> List[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    out = []
    for p in raw.split(","):
        p = p.strip()
        if p and p.isdigit():
            out.append(int(p))
    return out

def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(str(v).strip())
    except ValueError:
        return default

OPENAI_API_KEY         = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_BASE      = os.getenv("OPENAI_MODEL_BASE", "gpt-4o-mini")
OPENAI_MODEL_HEAVY     = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")
OPENAI_DAILY_TOKENS    = _env_int("OPENAI_DAILY_TOKENS", 20000)

# Agent működés
AGENT_REPLY_COOLDOWN   = _env_int("AGENT_REPLY_COOLDOWN_SEC", 15)
AGENT_ALLOWED_CHANNELS = _csv("AGENT_ALLOWED_CHANNELS")
FIRST10_USER_IDS       = _csv("FIRST10_USER_IDS")

# Profanity + szabályok
PROFANITY_FREE_WORDS   = _env_int("PROFANITY_FREE_WORDS", 2)
PROFANITY_STAGE1       = _env_int("PROFANITY_STAGE1_POINTS", 5)
PROFANITY_STAGE2       = _env_int("PROFANITY_STAGE2_POINTS", 3)
PROFANITY_STAGE3       = _env_int("PROFANITY_STAGE3_POINTS", 2)

# DB
DATABASE_URL           = os.getenv("DATABASE_URL", "")

# Discord
GUILD_ID               = _env_int("GUILD_ID")
OWNER_ID               = _env_int("OWNER_ID")
ALLOW_STAFF_FREESPEECH = os.getenv("ALLOW_STAFF_FREESPEECH", "false").lower() == "true"
