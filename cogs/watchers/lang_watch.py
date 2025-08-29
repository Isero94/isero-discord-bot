FEATURE_NAME = "guardian"
from discord.ext import commands

async def setup(bot):
    await bot.add_cog(LangWatch(bot))

class LangWatch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # Placeholder for language nudging; kept empty to avoid interference
        return
