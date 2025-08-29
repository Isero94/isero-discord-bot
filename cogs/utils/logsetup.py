FEATURE_NAME = "logging"

from discord.ext import commands
from loguru import logger
import sys, os, pathlib

LOG_DIR = pathlib.Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Configure Loguru
logger.remove()
logger.add(sys.stdout, level="INFO", backtrace=False, diagnose=False, enqueue=True)
logger.add(LOG_DIR / "bot.log", rotation="5 MB", retention=3, level="DEBUG", enqueue=True)

async def setup(bot):
    # not a real cog; just ensures logging is configured before others
    pass
