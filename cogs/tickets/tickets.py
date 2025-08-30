# cogs/tickets/tickets.py
from __future__ import annotations

import os
import asyncio
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ---- Szövegek/kinézet
HUB_TITLE = "Ticket Hub"
HUB_DESC = "Nyiss jegyet az alábbi gombbal. A kategóriát a következő lépésben választod ki."
OPEN_BTN_ID = "ticket:open"

CATEGORY_IDS = {
    "mebinu": "ticket:cat:mebinu",
    "commission": "ticket:cat:commission",
    "nsfw": "ticket:cat:nsfw",
    "help": "ticket:cat:help",
}

CATEGORY_LABELS = {
    "mebinu": "Mebinu",
    "commission": "Commission",
    "nsfw": "NSFW 18+",
    "help": "General Help",
}

# ---- Boss azonosítás (env -> ha nincs, akkor admin is jó)
def is_boss(member: discord.Member) -> bool:
    env_id = os.getenv("BOSS_USER_ID")
    if env_id:
        try:
            return member.id == int(env_id)
        except Exception:
            pass
    return member.guild_permissions.administrator


# ===== Views =====

class OpenTicketView(discord.ui.View):
    """A hubban látható egyetlen gomb (persistent)."""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id=OPEN_BTN_ID)
    async def open_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        """A csatornát tisztán tartjuk: a kategóriaválasztó ephemerálisan jelenik meg."""
        if interaction.response.is_done():
            # safety: ha egyszer már válaszoltunk valami miatt
            await interaction.followup.send(
                "Válassz kategóriát:", view=CategorySelectView(self.bot), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Válassz kategóriát:", view=CategorySelectView(self.bot), ephemeral=True
            )


