# cogs/watchers/sentiment_watch.py
from __future__ import annotations
import logging
import re
from discord.ext import commands
import discord
from storage.playercard import PlayerCardStore

log = logging.getLogger("watch.sentiment")

POS = {"király","nagyon jó","imádom","szupi","szuper","csodás","köszi","köszönöm","tetszik","érdekel"}
NEG = {"utálom","szar","sz@r","fos","dühös","ideges","fáradt","unalmas","nem érdekel","rossz","frusztrált"}

def _score(text: str) -> float:
    t = text.lower()
    pos = sum(1 for w in POS if re.search(rf"\b{re.escape(w)}\b", t))
    neg = sum(1 for w in NEG if re.search(rf"\b{re.escape(w)}\b", t))
    if pos == neg == 0:
        return 0.0
    val = (pos - neg) / max(1, (pos + neg))
    return max(-1.0, min(1.0, val))

class SentimentWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.content:
            return
        s = _score(message.content)
        if s == 0.0:
            return
        await PlayerCardStore.ensure_player(message.author.id)
        await PlayerCardStore.update_mood(message.author.id, s)
        await PlayerCardStore.add_signal(message.author.id, "sentiment", s, {"text_len": len(message.content)})
        log.debug("sentiment %.2f by %s", s, message.author.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(SentimentWatch(bot))
