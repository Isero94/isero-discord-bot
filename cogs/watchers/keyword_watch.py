FEATURE_NAME = "guardian"
from discord.ext import commands

async def setup(bot):
    await bot.add_cog(KeywordWatch(bot))

class KeywordWatch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # Placeholder for keyword triggers; kept minimal
        return
