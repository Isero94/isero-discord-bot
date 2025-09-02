# cogs/watchers/lang_watch.py
import re
import logging
import discord
from discord.ext import commands

log = logging.getLogger("isero.watch.lang")

POS_WORDS = {"köszi","köszönöm","szuper","jó","remek","thanks","great","awesome","love"}
NEG_WORDS = {"szar","rossz","utálom","idegesítő","baj","gáz","shit","hate","annoying"}

class LangWatch(commands.Cog):
    """Egyszerű pontozó: engagement/mood/promo -> scores táblába."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content:
            return

        ag = self.bot.get_cog("AgentGate")
        db = getattr(ag, "db", None) if ag else None
        if db is None:
            return

        text = message.content.strip()
        low = text.lower()
        pos = sum(w in low for w in POS_WORDS)
        neg = sum(w in low for w in NEG_WORDS)
        mood = max(min(pos - neg, 5), -5) / 5  # -1..1
        try:
            await db.log_signal(
                message.author.id,
                message.channel.id,
                mood,
                "other",
                0,
            )
        except Exception as e:
            log.debug("signal write failed: %s", e)

async def setup(bot: commands.Bot):
    await bot.add_cog(LangWatch(bot))
