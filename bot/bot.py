import os
import asyncio
import logging

import discord
from discord.ext import commands

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
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

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

        # App parancsok gyors szinkron
        try:
            if GUILD_ID:
                guild_obj = discord.Object(id=GUILD_ID)
                await self.tree.sync(guild=guild_obj)
                cmds = [c.name for c in self.tree.get_commands(guild=guild_obj)]
                log.info("App commands synced to guild %s", GUILD_ID)
                log.info("Registered app commands (guild %s): %s", GUILD_ID, cmds)
                log.info("Registered app commands count: %d", len(cmds))
            else:
                synced = await self.tree.sync()
                cmds = [c.name for c in synced]
                log.info("App commands synced (global)")
                log.info("Registered app commands (global): %s", cmds)
                log.info("Registered app commands count: %d", len(cmds))
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
