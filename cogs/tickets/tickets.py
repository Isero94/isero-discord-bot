# cogs/tickets/tickets.py
from __future__ import annotations

import os
from typing import Optional, Tuple

import discord
from discord import app_commands, Interaction
from discord.ext import commands
from loguru import logger

# --- Beállítások / konstansok ---
HUB_CHANNEL_ENV = "TICKET_HUB_CHANNEL_ID"  # a hub csatorna ID-ja .env-ben / Render env-ben

BTN_MEBINU     = "tickets:mebinu"
BTN_COMMISSION = "tickets:commission"
BTN_NSFW       = "tickets:nsfw18"
BTN_HELP       = "tickets:help"

TICKET_CATEGORY_NAME = "tickets"
TICKET_THREAD_PREFIX = "MEBINU | "  # thread cím előtag (személyre szabható)


def _env_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    try:
        return int(raw) if raw else None
    except Exception:
        return None


# ---------- VIEW: gombok saját callbackekkel ----------
class TicketHubView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)  # persistent
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.primary, custom_id=BTN_MEBINU)
    async def btn_mebinu(self, interaction: Interaction, button: discord.ui.Button):
        await self.cog._open_ticket(interaction, "Mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary, custom_id=BTN_COMMISSION)
    async def btn_commission(self, interaction: Interaction, button: discord.ui.Button):
        await self.cog._open_ticket(interaction, "Commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id=BTN_NSFW)
    async def btn_nsfw(self, interaction: Interaction, button: discord.ui.Button):
        await self.cog._open_ticket(interaction, "NSFW 18+")

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id=BTN_HELP)
    async def btn_help(self, interaction: Interaction, button: discord.ui.Button):
        await self.cog._open_ticket(interaction, "General Help")


# ---------- COG ----------
class Tickets(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.hub_channel_id: Optional[int] = _env_int(HUB_CHANNEL_ENV)

        # Persistent view regisztrálása (custom_id-k alapján túlél újraindítást)
        self.view = TicketHubView(self)
        self.bot.add_view(self.view)

    # ---- belső segédfüggvények ----
    def _get_hub_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        if not self.hub_channel_id:
            return None
        ch = guild.get_channel(self.hub_channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    @staticmethod
    def _hub_embed() -> discord.Embed:
        e = discord.Embed(
            title="Üdv a(z) #🧾｜ticket-hub-ban!",
            description=(
                "Válassz kategóriát a gombokkal. A rendszer külön privát threadet nyit neked.\n\n"
                "**Mebinu** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
                "**Commission** — Fizetős, egyedi art megbízás (scope, budget, határidő).\n"
                "**NSFW 18+** — Csak 18+; szigorúbb szabályzat & review.\n"
                "**General Help** — Gyors kérdés–válasz, útmutatás."
            ),
            colour=discord.Colour.blurple(),
        )
        e.set_footer(text="ISERO tickets")
        return e

    async def _post_hub_card(self, channel: discord.TextChannel) -> discord.Message:
        embed = self._hub_embed()
        return await channel.send(embed=embed, view=self.view)

    async def _ensure_category(self, guild: discord.Guild) -> discord.CategoryChannel:
        cat = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        if cat:
            return cat
        return await guild.create_category(TICKET_CATEGORY_NAME, reason="ISERO ticket rendszer")

    async def _delete_bot_messages(self, channel: discord.TextChannel) -> int:
        """Csak a bot által küldött üzenetek törlése a hub csatornában."""
        removed = 0
        async for msg in channel.history(limit=200):
            if msg.author == self.bot.user:
                try:
                    await msg.delete()
                    removed += 1
                except Exception as e:
                    logger.warning("Nem tudtam törölni egy üzenetet: {}", e)
        return removed

    async def _delete_ticket_threads(self, channel: discord.TextChannel) -> Tuple[int, int]:
        """A hubhoz tartozó threadek törlése (nyitott + archivált)."""
        removed_open = 0
        removed_arch = 0

        # Nyitott threadek
        for th in channel.threads:
            try:
                await th.delete()
                removed_open += 1
            except Exception as e:
                logger.warning("Thread törlés (open) hiba: {}", e)

        # Archivált threadek
        try:
            async for th in channel.archived_threads(limit=100):
                try:
                    await th.delete()
                    removed_arch += 1
                except Exception as e:
                    logger.warning("Thread törlés (archived) hiba: {}", e)
        except Exception as e:
            logger.warning("Archived threadek listázása sikertelen: {}", e)

        return removed_open, removed_arch

    async def _open_ticket(self, interaction: Interaction, kind: str):
        """Gomb-nyomásra új privát thread nyitása a hub csatornában."""
        await interaction.response.defer(ephemeral=True)

        hub = self._get_hub_channel(interaction.guild)
        if not hub:
            await interaction.followup.send(
                "⚠️ A hub csatorna nincs beállítva. Állítsd be a Render env-ben a **TICKET_HUB_CHANNEL_ID**-t.",
                ephemeral=True,
            )
            return

        category = await self._ensure_category(interaction.guild)

        title = f"{TICKET_THREAD_PREFIX}{interaction.user.display_name} — {kind}"
        try:
            thread = await hub.create_thread(name=title, type=discord.ChannelType.public_thread)
            # opció: áthelyezés kategóriába → thread-et nem lehet közvetlenül kategóriához rendelni,
            # ezért a hub csatorna helye határozza meg. Ha külön csatornát akarsz kategóriába,
            # itt lehetne létrehozni és abban nyitni threadet.
        except Exception as e:
            logger.error("Thread nyitási hiba: {}", e)
            await interaction.followup.send("❌ Nem sikerült ticketet nyitni. Nézd meg a bot jogosultságait.", ephemeral=True)
            return

        try:
            await thread.add_user(interaction.user)
        except Exception:
            pass  # ha már benne van / nincs jog, nem kritikus

        await interaction.followup.send(
            f"✅ Ticket nyitva: {thread.mention}  *(típus: {kind})*",
            ephemeral=True,
        )

    # ---- slash parancsok (admin/staff) ----

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.command(name="ticket_hub_setup", description="Ticket-hub üzenet újraküldése a hub csatornába.")
    async def ticket_hub_setup(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        hub = self._get_hub_channel(interaction.guild)
        if not hub:
            await interaction.followup.send(
                f"⚠️ Nincs beállítva hub csatorna. Add meg env-ben: **{HUB_CHANNEL_ENV}**.",
                ephemeral=True,
            )
            return

        removed = await self._delete_bot_messages(hub)
        msg = await self._post_hub_card(hub)
        logger.info("Hub újraküldve. Törölt bot üzenetek: {}. MsgID={}", removed, msg.id)
        await interaction.followup.send(
            f"✅ Hub frissítve. Törölt bot üzenetek: **{removed}**. Csatorna: {hub.mention}",
            ephemeral=True,
        )

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.command(name="ticket_hub_cleanup", description="Régi hub üzenetek és ticket threadek takarítása.")
    async def ticket_hub_cleanup(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        hub = self._get_hub_channel(interaction.guild)
        if not hub:
            await interaction.followup.send(
                f"⚠️ Nincs beállítva hub csatorna. Add meg env-ben: **{HUB_CHANNEL_ENV}**.",
                ephemeral=True,
            )
            return

        removed_msgs = await self._delete_bot_messages(hub)
        removed_open, removed_arch = await self._delete_ticket_threads(hub)

        logger.info(
            "TicketHub cleanup: msgs={}, threads_open={}, threads_arch={}",
            removed_msgs, removed_open, removed_arch
        )
        await interaction.followup.send(
            f"🧹 Kész. Törölt bot üzenetek: **{removed_msgs}**. "
            f"Threadek: **{removed_open}** nyitott, **{removed_arch}** archivált.",
            ephemeral=True,
        )


# --- kötelező belépési pont az extension-höz ---
async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
