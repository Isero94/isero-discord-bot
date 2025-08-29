import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def setup_hook():
    print("[BOOT] setup_hook")
    # COG-ok betöltése
    for ext in ("cogs.agent_gate", "cogs.tickets"):
        try:
            await bot.load_extension(ext)
            print(f"[BOOT] {ext} loaded ✅")
        except Exception as e:
            print(f"[BOOT] {ext} load ERROR: {e}")

@bot.event
async def on_ready():
    print("=== ISERO ONLINE ===")
    print(f"[BOOT] Bot user: {bot.user} (id={bot.user.id})")
    print(f"[BOOT] Guilds: {[g.name for g in bot.guilds]}")
    print(f"[BOOT] intents.message_content = {bot.intents.message_content}")

    # gyorsabb guild-specifikus sync, ha van GUILD_ID
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            print(f"[BOOT] App commands synced to guild {GUILD_ID}: {len(synced)}")
        else:
            synced = await bot.tree.sync()
            print(f"[BOOT] Global app commands synced: {len(synced)}")
    except Exception as e:
        print(f"[BOOT] app commands sync error: {e}")

# egyszerű életjel parancs
@bot.hybrid_command(name="ping", description="Pong teszt")
async def ping(ctx: commands.Context):
    await ctx.reply("Pong 🏓")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN hiányzik az env-ből.")
    print(">>> importing bot.py ...")
    print(f"[ENV] GUILD_ID={GUILD_ID} TOKEN set? {bool(TOKEN)}")
    print(">>> running bot.run()")
    bot.run(TOKEN)
