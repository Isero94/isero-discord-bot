import os
import asyncio
import logging

import discord
from discord.ext import commands

from bot.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ---- Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True

# ---- Env
TOKEN = os.getenv("DISCORD_TOKEN")

EXTENSIONS = [
    "cogs.utils.logsetup",
    "cogs.utils.health",
    "cogs.agent.agent_gate",
    "cogs.tickets.tickets",
    "cogs.ranks.progress",
    "cogs.ranks.rolesync",
    "cogs.watchers.lang_watch",
    "cogs.watchers.keyword_watch",
    "cogs.moderation.profanity_guard",  # <-- fontos
]

class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # COG-ok betöltése
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info(f"Loaded cog: {ext}")
            except Exception:
                log.exception(f"Failed to load {ext}")
        # App parancsok csak guild-scope-on
        try:
            guild_obj = discord.Object(id=settings.GUILD_ID)
            # töröljük a globál parancsokat
            self.tree.clear_commands(guild=None)
            await self.tree.sync(guild=None)
            # sync guildre
            await self.tree.sync(guild=guild_obj)
            names = [c.name for c in await self.tree.fetch_commands(guild=guild_obj)]
            log.info("Registered app commands (guild %s): %s", guild_obj.id, names)
            log.info("Registered app commands count: %d", len(names))
        except Exception:
            log.exception("Command sync failed")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} ({self.user.id})")

async def main():
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN missing in environment.")
    bot = Bot()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
