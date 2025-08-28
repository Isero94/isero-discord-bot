from discord.ext import commands
import discord
from config import CHANNELS
class LogHelper(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def send_embed(self,key,title,desc,color=0x5865F2):
        ch=self.bot.get_channel(CHANNELS.get(key));
        if ch: await ch.send(embed=discord.Embed(title=title,description=desc,color=color))
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def pinglog(self,ctx):
        await self.send_embed('logs','Ping','Log check OK'); await ctx.reply('Log sent.')
async def setup(bot): await bot.add_cog(LogHelper(bot))
