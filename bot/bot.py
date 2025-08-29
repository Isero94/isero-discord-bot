import asyncio, importlib, os, traceback
from dotenv import load_dotenv
import discord
from discord.ext import commands
from loguru import logger

from .config import FEATURES, LOG_CHANNEL_ID

COGS_TO_LOAD = [
    "cogs.utils.logsetup",        # logging first
    "cogs.agent.agent_gate",
    "cogs.tickets.tickets",
    "cogs.ranks.progress",
    "cogs.ranks.rolesync",
    "cogs.watchers.lang_watch",
    "cogs.watchers.keyword_watch",
    "cogs.adapters.deviantart",   # feature-flagged in cog if needed
]

async def main():
    load_dotenv()
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    # Make log mirror to Discord (optional)
    async def mirror_error_to_channel(msg: str):
        try:
            if LOG_CHANNEL_ID:
                ch = bot.get_channel(LOG_CHANNEL_ID)
                if ch:
                    await ch.send(f"```\n{msg[:1800]}\n```")
        except Exception:
            logger.exception("Failed to mirror log to channel")

    @bot.event
    async def on_ready():
        logger.info(f"Logged in as {bot.user}")

    @bot.event
    async def on_error(event_method, *args, **kwargs):
        exc_msg = traceback.format_exc()
        logger.error(f"on_error in {event_method}: {exc_msg}")
        await mirror_error_to_channel(exc_msg)

    @bot.event
    async def on_command_error(ctx, error):
        logger.error(f"Command error: {error}")
        await mirror_error_to_channel(f"Command error: {error}\n{traceback.format_exc()}"[:1900])
        await ctx.reply("Something went wrong. Logged for review.", mention_author=False)

    # Load cogs
    for ext in COGS_TO_LOAD:
        try:
            mod = importlib.import_module(ext)
            if hasattr(mod, "FEATURE_NAME"):
                feat = FEATURES.get(mod.FEATURE_NAME, True)
                if not feat:
                    logger.info(f"Feature disabled: {ext}")
                    continue
            if hasattr(mod, "setup"):
                await mod.setup(bot)
                logger.info(f"Loaded cog: {ext}")
        except Exception as e:
            logger.exception(f"Failed to load {ext}: {e}")
            await mirror_error_to_channel(f"Failed to load {ext}: {e}")

    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
