# cogs/tickets/tickets.py
from __future__ import annotations

import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands
from .forms import OpenTicketView, TicketsCog, hub_header_embed

# OWNER ID betöltése
try:
    # preferált: config.py
    from config import OWNER_ID as CONFIG_OWNER_ID  # type: ignore
    OWNER_ID = int(CONFIG_OWNER_ID)
except Exception:
    # fallback ENV-re
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))

HUB_TITLE = "ISERO Ticket Hub"

class Tickets(TicketsCog):
    """Ticket rendszer: Hub setup, cleanup, és interakciók."""
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

    # Perzisztens view regisztrálása induláskor (hogy újraindítás után is éljen a gomb)
    async def cog_load(self):
        self.bot.add_view(OpenTicketView(self))

    # --- Parancsok ---

    @app_commands.command(name="ticket_hub_setup", description="Set up the ISERO Ticket Hub here (owner only).")
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Run this inside a **text channel**.", ephemeral=True)
            return

        # Hub-üzenet küldése 1 db „Open Ticket” gombbal
        await interaction.response.send_message("Setting up hub...", ephemeral=True)
        view = OpenTicketView(self)
        msg = await interaction.channel.send(embed=hub_header_embed(), view=view)

        # opcionális: pin
        try:
            await msg.pin(reason="ISERO Ticket Hub")
        except discord.Forbidden:
            pass

        await interaction.followup.send("Ticket Hub is ready here.", ephemeral=True)

    @app_commands.command(name="ticket_hub_cleanup", description="Clean up bot hub messages in this channel (owner only).")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Run this inside a **text channel**.", ephemeral=True)
            return

        await interaction.response.send_message("Cleaning up bot messages in this hub…", ephemeral=True)

        deleted = 0
        async for m in channel.history(limit=500):
            if m.pinned:
                continue
            if m.author.id == self.bot.user.id:
                try:
                    await m.delete()
                    deleted += 1
                    await asyncio.sleep(0.35)  # rate-limit barát
                except discord.HTTPException:
                    await asyncio.sleep(1.0)

        await interaction.followup.send(f"Cleanup done. Removed **{deleted}** bot message(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
