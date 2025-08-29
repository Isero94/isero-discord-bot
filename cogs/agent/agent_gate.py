# cogs/agent/agent_gate.py
from __future__ import annotations

import os
import discord
from discord import app_commands
from discord.ext import commands

OWNER_ID_ENV = "OWNER_ID"  # a Render env-ben már nálad ott van

class AgentGate(commands.Cog, name="agent_gate"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        owner_raw = os.getenv(OWNER_ID_ENV, "").strip()
        self.owner_id = int(owner_raw) if owner_raw.isdigit() else None

    def _is_owner(self, user: discord.abc.User) -> bool:
        return self.owner_id is not None and user.id == self.owner_id

    @app_commands.command(
        name="isero_status",
        description="(Owner) Gyors állapotkérdés a bothoz.",
        default_member_permissions=discord.Permissions(manage_guild=True),
    )
    async def isero_status(self, interaction: discord.Interaction):
        if not self._is_owner(interaction.user):
            await interaction.response.send_message("Ehhez nincs jogosultságod.", ephemeral=True)
            return

        loaded = ", ".join(sorted(self.bot.cogs.keys()))
        await interaction.response.send_message(
            f"✅ ISERO fut.\nCogs: `{loaded}`",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
