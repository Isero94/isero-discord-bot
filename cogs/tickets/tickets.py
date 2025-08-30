from __future__ import annotations

import os
import re
import time
import asyncio
import logging
from typing import Optional, Literal, Callable

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ========= Env / config ======================================================
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))          # opcionális
TICKETS_CATEGORY_ID = int(os.getenv("TICKETS_CATEGORY_ID", "0"))        # opcionális
ARCHIVES_CATEGORY_ID = int(os.getenv("ARCHIVES_CATEGORY_ID", "0"))      # opcionális

# csak spam-ellen:
CREATE_COOLDOWN_SECONDS = 10

# egyetlen aktív ticket felhasználónként (globálisan, nem kategóriánként)
ONE_TICKET_PER_USER = True

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

NAME_PATTERN = re.compile(r"^(mebinu|commission|nsfw|general)[-_].+", re.IGNORECASE)


def make_ticket_topic(user_id: int, kind: str, archived: bool = False) -> str:
    return f"[ticket] owner={user_id} kind={kind} archived={int(archived)}"


def _guilds_opt() -> Callable:
    return app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)


# ========= Views =============================================================
class OpenTicketView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="tickets:open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        # csak per-user ephemeral prompt
        await interaction.response.send_message(
            CATEGORIES_HELP, view=CategorySelectView(self.cog), ephemeral=True
        )


class CategorySelectView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=120)
        self.cog = cog

    async def _go(self, i: discord.Interaction, kind: Literal["mebinu", "commission", "general"]):
        # “eltüntetjük” a promptot, hogy ne maradjanak kattintható gombok
        if not i.response.is_done():
            await i.response.edit_message(content="Working…", view=None)
        else:
            try:
                await i.edit_original_response(content="Working…", view=None)
            except Exception:
                pass
        await self.cog.create_ticket(i, kind=kind)

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:mebinu")
    async def mebinu(self, i: discord.Interaction, _): await self._go(i, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary, custom_id="tickets:cat:commission")
    async def commission(self, i: discord.Interaction, _): await self._go(i, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="tickets:cat:nsfw")
    async def nsfw(self, i: discord.Interaction, _):
        # helyben kérdezünk, és azonnal “eltakarítjuk” a nézetet válasz után
        await i.response.edit_message(content="Are you 18 or older?", view=NSFWConfirmView(self.cog))


    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="tickets:cat:general")
    async def general(self, i: discord.Interaction, _): await self._go(i, "general")


class NSFWConfirmView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=60)
        self.cog = cog

    async def _clean_and(self, i: discord.Interaction, do: Literal["yes", "no"]):
        # töröljük a nézetet, hogy ne legyen újrakattintás
        if not i.response.is_done():
            await i.response.edit_message(content="Processing…", view=None)
        else:
            try:
                await i.edit_original_response(content="Processing…", view=None)
            except Exception:
                pass

        if do == "yes":
            await self.cog.create_ticket(i, kind="nsfw")
        else:
            await i.followup.send("Understood. NSFW ticket cancelled.", ephemeral=True)

        # ha még megvan az eredeti ephemeral, töröljük
        try:
            await i.delete_original_response()
        except Exception:
            pass

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="tickets:nsfw:yes")
    async def yes(self, i: discord.Interaction, _): await self._clean_and(i, "yes")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="tickets:nsfw:no")
    async def no(self, i: discord.Interaction, _): await self._clean_and(i, "no")


class TicketOwnerControls(discord.ui.View):
    def __init__(self, cog: "Tickets", channel_id: int):
        super().__init__(timeout=None)
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
            try:
                opener_id = int(ch.topic.split("owner=")[1].split()[0])
            except Exception:
                opener_id = None

        if interaction.user.id not in {opener_id, OWNER_ID} and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Only the opener or staff can close this ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=False)
        ok = await self.cog.archive_ticket_channel(ch, closed_by=interaction.user)
        if ok:
            await interaction.followup.send("Ticket archived.", ephemeral=True)
        else:
            await interaction.followup.send("Failed to archive (permissions?).", ephemeral=True)


