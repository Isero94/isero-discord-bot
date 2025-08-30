# cogs/tickets/tickets.py

import os
import re
import time
import asyncio
import logging
import typing as T

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ------- Helpers: env ints safely -------

def _env_int(name: str) -> int | None:
    val = os.getenv(name, "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None

def _env_csv_ints(name: str) -> list[int]:
    raw = os.getenv(name, "") or ""
    out: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out


TICKET_HUB_CHANNEL_ID = _env_int("TICKET_HUB_CHANNEL_ID")
TICKETS_CATEGORY_ID   = _env_int("TICKETS_CATEGORY_ID")
ARCHIVE_CATEGORY_ID   = _env_int("ARCHIVE_CATEGORY_ID")
STAFF_ROLE_ID         = _env_int("STAFF_ROLE_ID")                 # optional
STAFF_EXTRA_ROLE_IDS  = _env_csv_ints("STAFF_EXTRA_ROLE_IDS")     # optional (vesszővel elválasztva)
TICKET_COOLDOWN_SEC   = _env_int("TICKET_COOLDOWN_SECONDS") or 20

# channel topic marker
def owner_marker(user_id: int) -> str:
    return f"owner:{user_id}"

# sanitize channel name
def slugify(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9\-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "ticket"

# ------- Views -------

class OpenTicketView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=None)  # persistent
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # category selection is ephemeral for the user only
        await interaction.response.send_message(
            embed=self.cog.category_embed(),
            view=CategoryView(self.cog),
            ephemeral=True
        )

class CategoryView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary)
    async def mebinu(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary)
    async def commission(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def nsfw(self, i: discord.Interaction, _: discord.ui.Button):
        # ask 18+ confirmation
        await i.response.send_message(
            "Are you 18 or older?",
            view=AgeView(self.cog),
            ephemeral=True
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def general_help(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "general-help")

class AgeView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "nsfw")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, _: discord.ui.Button):
        await i.response.send_message("NSFW ticket not created.", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_btn(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.close_current_ticket(i)

# ------- The Cog -------

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_open: dict[int, float] = {}  # cooldown map
        # persistent views
        self.bot.add_view(OpenTicketView(self))
        self.bot.add_view(CloseTicketView(self))
        log.info("[Tickets] cog ready (persistent views added)")

    # --------- Embeds ----------
    def hub_embed(self) -> discord.Embed:
        e = discord.Embed(title="Ticket Hub")
        e.description = (
            "Nyomd meg az **Open Ticket** gombot. A következő lépésben kategóriát választasz.\n"
            "A kategóriaválasztás ezután jön (ephemeral)."
        )
        return e

    def category_embed(self) -> discord.Embed:
        e = discord.Embed(title="Válassz kategóriát:")
        e.description = (
            "**• Mebinu** — gyűjthető figurák\n"
            "**• Commission** — fizetős egyedi munka\n"
            "**• NSFW 18+** — felnőtt tartalom (megerősítés szükséges)\n"
            "**• General Help** — gyors Q&A és útmutatás"
        )
        return e

    def welcome_embed(self, user: discord.User, kind: str) -> discord.Embed:
        title = f"Welcome — {kind.replace('-', ' ').title()}"
        e = discord.Embed(title=title)
        e.description = (
            f"Hello {user.mention}! Írd le röviden a kérésed.\n"
            "Egy moderátor hamarosan válaszol.\n\n"
            "*A ticket zárásához használd a gombot.*"
        )
        return e

    # --------- Utilities ----------
    def _cooldown_left(self, user_id: int) -> int:
        now = time.time()
        last = self.last_open.get(user_id, 0.0)
        remain = int(TICKET_COOLDOWN_SEC - (now - last))
        return remain if remain > 0 else 0

    async def _find_existing_ticket(self, guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
        cat = guild.get_channel(TICKETS_CATEGORY_ID) if TICKETS_CATEGORY_ID else None
        if not isinstance(cat, discord.CategoryChannel):
            return None
        for ch in cat.text_channels:
            if ch.topic and owner_marker(user_id) in ch.topic:
                return ch
        return None

    async def create_ticket_channel(self, i: discord.Interaction, key: str) -> discord.TextChannel:
        assert isinstance(i.user, (discord.Member, discord.User))
        guild = T.cast(discord.Guild, i.guild)
        user = T.cast(discord.Member, i.user)

        # category check
        cat: discord.CategoryChannel | None = None
        if TICKETS_CATEGORY_ID:
            x = guild.get_channel(TICKETS_CATEGORY_ID)
            if isinstance(x, discord.CategoryChannel):
                cat = x

        name = slugify(f"{key}-{user.display_name}")
        topic = f"{owner_marker(user.id)} | type:{key}"

        # permission overwrites: dict is REQUIRED
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True
            ),
        }
        # main staff role
        if STAFF_ROLE_ID:
            role = guild.get_role(STAFF_ROLE_ID)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
                )
        # extra staff roles
        for rid in STAFF_EXTRA_ROLE_IDS:
            extra = guild.get_role(rid)
            if extra and extra not in overwrites:
                overwrites[extra] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
                )

        ch = await guild.create_text_channel(
            name=name,
            category=cat,
            topic=topic,
            overwrites=overwrites
        )

        await ch.send(embed=self.welcome_embed(user, key), view=CloseTicketView(self))
        return ch

    async def on_category_chosen(self, i: discord.Interaction, key: str):
        # enforce one open + cooldown
        remain = self._cooldown_left(i.user.id)
        if remain > 0:
            await i.response.send_message(
                f"Please wait **{remain}s** before creating another ticket.",
                ephemeral=True
            )
            return

        # already open?
        existing = await self._find_existing_ticket(T.cast(discord.Guild, i.guild), i.user.id)
        if existing:
            await i.response.send_message(
                f"You already have an open ticket: {existing.mention}\n"
                "Please close it before opening a new one.",
                ephemeral=True
            )
            return

        await i.response.defer(ephemeral=True)
        ch = await self.create_ticket_channel(i, key)
        self.last_open[i.user.id] = time.time()
        await i.followup.send(f"Your ticket is ready: {ch.mention}", ephemeral=True)

    async def close_current_ticket(self, i: discord.Interaction):
        ch = T.cast(discord.TextChannel, i.channel)
        guild = T.cast(discord.Guild, i.guild)

        # move to archive if set
        if ARCHIVE_CATEGORY_ID:
            cat = guild.get_channel(ARCHIVE_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                try:
                    await ch.edit(category=cat)
                except discord.Forbidden:
                    pass

        # lock channel
        try:
            ow = ch.overwrites_for(guild.default_role)
            ow.view_channel = True  # látható maradhat
            ow.send_messages = False
            await ch.set_permissions(guild.default_role, overwrite=ow)
        except discord.Forbidden:
            pass

        await i.response.send_message("Ticket closed & archived.", ephemeral=True)

    # --------- Slash commands ----------
    @app_commands.command(name="ticket_hub_setup", description="Post the Ticket Hub here.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        channel = T.cast(discord.TextChannel, i.channel)

        # if env set and different, you can also choose that channel; here just post where command is used
        await channel.send(embed=self.hub_embed(), view=OpenTicketView(self))
        await i.followup.send("Ticket Hub posted.", ephemeral=True)

    @app_commands.command(name="ticket_hub_cleanup", description="Delete bot messages in this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        channel = T.cast(discord.TextChannel, i.channel)

        deleted = 0
        async for m in channel.history(limit=200):
            if m.author.id == self.bot.user.id:
                try:
                    await m.delete()
                    deleted += 1
                    await asyncio.sleep(0.2)
                except discord.Forbidden:
                    pass
        await i.followup.send(f"Cleanup done. Deleted messages: **{deleted}**", ephemeral=True)

    # --------- Optional text fallback (if Message Content intent is enabled) ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        raw = message.content.strip().lower()
        if raw in ("/ticket_hub_setup", "ticket_hub_setup"):
            perms = message.author.guild_permissions
            if not perms.manage_channels:
                return
            await message.channel.send(embed=self.hub_embed(), view=OpenTicketView(self))
        elif raw in ("/ticket_hub_cleanup", "ticket_hub_cleanup"):
            perms = message.author.guild_permissions
            if not perms.manage_messages:
                return
            deleted = 0
            async for m in message.channel.history(limit=200):
                if m.author.id == self.bot.user.id:
                    try:
                        await m.delete()
                        deleted += 1
                        await asyncio.sleep(0.2)
                    except discord.Forbidden:
                        pass
            await message.channel.send(f"Cleanup done. Deleted: **{deleted}**")

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
