import os, asyncio, discord
from discord.ext import commands
from dotenv import load_dotenv
from config import DISCORD_TOKEN, GUILD_ID

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents, help_command=None)

INITIAL_EXTENSIONS = [
    "cogs.profiles",
    "cogs.logging",
    "cogs.moderation",
    "cogs.agent_gate",
]

async def _load_extensions():
    for ext in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(ext)
            print(f"[BOOT] loaded {ext}")
        except Exception as e:
            print(f"[BOOT] FAILED {ext}: {e}")

class IseroBot(commands.Bot):
    async def setup_hook(self):
        await _load_extensions()
        try:
            if GUILD_ID:
                await self.tree.sync(guild=discord.Object(id=GUILD_ID))
                print(f"[BOOT] app commands synced to guild {GUILD_ID}")
            else:
                await self.tree.sync()
                print("[BOOT] global app commands synced")
        except Exception as e:
            print(f"[BOOT] sync failed: {e}")

@bot.event
async def on_ready():
    print(f"✅ ISERO online: {bot.user} ({bot.user.id})")

async def main():
    token = DISCORD_TOKEN or os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN env.")
    global bot
    bot = IseroBot(command_prefix=commands.when_mentioned_or("!"), intents=intents, help_command=None)
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
