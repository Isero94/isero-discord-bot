FEATURE_NAME = "ranks"
from discord.ext import commands

async def setup(bot):
    await bot.add_cog(RoleSync(bot))

class RoleSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
