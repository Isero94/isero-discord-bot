# cogs/tickets/tickets.py
from __future__ import annotations

import os
import asyncio
from typing import List, Tuple, Optional

import discord
from discord import app_commands
from discord.ext import commands

# ────────────────────────────────────────────────────────────────────────────────
# Segéd: guild scope (nem trükközzük __func__-kal, import idejében kiértékeljük)
# ────────────────────────────────────────────────────────────────────────────────

def _build_guild_scope_from_env() -> Tuple[discord.Object, ...]:
    raw = os.getenv("GUILD_ID", "")  # lehet 1 vagy több, pl: "123,456"
    ids: List[discord.Object] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(discord.Object(id=int(part)))
    return tuple(ids)

GUILD_SCOPE: Tuple[discord.Object, ...] = _build_guild_scope_from_env()

def scope_decorator() -> app_commands.Check:
    """
    Ha van GUILD_SCOPE, a parancsokat arra a guild(ek)re korlátozzuk,
    ha nincs, globálisan regisztrálódnak.
    """
    if GUILD_SCOPE:
        return app_commands.guilds(*GUILD_SCOPE)
    # no-op dekorátor, ha nincs megadva
    def _noop_decorator(func):
        return func
    return _noop_decorator  # type: ignore[return-value]


# ────────────────────────────────────────────────────────────────────────────────
# Beállítások environmentből
# ────────────────────────────────────────────────────────────────────────────────

HUB_CHANNEL_ID_ENV = "TICKET_HUB_CHANNEL_ID"

def _get_hub_channel_id_from_env() -> Optional[int]:
    val = os.getenv(HUB_CHANNEL_ID_ENV, "").strip()
    return int(val) if val.isdigit() else None


# ────────────────────────────────────────────────────────────────────────────────
# UI – kategóriagombok
# ────────────────────────────────────────────────────────────────────────────────

CATEGORIES = [
    ("Mebinu", "MEBINU"),
    ("Commission", "COMMISSION"),
    ("NSFW 18+", "NSFW18"),
    ("General Help", "GENERAL"),
]

class CategoryButton(discord.ui.Button):
    def __init__(self, label: str, code: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.code = code

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild and interaction.channel

        # A thread neve: KATEGÓRIA | DisplayName
        display = interaction.user.display_name
        thread_name = f"{self.label.upper()} | {display}"

        # Public thread a hubban
        parent: discord.TextChannel = interaction.channel  # type: ignore[assignment]
        thread = await parent.create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,  # 24h
            reason=f"Ticket opened by {interaction.user} ({self.code})",
        )

        # Berakunk egy nyitó üzenetet a threadbe
        open_text = (
            f"**{self.label}** jegy nyitva.\n"
            f"Kérlek írd le röviden, miben segíthetünk. "
            f"Staff hamarosan válaszol. <@{interaction.user.id}>"
        )
        await thread.send(open_text)

        # Ephemeral visszajelzés a kattintónak
        await interaction.response.send_message(
            f"Thread megnyitva: {thread.mention}",
            ephemeral=True
        )

