# cogs/tickets/tickets.py
import os
import time
import logging
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger(__name__)

def _get_int(name: str, default: int | None = None) -> int | None:
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

TICKET_HUB_CHANNEL_ID = _get_int("TICKET_HUB_CHANNEL_ID")
TICKETS_CATEGORY_ID   = _get_int("TICKETS_CATEGORY_ID")
ARCHIVE_CATEGORY_ID   = _get_int("ARCHIVE_CATEGORY_ID")
COOLDOWN_SECONDS      = _get_int("TICKET_COOLDOWN_SECONDS", 30)
STAFF_ROLE_ID         = _get_int("STAFF_ROLE_ID")  # opcionális

TICKET_TAG = "TICKET:user_id="  # ez kerül a topicba az azonosításhoz


# ---------- VIEWS ----------

class OpenTicketView(discord.ui.View):
    """Persistent 'Open Ticket' gomb a hubban."""
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary,
                       custom_id="isero:open_ticket")
    async def open_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.show_category_picker(interaction)


class CategoryView(discord.ui.View):
    """Ephemeral kategóriaválasztó."""
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary)
    async def mebinu(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary)
    async def commission(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def nsfw(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Elmúltál 18 éves?", view=AgeGateView(self.cog), ephemeral=True
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def general(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "general")


class AgeGateView(discord.ui.View):
    """NSFW életkor megerősítés."""
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=90)
        self.cog = cog

    async def _disable_and_edit(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Igen", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._disable_and_edit(interaction)
        await self.cog.on_category_chosen(interaction, "nsfw")

    @discord.ui.button(label="Nem", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._disable_and_edit(interaction)
        await interaction.followup.send(
            "A tartalom 18+, nem hoztunk létre ticketet.", ephemeral=True
        )


class CloseTicketView(discord.ui.View):
    """Persistent 'Close Ticket' gomb a ticket csatornákban."""
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger,
                       custom_id="isero:close_ticket")
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.close_ticket(interaction)


# ---------- COG ----------

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> channel_id cache; és cooldown nyilvántartás
        self.open_by_user: dict[int, int] = {}
        self.last_open_at: dict[int, float] = {}
        # persistent view-k regisztrálása
        bot.add_view(OpenTicketView(self))
        bot.add_view(CloseTicketView(self))
        log.info("[ISERO] Tickets cog loaded (persistent view ready)")

    # ------ Segédek ------

    def _tickets_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        if TICKETS_CATEGORY_ID:
            ch = guild.get_channel(TICKETS_CATEGORY_ID)
            return ch if isinstance(ch, discord.CategoryChannel) else None
        return None

    def _archive_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        if ARCHIVE_CATEGORY_ID:
            ch = guild.get_channel(ARCHIVE_CATEGORY_ID)
            return ch if isinstance(ch, discord.CategoryChannel) else None
        return None

    async def _user_has_open(self, guild: discord.Guild, user: discord.abc.User) -> bool:
        # cache ellenőrzés
        ch_id = self.open_by_user.get(user.id)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel) and (ch.category_id != ARCHIVE_CATEGORY_ID):
                return True
            # cache takarítás
            self.open_by_user.pop(user.id, None)

        tag = f"{TICKET_TAG}{user.id}"
        for ch in guild.text_channels:
            if ch.category_id == ARCHIVE_CATEGORY_ID:
                continue
            if (ch.topic or "").find(tag) != -1:
                self.open_by_user[user.id] = ch.id
                return True
        return False

    def _check_cooldown(self, user_id: int) -> int:
        """Visszaadja a hátralévő másodperceket (0 ha nincs cooldown)."""
        last = self.last_open_at.get(user_id, 0.0)
        left = COOLDOWN_SECONDS - int(time.time() - last)
        return max(0, left)

    async def _build_overwrites(
        self, guild: discord.Guild, member: discord.Member
    ) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
        # FONTOS: dict kell, nem lista!
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                add_reactions=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }
        if STAFF_ROLE_ID:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                    manage_messages=True,
                )
        return overwrites

    # ------ Folyamat ------

    async def show_category_picker(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        if not guild:
            return

        # meglévő ticket tiltás
        if await self._user_has_open(guild, user):
            await interaction.response.send_message(
                "Már van nyitott ticketed. Zárd be, mielőtt újat nyitsz.",
                ephemeral=True,
            )
            return

        # cooldown
        left = self._check_cooldown(user.id)
        if left > 0:
            await interaction.response.send_message(
                f"Várj még **{left}** mp-et, mielőtt új ticketet nyitsz.",
                ephemeral=True,
            )
            return

        # kategória választó (ephemeral)
        view = CategoryView(self)
        await interaction.response.send_message(
            "Válassz kategóriát:", view=view, ephemeral=True
        )

    async def on_category_chosen(self, interaction: discord.Interaction, key: str):
        guild = interaction.guild
        member = interaction.user
        if not (guild and isinstance(member, discord.Member)):
            return

        # dupla kattintások megelőzése – azonnal defer
        await interaction.response.defer(ephemeral=True, thinking=True)

        if await self._user_has_open(guild, member):
            await interaction.followup.send(
                "Már van nyitott ticketed. Zárd be, mielőtt újat nyitsz.",
                ephemeral=True,
            )
            return

        left = self._check_cooldown(member.id)
        if left > 0:
            await interaction.followup.send(
                f"Várj még **{left}** mp-et, mielőtt új ticketet nyitsz.",
                ephemeral=True,
            )
            return

        cat = self._tickets_category(guild)
        if not cat:
            await interaction.followup.send(
                "A ticket kategória nincs beállítva vagy nem található. "
                "Ellenőrizd a TICKETS_CATEGORY_ID értékét.",
                ephemeral=True,
            )
            return

        try:
            name = f"{key}-{member.display_name}".lower().replace(" ", "-")
            topic = f"{key} | {TICKET_TAG}{member.id}"
            overwrites = await self._build_overwrites(guild, member)

            ch = await guild.create_text_channel(
                name=name, category=cat, topic=topic, overwrites=overwrites
            )

            self.open_by_user[member.id] = ch.id
            self.last_open_at[member.id] = time.time()

            await ch.send(
                f"{member.mention} ticketet nyitott (**{key}**).",
                view=CloseTicketView(self),
            )

            await interaction.followup.send(f"A ticketed elkészült: {ch.mention}", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send(
                "Nincs jogosultságom csatornát létrehozni ebben a kategóriában. "
                "Adj **Manage Channels** és **Manage Messages** jogokat a botnak.",
                ephemeral=True,
            )
        except TypeError as te:
            # ide nem kellene visszaesni, de ha mégis…
            await interaction.followup.send(
                f"Hiba a csatorna létrehozásánál: {te}", ephemeral=True
            )
        except Exception as e:
            log.exception("Ticket create failed")
            await interaction.followup.send(
                f"Váratlan hiba történt a ticket létrehozásakor.", ephemeral=True
            )

    async def close_ticket(self, interaction: discord.Interaction):
        ch = interaction.channel
        guild = interaction.guild
        if not (guild and isinstance(ch, discord.TextChannel)):
            return

        topic = ch.topic or ""
        if TICKET_TAG not in topic:
            await interaction.response.send_message(
                "Ez nem ticket csatorna.", ephemeral=True
            )
            return

        # ki zárhatja: tulaj vagy staff/admin
        try:
            user_id = int(topic.split(TICKET_TAG)[1].split()[0])
        except Exception:
            user_id = 0

        is_owner = interaction.user.id == user_id
        is_staff = interaction.user.guild_permissions.manage_channels

        if not (is_owner or is_staff):
            await interaction.response.send_message(
                "Ezt csak a ticket tulajdonosa vagy egy moderátor zárhatja be.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # user elől elrejtés
        overwrites = ch.overwrites
        member = guild.get_member(user_id)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=False)

        # átmozgatás archívba (ha van)
        archive = self._archive_category(guild)

        try:
            await ch.edit(
                name=f"closed-{ch.name}",
                topic=f"{topic} | closed",
                overwrites=overwrites,
                category=archive or ch.category,
            )
        except Exception:
            log.exception("Close edit failed")

        self.open_by_user.pop(user_id, None)
        await ch.send("A ticket lezárva. Köszönjük!")

    # ------ Slash parancsok ------

    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="ticket_hub_setup", description="Open Ticket üzenet kihelyezése a hubba.")
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        hub = guild.get_channel(TICKET_HUB_CHANNEL_ID) if TICKET_HUB_CHANNEL_ID else None
        if not isinstance(hub, discord.TextChannel):
            hub = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None

        if not hub:
            await interaction.response.send_message(
                "Nem találom a hub csatornát. Állítsd be a TICKET_HUB_CHANNEL_ID-t.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        embed = discord.Embed(
            title="Ticket Hub",
            description=(
                "Nyomd meg az **Open Ticket** gombot. A következő lépésben kategóriát választasz.\n"
                "_A kategóriaválasztás ephemeral üzenetben jön, nem koszolja a csatornát._"
            ),
            color=discord.Color.blurple(),
        )
        await hub.send(embed=embed, view=OpenTicketView(self))
        await interaction.followup.send("Kész! A gomb kihelyezve.", ephemeral=True)

    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="ticket_hub_cleanup", description="A bot üzeneteinek takarítása a hubban.")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        hub = guild.get_channel(TICKET_HUB_CHANNEL_ID) if TICKET_HUB_CHANNEL_ID else None
        if not isinstance(hub, discord.TextChannel):
            hub = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None

        if not hub:
            await interaction.response.send_message(
                "Nem találom a hub csatornát. Állítsd be a TICKET_HUB_CHANNEL_ID-t.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        deleted = 0
        async for msg in hub.history(limit=200):
            if msg.author == self.bot.user:
                try:
                    await msg.delete()
                    deleted += 1
                except Exception:
                    pass

        await interaction.followup.send(
            f"Cleanup kész. Törölt üzenetek: **{deleted}**", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
