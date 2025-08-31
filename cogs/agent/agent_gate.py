# cogs/agent/agent_gate.py
# ISERO – Agent Gate (mention/wake-word kapu + modellhívás + biztonságos küldés)
# Javítás: 50035 "Unknown message" elkerülése (fail_if_not_exists + fallback send)

from __future__ import annotations

import os
import re
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List

import httpx
import discord
from discord.ext import commands

log = logging.getLogger("bot.agent_gate")


# ----------------------------
# Konfiguráció olvasása (ENV)
# ----------------------------

def _csv_list(val: str | None) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_HEAVY = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")

# Csatorna whitelist – ha üres, **nem** korlátozunk (figyelmeztetéssel),
# hogy tesztelni tudd. Ha szigorú whitelistet szeretnél, töltsd fel CSV-vel.
AGENT_ALLOWED_CHANNELS = _csv_list(os.getenv("AGENT_ALLOWED_CHANNELS", "").strip())
if not AGENT_ALLOWED_CHANNELS:
    log.warning("AGENT_ALLOWED_CHANNELS üres – agent válaszolhat minden csatornában (teszt mód).")

# Wake szavak (mention mellett)
WAKE_WORDS = [w.lower() for w in _csv_list(os.getenv("WAKE_WORDS", "isero,x"))]

# Napi token limit (egyszerű, best-effort becslés) és cooldown
AGENT_DAILY_TOKEN_LIMIT = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000"))
AGENT_REPLY_COOLDOWN_SECONDS = int(os.getenv("AGENT_REPLY_COOLDOWN_SECONDS", "20"))

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Max válasz hossz (Discord 2000 limit alatt maradunk)
MAX_REPLY_CHARS = 1900


# ----------------------------
# Segéd: egyszerű token-becslés
# ----------------------------

def approx_token_count(text: str) -> int:
    # durva becslés (4 char ~ 1 token)
    return max(1, len(text) // 4)


# ----------------------------
# Napi könyvelés (memória)
# ----------------------------

@dataclass
class Budget:
    day_key: str
    spent: int = 0


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
    payload = {"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 500}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions",
                              headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return text.strip()


# ----------------------------
# A Cog
# ----------------------------

class AgentGate(commands.Cog):
    """Mention/Wake kapu, napi keret, cooldown; biztonságos válasz-küldés."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._user_cooldowns: Dict[int, float] = {}
        self._budget = Budget(day_key=self._today_key())

    # -------- utilok --------

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _reset_budget_if_new_day(self):
        today = self._today_key()
        if self._budget.day_key != today:
            self._budget = Budget(day_key=today)

    def _check_and_book_tokens(self, tokens: int) -> bool:
        """Igaz, ha még belefér a napi keretbe és könyveli."""
        self._reset_budget_if_new_day()
        if self._budget.spent + tokens > AGENT_DAILY_TOKEN_LIMIT:
            return False
        self._budget.spent += tokens
        return True

    def _is_allowed_channel(self, channel: discord.abc.GuildChannel | discord.Thread) -> bool:
        """Ha van whitelist, csak ott; ha üres, engedjük (tesztbarát)."""
        if not AGENT_ALLOWED_CHANNELS:
            return True
        try:
            cid = str(channel.id)
        except Exception:
            return False
        return cid in AGENT_ALLOWED_CHANNELS

    def _is_wake(self, message: discord.Message) -> bool:
        # Mention?
        if self.bot.user and self.bot.user.mentioned_in(message):
            return True
        # Wake words?
        content = (message.content or "").lower()
        for w in WAKE_WORDS:
            # szó elején/szóközzel, vagy egyszerű tartalmazás
            if re.search(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", content):
                return True
        return False

    def _cooldown_ok(self, user_id: int) -> bool:
        last = self._user_cooldowns.get(user_id, 0)
        if (time.time() - last) >= AGENT_REPLY_COOLDOWN_SECONDS:
            self._user_cooldowns[user_id] = time.time()
            return True
        return False

    async def _safe_send_reply(self, message: discord.Message, text: str):
        """Biztonságos küldés: reference, de ha 50035, akkor sima send."""
        text = text.strip()
        if len(text) > MAX_REPLY_CHARS:
            text = text[:MAX_REPLY_CHARS] + "…"

        # Próbáljuk meg referenciával – ne bukjon el, ha eltűnt a source.
        ref = message.to_reference(fail_if_not_exists=False)
        try:
            await message.channel.send(
                content=text,
                reference=ref,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            # 50035 – Invalid Form Body / Unknown message → essünk vissza simára
            code = getattr(e, "code", None)
            log.warning("Reply reference bukott (code=%s) – fallback sima send.", code)
            await message.channel.send(
                content=text,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    # -------- események --------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1) Ne reagáljunk botokra / saját magunkra
        if message.author.bot:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return

        # 2) Csatorna whitelist
        if not self._is_allowed_channel(message.channel):
            return

        # 3) Mentions / wake words kapu
        if not self._is_wake(message):
            return

        # 4) Cooldown (owner kivétel)
        if message.author.id != OWNER_ID and not self._cooldown_ok(message.author.id):
            return

        # 5) Prompt készítés
        user_text = (message.content or "").strip()
        # vegyük le a botneveket / wake szavakat a prompt elejéről, hogy tisztább legyen
        lowered = user_text.lower()
        for w in WAKE_WORDS:
            lowered = re.sub(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", " ", lowered)
        if self.bot.user:
            mention = f"<@{self.bot.user.id}>"
            lowered = lowered.replace(mention, " ")
        user_prompt = re.sub(r"\s+", " ", lowered).strip()
        if not user_prompt:
            user_prompt = (message.content or "").strip()

        # 6) Token keret check (durva becslés)
        est = approx_token_count(user_prompt) + 150  # + válaszkeret
        if not self._check_and_book_tokens(est):
            await self._safe_send_reply(message, "Napi AI-keretünk most elfogyott. Próbáld meg később. 🙏")
            return

        # 7) OpenAI hívás
        system_msg = (
            "You are ISERO agent. Be concise (≤300 chars if possible). "
            "Hungarian-friendly tone, casual, helpful. Avoid unsafe content."
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt},
        ]

        model = OPENAI_MODEL
        # Egyszerű szabály: ownernek engedjük a heavy modellt @mention esetén
        if message.author.id == OWNER_ID and self.bot.user and self.bot.user.mentioned_in(message):
            model = OPENAI_MODEL_HEAVY

        try:
            reply_text = await call_openai_chat(messages, model=model)
        except httpx.HTTPError as e:
            log.exception("OpenAI hiba: %s", e)
            await self._safe_send_reply(message, "Most akadozom az AI-nál. Próbáljuk újra kicsit később. 🙇")
            return
        except Exception as e:
            log.exception("Váratlan AI hiba: %s", e)
            await self._safe_send_reply(message, "Valami váratlan történt. Jelentem a staffnak. ⚠️")
            return

        # 8) Biztonságos küldés (50035 fix)
        try:
            await self._safe_send_reply(message, reply_text)
        except Exception as e:
            log.exception("Küldési hiba: %s", e)


# -------- setup (cog regisztráció) --------

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
