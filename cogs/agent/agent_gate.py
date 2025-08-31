# cogs/agent/agent_gate.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from openai import OpenAI

from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_MODEL_HEAVY,          # opcionális, ha később váltani akarsz
    AGENT_DAILY_TOKEN_LIMIT,
    AGENT_ALLOWED_CHANNELS,
    OWNER_ID,
    GUILD_ID,
    OPENAI_DEFAULT_ARGS,
)

log = logging.getLogger("isero.agent")

SYSTEM_PROMPT = (
    "You are ISERO, a helpful, concise Discord assistant. "
    "Answer briefly (2–6 sentences), be friendly, and avoid policy violations. "
    "If the user asks for server rules or ticket help, give actionable steps."
)

def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

class AgentGate(commands.Cog):
    """Kapunyitó az üzenet-szintű AI válaszokhoz (on_message)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # napi token számláló (durva sapka, processz-szintű; restartkor nullázódik)
        self._day = _today_key()
        self._tokens_used = 0

        # OpenAI kliens (az openai==1.x csomag szerint)
        # Ha az OPENAI_API_KEY üres, a lib az ENV-ből is felveszi.
        self.client = OpenAI(api_key=OPENAI_API_KEY or None)

        model = OPENAI_MODEL or "gpt-4o-mini"
        log.info("[AgentGate] ready. Model=%s, Limit/24h=%s tokens", model, AGENT_DAILY_TOKEN_LIMIT)

    # ---- Segédek ----

    def _reset_if_new_day(self) -> None:
        today = _today_key()
        if today != self._day:
            self._day = today
            self._tokens_used = 0
            log.info("[AgentGate] Daily token counter reset.")

    def _within_budget(self) -> bool:
        self._reset_if_new_day()
        return self._tokens_used < AGENT_DAILY_TOKEN_LIMIT

    def _allowed_channel(self, channel_id: int) -> bool:
        if not AGENT_ALLOWED_CHANNELS:
            return True
        return channel_id in AGENT_ALLOWED_CHANNELS

    def _wants_reply(self, message: discord.Message) -> bool:
        # 1) ne reagáljunk saját magunkra vagy botokra
        if message.author.bot:
            return False

        # 2) csatorna-szűrés
        if not self._allowed_channel(message.channel.id):
            return False

        # 3) explicit mention vagy kulcsszavak
        me = message.guild.me if isinstance(message.guild, discord.Guild) else self.bot.user
        mentioned = False
        if me and hasattr(message, "mentions"):
            mentioned = any(m.id == me.id for m in message.mentions)

        if mentioned:
            return True

        txt = (message.content or "").strip().lower()
        if not txt:
            return False

        # egyszerű trigger szavak (teszteléshez)
        triggers = ("hello", "hi isero", "szia isero", "iseró", "isero")
        return any(t in txt for t in triggers)

    async def _chat(self, user_text: str) -> tuple[str, int]:
        """OpenAI hívás. Visszaad (reply_text, total_tokens)."""
        # Alap modell: OPENAI_MODEL; ha később csatorna/role alapján kell másik,
        # itt lehet feltétel szerint OPENAI_MODEL_HEAVY-t használni.
        model = OPENAI_MODEL or "gpt-4o-mini"

        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.6,
            max_tokens=300,   # rövid, de informatív válaszok
        )
        reply = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        total = getattr(usage, "total_tokens", 0) if usage else 0
        return reply.strip(), int(total or 0)

    # ---- Discord esemény ----

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message):
        try:
            # parancs-előfeldolgozás miatt ne zavarjuk a commandokat
            if message.guild is None:
                return

            if not self._wants_reply(message):
                return

            if not self._within_budget():
                log.warning("[AgentGate] Daily token limit reached: %s/%s",
                            self._tokens_used, AGENT_DAILY_TOKEN_LIMIT)
                return

            # egyszerű „gondolkodásjelző”
            async with message.channel.typing():
                reply, used = await asyncio.to_thread(self._chat, message.content)

            # token könyvelés
            self._tokens_used += used or 0
            log.info("[AgentGate] Replied, +%s tokens (day total: %s/%s)",
                     used, self._tokens_used, AGENT_DAILY_TOKEN_LIMIT)

            if reply:
                await message.reply(reply, mention_author=False)

        except Exception:
            log.exception("Exception in AgentGate.on_message")
            # ne dőljön el a bot – csak loggolunk


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
