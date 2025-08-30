# cogs/tickets/tickets.py
from __future__ import annotations

import os
import asyncio
import datetime as dt
import logging
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# --- Env / config ------------------------------------------------------------

GUILD_ID = int(os.getenv("GUILD_ID", "0"))              # e.g. 1409931599629385840
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# --- UI strings (English) ----------------------------------------------------

PANEL_TITLE = "Ticket Hub"
PANEL_DESCRIPTION = (
    "Press **Open Ticket** to start. In the next step you'll choose a category:\n\n"
    "• **Mebinu** — Collectible figures: requests, variants, codes, rarity.\n"
    "• **Commission** — Paid custom art: scope, budget, deadline.\n"
    "• **NSFW 18+** — Adults only; stricter rules and review.\n"
    "• **General Help** — Quick Q&A and guidance.\n"
)

WELCOME_TEXT = {
    "mebinu": "Welcome! This private thread is for Mebinu (collectibles). Please describe your request.",
    "commission": "Welcome! This private thread is for **Commission** work. Please share scope, budget and deadline.",
    "nsfw": "Welcome! This private thread is for **NSFW (18+)** topics. Follow the server rules strictly.",
    "general": "Welcome! This private thread is for **General Help**. Tell us what you need.",
}

THREAD_PREFIX = {
    "mebinu": "MEBINU",
    "commission": "COMMISSION",
    "nsfw": "NSFW",
    "general": "HELP",
}

# --- Views -------------------------------------------------------------------

