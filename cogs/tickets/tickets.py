# cogs/tickets/tickets.py
from __future__ import annotations

import os
from typing import Optional, Callable, Iterable, AsyncIterator

import discord
from discord import app_commands, Interaction
from discord.ext import commands
from loguru import logger


HUB_CHANNEL_ENV = "TICKET_HUB_CHANNEL_ID"

# Gombok egyedi custom_id-jei (persistent View-hoz)
BTN_MEBINU = "tickets:mebinu"
BTN_COMM   = "tickets:commission"
BTN_NSFW   = "tickets:nsfw18"
BTN_HELP   = "tickets:general"


def _env_int(name: str) -> Optional[int]:
    v = os.environ.get(name)
    try:
        return int(v) if v else None
    except Exception:
        return None


class TicketHubView(discord.ui.View):
    """Perzisztens gombsor a TicketHubhoz."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Mebinu",    custom_id=BTN_MEBINU, style=discord.ButtonStyle.primary))
        self.add_item(discord.ui.Button(label="Commission", custom_id=BTN_COMM,  style=discord.ButtonStyle.secondary))
        self.add_item(discord.ui.Button(label="NSFW 18+",   custom_id=BTN_NSFW,  style=discord.ButtonStyle.danger))
        self.add_item(discord.ui.Button(label="General Help", custom_id=BTN_HELP, style=discord.ButtonStyle.success))

    async def interaction_check(self, interaction: Interaction) -> bool:
        # Ticket gombokra mindenki kattinthat
        return True

    # A négy gomb mind ugyanide fut be a custom_id alapján
    @discord.ui.button(label="hidden", style=discord.ButtonStyle.secondary)
    async def _hidden(self, *_):  # sose hívódik; csak hogy View ne legyen üres
        pass

    async def on_error(self, error: Exception, item, interaction: Interaction) -> None:  # pragma: no cover
        logger.exception(error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Hiba történt…", ephemeral=True)


class Tickets(commands.Cog, name="tickets"):
    """Ticket Hub kiépítése és takarítása, thread-nyitás gombokkal."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.hub_channel_id: Optional[int] = _env_int(HUB_CHANNEL_ENV)

        # Persistent view regisztrálása reboot után is
        self.view = TicketHubView()
        bot.add_view(self.view)

        # gomb callbackek drótolása:
        bot.tree.add_command(app_commands.Command(
            name="tickets_button_router",
            description="internal",
            callback=self._button_router,  # nem látszik, csak a custom_id-k hívják
        ), override=True)

    # ---- Segédek ----------------------------------------------------------

    def _hub(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        if not self.hub_channel_id:
            return None
        ch = guild.get_channel(self.hub_channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    @staticmethod
    def _hub_embed() -> discord.Embed:
        e = discord.Embed(
            title="Üdv a(z) #🧾｜ticket-hub-ban!",
            description=(
                "Válassz kategóriát a gombokkal. A rendszer külön **privát threadet** nyit neked.\n\n"
                "**Mebinu** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
                "**Commission** — Fizetős, egyedi art megbízás *(scope, budget, határidő).* \n"
                "**NSFW 18+** — Csak 18+; szigorúbb szabályzat & review.\n"
                "**General Help** — Gyors kérdés–válasz, útmutatás."
            ),
            color=discord.Color.blurple(),
        )
        return e

    async def _post_hub_card(self, channel: discord.TextChannel) -> discord.Message:
        return await channel.send(embed=self._hub_embed(), view=self.view)

    async def _delete_bot_messages(self, channel: discord.TextChannel) -> int:
        """Töröl minden BOT-üzenetet a hubban (óvatosan, limit=2000)."""
        deleted = 0
        async for msg in channel.history(limit=2000, oldest_first=False):
            if msg.author == self.bot.user:
                try:
                    await msg.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass
        return deleted

    async def _delete_our_threads(self, channel: discord.TextChannel) -> int:
        """Törli a bot által létrehozott aktív és archivált threadeket a hub alatt."""
        count = 0

        # Aktív threadek
        for th in list(channel.threads):
            if th.owner_id == self.bot.user.id:
                try:
                    await th.delete()
                    count += 1
                except discord.HTTPException:
                    pass

        # Archivált threadek
        try:
            async for ath in channel.archived_threads(limit=200):
                if ath.owner_id == self.bot.user.id:
                    try:
                        await ath.delete()
                        count += 1
                    except discord.HTTPException:
                        pass
        except AttributeError:
            # Egyes shard/permission esetekben archived_threads nem elérhető
            pass

        return count

    async def _open_ticket(self, interaction: Interaction, kind: str) -> None:
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Ezt csak szerveren lehet használni.", ephemeral=True)

        hub = self._hub(guild)
        if not hub:
            return await interaction.response.send_message(
                f"A hub csatorna nincs beállítva. Állítsd be env-ben: `{HUB_CHANNEL_ENV}`.",
                ephemeral=True,
            )

        title = f"{kind.upper()} | {interaction.user.display_name}"
        try:
            thread = await hub.create_thread(
                name=title,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=1440,
                invitable=False,
            )
        except discord.HTTPException:
            # fallback: publikus thread
            thread = await hub.create_thread(
                name=title,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
            )

        try:
            await thread.add_user(interaction.user)
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title=f"Ticket megnyitva — {kind}",
            description="Írd le röviden a kérést / problémát. A staff hamarosan válaszol.",
            color=discord.Color.green(),
        )
        await thread.send(content=interaction.user.mention, embed=embed)
        await interaction.response.send_message("Megnyitottam a privát threadet. ✔️", ephemeral=True)

    # ---- Gomb-router (custom_id alapján) ----------------------------------

    async def _button_router(self, interaction: Interaction):
        cid = interaction.data.get("custom_id") if isinstance(interaction.data, dict) else None
        if cid == BTN_MEBINU:
            return await self._open_ticket(interaction, "Mebinu")
        if cid == BTN_COMM:
            return await self._open_ticket(interaction, "Commission")
        if cid == BTN_NSFW:
            return await self._open_ticket(interaction, "NSFW 18+")
        if cid == BTN_HELP:
            return await self._open_ticket(interaction, "General Help")

    # ---- /ticket_hub_setup ------------------------------------------------

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.command(name="ticket_hub_setup", description="TicketHub kártya újraposztolása gombokkal.")
    async def ticket_hub_setup(self, interaction: Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)

        hub = self._hub(guild)
        if not hub:
            return await interaction.response.send_message(
                f"A hub csatorna nincs beállítva. Állítsd be env-ben: `{HUB_CHANNEL_ENV}`.",
                ephemeral=True,
            )

        msg = await self._post_hub_card(hub)
