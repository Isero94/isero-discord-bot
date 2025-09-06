import discord
from discord.ext import commands

class CommissionFlow(commands.Cog):
    """Minimal commission ticket flow."""

    def __init__(self, bot):
        self.bot = bot

    async def start_flow(self, channel: discord.TextChannel, opener: discord.Member):
        tickets = self.bot.get_cog("Tickets")
        if tickets and hasattr(tickets, "post_welcome_and_sla"):
            await tickets.post_welcome_and_sla(channel, "commission", opener)
