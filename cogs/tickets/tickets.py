from __future__ import annotations

import os
import typing as t
import discord
from discord import app_commands
from discord.ext import commands

FEATURE_NAME = "ticket_hub"  # ezzel azonosítjuk a hub üzeneteket (embed footer)

HUB_TITLE = "Üdv a(z) #🧾 | ticket-hub-ban!"
HUB_DESC = (
    "Válassz kategóriát a gombokkal. A rendszer külön privát threadet nyit neked.\n\n"
    "**Mebinu** — Gyűjthető figura kérések, variánsok, kódok, ritkaság.\n"
    "**Commission** — Fizetős, egyedi art megbízás (scope, budget, határidő).\n"
    "**NSFW 18+** — Csak 18+; szigorúbb szabályzat & review.\n"
    "**General Help** — Gyors kérdés–válasz, útmutatás.\n"
)

CAT_MEBINU = "MEBINU"
CAT_COMM = "COMMISSION"
CAT_NSFW = "NSFW18"
CAT_HELP = "HELP"

def footer_text() -> str:
    return f"{FEATURE_NAME}"

# ---------------- UI: View + Gombok ----------------

class StartTicketButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, cat_key: str):
        super().__init__(label=label, style=style)
        self.cat_key = cat_key

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        await interaction.response.defer(ephemeral=True)

        hub_ch = interaction.channel
        if not isinstance(hub_ch, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send("Ez itt nem támogatott csatornatípus.", ephemeral=True)
            return

        user = interaction.user
        name = f"{self.cat_key} | {user.display_name}".strip()
        # Privát thread a hub csatorna alatt
        try:
            thread = await hub_ch.create_thread(
                name=name[:90],
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Ticket thread"
            )
        except Exception:
            # ha thread nem engedélyezett, fallback: sima nyilvános thread
            thread = await hub_ch.create_thread(
                name=name[:90],
                type=discord.ChannelType.public_thread,
                reason="Ticket thread (fallback)"
            )

        # behívjuk a felhasználót a threadbe
        try:
            await thread.add_user(user)
        except Exception:
            pass

        # első üzenet
        await thread.send(
            f"Opened pre-chat for **{self.cat_key}**.\n"
            "Each message must be ≤ **300** characters. Up to **10** rounds (you ↔ Isero)."
        )
        await interaction.followup.send(f"Thread opened: {thread.mention}", ephemeral=True)

class DetailsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Details", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        await interaction.response.send_message(HUB_DESC, ephemeral=True)

class TicketHubView(discord.ui.View):
    def __init__(self, *, timeout: t.Optional[float] = None):
        super().__init__(timeout=timeout)
        self.add_item(StartTicketButton("Mebinu", discord.ButtonStyle.primary, CAT_MEBINU))
        self.add_item(StartTicketButton("Commission", discord.ButtonStyle.primary, CAT_COMM))
        self.add_item(StartTicketButton("NSFW 18+", discord.ButtonStyle.danger, CAT_NSFW))
        self.add_item(StartTicketButton("General Help", discord.ButtonStyle.success, CAT_HELP))
        self.add_item(DetailsButton())

# ---------------- COG ----------------

class Tickets(commands.Cog):
    """Ticket Hub + takarítás + posztolás (slash és programból is hívható)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---------- PUBLIKUS METÓDUSOK (Agent is ezeket hívja) ----------

    async def cleanup_hub_messages(self, channel: discord.abc.Messageable, limit: int = 100) -> int:
        """Törli a korábbi hub üzeneteket egy csatornában. Visszaadja a törölt darabszámot."""
        deleted = 0

        # Csak TextChannel/Thread history-ja iterálható
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return 0

        async for msg in channel.history(limit=limit):
            if msg.author == channel.guild.me and msg.embeds:
                for e in msg.embeds:
                    f = e.footer.text if e.footer else ""
                    if f and FEATURE_NAME in f:
                        try:
                            await msg.delete()
                            deleted += 1
                        except Exception:
                            pass
                        break
        return deleted

    async def post_hub(self, channel: discord.abc.Messageable) -> None:
        """Kiteszi az aktuális hub üzenetet gombokkal."""
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        emb = discord.Embed(
            title=HUB_TITLE,
            description=HUB_DESC,
            color=discord.Color.gold(),
        )
        emb.set_footer(text=footer_text())

        view = TicketHubView()
        await channel.send(embed=emb, view=view)

    # ---------- SLASH PARANCSOK ----------

    @app_commands.command(name="ticket_hub_cleanup", description="Régi TicketHub üzenetek törlése a jelenlegi csatornában.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        deleted = await self.cleanup_hub_messages(interaction.channel)  # type: ignore[arg-type]
        await interaction.followup.send(f"Kész. Törölve: **{deleted}** üzenet.", ephemeral=True)

    @app_commands.command(name="ticket_hub_setup", description="TicketHub újraposztolása a jelenlegi csatornába.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.post_hub(interaction.channel)  # type: ignore[arg-type]
        await interaction.followup.send("Hub kiposztolva.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
