# cogs/tickets/tickets.py
from __future__ import annotations

import os
import asyncio
import logging
from typing import Optional, Literal, Callable

import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger(__name__)

# --- Env / config ------------------------------------------------------------

GUILD_ID = int(os.getenv("GUILD_ID", "0"))  # e.g. 1409931599629385840
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))  # hub text channel id
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # your user id

# --- UI strings (English) ----------------------------------------------------

PANEL_TITLE = "Ticket Hub"
PANEL_DESCRIPTION = (
    "Press **Open Ticket** to start. In the next step you'll choose a category.\n"
)

HELP_HEADER = (
    "**Choose a category:**\n"
    "• **Mebinu** — Collectible figures: requests, variants, codes, rarity.\n"
    "• **Commission** — Paid custom art: scope, budget, deadline.\n"
    "• **NSFW 18+** — Adults only; stricter rules & review.\n"
    "• **General Help** — Quick Q&A and guidance.\n"
)

WELCOME_TEXT = {
    "mebinu": "Welcome! This private thread is for **Mebinu** (collectibles). Please describe your request.",
    "commission": "Welcome! This private thread is for a **Commission**. Please share scope, budget and deadline.",
    "nsfw": "Welcome! This private thread is for **NSFW (18+)** topics. Follow the server rules strictly.",
    "general": "Welcome! This private thread is for **General Help**. Tell us what you need.",
}

THREAD_PREFIX = ""  # if you want a fixed prefix in thread names, set here
AUTOCLOSE_MINUTES = 0  # keep 0 (we won't auto-close)
ARCHIVE_MIN = 10080  # 7 days

# -----------------------------------------------------------------------------

def _is_owner_or_staff(member: discord.Member) -> bool:
    return member.id == OWNER_ID or member.guild_permissions.manage_guild

def _in_hub(channel: discord.abc.Messageable) -> bool:
    return isinstance(channel, discord.TextChannel) and (
        TICKET_HUB_CHANNEL_ID == 0 or channel.id == TICKET_HUB_CHANNEL_ID
    )

# --- Views -------------------------------------------------------------------

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CategoryView(user_id=interaction.user.id)
        await interaction.response.send_message(HELP_HEADER, view=view, ephemeral=True)


