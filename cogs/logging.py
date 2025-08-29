from discord.ext import commands

class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        try:
            await ctx.send(f"❗ Hiba: {error}")
        except Exception:
            pass
        print(f"[error] {error}")

async def setup(bot):
    await bot.add_cog(Logging(bot))
