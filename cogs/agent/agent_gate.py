# cogs/agent/agent_gate.py
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from typing import Tuple

import discord
from discord.ext import commands
from openai import OpenAI

from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_MODEL_HEAVY,
    AGENT_DAILY_TOKEN_LIMIT,
    AGENT_ALLOWED_CHANNELS,
    ALLOW_STAFF_FREESPEECH,
    STAFF_ROLE_ID,
    STAFF_EXTRA_ROLE_IDS,
)

log = logging.getLogger("isero.agent")

SYSTEM_BASE = (
    "Te ISERO A vagy, a szerver barátságos segítője. "
    "Válaszolj tömören, érthetően, alapból magyarul (vagy amilyen nyelven a felhasználó ír)."
)


class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # OpenAI kliens – ha az api_key None, akkor környezeti változóból olvassa.
        self.client = OpenAI(api_key=OPENAI_API_KEY or None)

        # Modellek
        self.model_default: str = OPENAI_MODEL or "gpt-4o-mini"
        self.model_heavy: str = OPENAI_MODEL_HEAVY or self.model_default

        # Napi token limit (durva sapka, a tényleges használat API usage-ből)
        self.limit_per_day: int = AGENT_DAILY_TOKEN_LIMIT

        # Opcionális csatorna-szűrő
        self.allowed_channels = set(AGENT_ALLOWED_CHANNELS or [])

        # Napi számláló
        self._used_today = 0
        self._day = dt.date.today()

        log.info(
            "[AgentGate] ready. Model=%s, Limit/24h=%s tokens",
            self.model_default,
            self.limit_per_day,
        )

    # ---------- belső utilok ----------

    def _rollover_if_new_day(self) -> None:
        today = dt.date.today()
        if today != self._day:
            self._day = today
            self._used_today = 0

    def _estimate_tokens(self, text: str) -> int:
        # gyors, óvatos becslés: ~4 karakter / token
        return max(1, int(len(text) / 4) + 3)

    def _may_speak_in(self, channel: discord.abc.GuildChannel) -> bool:
        # ha nincs megadva lista -> mindenhol válaszolhat
        if not self.allowed_channels:
            return True
        return channel.id in self.allowed_channels

    def _should_trigger(self, message: discord.Message) -> bool:
        # mention esetén mindig
        if self.bot.user and self.bot.user in message.mentions:
            return True
        # "isero" vagy "isero a" prefixek – case-insensitive
        lower = message.content.lower().strip()
        return lower.startswith("isero") or lower.startswith("isero a")

    def _pick_model(self, content: str) -> str:
        # felülbírálás: !!heavy flag
        if re.search(r"\b!!heavy\b", content, flags=re.I):
            return self.model_heavy
        # nagyobb/technikaibb üzenetekre "heavy"
        if "```" in content or len(content) > 600:
            return self.model_heavy
        return self.model_default

    async def _chat(self, content: str, *, author: discord.Member | None) -> Tuple[str, int]:
        """OpenAI hívás – (reply, used_tokens) visszaadása."""
        model = self._pick_model(content)

        messages = [
            {"role": "system", "content": SYSTEM_BASE},
            {"role": "user", "content": content},
        ]

        # A Python OpenAI kliens szinkron; ezért a hívást threadbe tesszük.
        resp = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=model,
            messages=messages,
            max_tokens=400,
            temperature=0.7,
        )

        reply = resp.choices[0].message.content or ""
        used = (
            resp.usage.total_tokens
            if getattr(resp, "usage", None)
            else self._estimate_tokens(content) + self._estimate_tokens(reply)
        )
        return reply, int(used)

    # ---------- eseményfigyelő ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # botokat, DM-et hagyjuk
        if message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return

        # csatorna-szűrés
        if not self._may_speak_in(message.channel):
            return

        # csak akkor indulunk, ha mention vagy "isero..." prefix
        if not self._should_trigger(message):
            return

        # stáb kedvezmény a limitre
        is_staff = False
        if isinstance(message.author, discord.Member):
            staff_ids = {rid for rid in [STAFF_ROLE_ID, *(STAFF_EXTRA_ROLE_IDS or [])] if rid}
            is_staff = any(r.id in staff_ids for r in message.author.roles)

        self._rollover_if_new_day()

        if self._used_today >= self.limit_per_day and not (ALLOW_STAFF_FREESPEECH and is_staff):
            await message.reply("A napi AI keret betelt. Próbáld meg holnap, vagy kérj stáb engedélyt. 🙏")
            return

        try:
            reply, used = await self._chat(message.content, author=message.author)
        except Exception:
            log.exception("Exception in AgentGate._chat")
            await message.reply("Hopp, most valami félresikerült az AI hívásnál. Próbáld újra kicsit később.")
            return

        self._used_today += used
        try:
            await message.reply(reply[:2000], mention_author=False)
        except discord.HTTPException:
            # fallback, ha a reply nem sikerül
            await message.channel.send(reply[:2000])


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