class CategoryView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This panel belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.primary, custom_id="ticket:cat:mebinu")
    async def mebinu(self, itx: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(itx, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary, custom_id="ticket:cat:commission")
    async def commission(self, itx: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(itx, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="ticket:cat:nsfw")
    async def nsfw(self, itx: discord.Interaction, _: discord.ui.Button):
        # Confirm age 18+
        view = Confirm18View(user_id=itx.user.id)
        await itx.response.send_message("Are you **18 or older**?", view=view, ephemeral=True)

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="ticket:cat:general")
    async def general(self, itx: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(itx, "general")


class Confirm18View(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This confirmation belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="ticket:18:yes")
    async def yes(self, itx: discord.Interaction, _: discord.ui.Button):
        await create_ticket_thread(itx, "nsfw")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="ticket:18:no")
    async def no(self, itx: discord.Interaction, _: discord.ui.Button):
        await itx.response.edit_message(content="Cancelled.", view=None)

# --- Thread creation helper ---------------------------------------------------

async def create_ticket_thread(itx: discord.Interaction, category: Literal["mebinu", "commission", "nsfw", "general"]):
    channel = itx.channel
    if not isinstance(channel, discord.TextChannel):
        await itx.response.send_message("This can only be used in a text channel.", ephemeral=True)
        return

    # Create a private thread in the hub channel
    user = itx.user
    thread_name = f"{THREAD_PREFIX}{category.upper()} | {getattr(user, 'display_name', user.name)}"
    try:
        thread = await channel.create_thread(
            name=thread_name[:98],
            type=discord.ChannelType.private_thread,
            auto_archive_duration=ARCHIVE_MIN,
            invitable=False,
        )
        await thread.add_user(user)
        await thread.send(f"**{WELCOME_TEXT[category]}**\n\n— <@{user.id}>")
    except discord.Forbidden:
        await itx.response.send_message("I don't have permission to create private threads here.", ephemeral=True)
        return
    except Exception as e:
        log.exception("Failed to create ticket thread: %s", e)
        await itx.response.send_message("Something went wrong while creating your ticket.", ephemeral=True)
        return

    # Acknowledge ephemerally
    if itx.response.is_done():
        await itx.followup.send(f"Your ticket is ready: {thread.mention}", ephemeral=True)
    else:
        await itx.response.send_message(f"Your ticket is ready: {thread.mention}", ephemeral=True)

# --- Main Cog ----------------------------------------------------------------

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent views so buttons keep working after restarts
        self.bot.add_view(OpenTicketView())
        log.info("[ISERO] Tickets cog loaded (tickets-2025-08-30c).")

    # ---------- SLASH COMMANDS (guild-scoped) ----------

    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda x: x)
    @app_commands.command(name="ticket_hub_setup", description="Place the Ticket Hub card in this channel.")
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        if not _is_owner_or_staff(interaction.user):
            return await interaction.response.send_message("Not enough permission.", ephemeral=True)
        if not _in_hub(interaction.channel):
            return await interaction.response.send_message("Wrong channel for the hub.", ephemeral=True)

        await self._place_hub_card(interaction.channel)  # type: ignore[arg-type]
        await interaction.response.send_message("Hub card placed.", ephemeral=True)

    @app_commands.describe(deep="If true, delete everything I can (last 14 days). Otherwise only bot/command noise.")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda x: x)
    @app_commands.command(name="ticket_hub_cleanup", description="Cleanup messages in this hub channel.")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        if not _is_owner_or_staff(interaction.user):
            return await interaction.response.send_message("Not enough permission.", ephemeral=True)
        if not _in_hub(interaction.channel):
            return await interaction.response.send_message("Wrong channel for the hub.", ephemeral=True)

        channel: discord.TextChannel = interaction.channel  # type: ignore[assignment]
        deleted = await self._cleanup_channel(channel, deep=bool(deep))
        # Replace hub card after cleanup
        await self._place_hub_card(channel)
        await interaction.response.send_message(f"Cleanup done. Deleted messages: **{deleted}**", ephemeral=True)

    # ---------- TEXT ALIASES (so typing works as before) ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots & DMs
        if message.author.bot or not message.guild:
            return
        content = message.content.strip().lower()
        if not content.startswith("/ticket_hub_"):
            return
        if not _in_hub(message.channel):
            return
        if not _is_owner_or_staff(message.author):  # type: ignore[arg-type]
            return

        try:
            if content.startswith("/ticket_hub_setup"):
                await self._place_hub_card(message.channel)  # type: ignore[arg-type]
                await message.add_reaction("✅")
            elif content.startswith("/ticket_hub_cleanup"):
                deep = "deep:true" in content or "deep: true" in content
                deleted = await self._cleanup_channel(message.channel, deep=deep)  # type: ignore[arg-type]
                await self._place_hub_card(message.channel)  # type: ignore[arg-type]
                await message.reply(f"Cleanup done. Deleted: **{deleted}**", mention_author=False)
        except Exception as e:
            log.exception("Alias handling error: %s", e)

    # ---------- helpers ----------

    async def _place_hub_card(self, channel: discord.TextChannel):
        # try to delete old hub cards from the bot to keep it clean
        try:
            async for msg in channel.history(limit=100):
                if msg.author == self.bot.user and msg.components:
                    # a previous card with a button
                    try:
                        await msg.delete()
                    except Exception:
                        pass
        except Exception:
            pass

        embed = discord.Embed(
            title=PANEL_TITLE,
            description=PANEL_DESCRIPTION,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Only one button. The category selection comes next.")

        await channel.send(embed=embed, view=OpenTicketView())

    async def _cleanup_channel(self, channel: discord.TextChannel, deep: bool = False) -> int:
        """
        Deletes messages in this hub channel.
        - deep=False: delete only bot/system/command-noise from last 14 days (safer).
        - deep=True: delete as many as Discord allows (14-day hard limit), in batches.
        Returns number of deleted messages.
        """
        def check(msg: discord.Message) -> bool:
            if deep:
                return True
            # "light" cleanup: bot messages, command attempts, or embeds from the hub
            txt = (msg.content or "").lower()
            is_cmd = txt.startswith("/tick_
