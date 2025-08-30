# cogs/tickets/tickets.py
from __future__ import annotations

import os
import re
import logging
from typing import Optional, Literal, Callable

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ===== Env / config ==========================================================
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))  # nem kötelező
TICKETS_CATEGORY_ID = int(os.getenv("TICKETS_CATEGORY_ID", "0"))  # új! nem kötelező
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Angol UI
PANEL_TITLE = "Ticket Hub"
PANEL_DESCRIPTION = (
    "Press **Open Ticket** to start. In the next step you'll choose a category.\n\n"
    "Click the button. Category selection comes next."
)
CATEGORIES_HELP = (
    "**Choose a category:**\n"
    "• **Mebinu** — Collectible figures: requests, variants, codes, rarity.\n"
    "• **Commission** — Paid custom art: scope, budget, deadline.\n"
    "• **NSFW 18+** — Adults only; stricter rules & review.\n"
    "• **General Help** — Quick Q&A and guidance."
)
WELCOME_TEXT = {
    "mebinu":     "Welcome! This private thread is for **Mebinu** (collectibles). Please describe your request.",
    "commission": "Welcome! This private thread is for **Commission** work. Please share scope, budget, deadline.",
    "nsfw":       "Welcome! This private thread is for **NSFW (18+)** topics. Follow the server rules strictly.",
    "general":    "Welcome! This private thread is for **General Help**. Tell us what you need.",
}
TICKET_NAME_PREFIX = {"mebinu": "mebinu", "commission": "commission", "nsfw": "nsfw", "general": "general"}

def make_ticket_topic(user_id: int, kind: str) -> str:
    return f"[ticket] owner={user_id} kind={kind}"

NAME_PATTERN = re.compile(r"^(mebinu|commission|nsfw|general)[-_].+", re.IGNORECASE)

def _guilds_opt() -> Callable:
    # ha meg van adva GUILD_ID, a parancsok guild-hoz kötve mennek (gyorsabb sync)
    return app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)


# ===== UI Views ==============================================================
class OpenTicketView(discord.ui.View):
    def __init__(self, cog: "Tickets", *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="tickets:open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(CATEGORIES_HELP, view=CategorySelectView(self.cog), ephemeral=True)


class CategorySelectView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:mebinu")
    async def mebinu(self, i: discord.Interaction, _): await self.cog.create_ticket(i, kind="mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:commission")
    async def commission(self, i: discord.Interaction, _): await self.cog.create_ticket(i, kind="commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="tickets:cat:nsfw")
    async def nsfw(self, i: discord.Interaction, _):
        await i.response.send_message("Are you 18 or older?", view=NSFWConfirmView(self.cog), ephemeral=True)

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="tickets:cat:general")
    async def general(self, i: discord.Interaction, _): await self.cog.create_ticket(i, kind="general")


class NSFWConfirmView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="tickets:nsfw:yes")
    async def yes(self, i: discord.Interaction, _): await self.cog.create_ticket(i, kind="nsfw")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="tickets:nsfw:no")
    async def no(self, i: discord.Interaction, _): await i.response.send_message("Understood. NSFW ticket cancelled.", ephemeral=True)


class TicketOwnerControls(discord.ui.View):
    def __init__(self, cog: "Tickets", channel_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.channel_id = channel_id

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="tickets:close")
    async def close_ticket(self, interaction: discord.Interaction, _):
        ch = interaction.client.get_channel(self.channel_id)
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message("Channel not found.", ephemeral=True)
            return

        opener_id = None
        if ch.topic and "owner=" in ch.topic:
            try: opener_id = int(ch.topic.split("owner=")[1].split()[0])
            except Exception: opener_id = None

        if interaction.user.id not in {opener_id, OWNER_ID} and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Only the opener or staff can close this ticket.", ephemeral=True)