# ========= Cog ===============================================================
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldown: dict[int, float] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        self.bot.add_view(OpenTicketView(self))
        log.info("[ISERO] Tickets cog loaded (persistent view ready)")

    # ----- helpers -----------------------------------------------------------
    async def resolve_tickets_category(
        self, *, guild: discord.Guild, hub_channel: Optional[discord.TextChannel]
    ) -> Optional[discord.CategoryChannel]:
        if TICKETS_CATEGORY_ID:
            cat = guild.get_channel(TICKETS_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                return cat

        if isinstance(hub_channel, discord.TextChannel) and isinstance(hub_channel.category, discord.CategoryChannel):
            return hub_channel.category

        for c in guild.categories:
            if c.name.lower().startswith(("tickets", "ticket")):
                return c

        try:
            perms = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            return await guild.create_category_channel("tickets", overwrites=perms, reason="ISERO auto-create tickets category")
        except discord.HTTPException as e:
            log.exception("Failed to create tickets category: %s", e)
            return None

    async def resolve_archives_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        if ARCHIVES_CATEGORY_ID:
            cat = guild.get_channel(ARCHIVES_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                return cat

        for c in guild.categories:
            if c.name.lower().startswith(("ticket-archives", "archives", "archív")):
                return c

        try:
            perms = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            return await guild.create_category_channel("ticket-archives", overwrites=perms, reason="ISERO create archives category")
        except discord.HTTPException as e:
            log.exception("Failed to create archives category: %s", e)
            return None

    def _parse_topic(self, topic: Optional[str]) -> tuple[Optional[int], Optional[str], bool]:
        if not topic or not topic.startswith("[ticket]"):
            return None, None, False
        owner = kind = None
        archived = False
        for part in topic.split():
            if part.startswith("owner="):
                try:
                    owner = int(part.split("=", 1)[1])
                except Exception:
                    owner = None
            elif part.startswith("kind="):
                kind = part.split("=", 1)[1]
            elif part.startswith("archived="):
                archived = part.split("=", 1)[1] == "1"
        return owner, kind, archived

    def _get_lock(self, user_id: int) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    async def find_existing_ticket(
        self, *, guild: discord.Guild, user_id: int, kind: str | None, search_category: Optional[discord.CategoryChannel]
    ) -> Optional[discord.TextChannel]:
        cats = [c for c in guild.categories]
        if search_category and search_category in cats:
            cats.remove(search_category)
            cats.insert(0, search_category)

        for cat in cats:
            for ch in cat.channels:
                if isinstance(ch, discord.TextChannel) and ch.topic:
                    owner, k, archived = self._parse_topic(ch.topic)
                    if archived:
                        continue
                    if owner == user_id and (kind is None or k == kind):
                        return ch
        return None

    async def archive_ticket_channel(self, ch: discord.TextChannel, *, closed_by: discord.abc.User) -> bool:
        guild = ch.guild
        archives = await self.resolve_archives_category(guild)
        if not archives:
            return False

        overwrites = dict(ch.overwrites)
        opener_id, kind, _ = self._parse_topic(ch.topic or "")
        if opener_id:
            opener = guild.get_member(opener_id)
            if opener:
                overwrites[opener] = discord.PermissionOverwrite(view_channel=False)

        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)

        try:
            await ch.edit(
                name=f"archived-{ch.name}",
                topic=make_ticket_topic(opener_id or 0, kind or "unknown", archived=True),
                category=archives,
                overwrites=overwrites,
                reason=f"Ticket archived by {closed_by}",
            )
            return True
        except discord.HTTPException as e:
            log.exception("Archive failed: %s", e)
            return False

    # ----- create ticket -----------------------------------------------------
    async def create_ticket(self, interaction: discord.Interaction, *, kind: Literal["mebinu", "commission", "nsfw", "general"]):
        now = time.time()
        last = self._cooldown.get(interaction.user.id, 0)
        if now - last < CREATE_COOLDOWN_SECONDS:
            remain = int(CREATE_COOLDOWN_SECONDS - (now - last) + 0.5)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Please wait **{remain}s** before creating another ticket.", ephemeral=True)
            else:
                await interaction.followup.send(f"Please wait **{remain}s** before creating another ticket.", ephemeral=True)
            return

        lock = self._get_lock(interaction.user.id)
        async with lock:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=False)

            guild = interaction.guild
            assert guild is not None
            hub_ch = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None

            category = await self.resolve_tickets_category(guild=guild, hub_channel=hub_ch)
            if not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send("Ticket category is not configured. Ask the admin.", ephemeral=True)
                return

            # blokk: ha már van NYITOTT ticket, bármi fajtából
            if ONE_TICKET_PER_USER:
                existing_any = await self.find_existing_ticket(
                    guild=guild, user_id=interaction.user.id, kind=None, search_category=category
                )
                if existing_any:
                    await interaction.followup.send(
                        f"You already have an open ticket: {existing_any.mention}\n"
                        f"Please **close it** before opening a new one.",
                        ephemeral=True,
                    )
                    return
            else:
                existing_same = await self.find_existing_ticket(
                    guild=guild, user_id=interaction.user.id, kind=kind, search_category=category
                )
                if existing_same:
                    await interaction.followup.send(
                        f"You already have an open **{kind}** ticket: {existing_same.mention}",
                        ephemeral=True,
                    )
                    return

            base = TICKET_NAME_PREFIX[kind]
            safe = re.sub(r"[^a-z0-9\-]", "", interaction.user.name.lower().replace(" ", "-"))
            name = f"{base}-{safe}"
            topic = make_ticket_topic(interaction.user.id, kind, archived=False)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            nsfw_flag = (kind == "nsfw")

            try:
                channel = await guild.create_text_channel(
                    name=name, category=category, topic=topic, nsfw=nsfw_flag,
                    overwrites=overwrites, reason=f"Ticket created by {interaction.user} ({kind})"
                )
                if hub_ch and hub_ch.category_id == channel.category_id:
                    await channel.edit(position=hub_ch.position + 1)
            except discord.HTTPException as e:
                log.exception("Failed to create ticket channel: %s", e)
                await interaction.followup.send("Failed to create ticket channel (permissions?).", ephemeral=True)
                return

            try:
                await channel.send(WELCOME_TEXT[kind])
                await channel.send("Owner controls:", view=TicketOwnerControls(self, channel.id))
            except discord.HTTPException:
                pass

            self._cooldown[interaction.user.id] = now

            await interaction.followup.send(f"Your ticket is ready: {channel.mention}", ephemeral=True)

            # takarítás: ha volt előző ephemeral prompt, töröljük
            try:
                await interaction.delete_original_response()
            except Exception:
                pass

    # ----- hub setup / cleanup ----------------------------------------------
    @_guilds_opt()
    @app_commands.command(name="ticket_hub_setup", description="Post the Ticket Hub panel into this channel.")
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

    @_guilds_opt()
    @app_commands.command(name="ticket_hub_cleanup", description="Cleanup this hub channel. Optionally delete all ticket channels.")
    @app_commands.describe(deep="Also delete all bot-made ticket channels.")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True, thinking=False)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Please run this inside the hub text channel.", ephemeral=True)
            return

        if not (interaction.user.guild_permissions.manage_guild or interaction.user.id == OWNER_ID):
            await interaction.followup.send("You need Manage Server to do this.", ephemeral=True)
            return

        deleted = 0
        try:
            deleted = len(await channel.purge(limit=1000, check=lambda m: not m.pinned,
                                              reason=f"Ticket hub cleanup by {interaction.user}"))
        except discord.Forbidden:
            await interaction.followup.send("Missing permissions to purge messages.", ephemeral=True)
            return
        except discord.HTTPException as e:
            log.exception("Purge failed: %s", e)

        removed_channels = 0
        if deep:
            guild = interaction.guild
            assert guild is not None
            ticket_cat = await self.resolve_tickets_category(guild=guild, hub_channel=channel)
            if ticket_cat:
                for ch in list(ticket_cat.channels):
                    if isinstance(ch, discord.TextChannel):
                        topic = ch.topic or ""
                        try_topic = topic.startswith("[ticket]")
                        try_name = NAME_PATTERN.match(ch.name) is not None
                        if try_topic or try_name:
                            try:
                                await ch.delete(reason=f"Ticket deep-cleanup by {interaction.user}")
                                removed_channels += 1
                            except discord.HTTPException:
                                pass

        try:
            embed = discord.Embed(title=PANEL_TITLE, description=PANEL_DESCRIPTION, color=discord.Color.blurple())
            await channel.send(embed=embed, view=OpenTicketView(self))
        except discord.HTTPException:
            pass

        note = f"Cleanup done. Deleted messages: **{deleted}**"
        if deep:
            note += f" • Removed ticket channels: **{removed_channels}**"
        await interaction.followup.send(note, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
