# cogs/watchers/marketing_watch.py
from __future__ import annotations
import logging
import re
from discord.ext import commands
import discord
from storage.playercard import PlayerCardStore

log = logging.getLogger("watch.marketing")

KW = [
    r"\b(mebinu|mebínó|mabinu)\b",
    r"\bcommission(s)?\b", r"\bcomm\s?\b",
    r"\bár(ak)?\b", r"\bprice(s)?\b", r"\bpay(ment)?\b",
    r"\bvennék|vásároln(ék|i)|buy\b",
    r"\brequest\b", r"\bslot(s)?\b",
]

def _points(text: str) -> int:
    t = text.lower()
    hits = sum(1 for pat in KW if re.search(pat, t))
    if hits == 0: 
        return 0
    # enyhe jel: +2, több találat: +5..+10
    return min(10, 2 + (hits - 1) * 3)

class MarketingWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.content:
            return
        pts = _points(message.content)
        if pts <= 0:
            return
        await PlayerCardStore.ensure_player(message.author.id)
        await PlayerCardStore.bump_marketing(message.author.id, pts)
        await PlayerCardStore.add_signal(message.author.id, "marketing", float(pts), {"len": len(message.content)})
        log.info("marketing +%d for %s", pts, message.author.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(MarketingWatch(bot))
