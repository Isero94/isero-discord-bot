# cogs/fun.py
import random
import discord
from discord import app_commands
from discord.ext import commands

class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /roll [oldalak] – alap 6
    @app_commands.command(name="roll", description="Dobókocka: alap 6 oldal, vagy adj meg oldalszámot.")
    @app_commands.describe(sides="Hány oldalú legyen a kocka? (alap 6)")
    async def roll(self, interaction: discord.Interaction, sides: int = 6):
        if sides < 2 or sides > 1000:
            return await interaction.response.send_message("2–1000 közötti oldal számot adj meg.", ephemeral=True)
        value = random.randint(1, sides)
        await interaction.response.send_message(f"🎲 {sides}-oldalú kocka dobása: **{value}**")

async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
