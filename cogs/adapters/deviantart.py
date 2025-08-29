FEATURE_NAME = "deviantart"
from discord.ext import commands

async def setup(bot):
    await bot.add_cog(DeviantArt(bot))

class DeviantArt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="dademo")
    async def dademo(self, ctx: commands.Context):
        await ctx.send("DeviantArt adapter (stub).")
