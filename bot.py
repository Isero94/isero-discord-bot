import os, asyncio, discord
from discord.ext import commands
from dotenv import load_dotenv
from config import DISCORD_TOKEN, GUILD_ID

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

INITIAL_EXTENSIONS = [
    "cogs.profiles",
    "cogs.logging",
    "cogs.moderation",
    "cogs.agent_gate",
]

class IseroBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_at = discord.utils.utcnow()

    async def setup_hook(self):
        print(f"[BOOT] ISERO setup_hook started...")
        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                print(f"[BOOT] Loaded {ext}")
            except Exception as e:
                print(f"[BOOT] FAILED to load {ext}: {e}")
        
        try:
            if GUILD_ID:
                await self.tree.sync(guild=discord.Object(id=GUILD_ID))
                print(f"[BOOT] App commands synced to guild {GUILD_ID}")
            else:
                await self.tree.sync()
                print("[BOOT] Global app commands synced")
        except Exception as e:
            print(f"[BOOT] Sync failed: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"✅ ISERO online: {self.user} ({self.user.id})")

async def main():
    token = DISCORD_TOKEN or os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN env.")
    
    bot = IseroBot(command_prefix=commands.when_mentioned_or("!"), intents=intents, help_command=None)
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
