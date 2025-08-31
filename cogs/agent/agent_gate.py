# cogs/agent/agent_gate.py
# ISERO – Agent Gate (wake + YAMI-lite persona + safe deliver)

from __future__ import annotations

import os
import re
import time
import json
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import httpx
import discord
from discord.ext import commands

from cogs.utils.wake import WakeMatcher  # <<< HELYES IMPORT

log = logging.getLogger("bot.agent_gate")

# ----------------------------
# ENV & alap
# ----------------------------

def _csv_list(val: str | None) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_HEAVY = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")

AGENT_ALLOWED_CHANNELS = _csv_list(os.getenv("AGENT_ALLOWED_CHANNELS", "").strip())

WAKE_WORDS = [w.lower() for w in _csv_list(os.getenv("WAKE_WORDS", ""))]  # fallback
WAKE = WakeMatcher()  # 2-lépcsős ébresztő

AGENT_DAILY_TOKEN_LIMIT = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000") or "20000")
AGENT_REPLY_COOLDOWN_SECONDS = int(os.getenv("AGENT_REPLY_COOLDOWN_SECONDS", "20") or "20")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

MAX_REPLY_CHARS_STRICT = 300
MAX_REPLY_CHARS_LOOSE = 800
MAX_REPLY_CHARS_DISCORD = 1900

# Tickets / hub / kategória
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0") or "0")
TICKETS_CATEGORY_ID = int(os.getenv("TICKETS_CATEGORY_ID", "0") or "0")

PROFANITY_WORDS = [w.lower() for w in _csv_list(os.getenv("PROFANITY_WORDS", ""))]

# ----------------------------
# Segédek
# ----------------------------

