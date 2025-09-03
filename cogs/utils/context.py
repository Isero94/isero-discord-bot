from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

import os
import discord

from bot.config import settings
from cogs.utils.wake import WakeMatcher

"""Utilities for resolving message context and cross-cog message flags."""

# ---------------------------------------------------------------------------
# Lightweight message-flag API so cogs can short-circuit on moderated/hidden
# messages. Flags are stored on the bot instance to be accessible across cogs.
# ---------------------------------------------------------------------------

HIDDEN = "isero.hidden"
MODERATED = "isero.moderated"

def _bags(bot) -> Dict[str, set[Tuple[int, int]]]:
    if not hasattr(bot, "_isero_flags"):
        bot._isero_flags = {HIDDEN: set(), MODERATED: set()}
    return bot._isero_flags  # type: ignore[attr-defined]

def _key(message) -> Tuple[int, int]:
    ch_id = getattr(getattr(message, "channel", None), "id", 0)
    msg_id = getattr(message, "id", None)
    if not isinstance(msg_id, int) or msg_id == 0:
        msg_id = id(message)
    return ch_id, msg_id

def mark_hidden(bot, message) -> None:
    _bags(bot)[HIDDEN].add(_key(message))

def mark_moderated(bot, message) -> None:
    _bags(bot)[MODERATED].add(_key(message))

def is_hidden(bot, message) -> bool:
    return _key(message) in _bags(bot)[HIDDEN]

def is_moderated(bot, message) -> bool:
    return _key(message) in _bags(bot)[MODERATED]

def is_flagged(bot, message) -> bool:
    bags = _bags(bot)
    key = _key(message)
    return key in bags[HIDDEN] or key in bags[MODERATED]


def _csv(val: str | None) -> list[str]:
    if not val:
        return []
    raw = val.strip().strip('"').strip("'")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


@dataclass
class MessageContext:
    guild_id: int
    channel_id: int
    channel_name: str
    category_id: Optional[int]
    category_name: Optional[str]
    is_thread: bool
    is_ticket: bool
    ticket_type: Optional[str]
    is_nsfw: bool
    is_owner: bool
    is_staff: bool
    locale: str
    user_display: str
    content: str = ""
    trigger: str = "free_text"
    was_mentioned: bool = False
    has_wake_word: bool = False
    msg_chars: int = 0
    has_attachments: bool = False
    char_limit: int = settings.MAX_MSG_CHARS
    brief_char_limit: int = settings.BRIEF_MAX_CHARS
    brief_image_limit: int = settings.BRIEF_MAX_IMAGES
    slash_command: Optional[str] = None


_TICKET_DB: Dict[int, str] = {}


async def resolve(obj: Any, *, trigger_reason: str | None = None) -> MessageContext:
    """Build a :class:`MessageContext` for a :class:`discord.Message` or :class:`discord.Interaction`."""
    if isinstance(obj, discord.Interaction):
        channel = obj.channel
        if channel is None and getattr(obj, "client", None):
            try:
                channel = await obj.client.fetch_channel(obj.channel_id)  # type: ignore[attr-defined]
            except Exception:
                channel = None
        user = obj.user
        content = ""
        attachments: list[Any] = []
        mentions: list[Any] = []
        role_mentions: list[Any] = []
        locale = getattr(obj, "locale", None) or getattr(getattr(obj, "guild", None), "preferred_locale", "en") or "en"
        slash_cmd = getattr(getattr(obj, "command", None), "name", None)
    elif isinstance(obj, discord.Message):
        channel = getattr(obj, "channel", None)
        user = getattr(obj, "author", None)
        content = getattr(obj, "content", "") or ""
        attachments = list(getattr(obj, "attachments", []))
        mentions = list(getattr(obj, "mentions", []))
        role_mentions = list(getattr(obj, "role_mentions", []))
        locale = getattr(user, "locale", "en") or "en"
        slash_cmd = None
    else:
        raise TypeError("resolve() needs Message or Interaction")

    trigger = trigger_reason or ("slash" if isinstance(obj, discord.Interaction) else "free_text")
    channel = channel or getattr(obj, "channel", None)
    category = getattr(channel, "category", None)
    cat_id = getattr(category, "id", None)
    cat_name = getattr(category, "name", None)
    is_ticket = cat_id == settings.CATEGORY_TICKETS
    ticket_type = _TICKET_DB.get(getattr(channel, "id", 0))

    topic = getattr(channel, "topic", "") or ""
    if not ticket_type and "ticket_type=" in topic:
        for part in topic.split():
            if part.startswith("ticket_type="):
                ticket_type = part.split("=", 1)[1]
                break
    if not ticket_type and isinstance(channel, discord.TextChannel):
        try:
            pins = await channel.pins()
            for pin in pins:
                for row in getattr(pin, "components", []):
                    for comp in getattr(row, "children", []):
                        cid = getattr(comp, "custom_id", "") or getattr(comp, "value", "")
                        if cid:
                            ticket_type = cid.split(":")[-1]
                            break
                    if ticket_type:
                        break
                if ticket_type:
                    break
        except Exception:
            pass
    if not ticket_type:
        name_low = getattr(channel, "name", "").lower()
        for key in ("mebinu", "commission", "nsfw", "help"):
            if key in name_low:
                ticket_type = key
                break
    is_nsfw = getattr(channel, "is_nsfw", lambda: False)() or (
        getattr(channel, "id", 0) in settings.nsfw_channels
    )
    bot_member = getattr(getattr(getattr(channel, "guild", None), "me", None), "id", None)
    bot_mention = f"<@{bot_member}>" if bot_member else None
    wake = WakeMatcher()
    extra_wake = _csv(os.getenv("WAKE_WORDS"))
    low = content.lower()
    was_mentioned = bool(bot_member and mentions and any(getattr(m, "id", 0) == bot_member for m in mentions))
    has_wake_word = wake.has_wake(content, bot_mention=bot_mention) or any(w in low for w in extra_wake)
    msg_chars = len(content)
    has_attachments = bool(attachments)
    roles = getattr(user, "roles", []) if user else []
    staff_ids = {settings.STAFF_ROLE_ID} | settings.staff_extra_roles
    is_staff = any(getattr(r, "id", 0) in staff_ids for r in roles)
    is_owner = bool(user and settings.OWNER_ID and getattr(user, "id", 0) == settings.OWNER_ID)
    display = getattr(user, "display_name", getattr(user, "name", ""))
    return MessageContext(
        guild_id=getattr(getattr(channel, "guild", None), "id", 0),
        channel_id=getattr(channel, "id", 0),
        channel_name=getattr(channel, "name", ""),
        category_id=cat_id,
        category_name=cat_name,
        is_thread=bool(getattr(channel, "thread", False)),
        is_ticket=is_ticket,
        ticket_type=ticket_type,
        is_nsfw=is_nsfw,
        is_owner=is_owner,
        is_staff=is_staff,
        locale=str(locale),
        user_display=display,
        content=content,
        trigger=trigger,
        was_mentioned=was_mentioned,
        has_wake_word=has_wake_word,
        msg_chars=msg_chars,
        has_attachments=has_attachments,
        slash_command=slash_cmd,
    )
