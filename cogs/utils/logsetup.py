import logging
from discord.ext import commands

LOG_FORMAT = "%(levelname)s:%(name)s:%(message)s"

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

class LogSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Alap logging
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

        # A discord.client loggerét lejjebb vesszük, hogy a PyNaCl WARNING ne zavarjon
        logging.getLogger("discord.client").setLevel(logging.ERROR)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.getLogger("bot").info("LogSetup ready.")

async def setup(bot: commands.Bot):
    await bot.add_cog(LogSetup(bot))
