from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import GUILD_ID

if GUILD_ID:
    _guilds = app_commands.guilds(discord.Object(id=GUILD_ID))
else:
    def _guilds(func):
        return func

class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="whoami", description="Show your player profile")
    @_guilds
    async def whoami(self, interaction: discord.Interaction) -> None:
        ag = self.bot.get_cog("AgentGate")
        db = getattr(ag, "db", None) if ag else None
        if db is None:
            await interaction.response.send_message("DB unavailable", ephemeral=True)
            return
        player = await db.get_player(interaction.user.id)
        mood, marketing = await db.get_scores(interaction.user.id)
        if not player:
            await interaction.response.send_message("Nincs adat", ephemeral=True)
            return
        msg = (
            f"role={player['role']} trust={player['trust']}\n"
            f"locale={player['locale']} style={player['style']}\n"
            f"mood_score={mood:.2f} marketing_score={marketing:.2f}"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="setpref", description="Set locale/style preferences")
    @_guilds
    async def setpref(self, interaction: discord.Interaction, locale: str, style: str) -> None:
        ag = self.bot.get_cog("AgentGate")
        db = getattr(ag, "db", None) if ag else None
        if db is None:
            await interaction.response.send_message("DB unavailable", ephemeral=True)
            return
        await db.set_pref(interaction.user.id, locale, style)
        await interaction.response.send_message("ok", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Profile(bot))
