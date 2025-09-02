from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class Health(commands.Cog):
    """Minimal diagnostic utilities."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="diag", description="Show basic diagnostic info")
    async def diag(self, interaction: discord.Interaction) -> None:
        ag = self.bot.get_cog("AgentGate")
        reason = "none"
        if ag and hasattr(ag, "channel_trigger_reason"):
            try:
                reason = ag.channel_trigger_reason(interaction.channel)  # type: ignore[arg-type]
            except Exception:
                reason = "none"
        await interaction.response.send_message(f"trigger_reason={reason}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
