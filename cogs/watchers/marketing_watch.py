# cogs/watchers/marketing_watch.py
import re
import discord
from discord.ext import commands
from storage.playercard import PlayerCardStore

KW = {
    "hu": ["megrendelés","ár","mennyi","vásárlás","commission","fizetős","határidő","költség"],
    "en": ["commission","price","how much","buy","deadline","budget","cost"]
}
PAT = re.compile("|".join(re.escape(x) for x in (KW["hu"]+KW["en"])), re.IGNORECASE)

class MarketingWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild:
            return
        text = (msg.content or "")
        if not text:
            return
        hit = len(PAT.findall(text))
        if hit == 0:
            return
        card = await PlayerCardStore.get_card(msg.author.id)
        card.marketing_score = min(100, card.marketing_score + 10*hit)
        card.scores["marketing"] = card.scores.get("marketing", 0.0) + hit
        await PlayerCardStore.upsert_card(card)
        await PlayerCardStore.add_signal(msg.author.id, "marketing", float(hit), {"text_len":len(text)})

async def setup(bot: commands.Bot):
    await bot.add_cog(MarketingWatch(bot))
