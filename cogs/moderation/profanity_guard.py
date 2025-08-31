# cogs/moderation/profanity_guard.py
from __future__ import annotations

import re
import logging
import discord
from discord.ext import commands

log = logging.getLogger("bot.profanity_guard")

PROFANITY = [
    "kurva", "geci", "fasz", "faszkutya", "szarházi", "csicska", "baszdmeg",
    "picsa", "köcsög", "buzi", "szopd", "szopjad", "f@sz"
]

def _star_word(m: re.Match) -> str:
    w = m.group(0)
    return w[0] + "*" * (len(w) - 2) + w[-1] if len(w) > 2 else "*" * len(w)

def _star_text(text: str) -> str:
    if not PROFANITY:
        return text
    pat = r"(?i)\b(" + "|".join(re.escape(w) for w in PROFANITY) + r")\b"
    return re.sub(pat, _star_word, text)

class ProfanityGuard(commands.Cog):
    """Csúnyaszó-őr: törli az eredetit és visszateszi csillagozva, szerző megjelölésével."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        txt = message.content or ""
        if not txt:
            return
        if re.search(r"(?i)\b(" + "|".join(re.escape(w) for w in PROFANITY) + r")\b", txt):
            can_manage = message.channel.permissions_for(message.guild.me).manage_messages if message.guild else False
            starred = _star_text(txt)
            try:
                if can_manage:
                    await message.delete()
                await message.channel.send(
                    content=f"{message.author.mention} mondta: {starred}",
                    allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
                )
                log.info("Profanity csillagozva és visszapostolva a(z) #%s csatornában.", getattr(message.channel, 'name', '?'))
            except Exception as e:
                log.exception("ProfanityGuard hiba: %s", e)

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
