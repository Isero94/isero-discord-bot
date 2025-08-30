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
        if not ag or not getattr(ag, "db", None):
            return
        db = ag.db  # type: ignore

        text = message.content.strip()
        # engagement: hossz + formázás
        engagement = min(max(len(text) // 50, 0), 5)
        if "\n" in text:
            engagement += 1
        # mood: +- kulcsszavak
        low = text.lower()
        pos = sum(w in low for w in POS_WORDS)
        neg = sum(w in low for w in NEG_WORDS)
        mood = max(min(pos - neg, 5), -5)
        # promo: link/discord meghívó
        promo = 1 if ("http://" in low or "https://" in low or "discord.gg/" in low) else 0
        total = max(0, engagement + max(mood,0) + promo)

        try:
            await db.upsert_user(message.author.id, f"{message.author.name}#{message.author.discriminator}")  # type: ignore
            await db.add_score(message.author.id, engagement, mood, promo, total)
        except Exception as e:
            log.debug("score write failed: %s", e)

async def setup(bot: commands.Bot):
    await bot.add_cog(LangWatch(bot))
