import os
import asyncio
from typing import Optional, Iterable

import discord
from discord import app_commands
from discord.ext import commands

FEATURE_NAME = "tickets"

# Kategóriák (gombcímkék) – itt tudsz átnevezni, ha szeretnéd
CAT_MEBINU = "Mebinu"
CAT_COMMISSION = "Commission"
CAT_NSFW = "NSFW 18+"
CAT_HELP = "General Help"

# Környezetből beolvasható fixek
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))

# Szűrők, amikre a cleanup figyel, ha nem csak a szerző = bot szerint törlünk
HUB_MARKERS: tuple[str, ...] = (
    "Üdv a(z) #",
    "TicketHub ready",
    "Válassz kategóriát a gombokkal",
    "Hub frissítve",
)


class HubView(discord.ui.View):
    def __init__(self, who_id: int):
        super().__init__(timeout=None)
        self.who_id = who_id  # a hub üzenet írója (bot)

    # Mebinu – primary
    @discord.ui.button(label=CAT_MEBINU, style=discord.ButtonStyle.primary, custom_id="tickets:mebinu")
    async def mebinu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_thread(interaction, CAT_MEBINU)

    # Commission – success (kértél más színt)
    @discord.ui.button(label=CAT_COMMISSION, style=discord.ButtonStyle.success, custom_id="tickets:commission")
    async def commission(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_thread(interaction, CAT_COMMISSION)

    # NSFW – danger
    @discord.ui.button(label=CAT_NSFW, style=discord.ButtonStyle.danger, custom_id="tickets:nsfw")
    async def nsfw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_thread(interaction, CAT_NSFW)

    # Help – secondary
    @discord.ui.button(label=CAT_HELP, style=discord.ButtonStyle.secondary, custom_id="tickets:help")
    async def helpbtn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_thread(interaction, CAT_HELP)

    async def _open_thread(self, interaction: discord.Interaction, category: str):
        # Thread név: "KATEGÓRIA | DisplayName"
        user = interaction.user
        base = f"{category} | {user.display_name}".strip()
        name = base[:95]  # thread név limit

        parent: discord.TextChannel = interaction.channel  # type: ignore

        # Privát thread a hub csatorna alatt
        try:
            thread = await parent.create_thread(
                name=name,
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            await thread.add_user(user)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Nincs jogosultság privát thread létrehozására ebben a csatornában.",
                ephemeral=True,
            )
            return

        # Üdvözlő üzenet – NINCS „kerek limit” táblázat, ahogy kérted
        embed = discord.Embed(
            title=f"{category} ticket",
            description=(
                f"Hello {user.mention}! Itt intézzük a **{category}** témádat. "
                "Írd le röviden, amire szükséged van. Képeket is csatolhatsz."
            ),
            color=discord.Color.blurple(),
        )
        await thread.send(embed=embed)
        await interaction.response.send_message(
            f"Ticket nyitva: {thread.mention}", ephemeral=True
        )


class Tickets(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.logger.info("%s: cog loaded", FEATURE_NAME)

    # ===== Helpers ============================================================

    def _guild_scope(self) -> list[discord.Object]:
        return [discord.Object(id=GUILD_ID)] if GUILD_ID else []

    def _resolve_hub(self, interaction: discord.Interaction) -> Optional[discord.TextChannel]:
        if TICKET_HUB_CHANNEL_ID:
            ch = interaction.client.get_channel(TICKET_HUB_CHANNEL_ID)
            if isinstance(ch, discord.TextChannel):
                return ch
        # fallback: az a csatorna, ahol épp állunk
        if isinstance(interaction.channel, discord.TextChannel):
            return interaction.channel
        return None

    async def _delete_messages(
        self,
        channel: discord.TextChannel,
        *,
        by_bot_only: bool = True,
        include_markers: bool = True,
    ) -> int:
        """
        Biztonságos egyenkénti törlés (bulk_delete 14 nap limit miatt nem megbízható).
        Rate limit barát (~0.25s/sikeres törlés).
        """
        deleted = 0
        me: discord.ClientUser = channel.guild.me or self.bot.user  # type: ignore

        async for msg in channel.history(limit=None, oldest_first=True):
            try:
                if by_bot_only:
                    if msg.author.id != me.id:
                        continue
                elif include_markers:
                    content = (msg.content or "") + " " + (msg.embeds[0].description if msg.embeds else "")
                    if (msg.author.id == me.id) or any(m in content for m in HUB_MARKERS):
                        pass
                    else:
                        continue

                await msg.delete()
                deleted += 1
                await asyncio.sleep(0.25)
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                # ha rate limit vagy túl régi, folytatjuk
                await asyncio.sleep(0.5)
                continue

        return deleted

    async def _delete_threads(self, channel: discord.TextChannel) -> int:
        """Minden thread törlése a hub alatt (aktív + archív)."""
        count = 0

        # Aktívak
        for th in list(channel.threads):
            try:
                await th.delete()
                count += 1
                await asyncio.sleep(0.25)
            except Exception:
                continue

        # Archívak – public
        async for th in channel.archived_threads(limit=None, private=False):
            try:
                await th.delete()
                count += 1
                await asyncio.sleep(0.25)
            except Exception:
                continue

        # Archívak – private
        async for th in channel.archived_threads(limit=None, private=True):
            try:
                await th.delete()
                count += 1
                await asyncio.sleep(0.25)
            except Exception:
                continue

        return count

    def _hub_embed(self, channel: discord.TextChannel) -> discord.Embed:
        desc = (
            "Válassz kategóriát a gombokkal. A rendszer külön **privát threadet** nyit neked.\n\n"
            f"**{CAT_MEBINU}** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
            f"**{CAT_COMMISSION}** — Fizetős, egyedi art megbízás *(scope, budget, határidő)*.\n"
            f"**{CAT_NSFW}** — Csak 18+; szigorúbb szabályzat & review.\n"
            f"**{CAT_HELP}** — Gyors kérdés–válasz, útmutatás."
        )
        e = discord.Embed(
            title=f"Üdv a(z) #{channel.name} | ticket-hub-ban!",
            description=desc,
            color=discord.Color.blurple(),
        )
        e.set_footer(text="Hub frissítve. Törölve: 0 üzenet.")
        return e

    # ===== Commands ===========================================================

    @app_commands.command(name="ticket_hub_setup", description="TicketHub üzenet újraposztolása (és bot-üzenetek takarítása).")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guilds(*_guild_scope.__func__(None))  # static-ish hívás
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        ch = self._resolve_hub(interaction)
        if not ch:
            await interaction.response.send_message("Nem találom a hub csatornát.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Bot-üzenetek takarítása (gyors, biztonságos)
        removed = await self._delete_messages(ch, by_bot_only=True, include_markers=True)

        # Friss hub üzenet
        embed = self._hub_embed(ch)
        msg = await ch.send(embed=embed, view=HubView(self.bot.user.id))  # type: ignore

        self.bot.logger.info("TicketHub setup done: removed=%s, new_msg_id=%s", removed, msg.id)
        await interaction.followup.send(
            f"Hub kész. Törölve: **{removed}** üzenet. Csatorna: {ch.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="ticket_hub_cleanup",
        description="TicketHub takarítás: bot-üzenetek törlése. 'deep' = thread törlés is.",
    )
    @app_commands.describe(deep="Ha igaz, MINDEN thread is törlődik a hub alatt (aktív + archív).")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guilds(*_guild_scope.__func__(None))
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        ch = self._resolve_hub(interaction)
        if not ch:
            await interaction.response.send_message("Nem találom a hub csatornát.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Üzenetek törlése (bot + marker alapú)
        removed_msgs = await self._delete_messages(ch, by_bot_only=False, include_markers=True)

        removed_threads = 0
        if deep:
            removed_threads = await self._delete_threads(ch)

        self.bot.logger.info(
            "TicketHub cleanup: removed_msgs=%s removed_threads=%s deep=%s",
            removed_msgs, removed_threads, deep
        )

        await interaction.followup.send(
            f"Takarítás kész. Törölt üzenetek: **{removed_msgs}**."
            + (f" Törölt threadek: **{removed_threads}**." if deep else ""),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
