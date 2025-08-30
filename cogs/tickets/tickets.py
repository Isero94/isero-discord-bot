# cogs/tickets/tickets.py
from __future__ import annotations

import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands
from .forms import OpenTicketView, TicketsCog, hub_header_embed

TICKETS_VERSION = "tickets-2025-08-30b"

try:
    from config import OWNER_ID as CONFIG_OWNER_ID  # type: ignore
    OWNER_ID = int(CONFIG_OWNER_ID)
except Exception:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))

HUB_TITLE = "ISERO Ticket Hub"

class Tickets(TicketsCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

    async def cog_load(self):
        print(f"[ISERO] Tickets cog loaded ({TICKETS_VERSION}).")
        self.bot.add_view(OpenTicketView(self))

    @app_commands.command(name="ticket_hub_setup", description="Set up the ISERO Ticket Hub here (owner only).")
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Run this inside a **text channel**.", ephemeral=True)
            return

        await interaction.response.send_message("Setting up hub...", ephemeral=True)
        view = OpenTicketView(self)
        msg = await interaction.channel.send(embed=hub_header_embed(), view=view)

        try:
            await msg.pin(reason="ISERO Ticket Hub")
        except discord.Forbidden:
            pass

        await interaction.followup.send("Ticket Hub is ready here.", ephemeral=True)

    @app_commands.describe(deep="(optional) legacy flag; no functional difference")
    @app_commands.command(name="ticket_hub_cleanup", description="Clean bot hub messages in this channel (owner only).")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: bool = False):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Run this inside a **text channel**.", ephemeral=True)
            return

        await interaction.response.send_message("Cleaning up bot messages in this hub…", ephemeral=True)

        deleted = 0
        async for m in channel.history(limit=1000):
            if m.pinned:
                continue
            if m.author.id == self.bot.user.id:
                try:
                    await m.delete()
                    deleted += 1
                    await asyncio.sleep(0.35)
                except discord.HTTPException:
                    await asyncio.sleep(1.0)

        await interaction.followup.send(f"Cleanup done. Removed **{deleted}** bot message(s).", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
