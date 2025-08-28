import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# --- Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# --- Bot ---
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    intents=intents,
    help_command=None,
)

# Mely cogokat töltsük be
INITIAL_EXTENSIONS = [
    "cogs.profiles",
    "cogs.logging",
    "cogs.moderation",
    "cogs.agent_gate",
]

async def _load_extensions_and_views():
    # COG-ok betöltése
    for ext in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(ext)
            print(f"[BOOT] Loaded {ext}")
        except Exception as e:
            print(f"[BOOT] Failed to load {ext}: {e}")

    # View hozzáadása (pl. gombok a ticket rendszerhez)
    try:
        # késői import, hogy ne legyen körkörös import
        from cogs.agent_gate import TicketHubView
        bot.add_view(TicketHubView())
        print("[BOOT] TicketHubView added")
    except Exception as e:
        print(f"[BOOT] Failed to add TicketHubView: {e}")

class IseroBot(commands.Bot):
    async def setup_hook(self):
        # mindent itt készítünk elő, mielőtt a bot teljesen feláll
        await _load_extensions_and_views()

        # (opcionális) slash parancsok szinkronja – ha csak 1 guildre akarod,
        # tedd ki env-be a GUILD_ID-t és így sync-eld:
        gid = os.getenv("GUILD_ID")
        try:
            if gid:
                guild = discord.Object(id=int(gid))
                await self.tree.sync(guild=guild)
                print(f"[BOOT] App commands synced to guild {gid}")
            else:
                await self.tree.sync()
                print("[BOOT] Global app commands synced")
        except Exception as e:
            print(f"[BOOT] Command sync failed: {e}")

@bot.event
async def on_ready():
    print(f"✅ ISERO online: {bot.user} ({bot.user.id})")

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing in environment.")

    # Használjuk a saját Bot osztályt a setup_hook miatt
    global bot
    bot = IseroBot(
        command_prefix=commands.when_mentioned_or("!"),
        intents=intents,
        help_command=None,
    )

    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
