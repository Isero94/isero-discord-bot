# cogs/tickets/tickets.py
from __future__ import annotations

import os
import re
import logging
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ===== Env / config ==========================================================
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))
TICKETS_CATEGORY_ID = int(os.getenv("TICKETS_CATEGORY_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Angol szövegek
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
    "mebinu":   "Welcome! This private thread is for **Mebinu** (collectibles). Please describe your request.",
    "commission": "Welcome! This private thread is for **Commission** work. Please share scope, budget, deadline.",
    "nsfw":     "Welcome! This private thread is for **NSFW (18+)** topics. Follow the server rules strictly.",
    "general":  "Welcome! This private thread is for **General Help**. Tell us what you need.",
}

TICKET_NAME_PREFIX = {
    "mebinu": "mebinu",
    "commission": "commission",
    "nsfw": "nsfw",
    "general": "general",
}

# Topic-tag, ami alapján deep cleanup megtalálja a csatornákat
def make_ticket_topic(user_id: int, kind: str) -> str:
    return f"[ticket] owner={user_id} kind={kind}"

# Egyszerű névminta fallback régi csatornákhoz (ha még nincs topic-tag)
NAME_PATTERN = re.compile(r"^(mebinu|commission|nsfw|general)[-_].+", re.IGNORECASE)


# ===== UI Views ==============================================================
class OpenTicketView(discord.ui.View):
    """A hubba kitett gomb – tartós (persistent) view."""

    def __init__(self, cog: "Tickets", *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="tickets:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Kategória választó ephemeral view
        await interacti
