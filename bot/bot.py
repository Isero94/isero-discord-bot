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

class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # ---------- ISERO PATCH: load order (profanity first) ----------
        from utils import policy as _policy
        want_v2 = _policy.getbool("FEATURES_PROFANITY_V2", default=False) or _policy.feature_on("profanity_v2")
        if want_v2:
            await self.load_extension("cogs.watchers.profanity_watch")
            log.info("Profanity Watcher v2 loaded (first)")
        else:
            await self.load_extension("cogs.moderation.profanity_guard")
            log.info("Legacy Profanity Guard loaded")
        await self.load_extension("cogs.watchers.lang_watch")
        await self.load_extension("cogs.watchers.keyword_watch")
        await self.load_extension("cogs.agent.agent_gate")
        await self.load_extension("cogs.tickets.tickets")
        await self.load_extension("cogs.ranks.progress")
        await self.load_extension("cogs.ranks.rolesync")
        await self.load_extension("cogs.utils.logsetup")
        await self.load_extension("cogs.utils.health")
        # ---------- ISERO PATCH END ----------

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
