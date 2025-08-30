# cogs/tickets/tickets.py
from __future__ import annotations

import asyncio
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ================== CONFIG (szövegek angolul) ==================

HUB_TITLE = "Ticket Hub"
HUB_DESC = (
    "Open a ticket with the button below. You'll pick a category in the next step."
)
HUB_BUTTON = "Open Ticket"

CATEGORY_PROMPT_TITLE = "Select a Category"
CATEGORY_PROMPT_DESC = (
    "**Mebinu** — Collectible figure requests, variants, codes, rarity.\n"
    "**Commission** — Paid, custom art requests (scope, budget, deadline).\n"
    "**NSFW 18+** — Strict rules & review (adults only).\n"
    "**General Help** — Quick Q&A and guidance."
)

AGE_CHECK_TITLE = "Age Confirmation"
AGE_CHECK_DESC = "This category is **18+**. Are you 18 or older?"

THREAD_GREETING = (
    "Welcome! This is your private thread for **{category}**.\n"
    "Please describe your request; staff will follow up here."
)

# ================== ENV HELPERS ==================

def env_int(name: str) -> Optional[int]:
    try:
        v = int(os.getenv(name, "0"))
        return v or None
    except Exception:
        return None

def get_guild_id() -> Optional[int]:
    return env_int("GUILD_ID")

def get_hub_channel_id() -> Optional[int]:
    return env_int("TICKET_HUB_CHANNEL_ID")

# ================== PERSISTENT VIEWS ==================

class OpenTicketView(discord.ui.View):
    """Persistent, non-expiring view for the hub card."""
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label=HUB_BUTTON,
        style=discord.ButtonStyle.primary,
        custom_id="hub_open_ticket_btn",
    )
    async def open_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = discord.Embed(
            title=CATEGORY_PROMPT_TITLE,
            description=CATEGORY_PROMPT_DESC,
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=CategoryView(),
            ephemeral=True,
        )

class CategoryView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Mebinu",
        style=discord.ButtonStyle.blurple,
        custom_id="cat_mebinu",
    )
    async def cat_mebinu(self, interaction: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(interaction, "Mebinu")

    @discord.ui.button(
        label="Commission",
        style=discord.ButtonStyle.primary,  # kék, nem szürke
        custom_id="cat_commission",
    )
    async def cat_commission(self, interaction: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(interaction, "Commission")

    @discord.ui.button(
        label="NSFW 18+",
        style=discord.ButtonStyle.danger,
        custom_id="cat_nsfw",
    )
    async def cat_nsfw(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = discord.Embed(
            title=AGE_CHECK_TITLE,
            description=AGE_CHECK_DESC,
            color=discord.Color.red(),
        )
        await interaction.response.send_message(
            embed=embed, view=AgeConfirmView(), ephemeral=True
        )

    @discord.ui.button(
        label="General Help",
        style=discord.ButtonStyle.success,
        custom_id="cat_help",
    )
    async def cat_help(self, interaction: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(interaction, "General Help")

class AgeConfirmView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Yes, I am 18+",
        style=discord.ButtonStyle.danger,
        custom_id="age_yes",
    )
    async def age_yes(self, interaction: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(interaction, "NSFW 18+")

    @discord.ui.button(
        label="No",
        style=discord.ButtonStyle.secondary,
        custom_id="age_no",
    )
    async def age_no(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Understood — please choose another category.", ephemeral=True
        )

# ================== THREAD CREATION ==================

async def create_ticket_thread(interaction: discord.Interaction, category: str):
    """Creates a private thread and adds the user."""
    # parent: current text channel (hub csatorna)
    if isinstance(interaction.channel, discord.TextChannel):
        parent = interaction.channel
    elif isinstance(interaction.channel, discord.Thread) and interaction.channel.parent:
        parent = interaction.channel.parent
    else:
        await interaction.response.send_message(
            "Cannot open a thread here.", ephemeral=True
        )
        return

    thread_name = f"{category} | {interaction.user.display_name}"
    thread = await parent.create_thread(
        name=thread_name,
        type=discord.ChannelType.private_thread,
        invitable=False,
    )
    await thread.add_user(interaction.user)

    await thread.send(
        THREAD_GREETING.format(category=category),
        allowed_mentions=discord.AllowedMentions.none(),
    )

    # biztos visszajelzés a usernek
    await interaction.response.send_message(
        f"Thread opened: {thread.mention}", ephemeral=True
    )

# ================== COG ==================

class Tickets(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Persistent view regisztrálása, hogy újraindítás után is éljen a gomb
        self.bot.add_view(OpenTicketView())

    # ---- HUB SETUP ----
    @app_commands.command(
        name="ticket_hub_setup",
        description="Publish the Ticket Hub card (single 'Open Ticket' button).",
    )
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        hub_channel = await self._resolve_hub_channel(interaction)
        if hub_channel is None:
            return

        embed = discord.Embed(
            title=HUB_TITLE, description=HUB_DESC, color=discord.Color.blurple()
        )
        msg = await hub_channel.send(embed=embed, view=OpenTicketView())

        await interaction.response.send_message(
            f"Hub card published in {hub_channel.mention} (message id: {msg.id}).",
            ephemeral=True,
        )

    # ---- HUB CLEANUP (ha kell) ----
    @app_commands.command(
        name="ticket_hub_cleanup",
        description="Clean the hub: delete bot messages; optionally archive/delete threads.",
    )
    @app_commands.describe(
        deep="If true, also archive/lock existing private threads from this hub."
    )
    async def ticket_hub_cleanup(
        self, interaction: discord.Interaction, deep: Optional[bool] = False
    ):
        hub_channel = await self._resolve_hub_channel(interaction)
        if hub_channel is None:
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        deleted = 0
        async for msg in hub_channel.history(limit=None, oldest_first=False):
            if msg.author == self.bot.user:
                try:
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.35)  # kíméljük a rate limitet
                except discord.HTTPException:
                    pass

        removed_threads = 0
        if deep:
            # Csak a hub parent alatt levő private threadekre
            for th in list(hub_channel.threads):
                try:
                    await th.edit(archived=True, locked=True)
                    removed_threads += 1
                    await asyncio.sleep(0.35)
                except discord.HTTPException:
                    pass

        await interaction.followup.send(
            f"Cleanup done.\n• Deleted messages: **{deleted}**\n"
            f"• Archived/locked threads: **{removed_threads}**{' (deep)' if deep else ''}",
            ephemeral=True,
        )

    # ---- RESET (kényelmi) ----
    @app_commands.command(
        name="ticket_hub_reset",
        description="Cleanup then publish a fresh Ticket Hub card.",
    )
    async def ticket_hub_reset(self, interaction: discord.Interaction):
        await self.ticket_hub_cleanup.callback(self, interaction, False)  # type: ignore
        await self.ticket_hub_setup.callback(self, interaction)  # type: ignore

    # ---- helper ----
    async def _resolve_hub_channel(
        self, interaction: discord.Interaction
    ) -> Optional[discord.TextChannel]:
        # először env-ből
        hub_id = get_hub_channel_id()
        if hub_id:
            ch = interaction.guild.get_channel(hub_id) if interaction.guild else None
            if isinstance(ch, discord.TextChannel):
                return ch

        # fallback: az aktuális csatorna legyen a hub
        if isinstance(interaction.channel, discord.TextChannel):
            return interaction.channel

        await interaction.response.send_message(
            "Hub channel not found. Set TICKET_HUB_CHANNEL_ID or run the command in a text channel.",
            ephemeral=True,
        )
        return None

# ================== EXTENSION ENTRYPOINT ==================

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