class CategoryView(discord.ui.View):
    def __init__(self, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        # Színek: kértél másik színt a Commissionre → Primary helyett Success
        for label, code in CATEGORIES:
            style = discord.ButtonStyle.primary
            if code == "COMMISSION":
                style = discord.ButtonStyle.success
            elif code == "NSFW18":
                style = discord.ButtonStyle.danger
            elif code == "GENERAL":
                style = discord.ButtonStyle.secondary
            self.add_item(CategoryButton(label, code, style))
        # NINCS külön "Details" gomb – mert a dobozban leírjuk a lényeget.


# ────────────────────────────────────────────────────────────────────────────────
# A cog
# ────────────────────────────────────────────────────────────────────────────────

class Tickets(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Segéd: hub csatorna felkutatása
    def _find_hub_channel_object(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        # 1) env alapján
        env_id = _get_hub_channel_id_from_env()
        if env_id:
            ch = guild.get_channel(env_id)
            if isinstance(ch, discord.TextChannel):
                return ch  # OK, megtalálva

        # 2) fallback: név alapján keresünk ticket-hub-ot
        for ch in guild.text_channels:
            if ch.name == "ticket-hub":
                return ch
        return None

    # ── Hub doboz
    def _build_hub_embed(self, channel: discord.TextChannel) -> discord.Embed:
        title = f"Üdv a(z) #{channel.name} | ticket-hub!-ban!"
        desc = (
            "Válassz kategóriát a gombokkal. A rendszer külön privát threadet nyit neked.\n\n"
            "**Mebinu** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
            "**Commission** — Fizetős, egyedi art megbízás (scope, budget, határidő).\n"
            "**NSFW 18+** — Csak 18+; szigorúbb szabályzat & review.\n"
            "**General Help** — Gyors kérdés–válasz, útmutatás."
        )
        emb = discord.Embed(
            title=title,
            description=desc,
            color=discord.Color.blurple(),
        )
        emb.set_footer(text="ISERO bot • tickets")
        return emb

    # ────────────────────────────────────────────────────────────────────────
    # /ticket_hub_setup – új doboz kirakása (nem töröl mindent, az a cleanup)
    # ────────────────────────────────────────────────────────────────────────
    @scope_decorator()
    @app_commands.command(
        name="ticket_hub_setup",
        description="TicketHub doboz kirakása a hub csatornába.",
        default_member_permissions=discord.Permissions(manage_guild=True),
    )
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        assert interaction.guild is not None

        hub = self._find_hub_channel_object(interaction.guild)
        if not hub:
            await interaction.response.send_message(
                f"Nem találom a hub csatornát. "
                f"Állítsd be env-ben a `{HUB_CHANNEL_ID_ENV}` változót, vagy nevezd el a csatornát `ticket-hub`-ra.",
                ephemeral=True,
            )
            return

        view = CategoryView()
        embed = self._build_hub_embed(hub)

        await hub.send(embed=embed, view=view)
        await interaction.response.send_message(
            f"✅ Hub frissítve: {hub.mention}",
            ephemeral=True
        )

    # ────────────────────────────────────────────────────────────────────────
    # /ticket_hub_cleanup – takarítás (régi bot üzenetek + threadek)
    # ────────────────────────────────────────────────────────────────────────
    @scope_decorator()
    @app_commands.command(
        name="ticket_hub_cleanup",
        description="Régi hub üzenetek és bot által nyitott threadek törlése.",
        default_member_permissions=discord.Permissions(manage_guild=True),
    )
    @app_commands.describe(deep="Ha igaz, a bot által nyitott threadeket is törli.")
    async def ticket_hub_cleanup(
        self,
        interaction: discord.Interaction,
        deep: bool = True
    ):
        assert interaction.guild is not None

        hub = self._find_hub_channel_object(interaction.guild)
        if not hub:
            await interaction.response.send_message(
                f"Nem találom a hub csatornát. "
                f"Állítsd be env-ben a `{HUB_CHANNEL_ID_ENV}` változót, vagy nevezd el a csatornát `ticket-hub`-ra.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        removed_msgs = 0
        removed_threads = 0

        # 1) Bot üzenetek törlése a hubból
        async for msg in hub.history(limit=None, oldest_first=False):
            try:
                # bot üzenete, és/vagy hozzávaló komponensek/ember?
                authored_by_bot = (msg.author.id == self.bot.user.id) if self.bot.user else False
                looks_like_hub = (
                    authored_by_bot
                    or bool(msg.components)
                    or (msg.embeds and "ticket-hub" in (msg.embeds[0].title or "").lower())
                    or (isinstance(msg.content, str) and msg.content.lower().startswith("thread opened:"))
                )
                if looks_like_hub:
                    await msg.delete()
                    removed_msgs += 1
                    # ne terheljük a ratelimitet
                    await asyncio.sleep(0.25)
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

        # 2) Threadek törlése (bot által nyitottak – owner a bot)
        if deep:
            # aktív threadek
            for th in list(hub.threads):
                try:
                    if th.owner_id == (self.bot.user.id if self.bot.user else 0):
                        await th.delete(reason="TicketHub cleanup (active)")
                        removed_threads += 1
                        await asyncio.sleep(0.25)
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass

            # archív threadek
            try:
                async for th in hub.archived_threads(limit=200, private=False):
                    if th.owner_id == (self.bot.user.id if self.bot.user else 0):
                        try:
                            await th.delete(reason="TicketHub cleanup (archived)")
                            removed_threads += 1
                            await asyncio.sleep(0.25)
                        except discord.Forbidden:
                            pass
                        except discord.HTTPException:
                            pass
            except AttributeError:
                # régebbi lib esetén nem mindenhol érhető el
                pass

        await interaction.followup.send(
            f"✅ Takarítás kész. Törölt üzenetek: **{removed_msgs}**."
            + (f" Törölt threadek: **{removed_threads}**." if deep else ""),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
