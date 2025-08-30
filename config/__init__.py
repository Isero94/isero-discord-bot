# config/__init__.py
# Központi konfiguráció ENV-ből, biztonságos parse-olással és jó defaultokkal.

from __future__ import annotations
import os
from typing import List, Optional


def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if v else default


def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if not v:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_csv_int(name: str) -> List[int]:
    v = os.getenv(name, "")
    out: List[int] = []
    for part in v.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out


def _env_csv_str(name: str) -> List[str]:
    v = os.getenv(name, "")
    out: List[str] = []
    for part in v.replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.append(part)
    return out


# ---- Alap Discord / OpenAI / adatbázis ----

DISCORD_TOKEN: str = _env_str("DISCORD_TOKEN")
GUILD_ID: Optional[int] = _env_int("GUILD_ID")
OWNER_ID: Optional[int] = _env_int("OWNER_ID")

OPENAI_API_KEY: str = _env_str("OPENAI_API_KEY")

# A fő csevegő modell neve. (Pl.: "gpt-4o-mini")
OPENAI_MODEL: str = _env_str("OPENAI_MODEL", "gpt-4o-mini")

# NÉV, AMIT AZ AGENT KÓD VÁR:
# Ha nincs külön megadva, ugyanaz, mint az OPENAI_MODEL.
OPENAI_MODEL_BASE: str = _env_str("OPENAI_MODEL_BASE", OPENAI_MODEL)

# Agent napi token limit (összes userre, durva sapka)
AGENT_DAILY_TOKEN_LIMIT: int = _env_int("AGENT_DAILY_TOKEN_LIMIT", 20000) or 20000

# Csak ezekben a csatornákban válaszoljon az Agent (opcionális)
AGENT_ALLOWED_CHANNELS: list[int] = _env_csv_int("AGENT_ALLOWED_CHANNELS")

# NSFW csatornák (pl. tiltott topikok figyeléséhez)
NSFW_CHANNELS: list[int] = _env_csv_int("NSFW_CHANNELS")

# Opcionális staff jogok
STAFF_ROLE_ID: Optional[int] = _env_int("STAFF_ROLE_ID")
STAFF_EXTRA_ROLE_IDS: list[int] = _env_csv_int("STAFF_EXTRA_ROLE_IDS")

# Ticket rendszerhez (ha a cog igényli ezeket)
TICKET_HUB_CHANNEL_ID: Optional[int] = _env_int("TICKET_HUB_CHANNEL_ID")
TICKETS_CATEGORY_ID: Optional[int] = _env_int("TICKETS_CATEGORY_ID")
ARCHIVE_CATEGORY_ID: Optional[int] = _env_int("ARCHIVE_CATEGORY_ID")
TICKET_COOLDOWN_SECONDS: int = _env_int("TICKET_COOLDOWN_SECONDS", 20) or 20

# Staff „szólásszabadság” (watchereknél/agentnél finomításokhoz)
ALLOW_STAFF_FREESPEECH: bool = _env_bool("ALLOW_STAFF_FREESPEECH", True)

# Adatbázis (PlayerDB) – ha külön modul használja
DATABASE_URL: str = _env_str("DATABASE_URL")

# ---- Profanity / toxicity pontozás (egyelőre csak score gyűjtés) ----
PROFANITY_FREE_WORDS: int = _env_int("PROFANITY_FREE_WORDS", 2) or 2
PROFANITY_STAGE1_POINTS: int = _env_int("PROFANITY_STAGE1_POINTS", 5) or 5
PROFANITY_STAGE2_POINTS: int = _env_int("PROFANITY_STAGE2_POINTS", 10) or 10
PROFANITY_STAGE3_POINTS: int = _env_int("PROFANITY_STAGE3_POINTS", 20) or 20

# ---- Sentiment keretek (marketing/watcherek finomhangolásához) ----
# 0.0–1.0 skálán gondolkodunk; ezek csak példák, minden felülírható ENV-ből.
SENTIMENT_NEG_HARD_BLOCK: float = float(_env_str("SENTIMENT_NEG_HARD_BLOCK", "0.05"))
SENTIMENT_NEG_SOFT_NOTE: float = float(_env_str("SENTIMENT_NEG_SOFT_NOTE", "0.15"))
SENTIMENT_POS_PROMO_HINT: float = float(_env_str("SENTIMENT_POS_PROMO_HINT", "0.70"))

# Kényelmi csomag OpenAI híváshoz (ha a kód így várja)
OPENAI_DEFAULT_ARGS = {
    "model": OPENAI_MODEL_BASE,
}
