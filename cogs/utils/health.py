from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class Health(commands.Cog):
    """Minimal diagnostic utilities."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check if the bot is alive")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!")

    @app_commands.command(name="diag", description="Show basic diagnostic info")
    async def diag(self, interaction: discord.Interaction) -> None:
        ag = self.bot.get_cog("AgentGate")
        reason = "none"
        if ag and hasattr(ag, "channel_trigger_reason"):
            try:
                reason = ag.channel_trigger_reason(interaction.channel)  # type: ignore[arg-type]
            except Exception:
                reason = "none"
        env = getattr(ag, "env_status", {}) if ag else {}
        msg = (
            f"trigger_reason={reason}\n"
            f"env bot_commands={env.get('bot_commands', 'unset')} "
            f"suggestions={env.get('suggestions', 'unset')} "
            f"tickets_category={env.get('tickets_category', 'unset')} "
            f"wake_words_count={env.get('wake_words_count', 0)} "
            f"deprecated_keys_detected={env.get('deprecated_keys_detected', False)}"
        )
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
