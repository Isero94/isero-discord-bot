# cogs/utils/text.py
from __future__ import annotations
import re
import os
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

import yaml
import discord
from loguru import logger as log

from bot.config import settings


def shorten(s: str, limit: Optional[int] = None) -> str:
    """Condense whitespace and cut to ``limit`` characters with ellipsis."""
    limit = limit or settings.MAX_MSG_CHARS
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


def truncate_by_chars(s: str, limit: int) -> str:
    """Cut string to ``limit`` characters, appending ellipsis if truncated."""
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


def no_repeat(s: str) -> str:
    """Collapse long character runs and duplicate words."""
    s = re.sub(r"(.)\1{4,}", r"\1\1\1", s)
    s = re.sub(r"(\b.+?\b)(?:\s+\1\b){1,}", r"\1", s, flags=re.IGNORECASE)
    return s.strip()


def chunk_message(text: str, limit: Optional[int] = None) -> List[str]:
    """Split ``text`` into <=limit character pieces with (n/m) prefixes.

    Each chunk fits within ``limit`` including the ``(n/m)`` marker when
    multiple chunks are returned.
    """
    limit = limit or settings.MAX_MSG_CHARS
    if len(text) <= limit:
        return [text]
    raw_chunks = [text[i : i + limit] for i in range(0, len(text), limit)]
    total = len(raw_chunks)
    out: List[str] = []
    for idx, chunk in enumerate(raw_chunks, start=1):
        if total > 1:
            prefix = f"({idx}/{total}) "
        else:
            prefix = ""
        allowed = limit - len(prefix)
        out.append(prefix + chunk[:allowed])
    return out


# region ISERO PATCH profanity_helpers
_PROF_SCORES: Dict[int, int] = {}


def load_profanity_words() -> List[str]:
    path = Path("config/profanity.yml")
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("words", [])
            if isinstance(data, list):
                return [str(w).strip() for w in data if str(w).strip()]
        except Exception:
            pass
    env = os.getenv("PROFANITY_WORDS", "")
    return [w.strip() for w in env.split(",") if w.strip()]


async def send_audit(bot, audit_channel_id: int, message: discord.Message, *, reason: str, original: str, redacted: str) -> None:
    ch = bot.get_channel(audit_channel_id)
    if ch:
        try:
            await ch.send(f"[{reason}] {original}\n{message.jump_url}")
        except Exception:
            pass


async def safe_echo(bot, channel: discord.abc.Messageable, content: str, *, mimic_webhook: bool = True, author: Optional[discord.abc.User] = None) -> None:
    await channel.send(content, allowed_mentions=discord.AllowedMentions.none())


async def echo_masked(bot, message: discord.Message, masked: str, ttl_s: int = 30):
    """Delete original then echo masked text via optional webhook mimic."""
    try:
        if getattr(settings, "USE_WEBHOOK_MIMIC", True) and hasattr(message.channel, "create_webhook"):
            wh = await message.channel.create_webhook(name=message.author.display_name)
            await wh.send(masked, avatar_url=message.author.display_avatar.url, username=message.author.display_name)
            await wh.delete()
        else:
            await message.channel.send(masked)
    except Exception as e:
        log.warning(f"echo_masked failed: {e}")


async def add_profanity_points(bot, user_id: int, points: int) -> int:
    _PROF_SCORES[user_id] = _PROF_SCORES.get(user_id, 0) + int(points)
    return _PROF_SCORES[user_id]


async def apply_timeout(bot, member: discord.Member, minutes: int, *, reason: str = "") -> None:
    if minutes <= 0:
        return
    try:
        await member.timeout(timedelta(minutes=minutes), reason=reason)
    except Exception:
        pass


async def timeout_member(message: discord.Message, minutes: int):
    """Timeout helper using message context; 0 => manual mute."""
    try:
        if minutes < 0:
            return
        member = message.guild.get_member(message.author.id)
        if member is None:
            return
        if minutes == 0:
            ch = message.guild.get_channel(settings.CHANNEL_MOD_LOGS)
            if ch:
                await ch.send(f"⚠️ Manual mute required for <@{member.id}> (profanity level 3).")
        else:
            await member.timeout(discord.utils.utcnow() + timedelta(minutes=minutes))
    except Exception as e:
        log.warning(f"timeout_member failed: {e}")
# endregion ISERO PATCH profanity_helpers
