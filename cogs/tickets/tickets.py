# cogs/tickets/tickets.py
from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime as dt
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ---- Env / config -----------------------------------------------------------
GUILD_ID = int(os.getenv("GUILD_ID", "0"))                 # e.g. 1409931599629385840
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))                 # optional; used for owner-bypass

# ---- UI text (English) ------------------------------------------------------
PANEL_TITLE = "Ticket Hub"
PANEL_DESCRIPTION = (
    "Press **Open Ticket** to start. In the next step you'll choose a category:\n\n"
    "• **Mebinu** — Collectible figures: requests, variants, codes, rarity.\n"
    "• **Commission** — Paid custom art: scope, budget, deadline.\n"
    "• **NSFW 18+** — Adults only; stricter rules & review.\n"
    "• **General Help** — Quick Q&A and guidance.\n"
)

WELCOME_TEXT = {
    "mebinu": (
        "Welcome! This private thread is for **Mebinu (collectibles)**. "
        "Please describe your request."
    ),
    "commission": (
        "Welcome! This private thread is for **Commission** work. "
        "Please share **scope**, **budget**, and **deadline**."
    ),
    "nsfw": (
        "Welcome! This private thread is for **NSFW (18+)** topics. "
        "Follow the server rules strictly."
    ),
    "general": (
        "Welcome! This private thread is for **General Help**. "
        "Tell us what you need."
    ),
}

THREAD_PREFIX = {
    "mebinu": "MEBINU",
    "commission": "COMMISSION",
    "nsfw": "NSFW18",
    "general": "HELP",
}

# -----------------------------------------------------------------------------


def _is_owner_or_mgr(inter: discord.Interaction) -> bool:
    if OWNER_ID and inter.user.id == OWNER_ID:
        return True
    perms = getattr(inter.user, "guild_permissions", None)
    return bool(perms and perms.manage_guild)


def _guild_scope():
    # guilds() decorator wants discord.Object
    return [discord.Object(id=GUILD_ID)] if GUILD_ID else []


class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="hub:open")
    async def open(self, inter: discord.Interaction, button: discord.ui.Button):
        # Ephemeral category panel only for the clicking user
        embed = discord.Embed(
            title="Choose a category",
            description=PANEL_DESCRIPTION,
            color=discord.Color.blurple(),
        )
        await inter.response.send_message(embed=embed, view=CategoryView(), ephemeral=True)


class CategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary, custom_id="cat:mebinu")
    async def mebinu(self, inter: discord.Interaction, button: discord.ui.Button):
        await Tickets.create_ticket_thread(inter, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary, custom_id="cat:commission")
    async def commission(self, inter: discord.Interaction, button: discord.ui.Button):
        await Tickets.create_ticket_thread(inter, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="cat:nsfw")
    async def nsfw(self, inter: discord.Interaction, button: discord.ui.Button):
        # Age-gate confirm first
        view = AgeGateView()
        embed = discord.Embed(
            title="NSFW 18+ Confirmation",
            description="This area is **18+ only**. Are you **18 or older**?",
            color=discord.Color.red(),
        )
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="cat:general")
    async def general(self, inter: discord.Interaction, button: discord.ui.Button):
        await Tickets.create_ticket_thread(inter, "general")


class AgeGateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.value: Optional[bool] = None

    @discord.ui.button(label="Yes, I'm 18+", style=discord.ButtonStyle.danger, custom_id="age:yes")
    async def yes(self, inter: discord.Interaction, button: discord.ui.Button):
        # Defer so we can create thread then edit ephemeral
        await inter.response.defer(ephemeral=True, thinking=True)
        await Tickets.create_ticket_thread(inter, "nsfw", responded=False)
        await inter.edit_original_response(content="NSFW ticket created.", view=None)
        self.value = True
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="age:no")
    async def no(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.send_message("Understood. NSFW ticket was **not** created.", ephemeral=True)
        self.value = False
        self.stop()


class Tickets(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ----------------- Hub setup -----------------
    @app_commands.guilds(*_guild_scope())
    @app_commands.command(name="ticket_hub_setup", description="Place the Ticket Hub card in this channel.")
    async def ticket_hub_setup(self, inter: discord.Interaction):
        if not _is_owner_or_mgr(inter):
            return await inter.response.send_message(
                "You need **Manage Server** (or be the owner) to run this.", ephemeral=True
            )

        if inter.channel_id != TICKET_HUB_CHANNEL_ID:
            return await inter.response.send_message(
                "This command can only be used in the configured **ticket-hub** channel.",
                ephemeral=True,
            )

        embed = discord.Embed(title=PANEL_TITLE, description="Click the button below to open a ticket.\n"
                               "You'll choose your category in the next step.",
                              color=discord.Color.brand_green())
        embed.set_footer(text="ticket_hub")

        view = OpenTicketView()
        await inter.response.send_message(embed=embed, view=view)
        log.info("Ticket Hub card placed by %s", inter.user)

    # ----------------- Local cleanup (hub only) -----------------
    @app_commands.guilds(*_guild_scope())
    @app_commands.describe(deep="Also remove ticket threads created by the bot.")
    @app_commands.command(name="ticket_hub_cleanup", description="Clean the Ticket Hub channel (local only).")
    async def ticket_hub_cleanup(self, inter: discord.Interaction, deep: Optional[bool] = False):
        if not _is_owner_or_mgr(inter):
            return await inter.response.send_message(
                "You need **Manage Server** (or be the owner) to run this.", ephemeral=True
            )

        if inter.channel_id != TICKET_HUB_CHANNEL_ID:
            return await inter.response.send_message(
                "Cleanup works **only** in the Ticket Hub channel.", ephemeral=True
            )

        ch = inter.channel
        assert isinstance(ch, discord.TextChannel)

        await inter.response.defer(ephemeral=True, thinking=True)

        removed = 0
        # Purge only messages from the bot itself (and only here).
        def _is_bot(m: discord.Message) -> bool:
            return m.author == inter.client.user

        try:
            # purge ignores >14 days; that's Discord limitation and OK here
            removed = await ch.purge(limit=None, check=_is_bot, bulk=True)
        except Exception as e:
            log.warning("Purge warning: %s", e)

        removed_threads = 0
        if deep:
            # Only threads created by the bot and with our known prefixes
            valid_prefixes = tuple(f"{p} |" for p in THREAD_PREFIX.values())

            async for thread in ch.threads:  # active threads
                pass  # property, not async iterator

            for th in list(ch.threads) + list(ch.archived_threads()):
                try:
                    # creator check
                    if th.owner_id != inter.client.user.id:
                        continue
                    if not any(th.name.startswith(pref) for pref in valid_prefixes):
                        continue
                    await th.delete(reason="ticket_hub_cleanup deep")
                    removed_threads += 1
                    await asyncio.sleep(0.4)  # be gentle with rate limits
                except Exception as e:
                    log.warning("Thread delete failed for %s: %s", th, e)

        await inter.followup.send(
            f"Cleanup done.\n• Deleted messages: **{removed}**\n• Deleted threads: **{removed_threads}**",
            ephemeral=True,
        )

    # ----------------- Thread creation helper -----------------
    @staticmethod
    async def create_ticket_thread(
        inter: discord.Interaction,
        kind: Literal["mebinu", "commission", "nsfw", "general"],
        responded: bool = True,
    ):
        """Creates a private thread in the hub channel and seeds it with a welcome message."""
        hub = inter.guild.get_channel(TICKET_HUB_CHANNEL_ID) if inter.guild else None
        if not isinstance(hub, discord.TextChannel):
            msg = "Ticket Hub channel is not configured or not a text channel."
            if responded:
                return await inter.response.send_message(msg, ephemeral=True)
            else:
                await inter.followup.send(msg, ephemeral=True)
                return

        prefix = THREAD_PREFIX[kind]
        user = inter.user
        # Thread name: PREFIX | DisplayName
        name = f"{prefix} | {getattr(user, 'display_name', user.name)}"

        try:
            thread = await hub.create_thread(
                name=name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=10080,  # 7 days
                reason=f"Ticket created: {kind}",
            )
        except discord.HTTPException as e:
            log.error("Failed to create thread: %s", e)
            if responded:
                return await inter.response.send_message("Couldn't create the ticket thread.", ephemeral=True)
            else:
                return await inter.followup.send("Couldn't create the ticket thread.", ephemeral=True)

        # Add the user to the private thread
        try:
            await thread.add_user(user)
        except Exception:
            pass

        # Seed welcome
        embed = discord.Embed(
            title=f"{prefix} Ticket",
            description=WELCOME_TEXT[kind],
            color=discord.Color.blurple(),
            timestamp=dt.utcnow(),
        )
        await thread.send(content=user.mention, embed=embed)

        # Final ephemeral confirmation to the clicker
        if responded:
            await inter.response.send_message(f"Ticket created: {thread.mention}", ephemeral=True)
        else:
            await inter.followup.send(f"Ticket created: {thread.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
