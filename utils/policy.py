from __future__ import annotations

from dataclasses import dataclass
from bot.config import settings
from cogs.utils.context import MessageContext


@dataclass
class DecideResult:
    should_reply: bool
    mode: str  # short, guided, redirect, silent
    reason: str
    char_limit: int


class ResponderPolicy:

    @classmethod
    def decide(cls, ctx: MessageContext) -> DecideResult:
        limit = settings.MAX_MSG_CHARS
        silence_redirect = {
            settings.CHANNEL_ANNOUNCEMENTS,
            settings.CHANNEL_RULES,
            settings.CHANNEL_SERVER_GUIDE,
            settings.CHANNEL_MOD_LOGS,
            settings.CHANNEL_MOD_QUEUE,
        }
        if ctx.channel_id == settings.CHANNEL_TICKET_HUB and ctx.trigger == "free_text":
            return DecideResult(False, "silent", "ticket_hub_free_text", limit)
        if ctx.channel_id in silence_redirect:
            return DecideResult(True, "redirect", "noise_channel", limit)
        if ctx.channel_id == settings.CHANNEL_GENERAL_CHAT:
            if not (ctx.was_mentioned or ctx.has_wake_word):
                return DecideResult(False, "silent", "general_no_trigger", limit)
            return DecideResult(True, "short", "general_short", limit)
        if ctx.is_ticket and ctx.ticket_type in {"mebinu", "commission", "nsfw", "help"}:
            if ctx.ticket_type == "nsfw" and ctx.category_id != settings.CATEGORY_NSFW:
                return DecideResult(True, "redirect", "nsfw_redirect", limit)
            return DecideResult(True, "guided", "ticket_guided", limit)
        return DecideResult(True, "short", "default", limit)
