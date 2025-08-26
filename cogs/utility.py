# cogs/utility.py
import platform
import time
import discord
from discord import app_commands
from discord.ext import commands

class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Prefixes ping: !ping
    @commands.command(name="ping")
    async def ping_prefix(self, ctx: commands.Context):
        start = time.perf_counter()
        msg = await ctx.reply("Pinging...")
        end = time.perf_counter()
        ws = round(self.bot.latency * 1000)
        rt = round((end - start) * 1000)
        await msg.edit(content=f"Pong!  WebSocket: **{ws}ms**, Round-trip: **{rt}ms**")

    # Slash ping: /ping
    @app_commands.command(name="ping", description="Válaszol ping/ponggal és késleltetéssel.")
    async def ping_slash(self, interaction: discord.Interaction):
        ws = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong!  WebSocket: **{ws}ms**")

    # Szerver infó (slash)
    @app_commands.command(name="server_info", description="Infó a jelenlegi szerverről.")
    async def server_info(self, interaction: discord.Interaction):
        g = interaction.guild
        if not g:
            return await interaction.response.send_message("Ezt szerveren lehet használni.", ephemeral=True)

        embed = discord.Embed(
            title=f"{g.name}",
            description=f"ID: `{g.id}`",
            color=discord.Color.teal(),
        )
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Tagok", value=str(g.member_count))
        embed.add_field(name="Csatornák", value=str(len(g.channels)))
        embed.set_footer(text=f"Python {platform.python_version()} • discord.py {discord.__version__}")
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
