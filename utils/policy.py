from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Dict
from bot.config import settings
from cogs.utils.context import MessageContext


@dataclass
class DecideResult:
    should_reply: bool
    mode: str  # short, guided, redirect, silent
    reason: str
    char_limit: int


class ResponderPolicy:
    quiet_until: Dict[int, float] = {}

    @classmethod
    def quiet_channel(cls, channel_id: int, ttl: int = 3600) -> None:
        cls.quiet_until[channel_id] = time.time() + ttl

    @classmethod
    def unquiet_channel(cls, channel_id: int) -> None:
        cls.quiet_until.pop(channel_id, None)

    @classmethod
    def _is_quiet(cls, channel_id: int) -> bool:
        exp = cls.quiet_until.get(channel_id)
        return bool(exp and exp > time.time())

    @staticmethod
    def get_reply_limit(ctx: MessageContext) -> int:
        """Return max character count for replies in this context."""
        # For now every context shares the same hard cap (300 chars)
        return 300

    @classmethod
    def decide(cls, ctx: MessageContext) -> DecideResult:
        limit = cls.get_reply_limit(ctx)
        silence_redirect = {
            settings.CHANNEL_ANNOUNCEMENTS,
            settings.CHANNEL_RULES,
            settings.CHANNEL_SERVER_GUIDE,
            settings.CHANNEL_MOD_LOGS,
            settings.CHANNEL_MOD_QUEUE,
        }
        cid = getattr(ctx, "channel_id", None)
        trigger = getattr(ctx, "trigger", "free_text")
        if cls._is_quiet(cid) and not getattr(ctx, "is_owner", False):
            return DecideResult(False, "silent", "channel_quiet", limit)

        talk = {
            settings.CHANNEL_GENERAL_CHAT,
            settings.CHANNEL_BOT_COMMANDS,
            settings.CHANNEL_SUGGESTIONS,
        }
        if cid == settings.CHANNEL_TICKET_HUB and trigger == "free_text":
            return DecideResult(False, "silent", "ticket_hub_free_text", limit)
        if cid in silence_redirect:
            return DecideResult(True, "redirect", "noise_channel", limit)

        content = getattr(ctx, "content", "")
        if cid in talk:
            if getattr(ctx, "is_owner", False):
                return DecideResult(True, "short", "owner_override", limit)
            if "?" in content:
                return DecideResult(True, "short", "question_in_general", limit)
            if cid != settings.CHANNEL_GENERAL_CHAT:
                return DecideResult(False, "silent", "no_trigger_talk", limit)

        if cid == settings.CHANNEL_GENERAL_CHAT:
            if not (getattr(ctx, "was_mentioned", False) or getattr(ctx, "has_wake_word", False)):
                return DecideResult(False, "silent", "general_no_trigger", limit)
            return DecideResult(True, "short", "general_short", limit)
        is_ticket = getattr(ctx, "is_ticket", False)
        ticket_type = getattr(ctx, "ticket_type", None)
        category_id = getattr(ctx, "category_id", None)
        if is_ticket and ticket_type in {"mebinu", "commission", "nsfw", "help"}:
            if ticket_type == "nsfw" and category_id != settings.CATEGORY_NSFW:
                return DecideResult(True, "redirect", "nsfw_redirect", limit)
            return DecideResult(True, "guided", "ticket_guided", limit)
        return DecideResult(True, "short", "default", limit)
