# cogs/agent/agent_gate.py
from __future__ import annotations

import os
import platform
import time
import discord
from discord import app_commands, Interaction
from discord.ext import commands

BOOT_TS = time.time()


class AgentGate(commands.Cog, name="agent_gate"):
    """Owner-only segéd parancsok Issero állapot- és diagnosztikához."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # OWNER_ID az env-ben (Render: OWNER_ID)
        self.owner_id: int = int(os.environ.get("OWNER_ID", "0"))

    # csak guildben látszódjon
    async def cog_check(self, ctx: commands.Context) -> bool:  # pragma: no cover
        return ctx.guild is not None

    # ---- Segédek ----------------------------------------------------------

    def _is_owner(self, user_id: int) -> bool:
        return self.owner_id != 0 and user_id == self.owner_id

    async def _ephemeral_denied(self, interaction: Interaction) -> None:
        await interaction.response.send_message(
            "Ehhez a parancshoz nincs jogosultságod.", ephemeral=True
        )

    # ---- Slash: /isero_status ---------------------------------------------

    @app_commands.default_permissions(manage_guild=True)  # d.py 2.4 helyes forma
    @app_commands.guild_only()
    @app_commands.command(name="isero_status", description="Issero rövid rendszerállapot (owner only).")
    async def isero_status(self, interaction: Interaction) -> None:
        if not self._is_owner(interaction.user.id):
            return await self._ephemeral_denied(interaction)

        up = time.time() - BOOT_TS
        embed = discord.Embed(
            title="Issero státusz",
            description="Gyors diagnosztika",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Bot", value=str(self.bot.user), inline=True)
        embed.add_field(name="Latency", value=f"{self.bot.latency*1000:.0f} ms", inline=True)
        embed.add_field(name="Uptime", value=f"{up/3600:.2f} óra", inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
