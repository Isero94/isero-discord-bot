# cogs/watchers/sentiment_watch.py
import re
import discord
from discord.ext import commands
from storage.playercard import PlayerCardStore

POS = {"köszi","köszönöm","szuper","remek","tetszik","imádom","love","great","awesome","wow"}
NEG = {"szar","fos","utálom","unalmas","idegesítő","borzalom","hate","terrible","shit","fuck"}

WORD = re.compile(r"\w+", re.UNICODE)

class SentimentWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild:
            return
        text = (msg.content or "").lower()
        if not text:
            return

        pos = sum(1 for w in WORD.findall(text) if w in POS)
        neg = sum(1 for w in WORD.findall(text) if w in NEG)
        if pos == 0 and neg == 0:
            return

        val = (pos - neg) / max(1, (pos + neg))
        # gördülő átlag: 0.7 súly a régi értékre
        card = await PlayerCardStore.get_card(msg.author.id)
        card.mood = 0.7*card.mood + 0.3*val
        await PlayerCardStore.upsert_card(card)
        await PlayerCardStore.add_signal(msg.author.id, "sentiment", float(val), {"pos":pos,"neg":neg})

async def setup(bot: commands.Bot):
    await bot.add_cog(SentimentWatch(bot))
