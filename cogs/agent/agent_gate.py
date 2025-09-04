# ISERO – Agent Gate (wake + ticket-érzékeny válasz + YAMI-lite persona)
from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import httpx
import discord
from discord.ext import commands
from cogs.utils import context as ctx_flags
from bot.config import settings
from cogs.agent.playerdb import PlayerDB

from cogs.utils.wake import WakeMatcher
from cogs.utils.text import chunk_message, truncate_by_chars
from cogs.utils.throttling import should_redirect
from cogs.utils.context import resolve
from utils.policy import ResponderPolicy

log = logging.getLogger("bot.agent_gate")

# ----------------------------
# ENV helpers
# ----------------------------
def _csv_list(val: str | None) -> List[str]:
    if not val:
        return []
    raw = val.strip().strip('"').strip("'")
    return [x.strip().strip('"').strip("'") for x in raw.split(",") if x.strip()]

def _env_int(name: str, default: int | None = None) -> int | None:
    v = (os.getenv(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default

def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "y", "on"}

OPENAI_API_KEY = (
    os.getenv("OPENAI_API_KEY")
    or os.getenv("OPENAI_APIKEY")
    or os.getenv("OPENAI_KEY")
)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_HEAVY = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")

AGENT_ALLOWED_CHANNELS = _csv_list(os.getenv("AGENT_ALLOWED_CHANNELS", ""))

WAKE = WakeMatcher()
WAKE_WORDS = [w.lower() for w in _csv_list(os.getenv("WAKE_WORDS", ""))]

AGENT_DAILY_TOKEN_LIMIT = _env_int("AGENT_DAILY_TOKEN_LIMIT", 20000) or 20000
AGENT_REPLY_COOLDOWN_SECONDS = _env_int("AGENT_REPLY_COOLDOWN_SECONDS", 20) or 20
AGENT_SESSION_MIN_CHARS = _env_int("AGENT_SESSION_MIN_CHARS", 4) or 4
AGENT_DEDUP_TTL_SECONDS = _env_int("AGENT_DEDUP_TTL_SECONDS", 5) or 5

OWNER_ID = _env_int("OWNER_ID", 0) or 0

MAX_REPLY_CHARS_STRICT = 300
MAX_REPLY_CHARS_LOOSE  = 800
MAX_REPLY_CHARS_DISCORD = 1900

_deprecated_keys_detected = False
if os.getenv("TICKET_HUB_CHANNEL_ID") or os.getenv("CATEGORY_TICKETS"):
    _deprecated_keys_detected = True

TICKET_HUB_CHANNEL_ID = _env_int(
    "CHANNEL_TICKET_HUB", _env_int("TICKET_HUB_CHANNEL_ID", 0)
) or 0
TICKETS_CATEGORY_ID = _env_int(
    "TICKETS_CATEGORY_ID", _env_int("CATEGORY_TICKETS", 0)
) or 0
BOT_COMMANDS_CHANNEL_ID = _env_int("CHANNEL_BOT_COMMANDS", 0) or 0
SUGGESTIONS_CHANNEL_ID = _env_int("CHANNEL_SUGGESTIONS", 0) or 0
ANNOUNCEMENTS_CHANNEL_ID = _env_int("CHANNEL_ANNOUNCEMENTS", 0) or 0
RULES_CHANNEL_ID = _env_int("CHANNEL_RULES", 0) or 0
SERVER_GUIDE_CHANNEL_ID = _env_int("CHANNEL_SERVER_GUIDE", 0) or 0
MOD_LOGS_CHANNEL_ID = _env_int("CHANNEL_MOD_LOGS", 0) or 0
MOD_QUEUE_CHANNEL_ID = _env_int("CHANNEL_MOD_QUEUE", 0) or 0
GENERAL_CHAT_CHANNEL_ID = _env_int("CHANNEL_GENERAL_CHAT", 0) or 0

PROFANITY_WORDS = [w.lower() for w in _csv_list(os.getenv("PROFANITY_WORDS", ""))]
AGENT_MASK_PROFANITY_TO_MODEL = _env_bool("AGENT_MASK_PROFANITY_TO_MODEL", True)

# ----------------------------
# Utils
# ----------------------------
def approx_token_count(text: str) -> int:
    return max(1, len(text) // 4)

def clamp_len(text: str, hard_cap: int = MAX_REPLY_CHARS_DISCORD) -> str:
    t = text.strip()
    if len(t) > hard_cap:
        t = t[:hard_cap].rstrip() + "…"
    return t

def _channel_mention(guild: Optional[discord.Guild], ch_id: int, fallback_name: str) -> str:
    if guild and ch_id:
        ch = guild.get_channel(ch_id)
        if isinstance(ch, discord.abc.GuildChannel):
            return ch.mention
    if guild:
        ch = discord.utils.get(guild.text_channels, name=fallback_name)
        if ch:
            return ch.mention
    return f"#{fallback_name}"

def _mask_profane(text: str) -> str:
    if not PROFANITY_WORDS:
        return text
    t = text
    for w in PROFANITY_WORDS:
        if not w:
            continue
        t = re.sub(rf"(?i)(^|\W){re.escape(w)}(\W|$)", r"\1****\2", t)
    return t

# region ISERO PATCH agent_helpers
def agent_summarize_user_text(text: str, cap: int = MAX_REPLY_CHARS_STRICT) -> str:
    text = text.strip()
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"
# endregion ISERO PATCH agent_helpers

def _ticket_owner_id(ch: discord.abc.GuildChannel | discord.Thread) -> Optional[int]:
    topic = None
    if isinstance(ch, discord.TextChannel):
        topic = ch.topic or ""
    elif isinstance(ch, discord.Thread) and isinstance(ch.parent, discord.TextChannel):
        topic = ch.parent.topic or ""
    m = re.search(r"owner:(\d+)", topic or "")
    return int(m.group(1)) if m else None

_warned_missing_ticket_category = False


def _is_ticket_context(ch: discord.abc.GuildChannel | discord.Thread) -> bool:
    global _warned_missing_ticket_category
    try:
        if TICKET_HUB_CHANNEL_ID and getattr(ch, "id", 0) == TICKET_HUB_CHANNEL_ID:
            return True
        cat_id = None
        cat = None
        if isinstance(ch, discord.Thread) and ch.parent:
            cat_id = getattr(ch.parent, "category_id", 0) or 0
            cat = getattr(ch.parent, "category", None)
        else:
            cat_id = getattr(ch, "category_id", 0) or 0
            cat = getattr(ch, "category", None)
        if TICKETS_CATEGORY_ID:
            if cat_id == TICKETS_CATEGORY_ID:
                return True
        else:
            if cat and getattr(cat, "name", "").lower() == "tickets":
                if not _warned_missing_ticket_category:
                    log.warning("TICKETS_CATEGORY_ID not set; falling back to category name 'tickets'")
                    _warned_missing_ticket_category = True
                return True
    except Exception:
        pass
    return False


def _is_implicit_channel(ch: discord.abc.GuildChannel | discord.Thread) -> bool:
    """Return True if messages in this channel can trigger implicitly."""
    try:
        if BOT_COMMANDS_CHANNEL_ID and getattr(ch, "id", 0) == BOT_COMMANDS_CHANNEL_ID:
            return True
        if SUGGESTIONS_CHANNEL_ID and getattr(ch, "id", 0) == SUGGESTIONS_CHANNEL_ID:
            return True
        if _is_ticket_context(ch):
            return True
        # fallback by name to reduce ENV coupling
        name = getattr(ch, "name", "")
        if name in {"bot-commands", "ticket-hub", "suggestions"}:
            return True
    except Exception:
        pass
    return False


_NOISE_WORDS = {"hello", "hi", "hey", "szia"}


def _is_noise(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t in {"?", "??"}:
        return True
    words = t.split()
    if len(words) <= 2:
        base = re.sub(r"[!?.,]", "", t).lower()
        if base in _NOISE_WORDS:
            return True
    return False

# ----------------------------
# Budget
# ----------------------------
@dataclass
class Budget:
    day_key: str
    spent: int = 0

# ----------------------------
# Player-card
# ----------------------------
def _default_player_card(user_id: int) -> Dict[str, object]:
    return {
        "tone": {"sarcasm": 0.65, "warmth": 0.2, "emoji": True},
        "promo": {"affinity": 0.3},
        "lang": "hu",
        "owner": (user_id == OWNER_ID),
    }

def _load_player_card(user_id: int) -> Dict[str, object]:
    try:
        from cogs.storage.playercard import get_player_card  # opcionális
        pc = get_player_card(user_id) or {}
    except Exception:
        pc = {}
    base = _default_player_card(user_id)
    base.update(pc)
    return base

# ----------------------------
# OpenAI
# ----------------------------
async def call_openai_chat(messages: list[dict], model: str, timeout_s: float = 30.0) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY hiányzik az ENV-ből")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 600}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions",
                              headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return (text or "").strip()

# ----------------------------
# Persona
# ----------------------------
YAMI_PERSONA = """
Te ISERO vagy – domináns, sötét humorú operátor. Száraz szarkazmus, rövid, odavágó mondatok.
Káromkodás visszafogottan. Nem bántalmazol, nem buzdítasz erőszakra. Nem beszélsz a működésedről.
Promó témánál rövid összefoglaló + irány a ticket (ha nem ticketben vagyunk). Máskor lényegre törő válasz.
""".strip()

_AI_LEAK_PATTERNS = [
    r"\b(tudásom.*20\d{2}|képzésem|nyelvi modell|large language model|LLM|GPT|OpenAI)\b",
    r"\b(nem.*internetet.*keresni)\b",
]
_FORBIDDEN_PATTERNS = [
    r"\b(öngyilk|öld meg|vérengz)\b",
    r"\b(gyűlöl|utál.*csoport)\b",
    r"\b(kulcs|api key|token)\b.*(ad|küld|mutat)",
]

def sanitize_model_reply(text: str) -> str:
    t = text
    for pat in _AI_LEAK_PATTERNS + _FORBIDDEN_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            t = re.sub(pat, "—", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return clamp_len(t)

def decide_length_bounds(user_prompt: str, promo_focus: bool) -> Tuple[int, int]:
    long_triggers = ["ár", "mebinu", "commission", "részlet", "opció", "ticket", "spec", "technika", "debug"]
    if promo_focus or any(w in user_prompt.lower() for w in long_triggers) or len(user_prompt) > 200:
        return MAX_REPLY_CHARS_LOOSE, MAX_REPLY_CHARS_DISCORD
    return MAX_REPLY_CHARS_STRICT, MAX_REPLY_CHARS_DISCORD

def build_system_msg(pc: Dict[str, object]) -> str:
    return (
        YAMI_PERSONA
        + f"\nFinomhangolás: sarcasm={pc.get('tone', {}).get('sarcasm', 0.65)}, "
          f"warmth={pc.get('tone', {}).get('warmth', 0.2)}, emoji={pc.get('tone', {}).get('emoji', True)}."
    )

# ----------------------------
# Cog
# ----------------------------
class AgentGate(commands.Cog):
    """Wake + napi keret + cooldown + dedup + ticket-érzékeny linkelés."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._user_cooldowns: Dict[int, float] = {}
        self._budget = Budget(day_key=time.strftime("%Y-%m-%d"))
        self._dedup: Dict[int, tuple[str, float]] = {}   # user_id -> (last_text, ts)
        self._ai_calls: Dict[Tuple[int, int], int] = {}
        self._last_msg: Dict[Tuple[int, int], float] = {}
        # Some legacy cogs (e.g. keyword watcher) still look for `ag.db`.
        # Initialise to `None` so they can `getattr(ag, "db", None)` safely.
        self.db = None
        self.env_status = {
            "bot_commands": BOT_COMMANDS_CHANNEL_ID or "unset",
            "suggestions": SUGGESTIONS_CHANNEL_ID or "unset",
            "tickets_category": TICKETS_CATEGORY_ID or "unset",
            "wake_words_count": len(WAKE_WORDS),
            "deprecated_keys_detected": _deprecated_keys_detected,
        }

    def _reset_budget_if_new_day(self):
        today = time.strftime("%Y-%m-%d")
        if self._budget.day_key != today:
            self._budget = Budget(day_key=today)

    def _check_and_book_tokens(self, tokens: int) -> bool:
        self._reset_budget_if_new_day()
        if self._budget.spent + tokens > AGENT_DAILY_TOKEN_LIMIT:
            return False
        self._budget.spent += tokens
        return True

    def _is_allowed_channel(self, channel: discord.abc.GuildChannel | discord.Thread) -> bool:
        if not AGENT_ALLOWED_CHANNELS:
            return True
        try:
            ids = {str(getattr(channel, "id", ""))}
            if isinstance(channel, discord.Thread) and channel.parent:
                ids.add(str(channel.parent.id))
            return any(cid in AGENT_ALLOWED_CHANNELS for cid in ids)
        except Exception:
            return False

    def _cooldown_ok(self, user_id: int) -> bool:
        last = self._user_cooldowns.get(user_id, 0)
        if (time.time() - last) >= AGENT_REPLY_COOLDOWN_SECONDS:
            self._user_cooldowns[user_id] = time.time()
            return True
        return False

    def _ai_gate(self, message: discord.Message, ctx) -> bool:
        if not settings.FEATURES_AI_GATE_V1:
            return True
        text = (message.content or "").lower()
        heur = False
        if message.author.id == (settings.OWNER_ID or 0) and ResponderPolicy.is_talk_channel(ctx):
            heur = True
        elif "?" in text or any(k in text for k in ["hogyan", "miért", "segíts", "how", "why"]):
            heur = True
        elif ctx.is_ticket:
            heur = True
        elif ctx.was_mentioned or ctx.has_wake_word:
            heur = True
        if not heur:
            return False
        now = time.time()
        hour = int(now // 3600)
        key = (message.author.id, hour)
        if self._ai_calls.get(key, 0) >= settings.AI_MAX_CALLS_PER_USER_HOUR:
            return False
        self._ai_calls[key] = self._ai_calls.get(key, 0) + 1
        dkey = (message.author.id, message.channel.id)
        last = self._last_msg.get(dkey, 0)
        if now - last < (settings.AI_DEBOUNCE_MS / 1000):
            return False
        self._last_msg[dkey] = now
        return True

    def channel_trigger_reason(self, channel: discord.abc.GuildChannel | discord.Thread) -> str:
        """Return trigger reason hint for /diag."""
        return "implicit" if _is_implicit_channel(channel) else "mention"


    def _dedup_ok(self, user_id: int, text: str) -> bool:
        now = time.time()
        last = self._dedup.get(user_id)
        if not last:
            self._dedup[user_id] = (text, now)
            return True
        last_text, ts = last
        if text == last_text and (now - ts) < (AGENT_DEDUP_TTL_SECONDS or 5):
            return False
        self._dedup[user_id] = (text, now)
        return True

    async def _safe_send_reply(self, message: discord.Message, text: str):
        ref = message.to_reference(fail_if_not_exists=False)
        for chunk in chunk_message(clamp_len(text)):
            try:
                await message.channel.send(
                    content=chunk,
                    reference=ref,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                await message.channel.send(
                    content=chunk,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            ref = None

    async def _handle_owner_cmd(self, message: discord.Message, cmd: str) -> None:
        cmd_low = cmd.lower()
        if cmd_low == "sync commands":
            guild = discord.Object(id=settings.GUILD_ID) if settings.GUILD_ID else None
            await self.bot.tree.sync(guild=guild)
            await self._safe_send_reply(message, "commands synced")
            return
        if cmd_low == "quiet here":
            ResponderPolicy.quiet_channel(message.channel.id, ttl=3600)
            await self._safe_send_reply(message, "Muted this channel for 60 minutes.")
            return
        if cmd_low == "unquiet here":
            ResponderPolicy.unquiet_channel(message.channel.id)
            await self._safe_send_reply(message, "Channel unmuted.")
            return
        if cmd_low == "diag here":
            ctx = await resolve(message)
            await self._safe_send_reply(message, f"channel={ctx.channel_name} ticket={ctx.is_ticket}")
            return
        m = re.match(r"summarize last (\d+)", cmd_low)
        if m:
            n = int(m.group(1))
            lines = []
            async for msg in message.channel.history(limit=n):
                lines.append(f"{msg.author.display_name}: {msg.content}")
            await self._safe_send_reply(message, "\n".join(lines))
            return
        await self._safe_send_reply(message, "unknown admin command")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return
        if TICKET_HUB_CHANNEL_ID and message.channel.id == TICKET_HUB_CHANNEL_ID:
            log.info("hub-silence: skipped free-text in #ticket-hub")
            return
        if not self._is_allowed_channel(message.channel):
            return

        raw = (message.content or "").strip()
        if not raw or _is_noise(raw):
            return

        # Moderáció által eltüntetett üzeneteket hagyjuk figyelmen kívül
        if ctx_flags.is_flagged(message):
            return

        if settings.OWNER_NL_ENABLED and raw.startswith(settings.OWNER_ACTIVATION_PREFIX):
            if message.author.id == (settings.OWNER_ID or 0):
                cmd = raw[len(settings.OWNER_ACTIVATION_PREFIX):].strip()
                await self._handle_owner_cmd(message, cmd)
            return

        ctx = await resolve(message)

        ticket_owner = _ticket_owner_id(message.channel)

        if (
            len(raw) < (AGENT_SESSION_MIN_CHARS or 1)
            and not (ticket_owner and message.author.id == ticket_owner)
        ):
            return
        if not self._dedup_ok(message.author.id, raw):
            return

        decision = ResponderPolicy.decide(ctx)
        if not decision.should_reply or decision.mode == "silent":
            return
        if decision.mode == "redirect":
            key = f"redir:{message.channel.id}:{message.author.id}:{decision.reason}"
            if should_redirect(key):
                if BOT_COMMANDS_CHANNEL_ID:
                    dest = _channel_mention(message.guild, BOT_COMMANDS_CHANNEL_ID, "bot-commands")
                    await self._safe_send_reply(message, f"Itt nem válaszolok, gyere ide: {dest}")
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if decision.mode == "guided" and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        if ctx.is_ticket and ctx.ticket_type == "mebinu":
            questions = [
                "Melyik termék vagy téma? (figura/variáns)",
                "Mennyiség, ritkaság, színvilág?",
                "Határidő (nap/dátum)?",
                "Keret (HUF/EUR)?",
                "Van 1–4 referencia kép?",
                "Ha kész a rövid leírás, nyomd meg a Én írom meg gombot (max 800 karakter + 4 kép).",
            ]
            for part in chunk_message("\n".join(questions)):
                await self._safe_send_reply(message, part)
            return

        # ping-pong
        low = raw.lower()

        where_q = re.search(
            r"melyik csatorn|hol vagyunk|which channel|what channel|mi ez a ticket", low
        )
        if where_q:
            if ctx.locale.startswith("hu"):
                reply = (
                    f"Csatorna: {message.channel.mention} (#{ctx.channel_name}), "
                    f"Kategória: {ctx.category_name or 'nincs'}, "
                    f"Ticket: {'igen' if ctx.is_ticket else 'nem'}"
                )
                if ctx.is_ticket:
                    reply += f", Típus: {ctx.ticket_type or 'ismeretlen'}"
            else:
                reply = (
                    f"Channel: {message.channel.mention} (#{ctx.channel_name}), "
                    f"Category: {ctx.category_name or 'none'}, "
                    f"Ticket: {'yes' if ctx.is_ticket else 'no'}"
                )
                if ctx.is_ticket:
                    reply += f", Type: {ctx.ticket_type or 'unknown'}"
            await self._safe_send_reply(message, reply)
            return

        if re.search(r"\bping(el|elsz|elek|etek|etni)?\b", low):
            await self._safe_send_reply(message, "pong")
            return

        mention = self.bot.user and self.bot.user.mentioned_in(message)
        bot_mention = f"<@{self.bot.user.id}>" if self.bot.user else None
        user_prompt = WAKE.strip(raw, bot_mention=bot_mention) or raw
        prompt_for_model = _mask_profane(user_prompt) if AGENT_MASK_PROFANITY_TO_MODEL else user_prompt

        est = approx_token_count(prompt_for_model) + 180
        if not self._check_and_book_tokens(est):
            await self._safe_send_reply(message, "A napi AI-keret most elfogyott. Próbáld később.")
            return

        pc = _load_player_card(message.author.id)
        promo_focus = any(
            k in user_prompt.lower() for k in ["mebinu", "ár", "árak", "commission", "nsfw", "vásárl", "ticket"]
        )
        if ctx.channel_id == GENERAL_CHAT_CHANNEL_ID:
            promo_focus = False

        sys_msg = build_system_msg(pc)
        soft_cap, _ = decide_length_bounds(user_prompt, promo_focus)
        soft_cap = min(soft_cap, decision.char_limit)

        guide = [
            f"Maximális hossz: {soft_cap} karakter. Rövid, feszes mondatok.",
            "Ne beszélj a saját működésedről vagy korlátaidról.",
        ]
        if promo_focus and not ctx.is_ticket:
            ticket_mention = _channel_mention(message.guild, TICKET_HUB_CHANNEL_ID, "ticket-hub")
            guide.append(
                f"Ha MEBINU/ár/commission téma: 1–2 mondat + terelés ide: {ticket_mention}."
            )

        assistant_rules = " ".join(guide)
        if not self._ai_gate(message, ctx):
            return
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "system", "content": assistant_rules},
            {"role": "user", "content": prompt_for_model},
        ]

        model = OPENAI_MODEL_HEAVY if (message.author.id == OWNER_ID and self.bot.user and self.bot.user.mentioned_in(message)) else OPENAI_MODEL

        try:
            reply = await call_openai_chat(messages, model=model)
        except httpx.HTTPError as e:
            log.exception("OpenAI hiba: %s", e)
            await self._safe_send_reply(message, "Most akadozom. Próbáljuk kicsit később.")
            return
        except Exception as e:
            log.exception("Váratlan AI hiba: %s", e)
            await self._safe_send_reply(message, "Váratlan hiba. Jelentem a staffnak.")
            return

        reply = sanitize_model_reply(reply)
        reply = truncate_by_chars(reply, soft_cap)

        try:
            await self._safe_send_reply(message, reply)
        except Exception as e:
            log.exception("Küldési hiba: %s", e)

# ---- setup ----
async def setup(bot: commands.Bot):
    ag = AgentGate(bot)
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        ag.db = PlayerDB(db_url, owner_id=settings.OWNER_ID)
        try:
            await ag.db.start()
        except Exception as e:
            log.warning("PlayerDB init failed: %s", e)
            ag.db = None
    await bot.add_cog(ag)
