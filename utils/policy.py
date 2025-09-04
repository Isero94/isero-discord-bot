from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Dict

import discord

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

    @staticmethod
    def is_talk_channel(ctx: MessageContext) -> bool:
        """Return True if channel is considered a talk/general channel."""
        talk_channels = {
            settings.CHANNEL_GENERAL_CHAT,
            settings.CHANNEL_BOT_COMMANDS,
            settings.CHANNEL_SUGGESTIONS,
        }
        talk_categories = {
            settings.CATEGORY_GAMING,
            settings.CATEGORY_ART,
            settings.CATEGORY_SOCIAL,
        }
        return ctx.channel_id in talk_channels or (
            ctx.category_id in talk_categories if ctx.category_id is not None else False
        )

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

        talk = cls.is_talk_channel(ctx)
        if cid == settings.CHANNEL_TICKET_HUB and trigger == "free_text":
            return DecideResult(False, "silent", "ticket_hub_free_text", limit)
        if cid in silence_redirect:
            return DecideResult(True, "redirect", "noise_channel", limit)

        content = getattr(ctx, "content", "")
        if talk:
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
            # region ISERO PATCH FEATURE_FLAGS_ENFORCE
            if ticket_type == "mebinu" and not settings.FEATURES_MEBINU_DIALOG_V1:
                return DecideResult(True, "short", "ticket_legacy", limit)
            # endregion ISERO PATCH FEATURE_FLAGS_ENFORCE
            if ticket_type == "nsfw" and category_id != settings.CATEGORY_NSFW:
                return DecideResult(True, "redirect", "nsfw_redirect", limit)
        return DecideResult(True, "guided", "ticket_guided", limit)
        return DecideResult(True, "short", "default", limit)


# region ISERO PATCH feature_helpers
def getbool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in {"1", "true", "yes", "on"}

def getint(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default


def getstr(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def getenv(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def feature_on(name: str) -> bool:
    key = f"FEATURES_{name.upper()}"
    return getbool(key, False)

# region ISERO PATCH profanity_helpers
def is_exempt_user(user) -> bool:
    ids = os.getenv("PROFANITY_EXEMPT_USER_IDS", "")
    idset = {int(x.strip()) for x in ids.split(",") if x.strip().isdigit()}
    return int(getattr(user, "id", 0)) in idset

def is_nsfw(channel) -> bool:
    nsfw_ids = os.getenv("NSFW_CHANNELS", "")
    idset = {int(x.strip()) for x in nsfw_ids.split(",") if x.strip().isdigit()}
    return getattr(channel, "id", 0) in idset or getattr(channel, "is_nsfw", lambda: False)()
# endregion ISERO PATCH profanity_helpers
# endregion ISERO PATCH feature_helpers

# region ISERO PATCH profanity_timeouts
def profanity_thresholds():
    lvl1 = getint("PROFANITY_LVL1_THRESHOLD", default=5)
    lvl2 = getint("PROFANITY_LVL2_THRESHOLD", default=8)
    lvl3 = getint("PROFANITY_LVL3_THRESHOLD", default=11)
    return lvl1, lvl2, lvl3


def profanity_free_per_message():
    return getint("PROFANITY_FREE_WORDS_PER_MSG", default=2)


def profanity_timeouts_minutes():
    t1 = getint("PROFANITY_TIMEOUT_MIN_LVL1", default=40)
    t2 = getint("PROFANITY_TIMEOUT_MIN_LVL2", default=480)  # 8 óra
    t3 = getint("PROFANITY_TIMEOUT_MIN_LVL3", default=0)    # 0 = feloldásig
    return t1, t2, t3
# endregion ISERO PATCH profanity_timeouts
