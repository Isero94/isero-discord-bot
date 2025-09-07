import discord
from discord.ext import commands

class MebinuFlow(commands.Cog):
    """Minimal Mebinu ticket flow – only welcome and legacy sweeper."""

    def __init__(self, bot):
        self.bot = bot
        self._legacy_markers = [
            "Melyik termék vagy téma?",
            "Mennyiség, ritkaság, színvilág?",
            "Határidő",
            "Keret (HUF/EUR)?",
            "Van 1-4 referencia",
            "max 800 karakter",
        ]

    async def start_flow(self, channel: discord.TextChannel, opener: discord.Member):
        tickets = self.bot.get_cog("Tickets")
        if tickets and hasattr(tickets, "post_welcome_and_sla"):
            await tickets.post_welcome_and_sla(channel, "mebinu", opener)
        await self._sweep_legacy(channel)

    async def _sweep_legacy(self, channel: discord.TextChannel):
        try:
            async for m in channel.history(limit=25):
                if m.author.bot and any(k in (m.content or "") for k in self._legacy_markers):
                    try:
                        await m.delete()
                    except Exception:
                        pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.author.bot:
            return
        if any(k in (message.content or "") for k in self._legacy_markers):
            try:
                await message.delete()
            except Exception:
                pass
