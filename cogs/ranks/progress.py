FEATURE_NAME = "ranks"
from discord.ext import commands

async def setup(bot):
    await bot.add_cog(RankProgress(bot))

class RankProgress(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="rank")
    async def rank(self, ctx: commands.Context):
        bar = "[##########----------]"  # demo only
        await ctx.send(f"Your rank progress: {bar}")
