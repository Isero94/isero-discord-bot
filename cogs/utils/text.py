# cogs/utils/text.py
from __future__ import annotations
import re
import os
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
import discord
from loguru import logger as log
from .profanity_db import load_db

from bot.config import settings
from utils import policy, logsetup
import discord

log = logsetup.get_logger(__name__)


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
    """Unified loader: mini DB + pack fájlok + YAML/env fallback."""
    db_path = os.getenv("PROFANITY_DB_PATH", "config/profanity_db.json")
    packs_env = os.getenv("PROFANITY_PACKS", "")
    packs = [p for p in packs_env.split(";") if p.strip()]
    words = load_db(db_path, packs)
    if words:
        return words
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

# region ISERO PATCH star_mask_all
try:
    import regex as _re  # type: ignore
except Exception:  # pragma: no cover
    import re as _re  # type: ignore

def star_mask_all(text: str, match_words: list[str]) -> str:
    """Star out every profane word while keeping first/last chars."""
    if not match_words:
        return text

    def _mask(m: _re.Match) -> str:
        w = m.group(0)
        if len(w) <= 2:
            return w[0] + "*" * (len(w) - 1)
        return w[0] + "*" * (len(w) - 2) + w[-1]

    pat = "(" + "|".join(match_words) + ")"
    return _re.sub(pat, _mask, text, flags=_re.IGNORECASE | _re.DOTALL)
# endregion ISERO PATCH star_mask_all

# --- ISERO PATCH profanity detection helpers ---
try:
    import regex as _re
    _HAS_REGEX = True
except Exception:  # pragma: no cover
    import re as _re  # type: ignore
    _HAS_REGEX = False

_PROF_RX: Optional[_re.Pattern] = None


def _compile_prof() -> _re.Pattern:
    global _PROF_RX
    if _PROF_RX is not None:
        return _PROF_RX
    words = load_profanity_words()
    def var(ch: str) -> str:
        m = {
            'a': '[aá@4]',
            'e': '[eé3]',
            'i': '[ií1l!]',
            'o': '[oóöő0]',
            'u': '[uúüűv]',
            'c': '(?:c(?:h)?)',
            's': '[s$5]',
            'z': '[z2]',
            'g': '[g9]',
            'b': '[b8]',
        }
        return m.get(ch.lower(), _re.escape(ch))
    sep = r"(?:\s|\N{NO-BREAK SPACE}|[^\w]|[\d_]){0,3}"
    parts = []
    for w in words:
        letters = [f"{var(ch)}+" for ch in w]
        parts.append(sep.join(letters))
    core = "|".join(parts) or r"$^"
    bound_l = r"(?<!\p{L})" if _HAS_REGEX else r"(?<![^\W\d_])"
    bound_r = r"(?!\p{L})" if _HAS_REGEX else r"(?![^\W\d_])"
    _PROF_RX = _re.compile(rf"{bound_l}(?:{core}){bound_r}", _re.IGNORECASE | _re.DOTALL)
    return _PROF_RX


def find_profanities(text: str) -> List[Tuple[int, int]]:
    rx = _compile_prof()
    return [m.span() for m in rx.finditer(text)]


def star_out(text: str, hits: List[Tuple[int, int]], mask: str = "*") -> str:
    if not hits:
        return text
    chars = list(text)
    for s, e in hits:
        for i in range(s, e):
            if not chars[i].isspace():
                chars[i] = mask
    return "".join(chars)


async def webhook_echo(channel: discord.TextChannel, author: discord.Member, content: str, ttl_seconds: int = 30):
    if not policy.getbool("USE_WEBHOOK_MIMIC", False):
        await channel.send(f"{author.mention}: {content}")
        return
    hooks = await channel.webhooks()
    hook = next((h for h in hooks if h.name == "ISERO Echo"), None)
    if not hook:
        hook = await channel.create_webhook(name="ISERO Echo", reason="profanity echo")
    await hook.send(content, username=author.display_name, avatar_url=author.display_avatar.url)


async def timeout_member(member: discord.Member, minutes: int, reason: str = ""):
    if minutes < 0:
        return
    try:
        if minutes == 0:
            await member.timeout(None, reason=reason)
        else:
            await member.timeout(timedelta(minutes=minutes), reason=reason)
    except Exception:
        log.exception("timeout_member failed (perm?)")


async def modlog_profanity(message: discord.Message, *, original: str, starred: str, hits, level: int):
    ch_id = policy.getint("CHANNEL_MOD_LOGS", 0)
    if not ch_id:
        return
    ch = message.guild.get_channel(ch_id) if message.guild else None
    if not ch:
        return
    lvl = f"L{level}" if level else "L0"
    try:
        await ch.send(f"[profanity:{lvl}] {message.author.mention} in <#{message.channel.id}>\n`{original}`\n→ `{starred}`")
    except Exception:
        log.exception("modlog send failed")
