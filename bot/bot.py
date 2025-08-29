import os
import asyncio
import importlib
import logging

import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True
INTENTS.reactions = True

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

EXTENSIONS = [
    "cogs.utils.logsetup",
    "cogs.agent.agent_gate",
    "cogs.tickets.tickets",
    "cogs.ranks.progress",
    "cogs.ranks.rolesync",
    "cogs.watchers.lang_watch",
    "cogs.watchers.keyword_watch",
    # "cogs.adapters.deviantart",  # kikapcsolva
]

class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self) -> None:
        # COG-ok betöltése biztonságosan
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info(f"Loaded cog: {ext}")
            except Exception:
                log.exception(f"Failed to load {ext}")

        # App parancsok szinkronizálása GUILD-re (instant)
        try:
            if GUILD_ID:
                await self.tree.sync(guild=discord.Object(id=GUILD_ID))
                log.info(f"App commands synced to guild {GUILD_ID}")
            else:
                await self.tree.sync()
                log.info("App commands synced (global)")
        except Exception:
            log.exception("Command sync failed")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} ({self.user.id})")

async def main():
    bot = Bot()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN missing in environment.")
    asyncio.run(main())
