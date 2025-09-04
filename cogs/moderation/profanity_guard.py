# cogs/moderation/profanity_guard.py
from __future__ import annotations
import os
import re
import datetime as dt
from typing import List

import discord
from discord.ext import commands

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default

FREE_PER_MSG = _env_int("PROFANITY_FREE_WORDS_PER_MSG", 2)
LVL1 = _env_int("PROFANITY_LVL1_THRESHOLD", 5)
LVL2 = _env_int("PROFANITY_LVL2_THRESHOLD", 8)
LVL3 = _env_int("PROFANITY_LVL3_THRESHOLD", 11)
TO_MIN_L2 = _env_int("PROFANITY_TIMEOUT_MIN_LVL2", 40)
TO_MIN_L3 = _env_int("PROFANITY_TIMEOUT_MIN_LVL3", 0)  # 0 = manuális “indefinite”
USE_WEBHOOK_MIMIC = os.getenv("USE_WEBHOOK_MIMIC", "true").lower() == "true"

MOD_LOG_CH = int(os.getenv("CHANNEL_MOD_LOGS", "0"))

WORDS = [w.strip() for w in os.getenv("PROFANITY_WORDS", "").split(",") if w.strip()]
RE_WORDS = re.compile(r"(?i)\b(?:%s)\b" % "|".join(re.escape(w) for w in WORDS)) if WORDS else None

def _mask_word(w: str) -> str:
    if len(w) <= 2:
        return "*" * len(w)
    return w[0] + "*" * (len(w) - 2) + w[-1]

def _star_text(txt: str) -> str:
    if not RE_WORDS:
        return txt
    def repl(m: re.Match) -> str:
        return _mask_word(m.group(0))
    return RE_WORDS.sub(repl, txt)

class ProfanityGuard(commands.Cog):
    """Csillagozás + küszöbözött némítás + logolás."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # region ISERO PATCH guard_passthrough_when_v2
        from utils import policy as _policy
        self.disabled_by_feature = _policy.getbool("FEATURES_PROFANITY_V2", default=False) or _policy.feature_on("profanity_v2")
        # endregion ISERO PATCH guard_passthrough_when_v2
        # user_id -> rolling excess counter (egyszerű, memóriás)
        self._excess = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not RE_WORDS:
            return
        # region ISERO PATCH guard_passthrough_when_v2
        if getattr(self, "disabled_by_feature", False):
            return
        # endregion ISERO PATCH guard_passthrough_when_v2
        if not message.guild or message.author.bot:
            return

        # számolás
        found = RE_WORDS.findall(message.content)
        if not found:
            return

        excess = max(0, len(found) - FREE_PER_MSG)

        # törlés + repost csillagozva (ha engedve)
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        masked = _star_text(message.content)

        if USE_WEBHOOK_MIMIC:
            try:
                wh = await self._get_or_create_webhook(message.channel)
                await wh.send(
                    content=masked,
                    username=message.author.display_name,
                    avatar_url=message.author.display_avatar.url if message.author.display_avatar else discord.Embed.Empty,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception:
                await message.channel.send(masked, allowed_mentions=discord.AllowedMentions.none())
        else:
            await message.channel.send(masked, allowed_mentions=discord.AllowedMentions.none())

        # counter frissítés
        if excess:
            self._excess[message.author.id] = self._excess.get(message.author.id, 0) + excess

        # szintkezelés
        total = self._excess.get(message.author.id, 0)
        action = None
        if total >= LVL3:
            action = "L3"
        elif total >= LVL2:
            action = "L2"
        elif total >= LVL1:
            action = "L1"

        if action:
            await self._apply_action(message, action, total)

        # log
        if MOD_LOG_CH:
            await self._log(message, masked, found, excess, total, action)

    async def _apply_action(self, message: discord.Message, action: str, total: int):
        member = message.author
        if not isinstance(member, discord.Member):
            try:
                member = await message.guild.fetch_member(member.id)
            except Exception:
                return

        if action == "L1":
            await message.channel.send(f"{member.mention} Figyi, ezt most csillagoztam. Tartsuk kulturáltan. (számláló: {total})",
                                       allowed_mentions=discord.AllowedMentions.none())
        elif action == "L2":
            if TO_MIN_L2 > 0:
                until = dt.datetime.utcnow() + dt.timedelta(minutes=TO_MIN_L2)
                try:
                    await member.timeout(until, reason="Profanity L2")
                    await message.channel.send(f"{member.mention} 40 perces timeout. (számláló: {total})",
                                               allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    pass
        elif action == "L3":
            if TO_MIN_L3 > 0:
                until = dt.datetime.utcnow() + dt.timedelta(minutes=TO_MIN_L3)
                try:
                    await member.timeout(until, reason="Profanity L3")
                    await message.channel.send(f"{member.mention} Timeout alkalmazva. (számláló: {total})",
                                               allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    pass
            else:
                # manuális intézkedés – ping modoknak
                if MOD_LOG_CH:
                    ch = message.guild.get_channel(MOD_LOG_CH)
                    if ch:
                        await ch.send(f"[L3] Manuális intézkedés szükséges {member.mention} ügyében. (számláló: {total})")

    async def _log(self, message: discord.Message, masked: str, found: List[str], excess: int, total: int, action: str | None):
        ch = message.guild.get_channel(MOD_LOG_CH)
        if not ch:
            return
        em = discord.Embed(title="Profanity event", color=discord.Color.orange())
        em.add_field(name="User", value=f"{message.author} ({message.author.id})", inline=False)
        em.add_field(name="Channel", value=f"{message.channel.mention}", inline=False)
        em.add_field(name="Found", value=f"{len(found)} (excess {excess}, total {total})", inline=True)
        if action:
            em.add_field(name="Action", value=action, inline=True)
        em.add_field(name="Original (masked)", value=masked[:1024], inline=False)
        em.timestamp = dt.datetime.utcnow()
        try:
            await ch.send(embed=em)
        except Exception:
            pass

    async def _get_or_create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        hooks = await channel.webhooks()
        for h in hooks:
            if h.name == "ISERO-mask":
                return h
        return await channel.create_webhook(name="ISERO-mask")

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
