# cogs/moderation.py
import discord
from discord import app_commands
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /clear mennyiség – üzenetek törlése
    @app_commands.command(name="clear", description="Üzenetek törlése az aktuális csatornából.")
    @app_commands.describe(amount="Hány utolsó üzenetet töröljünk? (1-200)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 200:
            return await interaction.response.send_message("1 és 200 közötti számot adj meg.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Törölve: **{len(deleted)}** üzenet.", ephemeral=True)

    # Prefix változat: !clear 10
    @commands.has_permissions(manage_messages=True)
    @commands.command(name="clear")
    async def clear_prefix(self, ctx: commands.Context, amount: int):
        if amount < 1 or amount > 200:
            return await ctx.reply("1 és 200 közötti számot adj meg.")
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.send(f"Törölve: **{len(deleted)}** üzenet.", delete_after=5)

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