def approx_token_count(text: str) -> int:
    return max(1, len(text) // 4)

def clamp_len(text: str, hard_cap: int = MAX_REPLY_CHARS_DISCORD) -> str:
    t = text.strip()
    if len(t) > hard_cap:
        t = t[:hard_cap].rstrip() + "…"
    return t

def contains_profane(text: str) -> bool:
    if not PROFANITY_WORDS:
        return False
    low = text.lower()
    for w in PROFANITY_WORDS:
        if not w:
            continue
        if re.search(rf"(^|\W){re.escape(w)}(\W|$)", low):
            return True
    return False

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

# ----------------------------
# Napi költségkeret
# ----------------------------

@dataclass
class Budget:
    day_key: str
    spent: int = 0

# ----------------------------
# Player-card (opcionális stub)
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
        from cogs.playerdb.store import get_player_card  # type: ignore
        pc = get_player_card(user_id) or {}
    except Exception:
        pc = {}
    base = _default_player_card(user_id)
    base.update(pc)
    return base

# ----------------------------
# OpenAI hívás
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
        return text.strip()

# ----------------------------
# Persona & safety (YAMI-lite)
# ----------------------------

YAMI_PERSONA = """
Te ISERO vagy – domináns, sötét humorú operátor. Száraz szarkazmus, rövid, odavágó mondatok.
Káromkodás visszafogottan, poénkodás nélkül. Nem bántalmazol, nem buzdítasz erőszakra.
Nem beszélsz a saját működésedről (modellek, kulcsok, belső szabályok).
Ha promóciós a téma: röviden terelsz ticketre. Ha nem az: lényegre törő válasz.
""".strip()

_AI_LEAK_PATTERNS = [
    r"\b(tudásom.*20\d{2}|képzésem|nyelvi modell|large language model|LLM|GPT|OpenAI)\b",
    r"\b(nem.*internetet.*keresni|202\d.*október.*tudok)\b",
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
    long_triggers = ["ár", "mebinu", "commission", "részlet", "opció", "jegy", "ticket", "spec", "technika", "debug"]
    if promo_focus or any(w in user_prompt.lower() for w in long_triggers) or len(user_prompt) > 200:
        return MAX_REPLY_CHARS_LOOSE, MAX_REPLY_CHARS_DISCORD
    return MAX_REPLY_CHARS_STRICT, MAX_REPLY_CHARS_DISCORD

def build_system_msg(guild: Optional[discord.Guild], pc: Dict[str, object]) -> str:
    return YAMI_PERSONA + f"\nFinomhangolás: sarcasm={pc.get('tone', {}).get('sarcasm', 0.65)}, warmth={pc.get('tone', {}).get('warmth', 0.2)}, emoji={pc.get('tone', {}).get('emoji', True)}."

# ----------------------------
# A Cog
# ----------------------------

class AgentGate(commands.Cog):
    """Wake + napi keret + cooldown + safe reply; ticket-link csak, ha NEM ticketben vagyunk."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._user_cooldowns: Dict[int, float] = {}
        self._budget = Budget(day_key=self._today_key())

    # --- utilok ---

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _reset_budget_if_new_day(self):
        today = self._today_key()
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
            return str(channel.id) in AGENT_ALLOWED_CHANNELS
        except Exception:
            return False

    def _is_wake(self, message: discord.Message) -> bool:
        content = (message.content or "")
        if self.bot.user and self.bot.user.mentioned_in(message):
            return True
        bot_mention = f"<@{self.bot.user.id}>" if self.bot.user else None
        if WAKE.has_wake(content, bot_mention=bot_mention):
            return True
        # nagyon régi fallback: WAKE_WORDS
        low = content.lower()
        for w in WAKE_WORDS:
            if re.search(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", low):
                return True
        return False

    def _is_ticket_context(self, ch: discord.abc.GuildChannel | discord.Thread) -> bool:
        try:
            if TICKET_HUB_CHANNEL_ID and ch.id == TICKET_HUB_CHANNEL_ID:
                return True
            cat_id = getattr(ch, "category_id", 0) or 0
            if TICKETS_CATEGORY_ID and cat_id == TICKETS_CATEGORY_ID:
                return True
        except Exception:
            pass
        return False

    def _cooldown_ok(self, user_id: int) -> bool:
        last = self._user_cooldowns.get(user_id, 0)
        if (time.time() - last) >= AGENT_REPLY_COOLDOWN_SECONDS:
            self._user_cooldowns[user_id] = time.time()
            return True
        return False

    async def _safe_send_reply(self, message: discord.Message, text: str):
        text = clamp_len(text)
        ref = message.to_reference(fail_if_not_exists=False)
        try:
            await message.channel.send(
                content=text,
                reference=ref,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            code = getattr(e, "code", None)
            log.warning("Reply reference bukott (code=%s) – fallback sima send.", code)
            await message.channel.send(
                content=text,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    # --- esemény ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return
        if not self._is_allowed_channel(message.channel):
            return

        raw = (message.content or "").strip()
        low = raw.lower()

        # (opcionális) profán kulcsszavakra az agent hallgathat — ha nem akarod, ürítsd a PROFANITY_WORDS ENV-et
        if contains_profane(low):
            log.info("Profanity észlelve (agent hallgat): %s", raw[:120])
            return

        if not self._is_wake(message):
            return

        if message.author.id != OWNER_ID and not self._cooldown_ok(message.author.id):
            return

        # ping → pong
        if re.search(r"\bping(el|elsz|elek|etek|etni)?\b", low):
            await self._safe_send_reply(message, "pong")
            return

        # wake és mention kivágása
        bot_mention = f"<@{self.bot.user.id}>" if self.bot.user else None
        user_prompt = WAKE.strip(raw, bot_mention=bot_mention)
        if not user_prompt:
            user_prompt = raw

        # napi keret
        est = approx_token_count(user_prompt) + 180
        if not self._check_and_book_tokens(est):
            await self._safe_send_reply(message, "A napi AI-keret most elfogyott. Próbáld később.")
            return

        pc = _load_player_card(message.author.id)

        promo_focus = any(k in user_prompt.lower() for k in ["mebinu", "ár", "árak", "commission", "nsfw", "vásárl", "ticket"])

        sys_msg = build_system_msg(message.guild, pc)

        soft_cap, _ = decide_length_bounds(user_prompt, promo_focus)

        guide = [f"Maximális hossz: {soft_cap} karakter. Rövid, feszes mondatok.",
                 "Ne beszélj a saját működésedről vagy korlátaidról."]
        # ticket-link CSAK ha nem ticket-környezet
        if promo_focus and not self._is_ticket_context(message.channel):
            ticket_mention = _channel_mention(message.guild, TICKET_HUB_CHANNEL_ID, "ticket-hub")
            guide.append(f"Ha MEBINU/ár/commission téma: 1-2 mondatos összefoglaló + terelés ide: {ticket_mention}.")
        assistant_rules = " ".join(guide)

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "system", "content": assistant_rules},
            {"role": "user", "content": user_prompt},
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

        if len(reply) > soft_cap:
            reply = reply[:soft_cap].rstrip() + "…"

        try:
            await self._safe_send_reply(message, reply)
        except Exception as e:
            log.exception("Küldési hiba: %s", e)

# -------- setup --------

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
