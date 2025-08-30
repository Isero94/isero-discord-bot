# cogs/tickets/tickets.py
# Teljes, önállóan bemásolható verzió (discord.py 2.4.x)
# Funkciók:
# - Ticket Hub panel (Open Ticket) – persistent view
# - Kategória-választó (Mebinu / Commission / NSFW 18+ / General Help) – ephemerálisan
# - NSFW 18+ megerősítés (Yes/No)
# - Egy felhasználó = 1 aktív ticket (archív nem számít)
# - Per-user cooldown (ENV: TICKET_COOLDOWN_SECONDS, default 20)
# - /ticket_hub_setup  – hub újrapakolása (opcionális takarítással)
# - /ticket_hub_cleanup – takarítás + hub visszarakás (interaction defer → followup, nincs “Unknown interaction”)
# - /close – ticket lezárás/archiválás (ARCHIVE_CATEGORY_ID használatával, ha megadott)
#
# Szükséges ENV változók Renderen:
#   TICKET_HUB_CHANNEL_ID    (szám)
#   TICKETS_CATEGORY_ID      (szám)
#   ARCHIVE_CATEGORY_ID      (szám, opcionális; ha nincs, a ticket kategóriában hagyjuk és "arch-" prefixet kap)
#   TICKET_COOLDOWN_SECONDS  (szám, opcionális; default 20)
#   OWNER_ID                 (szám – a tulaj; csak naplózásnál használjuk itt)
#
# Megjegyzés:
# - A ticket csatorna topic-jába bekerül: "owner:<USER_ID> | opened:<ISO_DATETIME>"
#   Ezt használjuk az "egy aktív ticket / user" gyors ellenőrzésére.

from __future__ import annotations

import os
import re
import logging
import asyncio
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands


log = logging.getLogger(__name__)

# ------------------------------- Segéd --------------------------------- #

def _to_int(env_name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(env_name, "").strip() or default)
    except Exception:
        return default


def _slugify(name: str) -> str:
    """Egyszerű, discord-csatorna-barát név."""
    s = name.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_.]", "", s)
    s = s.strip("-._")
    return s or "user"


