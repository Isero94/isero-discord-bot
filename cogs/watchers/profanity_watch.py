# cogs/watchers/profanity_watch.py
import discord
from discord.ext import commands

from config import ALLOW_STAFF_FREESPEECH, PROFANITY_FREE_WORDS
from storage.playercard import PlayerCardStore
from utils.text import star_profanity

PROFANE = {
    # HU + EN (példa; bővíthető)
    "geci","fasz","picsa","kurva","baszd","bazd","szar","fos",
    "fuck","shit","bitch","asshole","dick","cunt"
}

async def _get_or_create_webhook(ch: discord.TextChannel) -> discord.Webhook:
    hooks = await ch.webhooks()
    for h in hooks:
        if h.name == "ISERO-Proxy":
            return h
    return await ch.create_webhook(name="ISERO-Proxy")

class ProfanityWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not isinstance(msg.channel, discord.TextChannel):
            return
        if ALLOW_STAFF_FREESPEECH and (msg.author.guild_permissions.manage_messages or msg.author.guild_permissions.manage_channels):
            return

        text = (msg.content or "")
        if not text:
            return

        starred, hits = star_profanity(text, PROFANE, free_words=PROFANITY_FREE_WORDS)
        if hits <= PROFANITY_FREE_WORDS:
            # “free” keretben maradt → csak pontozunk
            card = await PlayerCardStore.get_card(msg.author.id)
            card.scores["toxicity"] = card.scores.get("toxicity", 0.0) + max(0, hits - PROFANITY_FREE_WORDS)
            await PlayerCardStore.upsert_card(card)
            return

        # túl sok csúnyaszó -> törlés + webhookos csillagozott visszaküldés
        try:
            await msg.delete()
        except discord.Forbidden:
            return

        try:
            hook = await _get_or_create_webhook(msg.channel)
            await hook.send(
                content=starred,
                username=msg.author.display_name,
                avatar_url=msg.author.display_avatar.url if msg.author.display_avatar else discord.utils.MISSING,
                allowed_mentions=discord.AllowedMentions.none()
            )
        except Exception:
            # ha a webhook sem megy, legalább írjunk vissza
            try:
                await msg.channel.send(starred)
            except Exception:
                pass

        # pontozás
        card = await PlayerCardStore.get_card(msg.author.id)
        over = hits - PROFANITY_FREE_WORDS
        card.profanity["points"] = int(card.profanity.get("points", 0)) + over
        await PlayerCardStore.upsert_card(card)
        await PlayerCardStore.add_signal(msg.author.id, "profanity", float(over), {"hits":hits})

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityWatch(bot))
