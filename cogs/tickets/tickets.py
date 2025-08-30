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
        await interaction.response.send_message(
            CATEGORIES_HELP,
            view=CategorySelectView(self.cog),
            ephemeral=True
        )


class CategorySelectView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:mebinu")
    async def mebinu(self, i: discord.Interaction, _):
        await self.cog.create_ticket(i, kind="mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:commission")
    async def commission(self, i: discord.Interaction, _):
        await self.cog.create_ticket(i, kind="commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="tickets:cat:nsfw")
    async def nsfw(self, i: discord.Interaction, _):
        # 18+ megerősítés
        await i.response.send_message(
            "Are you 18 or older?",
            view=NSFWConfirmView(self.cog),
            ephemeral=True
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="tickets:cat:general")
    async def general(self, i: discord.Interaction, _):
        await self.cog.create_ticket(i, kind="general")


class NSFWConfirmView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="tickets:nsfw:yes")
    async def yes(self, i: discord.Interaction, _):
        await self.cog.create_ticket(i, kind="nsfw")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="tickets:nsfw:no")
    async def no(self, i: discord.Interaction, _):
        await i.response.send_message("Understood. NSFW ticket cancelled.", ephemeral=True)


class TicketOwnerControls(discord.ui.View):
    """Ephemeral kontroll – csak a nyitó látja a ticket csatornában."""
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

        # Csak a nyitó vagy OWNER zárhatja
        opener_id = None
        if ch.topic and "owner=" in ch.topic:
            try:
                opener_id = int(ch.topic.split("owner=")[1].split()[0])
            except Exception:
                opener_id = None

        if interaction.user.id not in {opener_id, OWNER_ID} and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Only the opener or staff can close this ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await ch.delete(reason=f"Ticket closed by {interaction.user}")
            await interaction.followup.send("Ticket closed.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Failed to close ticket (permissions?).", ephemeral=True)


# ====== Cog =================================================================
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Persistent view regisztráció
    async def cog_load(self) -> None:
        self.bot.add_view(OpenTicketView(self))
        log.info("[ISERO] Tickets cog loaded (persistent view ready)")

    # ------------- Helper: create ticket channel ----------------------------
    async def create_ticket(self, interaction: discord.Interaction, *, kind: Literal["mebinu", "commission", "nsfw", "general"]):
        # Ha még nem válaszoltunk, válaszoljunk ephemeral-lel
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)

        guild = interaction.guild
        assert guild is not None

        category = guild.get_channel(TICKETS_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("Ticket category is not configured. Ask the admin.", ephemeral=True)
            return

        # Csatornanév
        base = TICKET_NAME_PREFIX[kind]
        safe_name = re.sub(r"[^a-z0-9\-]", "", interaction.user.name.lower().replace(" ", "-"))
        name = f"{base}-{safe_name}"

        # Permission overwrites: ticket nyitó + staff (Manage Channels vagy Admin)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        # Egyszerű: staffnak Manage Channels alapján úgyis látszik. Ha külön role kell később, ide vehetjük.

        topic = make_ticket_topic(interaction.user.id, kind)
        nsfw_flag = (kind == "nsfw")

        try:
            channel = await guild.create_text_channel(
                name=name,
                category=category,
                topic=topic,
                nsfw=nsfw_flag,
                reason=f"Ticket created by {interaction.user} ({kind})",
            )
        except discord.HTTPException as e:
            log.exception("Failed to create ticket channel: %s", e)
            await interaction.followup.send("Failed to create ticket channel (permissions?).", ephemeral=True)
            return

        # Üdvözlő üzenet a csatornába
        try:
            await channel.send(WELCOME_TEXT[kind])
        except discord.HTTPException:
            pass

        # Ephemeral kontroll csak a nyitónak – „switch, amit csak ő lát”
        await interaction.followup.send(
            f"Your ticket is ready: {channel.mention}",
            view=TicketOwnerControls(self, channel.id),
            ephemeral=True
        )

    # ------------- Hub setup -------------------------------------------------
    @app_commands.command(name="ticket_hub_setup", description="Post the Ticket Hub panel into this channel.")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=False)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Please run this inside a text channel.", ephemeral=True)
            return

        embed = discord.Embed(title=PANEL_TITLE, description=PANEL_DESCRIPTION, color=discord.Color.blurple())
        try:
            await channel.send(embed=embed, view=OpenTicketView(self))
            await interaction.followup.send("Ticket Hub panel posted.", ephemeral=True)
        except discord.HTTPException as e:
            log.exception("Failed to post hub panel: %s", e)
            await interaction.followup.send("Failed to post panel (permissions?).", ephemeral=True)

    # ------------- Hub cleanup ----------------------------------------------
    @app_commands.command(name="ticket_hub_cleanup", description="Cleanup this hub channel. Optionally delete all ticket channels.")
    @app_commands.describe(deep="Also delete all bot-made ticket channels.")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        # AZONNAL defer → nincs Unknown interaction
        await interaction.response.defer(ephemeral=True, thinking=False)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Please run this inside the hub text channel.", ephemeral=True)
            return

        # Csak admin/owner futtathatja
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.id == OWNER_ID):
            await interaction.followup.send("You need Manage Server to do this.", ephemeral=True)
            return

        # 1) Hub csatorna takarítás
        deleted = 0
        try:
            def _check(msg: discord.Message) -> bool:
                # mindent visz, kivéve a pinned-et
                return not msg.pinned
            deleted = len(await channel.purge(limit=None, check=_check, reason=f"Ticket hub cleanup by {interaction.user}"))
        except discord.Forbidden:
            await interaction.followup.send("Missing permissions to purge messages.", ephemeral=True)
            return
        except discord.HTTPException as e:
            log.exception("Purge failed: %s", e)

        # 2) Ha deep: ticket csatornák törlése (topic tag vagy névminta alapján)
        removed_channels = 0
        if deep:
            guild = interaction.guild
            if guild:
                for ch in guild.channels:
                    if isinstance(ch, discord.TextChannel) and ch.category_id == TICKETS_CATEGORY_ID:
                        topic = ch.topic or ""
                        if topic.startswith("[ticket]"):
                            try:
                                await ch.delete(reason=f"Ticket deep-cleanup by {interaction.user}")
                                removed_channels += 1
                                continue
                            except discord.HTTPException:
                                pass
                        # fallback – régi nevek
                        if NAME_PATTERN.match(ch.name):
                            try:
                                await ch.delete(reason=f"Ticket deep-cleanup (fallback) by {interaction.user}")
                                removed_channels += 1
                            except discord.HTTPException:
                                pass

        # 3) Panel visszarakása
        try:
            embed = discord.Embed(title=PANEL_TITLE, description=PANEL_DESCRIPTION, color=discord.Color.blurple())
            await channel.send(embed=embed, view=OpenTicketView(self))
        except discord.HTTPException:
            pass

        # 4) Followup válasz (már defereltünk)
        note = f"Cleanup done. Deleted messages: **{deleted}**"
        if deep:
            note += f" • Removed ticket channels: **{removed_channels}**"
        await interaction.followup.send(note, ephemeral=True)


# ===== Setup ================================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