class OpenTicketView(discord.ui.View):
    """Persistent view for the public hub panel (only 'Open Ticket')."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Open Ticket",
                style=discord.ButtonStyle.primary,
                custom_id="tickets:open",
            )
        )

class CategoryView(discord.ui.View):
    """Ephemeral category picker with short description (embed above)."""
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:mebinu")
    async def mebinu(self, interaction: discord.Interaction, _):
        await Tickets.open_thread_from_button(interaction, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary, custom_id="tickets:cat:commission")
    async def commission(self, interaction: discord.Interaction, _):
        await Tickets.open_thread_from_button(interaction, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="tickets:cat:nsfw")
    async def nsfw(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Are you **18 or older**?",
            view=NSFWConfirmView(),
            ephemeral=True,
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="tickets:cat:general")
    async def general(self, interaction: discord.Interaction, _):
        await Tickets.open_thread_from_button(interaction, "general")

class NSFWConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, I'm 18+", style=discord.ButtonStyle.danger, custom_id="tickets:nsfw:yes")
    async def yes(self, interaction: discord.Interaction, _):
        await Tickets.open_thread_from_button(interaction, "nsfw")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="tickets:nsfw:no")
    async def no(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="NSFW ticket cancelled.", view=None)

# --- Cog ---------------------------------------------------------------------

class Tickets(commands.Cog, name="tickets"):
    """Ticket Hub cog – English UI, hub-local cleanup, NSFW age-gate."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(OpenTicketView())  # persistent

    # Helpers -----------------------------------------------------------------

    @staticmethod
    def _hub_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
        ch = guild.get_channel(TICKET_HUB_CHANNEL_ID)
        return ch if isinstance(ch, discord.TextChannel) else None

    @staticmethod
    async def _ensure_reply(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)

    @staticmethod
    async def open_thread_from_button(
        interaction: discord.Interaction,
        category: Literal["mebinu", "commission", "nsfw", "general"],
    ):
        await Tickets._ensure_reply(interaction)

        guild = interaction.guild
        user = interaction.user
        if not guild:
            await interaction.followup.send("This can only be used in a server.", ephemeral=True)
            return

        hub = Tickets._hub_channel(guild)
        if not hub:
            await interaction.followup.send("Ticket hub channel is not configured or missing.", ephemeral=True)
            return

        thread_name = f"{THREAD_PREFIX[category]} | {user.display_name}"
        try_types = [discord.ChannelType.private_thread, discord.ChannelType.public_thread]

        thread: Optional[discord.Thread] = None
        for typ in try_types:
            try:
                thread = await hub.create_thread(
                    name=thread_name,
                    type=typ,
                    invitable=False if typ is discord.ChannelType.private_thread else True,
                    auto_archive_duration=1440,
                    reason=f"Ticket opened by {user} ({category})",
                )
                break
            except discord.Forbidden:
                continue

        if thread is None:
            await interaction.followup.send(
                "I couldn't create a thread here (missing permissions). Please contact staff.",
                ephemeral=True,
            )
            return

        try:
            await thread.add_user(user)
        except Exception:
            pass

        await thread.send(f"{user.mention} {WELCOME_TEXT[category]}")
        await interaction.followup.send(f"Thread opened: **{thread.name}**", ephemeral=True)

    # Interaction routing for the persistent button ---------------------------

    @commands.Cog.listener("on_interaction")
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if interaction.data and interaction.data.get("custom_id") == "tickets:open":
            embed = discord.Embed(
                title="Choose a category",
                description=PANEL_DESCRIPTION,
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, view=CategoryView(), ephemeral=True)

    # Setup / Cleanup ---------------------------------------------------------

    def _is_owner_or_manager(self, itx: discord.Interaction) -> bool:
        if itx.user and itx.user.id == OWNER_ID:
            return True
        perms = itx.user.guild_permissions if isinstance(itx.user, discord.Member) else None
        return bool(perms and (perms.manage_guild or perms.manage_channels))

    @app_commands.command(name="ticket_hub_setup", description="Post the Ticket Hub panel in this channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def hub_setup(self, interaction: discord.Interaction):
        if not self._is_owner_or_manager(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Run this in a text channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title=PANEL_TITLE,
            description="Click the button below to open a private ticket. You'll pick the category in the next step.",
            color=discord.Color.dark_theme(),
        ).set_footer(text="ticket_hub")

        await interaction.response.send_message("Panel posted.", ephemeral=True)
        await channel.send(embed=embed, view=OpenTicketView())

    @app_commands.command(
        name="ticket_hub_cleanup",
        description="Clean messages in THIS ticket-hub channel (safe, local only).",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        if not self._is_owner_or_manager(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Run this in the ticket-hub text channel.", ephemeral=True)
            return
        if channel.id != TICKET_HUB_CHANNEL_ID:
            await interaction.response.send_message(
                "This command only works in the configured ticket-hub channel.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Cleaning…", ephemeral=True)

        deleted_total = 0
        try:
            while True:
                batch = await channel.purge(
                    limit=100,
                    check=lambda m: not m.pinned,
                    bulk=True,
                    reason="ticket_hub_cleanup",
                )
                deleted_total += len(batch)
                if len(batch) < 100:
                    break
                await asyncio.sleep(1.0)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete messages here.", ephemeral=True)
            return

        removed_threads = 0
        if deep:
            for th in channel.threads:
                if th.owner_id == self.bot.user.id or any(th.name.startswith(p) for p in THREAD_PREFIX.values()):
                    try:
                        await th.delete(reason="ticket_hub_cleanup deep")
                        removed_threads += 1
                        await asyncio.sleep(0.5)
                    except Exception:
                        try:
                            await th.archive(locked=True, reason="ticket_hub_cleanup deep (archive)")
                            removed_threads += 1
                        except Exception:
                            pass

        await interaction.followup.send(
            f"Cleanup done. Deleted messages: **{deleted_total}**."
            + (f" Deleted/archived threads: **{removed_threads}**." if deep else ""),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("tickets cog ready")

# --- Extension entry ---------------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
    if GUILD_ID:
        try:
            await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        except Exception as e:
            log.warning("App command sync (guild) failed: %r", e)
    else:
        try:
            await bot.tree.sync()
        except Exception as e:
            log.warning("App command sync (global) failed: %r", e)
