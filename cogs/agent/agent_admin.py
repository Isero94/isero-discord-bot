# cogs/agent/agent_admin.py
from __future__ import annotations

import os
import discord
from discord import app_commands
from discord.ext import commands

OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

class AgentAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def can_run(self, itx: discord.Interaction) -> bool:
        if itx.user.id == OWNER_ID:
            return True
        member = itx.user if isinstance(itx.user, discord.Member) else None
        return bool(member and member.guild_permissions.manage_guild)

    @app_commands.command(name="broadcast", description="Körüzenet @everyone-nal az aktuális csatornába.")
    @app_commands.describe(message="Mit küldjön ki @everyone-nak?")
    async def broadcast(self, itx: discord.Interaction, message: str):
        if not self.can_run(itx):
            return await itx.response.send_message("Nincs jogod ehhez.", ephemeral=True)

        # megpróbálunk @everyone-t engedni csak erre az üzenetre
        try:
            await itx.channel.send(
                f"@everyone {message}",
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )
            await itx.response.send_message("Kész. 📢", ephemeral=True)
        except Exception as e:
            await itx.response.send_message(f"Hiba a küldésnél: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentAdmin(bot))