# ------------------------------ A Cog ---------------------------------- #

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.hub_channel_id: int = _to_int("TICKET_HUB_CHANNEL_ID")
        self.ticket_category_id: int = _to_int("TICKETS_CATEGORY_ID")
        self.archive_category_id: Optional[int] = _to_int("ARCHIVE_CATEGORY_ID") or None
        self.cooldown_secs: int = _to_int("TICKET_COOLDOWN_SECONDS", 20)

        # per-user cooldown: {user_id: monotonic_until}
        self.cooldowns: dict[int, float] = {}

        self._views_added = False

    # ---- Életciklus ---- #

    async def cog_load(self) -> None:
        # Persistent view: csak a HubView-ot kell beregisztrálni
        if not self._views_added:
            self.bot.add_view(HubView(self))  # timeout=None, persistent
            self._views_added = True
        log.info("[ISERO] Tickets cog loaded (persistent view ready)")

    # --------------------- Publikus segédfüggvények --------------------- #

    async def post_hub(self, channel: discord.TextChannel) -> None:
        """Kiteszi a Hub panelt az adott csatornába."""
        embed = discord.Embed(
            title="Ticket Hub",
            description="Nyomd meg az **Open Ticket** gombot a kezdéshez. A következő lépésben kategóriát választasz.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Kattints a gombra. A kategóriaválasztás következik.")
        try:
            await channel.send(embed=embed, view=HubView(self))
        except discord.HTTPException as e:
            log.warning("Hub post failed: %r", e)

    async def get_hub_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        ch = guild.get_channel(self.hub_channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    def get_ticket_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        cat = guild.get_channel(self.ticket_category_id)
        return cat if isinstance(cat, discord.CategoryChannel) else None

    def get_archive_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        if not self.archive_category_id:
            return None
        cat = guild.get_channel(self.archive_category_id)
        return cat if isinstance(cat, discord.CategoryChannel) else None

    async def has_open_ticket(self, guild: discord.Guild, user_id: int) -> bool:
        """True ha a felhasználónak van **aktív** ticketje (archív nem számít)."""
        cat = self.get_ticket_category(guild)
        if not cat:
            return False
        for ch in cat.channels:
            if isinstance(ch, discord.TextChannel) and ch.topic:
                if f"owner:{user_id}" in ch.topic and not ch.name.startswith("arch-"):
                    return True
        return False

    def _category_embed(self) -> discord.Embed:
        em = discord.Embed(
            title="Válassz kategóriát:",
            description=(
                "• **Mebinu** — Gyűjthető figurák: kérések, variánsok, kódok, ritkaság.\n"
                "• **Commission** — Fizetős megbízás: terjedelem, költség, határidő.\n"
                "• **NSFW 18+** — Csak felnőtteknek; szigorúbb szabályok.\n"
                "• **General Help** — Gyors Q&A és iránymutatás.\n"
            ),
            color=discord.Color.dark_theme()
        )
        return em

    async def create_ticket_channel(
        self,
        interaction: discord.Interaction,
        category_key: Literal["mebinu", "commission", "nsfw", "help"]
    ) -> discord.TextChannel:
        """Létrehoz egy ticket csatornát a ticket kategóriában.
        A kategória-permeket **örökli** (sync), így a staff jogokat elég a kategórián állítani.
        """
        guild = interaction.guild
        assert guild is not None

        cat = self.get_ticket_category(guild)
        if not cat:
            raise RuntimeError("TICKETS_CATEGORY_ID hibás vagy nincs beállítva.")

        uname = _slugify(interaction.user.name)
        base = f"{category_key}-{uname}"
        name = base

        # Ütközés esetén toldunk egy rövid számlálót
        i = 2
        while discord.utils.get(cat.channels, name=name):
            name = f"{base}-{i}"
            i += 1

        topic = f"owner:{interaction.user.id} | opened:{discord.utils.utcnow().isoformat()}"

        # A kategóriáról szinkronizáljuk a jogosultságokat: staff elérést ott kezeld.
        ch = await guild.create_text_channel(
            name=name,
            category=cat,
            topic=topic
        )

        # Üdvözlő üzenet a csatornába
        greet = discord.Embed(
            title="Üdv a ticketedben!",
            description=(
                "Írd le röviden, miben tudunk segíteni.\n\n"
                "Ha végeztünk, használd a **/close** parancsot a lezáráshoz.\n"
            ),
            color=discord.Color.green()
        )
        greet.set_footer(text=f"Kategória: {category_key.upper()} • Tulaj: {interaction.user.name}")
        try:
            await ch.send(content=interaction.user.mention, embed=greet)
        except discord.HTTPException:
            pass

        return ch

    # ------------------------------- Parancsok ------------------------------ #

    @app_commands.command(name="ticket_hub_setup", description="Ticket hub panel kihelyezése (opcionálisan takarít is).")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, interaction: discord.Interaction, cleanup: Optional[bool] = False):
        await interaction.response.defer(ephemeral=True, thinking=False)

        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("Csak szerveren használható.", ephemeral=True)

        hub = await self.get_hub_channel(guild)
        if not hub:
            return await interaction.followup.send("A TICKET_HUB_CHANNEL_ID nincs jól beállítva.", ephemeral=True)

        deleted = 0
        if cleanup:
            async for m in hub.history(limit=None, oldest_first=False):
                if m.author == self.bot.user:
                    try:
                        await m.delete()
                        deleted += 1
                    except discord.HTTPException:
                        pass

        await self.post_hub(hub)
        await interaction.followup.send(f"Hub kész. Törölt üzenetek: **{deleted}**", ephemeral=True)

    @app_commands.command(name="ticket_hub_cleanup", description="Hub takarítás és panel visszarakás.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        # Unknown interaction elkerülése: defer → hosszabb művelet jöhet
        await interaction.response.defer(ephemeral=True, thinking=False)

        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("Csak szerveren használható.", ephemeral=True)

        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("Nem szövegcsatorna.", ephemeral=True)

        deleted = 0
        try:
            async for m in ch.history(limit=None, oldest_first=False):
                # deep=True esetén agresszívabban pucolunk (bot összes üzenete),
                # deep=False esetén csak a panel/komponensek tipikus üzeneteit.
                if m.author == self.bot.user:
                    if not deep:
                        # hagyhatnánk más bot-üzeneteket is, de praktikus mindent vinni
                        pass
                    try:
                        await m.delete()
                        deleted += 1
                    except discord.HTTPException:
                        pass
        finally:
            # Panel visszarakása
            await self.post_hub(ch)

        await interaction.followup.send(f"Cleanup kész. Törölve: **{deleted}**", ephemeral=True)

    @app_commands.command(name="close", description="Lezárja és archiválja az aktuális ticketet.")
    async def close_ticket(self, interaction: discord.Interaction, reason: Optional[str] = None):
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message("Nem ticket csatorna.", ephemeral=True)

        # Csak ticket csatornán legyen használható (topicban owner:<id>)
        if not (ch.topic and "owner:" in ch.topic):
            return await interaction.response.send_message("Ez nem ticket csatorna.", ephemeral=True)

        # Jogosultság: staff (manage_channels) VAGY a ticket tulaja
        is_staff = interaction.user.guild_permissions.manage_channels
        is_owner = False
        try:
            m = re.search(r"owner:(\d+)", ch.topic or "")
            if m and int(m.group(1)) == interaction.user.id:
                is_owner = True
        except Exception:
            pass

        if not (is_staff or is_owner):
            return await interaction.response.send_message("Nincs jogod lezárni ezt a ticketet.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=False)

        guild = interaction.guild
        assert guild is not None

        new_name = ch.name
        if not new_name.startswith("arch-"):
            new_name = f"arch-{new_name}"

        new_category = self.get_archive_category(guild) or ch.category

        try:
            await ch.edit(name=new_name, category=new_category)
        except discord.HTTPException as e:
            log.warning("Ticket archive edit failed: %r", e)

        await interaction.followup.send("Ticket archiválva. Köszönjük!", ephemeral=True)

    # ---------------------------- View callbackok --------------------------- #

    async def on_open_ticket_clicked(self, interaction: discord.Interaction):
        """Open Ticket gomb callback – itt dől el minden:
           - van-e aktív ticket
           - cooldown
           - ha oké, kategória-választó megy EPHEMERÁLIS üzenetként
        """
        import time

        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)

        # Aktív ticket check ELŐSZÖR → ne jelenjen meg a választó se.
        if await self.has_open_ticket(guild, interaction.user.id):
            return await interaction.response.send_message(
                "Már van egy nyitott ticketed. Zárd le a **/close** paranccsal, mielőtt újat nyitsz.",
                ephemeral=True
            )

        # Cooldown
        now = time.monotonic()
        until = self.cooldowns.get(interaction.user.id, 0.0)
        if now < until:
            return await interaction.response.send_message(
                "Kérlek, várj egy kicsit, mielőtt új ticketet nyitsz.",
                ephemeral=True
            )
        self.cooldowns[interaction.user.id] = now + float(self.cooldown_secs)

        # Kategória-választó (ephemeral) – így a hub tiszta marad
        await interaction.response.send_message(
            embed=self._category_embed(),
            view=CategoryView(self),
            ephemeral=True
        )

    async def on_category_chosen(self, interaction: discord.Interaction, category_key: str):
        """Mebinu / Commission / Help közvetlenül ticketet nyit;
           NSFW külön megerősítést kér.
        """
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)

        if category_key == "nsfw":
            # NSFW megerősítés
            return await interaction.response.edit_message(
                embed=discord.Embed(
                    title="Elmúltál 18 éves?",
                    color=discord.Color.red()
                ),
                view=NSFWConfirmView(self)
            )

        # Egyéb kategóriák – ticket létrehozás
        ch = await self.create_ticket_channel(interaction, category_key)  # type: ignore
        # Tisztítjuk az ephemeral üzenetet (választó eltűnik)
        await interaction.response.edit_message(content=None, embed=None, view=None)
        # Privát link a usernek
        await interaction.followup.send(f"A ticketed elkészült: {ch.mention}", ephemeral=True)

    async def on_nsfw_confirm(self, interaction: discord.Interaction, confirmed: bool):
        if not confirmed:
            try:
                await interaction.response.edit_message(content="Értettem, nem nyitunk NSFW ticketet.", embed=None, view=None)
            except discord.HTTPException:
                pass
            return

        # Igen → NSFW ticket
        ch = await self.create_ticket_channel(interaction, "nsfw")  # type: ignore
        try:
            await interaction.response.edit_message(content=None, embed=None, view=None)
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"A ticketed elkészült: {ch.mention}", ephemeral=True)


# ------------------------------- Views ---------------------------------- #

class HubView(discord.ui.View):
    """Állandó (persistent) view a hub üzeneten."""
    def __init__(self, cog: Tickets):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_open_ticket_clicked(interaction)


class CategoryView(discord.ui.View):
    """Ephemeral kategória választó (nem persistent)."""
    def __init__(self, cog: Tickets):
        super().__init__(timeout=180)  # 3 perc után magától lejár
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary)
    async def mebinu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary)
    async def commission(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def nsfw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "nsfw")

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_category_chosen(interaction, "help")


class NSFWConfirmView(discord.ui.View):
    """NSFW megerősítés Yes/No – ephemeral."""
    def __init__(self, cog: Tickets):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_nsfw_confirm(interaction, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.on_nsfw_confirm(interaction, False)


# ----------------------------- setup() ---------------------------------- #

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