class CategorySelectView(discord.ui.View):
    """Ephemerális 4 gombos kategóriaválasztó."""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def _open_thread(self, interaction: discord.Interaction, label_key: str):
        channel = interaction.channel
        assert isinstance(channel, discord.TextChannel), "A hubnak szöveges csatornának kell lennie."

        label = CATEGORY_LABELS[label_key]
        thread_name = f"{label.upper()} | {interaction.user.display_name}"

        try:
            new_thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=10080,  # 7 nap
                reason=f"Ticket hub – {label} by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Nincs jogosultságom privát threadet nyitni (Manage Threads, Create Private Threads).",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.response.send_message(f"Hiba történt a thread nyitásakor: `{e}`", ephemeral=True)
            return

        # Add user
        try:
            await new_thread.add_user(interaction.user)
        except Exception:
            pass

        # Üdvözlő üzenet a threadben (itt fog beszélgetni az agenttel)
        try:
            await new_thread.send(
                f"Üdv {interaction.user.mention}! Ez a privát szál a(z) **{label}** kategóriához. "
                f"Írd le a részleteket; innen visszük tovább. "
                f"@here csak a staff látja ezt a szálat."
            )
        except Exception:
            pass

        # A parent csatornában megjelenő „Thread opened:” rendszerüzenet eltakarítása (ha törölhető)
        await asyncio.sleep(0.3)
        try:
            async for m in channel.history(limit=6):
                if m.type in (discord.MessageType.thread_created,):
                    try:
                        # ha ehhez a threadhez tartozik
                        if new_thread.id in [t.id for t in getattr(m, "thread", [])] or str(new_thread.id) in m.content:
                            await m.delete()
                            break
                    except Exception:
                        pass
                # fallback: ha a rendszerüzenet nem kapcsolódik közvetlen attributummal,
                # de megemlíti a threadet
                if new_thread.mention in (m.content or ""):
                    try:
                        await m.delete()
                        break
                    except Exception:
                        pass
        except Exception:
            pass

        # Ephemerális visszajelzés, hogy ne szemeteljünk a hubba
        if interaction.response.is_done():
            await interaction.followup.send(f"Thread nyitva: {new_thread.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Thread nyitva: {new_thread.mention}", ephemeral=True)

    # --- 4 kategóriagomb ---

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.primary, custom_id=CATEGORY_IDS["mebinu"])
    async def cat_mebinu(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary, custom_id=CATEGORY_IDS["commission"])
    async def cat_commission(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id=CATEGORY_IDS["nsfw"])
    async def cat_nsfw(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "nsfw")

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id=CATEGORY_IDS["help"])
    async def cat_help(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._open_thread(interaction, "help")


# ===== Cog =====

class Tickets(commands.Cog, name="tickets"):
    """Ticket Hub: 1 gombos tiszta hub, ephemerális kategóriaválasztó, teljes cleanup, boss-fallback."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # persistent OpenTicket gomb
        self.bot.add_view(OpenTicketView(self.bot))

    # -------- Közös munkamag --------

    async def _post_clean_hub_card(self, channel: discord.TextChannel):
        """Kiteszi az 1 gombos hub-kártyát."""
        embed = discord.Embed(
            title=HUB_TITLE,
            description=HUB_DESC,
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text="ticket_hub")
        view = OpenTicketView(self.bot)
        await channel.send(embed=embed, view=view)

    async def _cleanup_core(self, channel: discord.TextChannel, deep: bool, full: bool) -> tuple[int, int]:
        """
        Törlés végiglépkedve (nem bulk), így nincs 14 napos limit gond.
        full=True esetén MINDENT törlünk (nem csak a bot üzeneteit).
        Visszatér: (törölt_üzenetek, törölt_threadek)
        """
        removed_msgs = 0

        async for msg in channel.history(limit=None, oldest_first=True):
            try:
                # ne hagyjunk semmit: ha full, minden megy; ha nem, akkor csak a bot/hub elemek
                if full or msg.author.bot or msg.type in (discord.MessageType.thread_created,):
                    if msg.pinned:
                        try:
                            await msg.unpin(reason="TicketHub cleanup")
                        except Exception:
                            pass
                    await msg.delete()
                    removed_msgs += 1
            except Exception:
                pass

        removed_threads = 0
        if deep:
            # Aktív threadek
            for th in list(channel.threads):
                try:
                    # csak a bot tulajdonolta szálakat gyaloljuk (óvatosan)
                    if th.owner_id == self.bot.user.id:
                        await th.delete(reason="TicketHub cleanup (active)")
                        removed_threads += 1
                except Exception:
                    # force-archive + delete
                    try:
                        await th.edit(archived=True, locked=True, reason="TicketHub cleanup (force-archive)")
                        await asyncio.sleep(0.2)
                        await th.delete(reason="TicketHub cleanup (after-archive)")
                        removed_threads += 1
                    except Exception:
                        pass

            # Archivált public
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

            # Archivált private
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

        return removed_msgs, removed_threads

    # -------- Slash parancsok --------

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(
        name="ticket_hub_cleanup",
        description="MINDEN üzenet törlése a hubból + bot-threadek törlése (alap: teljes & mély).",
    )
    @app_commands.describe(
        full="Ha igaz, minden üzenetet törlök (ajánlott).",
        deep="Ha igaz, a bot által nyitott threadeket is törlöm (aktív+archivált).",
    )
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, full: bool = True, deep: bool = True):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Ezt csak szöveges csatornában tudom futtatni.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        removed_msgs, removed_threads = await self._cleanup_core(interaction.channel, deep=deep, full=full)
        await interaction.followup.send(
            f"✅ Takarítás kész.\n"
            f"• Törölt üzenetek: **{removed_msgs}**\n"
            f"• Törölt threadek: **{removed_threads}**{' (mély)' if deep else ''}\n"
            f"Most kihelyezem a hub kártyát…",
            ephemeral=True,
        )
        # tiszta kártya visszarakása
        try:
            await self._post_clean_hub_card(interaction.channel)
        except Exception:
            pass

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(
        name="ticket_hub_setup",
        description="Kihelyez egy tiszta Ticket Hub kártyát (1 gomb: Open Ticket).",
    )
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Ezt csak szöveges csatornában tudom futtatni.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self._post_clean_hub_card(interaction.channel)
        await interaction.followup.send("Hub kártya kihelyezve ebbe a csatornába.", ephemeral=True)

    # -------- Boss-fallback: üzenet figyelő --------

    @commands.Cog.listener("on_message")
    async def _boss_text_fallback(self, message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return

        member = message.author if isinstance(message.author, discord.Member) else None
        if not member or not is_boss(member):
            return

        content = message.content.strip().lower()

        cleanup_patterns = [
            r"^/ticket_hub_cleanup\b",
            r"\b(takar(í|i)tsd( meg)? a hubot)\b",
            r"\bhub cleanup\b",
        ]
        setup_patterns = [
            r"^/ticket_hub_setup\b",
            r"\b(hub (be)?(áll|allit|állítsd|állitsd) (fel|ki))\b",
            r"\bhub setup\b",
        ]

        async def del_cmd():
            try:
                await message.delete()
            except Exception:
                pass

        # CLEANUP -> teljes + mély
        if any(re.search(p, content) for p in cleanup_patterns):
            await del_cmd()
            removed_msgs, removed_threads = await self._cleanup_core(message.channel, deep=True, full=True)
            try:
                await message.channel.send(
                    f"✅ (boss) Takarítás kész.\n"
                    f"• Törölt üzenetek: **{removed_msgs}**\n"
                    f"• Törölt threadek: **{removed_threads}** (mély)\n"
                    f"→ Hub kártya kihelyezve."
                )
            except Exception:
                pass
            try:
                await self._post_clean_hub_card(message.channel)
            except Exception:
                pass
            return

        # SETUP
        if any(re.search(p, content) for p in setup_patterns):
            await del_cmd()
            try:
                await self._post_clean_hub_card(message.channel)
                await message.channel.send("✅ (boss) Hub kártya kihelyezve.")
            except Exception:
                pass
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
