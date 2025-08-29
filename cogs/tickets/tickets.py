import os
import logging
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("bot")

FEATURE_NAME = "tickets"

# ---- ENV ----
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))
ARCHIVES_CHANNEL_ID = int(os.getenv("ARCHIVES_CHANNEL_ID", "0"))  # opcionális

# ---- Kategóriák (fix 4) ----
CATS = [
    ("Mebinu", "mebinu"),
    ("Commission", "commission"),
    ("NSFW 18+", "nsfw"),
    ("General Help", "general"),
]

DETAILS_TEXT = (
    "**Mebinu** — Collectible figure requests, variants, codes, rarity.\n"
    "**Commission** — Paid custom art request; scope, budget, deadline.\n"
    "**NSFW 18+** — 18+ submissions; stricter policy & review.\n"
    "**General Help** — Quick Q&A and guidance."
)


# ----------------- PERSISTENT HUB VIEW -----------------
class CategoryButton(discord.ui.Button):
    def __init__(self, label: str, key: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            custom_id=f"ticket_cat_{key}",
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        if self.key == "nsfw":
            view = AgeGateView(self.key)
            await interaction.response.send_message(
                "This ticket is **18+**. Please confirm your age to continue.",
                view=view,
                ephemeral=True,
            )
            return

        await open_ticket_thread(interaction, self.key)


class DetailsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Details",
            custom_id="ticket_details",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(DETAILS_TEXT, ephemeral=True)


class TicketHubView(discord.ui.View):
    """Fő (persistent) gombsor a #ticket-hub üzeneten."""
    def __init__(self):
        super().__init__(timeout=None)  # persistent
        for label, key in CATS:
            self.add_item(CategoryButton(label, key))
        self.add_item(DetailsButton())


# ----------------- 18+ KAPU -----------------
class AgeConfirmButton(discord.ui.Button):
    def __init__(self, key: str):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="I'm 18+",
            custom_id=f"age_yes_{key}",
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        await open_ticket_thread(interaction, self.key)


class AgeCancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.danger, label="Cancel", custom_id="age_no")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Cancelled.", view=None)


class AgeGateView(discord.ui.View):
    def __init__(self, key: str):
        super().__init__(timeout=120)
        self.add_item(AgeConfirmButton(key))
        self.add_item(AgeCancelButton())


# ----------------- KÖZÖS FUNKCIÓ -----------------
async def open_ticket_thread(interaction: discord.Interaction, key: str):
    """Thread nyitása + első üzenet (a limit szöveget nem mutatjuk)."""
    channel = interaction.channel
    user = interaction.user

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This command works only in a text channel.", ephemeral=True
        )
        return

    starter = await channel.send("Thread opened.")
    th = await starter.create_thread(
        name=f"{key.upper()} | {user.display_name}",
        auto_archive_duration=1440,
    )
    await th.send(
        f"Opened pre-chat for **{key.upper()}**.\n"
        f"Hi {user.mention}! Tell me the essentials and we'll take it from there."
    )
    try:
        await th.add_user(user)
    except Exception:
        pass

    await interaction.response.send_message(f"Thread created: {th.mention}", ephemeral=True)

    if ARCHIVES_CHANNEL_ID:
        try:
            ach = interaction.client.get_channel(ARCHIVES_CHANNEL_ID)
            if isinstance(ach, discord.TextChannel):
                await ach.send(f"Thread opened: {th.mention} — by {user.mention}")
        except Exception as e:
            log.warning("Archive notify failed: %r", e)


# ----------------- SEGÉDFÜGGVÉNYEK: AI/ADMIN IS HÍVNI TUDJA -----------------
async def post_ticket_hub(channel: discord.TextChannel) -> discord.Message:
    """Új TicketHub üzenet kirakása megadott csatornába."""
    msg = await channel.send("TicketHub ready. Click to start.", view=TicketHubView())
    log.info("[tickets] New TicketHub message posted in #%s", channel.name)
    return msg


async def cleanup_ticket_hub(channel: discord.TextChannel) -> int:
    """Bot által küldött régi hub-üzenetek törlése a csatornában. Visszaad: törölt darabszám."""
    deleted = 0
    async for m in channel.history(limit=200):
        if m.author == channel.guild.me and (
            "TicketHub ready" in (m.content or "") or any(m.components)
        ):
            try:
                await m.delete()
                deleted += 1
            except Exception:
                pass
    log.info("[tickets] Cleanup in #%s removed %d message(s).", channel.name, deleted)
    return deleted


# ----------------- COG -----------------
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketHubView())  # restart után is éljen
        log.info("[%s] Persistent TicketHub view registered.", FEATURE_NAME)

    @app_commands.command(name="ticket_hub", description="Post a fresh Ticket Hub block.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_hub(self, interaction: discord.Interaction):
        if TICKET_HUB_CHANNEL_ID and interaction.channel_id != TICKET_HUB_CHANNEL_ID:
            await interaction.response.send_message(
                "Please run this in the configured Ticket Hub channel.", ephemeral=True
            ); return
        await interaction.response.defer(ephemeral=True)
        msg = await post_ticket_hub(interaction.channel)  # type: ignore
        await interaction.followup.send(f"TicketHub posted: {msg.jump_url}", ephemeral=True)

    @app_commands.command(
        name="ticket_hub_cleanup",
        description="Delete recent Ticket Hub bot messages in this channel.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Works only in a text channel.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        deleted = await cleanup_ticket_hub(interaction.channel)
        await interaction.followup.send(f"Cleanup done. Deleted: **{deleted}** message(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
