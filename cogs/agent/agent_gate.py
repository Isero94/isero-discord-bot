# cogs/agent/agent_gate.py
from __future__ import annotations

import os
import asyncio
from typing import Optional, Tuple

import discord
from discord.ext import commands
from loguru import logger as _logger

# Konfig: a meglévő config modulodból olvasunk.
# (OPENAI_MODEL_HEAVY-t nem kötelező a configban definiálni: ENV-ből is felvesszük.)
from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    AGENT_DAILY_TOKEN_LIMIT,
    AGENT_ALLOWED_CHANNELS,
)

# Loguru tag
logger = _logger.bind(name="isero.agent")

# OpenAI sync kliens (OpenAI 1.x)
from openai import OpenAI


def _coerce_int_list(xs: list[int] | None) -> list[int]:
    return xs if isinstance(xs, list) else []


class AgentGate(commands.Cog):
    """Könnyű kapu a szerveres üzenet -> OpenAI válaszhoz."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Modell kiválasztás: alap + opcionális "heavy" ENV változó
        self.model_base: str = OPENAI_MODEL or "gpt-4o-mini"
        self.model_heavy: str = os.getenv("OPENAI_MODEL_HEAVY", self.model_base)

        # Napi token limit (memóriában számoljuk; újraindításkor reset)
        self.daily_limit: int = int(AGENT_DAILY_TOKEN_LIMIT or 20000)
        self.used_today: int = 0

        # Engedélyezett csatornák (üres lista => minden csatorna oké)
        self.allowed_channels: list[int] = _coerce_int_list(AGENT_ALLOWED_CHANNELS)

        # OpenAI kliens (szinkron)
        self.client = OpenAI(api_key=OPENAI_API_KEY)

        # Trigger-szavak (ha nem mention vagy reply)
        self.triggers = ("isero", "ísero", "íseró")

    async def cog_load(self):
        logger.info(
            f"[AgentGate] ready. Model={self.model_base}, Limit/24h={self.daily_limit} tokens"
        )

    # ---------- Segédek ----------

    def _should_answer(self, message: discord.Message) -> bool:
        """Döntés: válaszoljon-e az Agent erre az üzenetre."""
        if message.author.bot:
            return False
        if not isinstance(message.channel, discord.abc.Messageable):
            return False
        if message.guild is None:
            # DM-ekre itt most nem válaszolunk
            return False

        # Csatorna-szűrés (csak ha meg van adva)
        if self.allowed_channels:
            if message.channel.id not in self.allowed_channels:
                return False

        content = (message.content or "").strip()

        # 1) bot mention
        if self.bot.user and self.bot.user in message.mentions:
            return True

        # 2) reply a bot korábbi üzenetére
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            orig = message.reference.resolved
            if orig.author and orig.author.id == self.bot.user.id:
                return True

        # 3) trigger szóval kezdődik
        lower = content.lower()
        if any(lower.startswith(t) for t in self.triggers):
            return True

        return False

    def _select_model(self, text: str) -> str:
        """
        Egyszerű modellválasztó:
          - ha az üzenetben van 'heavy:' vagy '/heavy', a nagy modellt használja,
          - egyébként a base modellt.
        """
        t = text.lower()
        if "heavy:" in t or t.startswith("/heavy") or t.startswith("isero heavy"):
            return self.model_heavy
        return self.model_base

    def _chat_sync(self, text: str) -> Tuple[str, int]:
        """
        SZINKRON hívás az OpenAI chat completions API-hoz.
        Visszaad: (válasz_szöveg, token_felhasználás).
        """
        model = self._select_model(text)

        # Ha a felhasználó "isero" triggerrel kezdte, vágjuk le a triggert, hogy tisztább legyen a prompt
        clean = text
        for t in self.triggers:
            if clean.lower().startswith(t):
                clean = clean[len(t) :].lstrip(" :,-–")
                break

        # Biztonsági limit
        if self.used_today >= self.daily_limit:
            return "A napi keret kimerült. Próbáld később. 💤", 0

        # Chat hívás
        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ISERO's helpful Discord assistant. "
                        "Answer concisely, be friendly, and avoid unsafe content."
                    ),
                },
                {"role": "user", "content": clean},
            ],
            temperature=0.6,
            max_tokens=500,
        )

        text_out = (resp.choices[0].message.content or "").strip()
        used_tokens = 0
        try:
            # OpenAI 1.x usage objektum
            used_tokens = int(getattr(resp, "usage").total_tokens)  # type: ignore
        except Exception:
            try:
                # Biztonsági fallback
                used_tokens = int(getattr(resp, "usage").get("total_tokens", 0))  # type: ignore
            except Exception:
                used_tokens = 0

        return text_out, used_tokens

    # ---------- Eseménykezelő ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # A saját parancsrendszerünknek teret hagyunk
        if message.author.bot:
            return

        if not self._should_answer(message):
            return

        try:
            # SZINKRON függvényt futtatunk threadben -> nem blokkolja az event loopot
            reply_text, used = await asyncio.to_thread(self._chat_sync, message.content)

            if used > 0:
                self.used_today += used

            if reply_text:
                await message.channel.send(reply_text)

        except Exception:
            logger.exception("Exception in AgentGate.on_message")

    # ---------- Slash parancs: /ask ----------
    @discord.app_commands.command(name="ask", description="Kérdezd az Agentet (opcionálisan heavy modellel).")
    @discord.app_commands.describe(prompt="Mit kérdezel?", heavy="Használjon-e heavy modellt (ha van beállítva).")
    async def ask(self, interaction: discord.Interaction, prompt: str, heavy: Optional[bool] = False):
        try:
            text = f"heavy: {prompt}" if heavy else prompt
            reply_text, used = await asyncio.to_thread(self._chat_sync, text)
            if used > 0:
                self.used_today += used
            await interaction.response.send_message(reply_text or "…", ephemeral=False)
        except Exception:
            logger.exception("Exception in /ask")
            await interaction.response.send_message("Hopp, hiba történt. 😕", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
