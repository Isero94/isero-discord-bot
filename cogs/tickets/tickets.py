# cogs/tickets/tickets.py
from __future__ import annotations

import asyncio
from typing import Optional, Iterable

import discord
from discord import app_commands
from discord.ext import commands


HUB_TITLE = "Üdv a(z) #️⃣ | ticket-hub-ban!"
HUB_DESC = (
    "Válassz kategóriát a gombokkal. A rendszer külön privát threadet nyit neked.\n\n"
    "**Mebinu** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
    "**Commission** — Fizetős, egyedi art megbízás (scope, budget, határidő).\n"
    "**NSFW 18+** — Csak 18+; szigorúbb szabályzat & review.\n"
    "**General Help** — Gyors kérdés-válasz, útmutatás."
)

BTN_CUSTOM_IDS = {
    "mebinu": "ticket:mebinu",
    "commission": "ticket:commission",
    "nsfw": "ticket:nsfw",
    "help": "ticket:help",
}


def _is_our_hub_message(msg: discord.Message) -> bool:
    """Heurisztika: saját hub-kártya vagy a hozzá tartozó gombok."""
    if msg.author.bot:
        # Ha van embed és a cím egyezik
        if msg.embeds:
            title = (msg.embeds[0].title or "").strip()
            if title == HUB_TITLE:
                return True
        # Ha vannak komponensek és a custom_id-k egyeznek
        for row in msg.components:
            for comp in row.children:
                if isinstance(comp, discord.Button) and comp.custom_id in BTN_CUSTOM_IDS.values():
                    return True
    return False


class TicketHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)  # persistent
        self.bot = bot

    async def _open_thread(
        self,
        interaction: discord.Interaction,
        label: str,
    ):
        channel = interaction.channel
        assert isinstance(channel, discord.TextChannel), "A hubnak szöveges csatornának kell lennie."

        # A thread neve
        thread_name = f"{label.upper()} | {interaction.user.display_name}"

        # Privát thread létrehozása (7 nap auto-archive)
        try:
            new_thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=10080,
                reason=f"Ticket hub – {label} by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Nincs jogosultságom privát threadet nyitni itt (Manage Threads, Create Private Threads szükséges).",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.response.send_message(f"Hiba történt a thread nyitásakor: `{e}`", ephemeral=True)
            return

        # Felhasználó hozzáadása és köszöntő
        try:
            await new_thread.add_user(interaction.user)
        except Exception:
            pass

        try:
            await new_thread.send(
                f"Üdv {interaction.user.mention}! Ez a privát szál a(z) **{label}** kategóriához. "
                f"Írd le a részleteket; itt folytatjuk. "
            )
        except Exception:
            pass

        # Ephemeral visszajelzés linkkel
        if interaction.response.is_done():
            await interaction.followup.send(f"Thread nyitva: {new_thread.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Thread nyitva: {new_thread.mention}", ephemeral=True)

    # Gombok (persistent custom_id-val)
    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.primary, custom_id=BTN_CUSTOM_IDS["mebinu"])
    async def btn_mebinu(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "Mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary, custom_id=BTN_CUSTOM_IDS["commission"])
    async def btn_commission(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "Commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id=BTN_CUSTOM_IDS["nsfw"])
    async def btn_nsfw(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "NSFW 18+")

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id=BTN_CUSTOM_IDS["help"])
    async def btn_help(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "General Help")


class Tickets(commands.Cog, name="tickets"):
    """Ticket hub cog: setup + cleanup + gombok."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Persistent view regisztrálása (restart után is élnek a gombok)
        self.bot.add_view(TicketHubView(self.bot))

    # --- HUB SETUP ---

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name="ticket_hub_setup", description="TicketHub kártya és gombok kihelyezése a jelenlegi csatornába.")
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Ezt csak szöveges csatornában tudom futtatni.", ephemeral=True)
            return

        embed = discord.Embed(
            title=HUB_TITLE,
            description=HUB_DESC,
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text="ticket_hub")

        view = TicketHubView(self.bot)

        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.followup.send("Hub kártya kihelyezve ebbe a csatornába.", ephemeral=True)

    # --- HUB CLEANUP ---

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        deep="Ha be van kapcsolva, a bot által nyitott threadeket (aktív + archivált) is törlöm.",
    )
    @app_commands.command(name="ticket_hub_cleanup", description="Régi hub üzenetek és (opcionálisan) bot-threadek törlése ebben a csatornában.")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: bool = True):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Ezt csak szöveges csatornában tudom futtatni.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1) Régi üzenetek törlése — EGYENKÉNT, hogy 14+ naposaknál se akadjon el
        removed_msgs = 0

        async for msg in channel.history(limit=None, oldest_first=True):
            try:
                if msg.author.id == self.bot.user.id or _is_our_hub_message(msg):
                    # Pinned üzeneteket is leszedjük
                    if msg.pinned:
                        try:
                            await msg.unpin(reason="TicketHub cleanup")
                        except Exception:
                            pass
                    await msg.delete()
                    removed_msgs += 1
            except discord.Forbidden:
                # Nincs jog törölni – továbblépünk, de jelezzük a végén
                pass
            except Exception:
                pass

        # 2) Threadek törlése (ha deep)
        removed_threads = 0
        if deep:
            # Aktív threadek
            for th in list(channel.threads):
                try:
                    if th.owner_id == self.bot.user.id:
                        await th.delete(reason="TicketHub cleanup (active)")
                        removed_threads += 1
                except Exception:
                    # Ha nem sikerül, próbáljuk archiválni és újrapróbálni
                    try:
                        await th.edit(archived=True, locked=True, reason="TicketHub cleanup (force-archive)")
                        await asyncio.sleep(0.2)
                        await th.delete(reason="TicketHub cleanup (after-archive)")
                        removed_threads += 1
                    except Exception:
                        pass

            # Archivált threadek – public
            try:
                async for th in channel.archived_threads(limit=None, private=False):
                    try:
                        if th.owner_id == self.bot.user.id:
                            await th.delete(reason="TicketHub cleanup (archived public)")
                            removed_threads += 1
                    except Exception:
                        pass
            except Exception:
                pass

            # Archivált threadek – private
            try:
                async for th in channel.archived_threads(limit=None, private=True):
                    try:
                        if th.owner_id == self.bot.user.id:
                            await th.delete(reason="TicketHub cleanup (archived private)")
                            removed_threads += 1
                    except Exception:
                        pass
            except Exception:
                pass

        await interaction.followup.send(
            f"✅ Takarítás kész.\n"
            f"• Törölt üzenetek: **{removed_msgs}**\n"
            f"• Törölt threadek: **{removed_threads}**{' (mély takarítás)' if deep else ''}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
