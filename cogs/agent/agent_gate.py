# cogs/agent/agent_gate.py
import asyncio
import math
from datetime import datetime, timezone
from typing import Optional, Tuple

import discord
from discord.ext import commands
from openai import OpenAI

from config import (
    OPENAI_API_KEY, OPENAI_MODEL_BASE, OPENAI_MODEL_HEAVY, OPENAI_DAILY_TOKENS,
    AGENT_REPLY_COOLDOWN, AGENT_ALLOWED_CHANNELS, FIRST10_USER_IDS,
    GUILD_ID, OWNER_ID
)
from storage.playercard import PlayerCardStore, PlayerCard
from cogs.utils.throttling import Throttle
from cogs.agent.policy import build_system_prompt

def _estimate_tokens(text: str) -> int:
    # fallback, kb. 4 char/token
    return max(1, math.ceil(len(text) / 4))

class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
        self._throttle = Throttle()
        self._global_tokens_today = 0
        self._guild_name_cache: Optional[str] = None

    async def cog_load(self):
        # attach store a bot-ra, hogy a watcherek is megtalálják
        self.bot.pc_store = PlayerCardStore

    # -------- belső döntés ----------
    def _allowed_channel(self, ch: discord.abc.GuildChannel) -> bool:
        if not AGENT_ALLOWED_CHANNELS:
            return True
        return getattr(ch, "id", None) in AGENT_ALLOWED_CHANNELS

    def _is_ticket(self, ch: discord.abc.GuildChannel) -> bool:
        n = (getattr(ch, "name", "") or "").lower()
        return n.endswith("-tiq") or "ticket" in n

    def _should_reply(self, message: discord.Message) -> bool:
        if message.author.bot or not message.guild:
            return False
        if not self._allowed_channel(message.channel):
            return False
        me = message.guild.me
        if me and message.mentions and me in message.mentions:
            return True
        if self._is_ticket(message.channel):
            return True
        return False

    def _choose_model(self, card: PlayerCard) -> Tuple[str, int]:
        # default
        model = OPENAI_MODEL_BASE
        max_tokens = 300

        # owner vagy high marketing: próbálj heavy-t, ha van keret
        if (card.flags.get("owner") or card.marketing_score >= 60) and self._global_tokens_today < int(OPENAI_DAILY_TOKENS * 0.7):
            model = OPENAI_MODEL_HEAVY
            max_tokens = 420

        # ha nagyon fogy a keret, kurtíts
        if self._global_tokens_today > int(OPENAI_DAILY_TOKENS * 0.9):
            max_tokens = 150
            model = OPENAI_MODEL_BASE
        return model, max_tokens

    # -------- OpenAI hívás ----------
    async def _ask(self, card: PlayerCard, message: discord.Message) -> Optional[str]:
        in_ticket = self._is_ticket(message.channel)
        sys = build_system_prompt(card, in_ticket, self._guild_name_cache)
        user = message.content.strip()

        model, max_tokens = self._choose_model(card)

        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role":"system","content": sys},
                {"role":"user","content": user}
            ],
            temperature=0.6,
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        # token számítás
        used = 0
        try:
            used = int(resp.usage.total_tokens)  # type: ignore[attr-defined]
        except Exception:
            used = _estimate_tokens(user) + _estimate_tokens(text)

        self._global_tokens_today += used
        await PlayerCardStore.bump_tokens(message.author.id, used)
        return text

    # -------- események ----------
    @commands.Cog.listener()
    async def on_ready(self):
        try:
            if GUILD_ID:
                g = self.bot.get_guild(GUILD_ID)
                if g:
                    self._guild_name_cache = g.name
        except Exception:
            pass
        self.bot.logger.info("[AgentGate] ready. Model=%s, Limit/24h=%s tokens", OPENAI_MODEL_BASE, OPENAI_DAILY_TOKENS)  # type: ignore

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self._should_reply(message):
            return

        # cooldown per-user
        key = f"agent:{message.author.id}"
        left = self._throttle.remaining(key, AGENT_REPLY_COOLDOWN)
        if left > 0:
            # udvarias jelzés ticketben
            if self._is_ticket(message.channel):
                try:
                    await message.channel.send(f"Please wait **{left}s** before I answer again.", delete_after=5)
                except Exception:
                    pass
            return
        self._throttle.allow(key, AGENT_REPLY_COOLDOWN)

        # napi globális limit
        if self._global_tokens_today >= OPENAI_DAILY_TOKENS:
            try:
                await message.channel.send("Daily AI budget is used up. I’ll be back after reset. ⏳")
            except Exception:
                pass
            return

        # player card betöltése
        card = await PlayerCardStore.get_card(message.author.id)

        # owner / first10 jelzés
        if message.author.id == OWNER_ID:
            card.flags["owner"] = True
        if message.author.id in FIRST10_USER_IDS:
            card.first10 = True

        # hívás
        try:
            reply = await self._ask(card, message)
        except Exception as e:
            try:
                await message.channel.send("Agent error while thinking. Please try again. 🧯")
            except Exception:
                pass
            self.bot.logger.exception("Agent error: %s", e)  # type: ignore
            return

        if not reply:
            return

        try:
            await message.channel.send(reply)
        except discord.Forbidden:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
