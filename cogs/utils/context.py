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
    char_limit: int = settings.MAX_MSG_CHARS


def resolve(channel: discord.abc.GuildChannel) -> MessageContext:
    """Build a :class:`MessageContext` for ``channel``."""
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
    is_nsfw = getattr(channel, "is_nsfw", lambda: False)() or (
        channel.id in settings.nsfw_channels
    )
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
    )
