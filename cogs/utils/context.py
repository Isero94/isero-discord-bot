from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import discord

from bot.config import settings


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
    char_limit: int = settings.MAX_MSG_CHARS
    brief_char_limit: int = settings.BRIEF_MAX_CHARS
    brief_image_limit: int = settings.BRIEF_MAX_IMAGES


def resolve(message: discord.Message) -> MessageContext:
    """Build a :class:`MessageContext` for ``message``."""
    channel = message.channel
    member = getattr(message, "author", None)
    category = getattr(channel, "category", None)
    cat_id = category.id if category else None
    cat_name = category.name if category else None
    is_ticket = cat_id == settings.CATEGORY_TICKETS
    ticket_type = None
    topic = getattr(channel, "topic", "") or ""
    if "ticket_type=" in topic:
        for part in topic.split():
            if part.startswith("ticket_type="):
                ticket_type = part.split("=", 1)[1]
                break
    if not ticket_type:
        name_low = channel.name.lower()
        for key in ("mebinu", "commission", "nsfw", "help"):
            if key in name_low:
                ticket_type = key
                break
    is_nsfw = getattr(channel, "is_nsfw", lambda: False)() or (
        channel.id in settings.nsfw_channels
    )
    is_owner = bool(member and settings.OWNER_ID and member.id == settings.OWNER_ID)
    roles = getattr(member, "roles", []) if member else []
    staff_ids = {settings.STAFF_ROLE_ID} | settings.staff_extra_roles
    is_staff = any(getattr(r, "id", 0) in staff_ids for r in roles)
    locale = getattr(member, "locale", "en") or "en"
    display = getattr(member, "display_name", getattr(member, "name", ""))
    return MessageContext(
        guild_id=getattr(channel.guild, "id", 0),
        channel_id=channel.id,
        channel_name=channel.name,
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
    )
