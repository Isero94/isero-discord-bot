import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0") or "0")

# ---- INTENTS: kell a message_content! ----
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    try:
        await bot.load_extension("cogs.agent_gate")
        print("[BOOT] cogs.agent_gate loaded ✅")
    except Exception as e:
        print(f"[BOOT] cogs.agent_gate load ERROR: {e}")

@bot.event
async def on_ready():
    print("=== ISERO ONLINE ===")
    print(f"[BOOT] Bot user: {bot.user} (id={bot.user.id})")
    print(f"[BOOT] Guilds: {[g.name for g in bot.guilds]}")
    print(f"[BOOT] Intents.message_content = {bot.intents.message_content}")
    # Parancsok sync
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            print(f"[BOOT] App commands synced to guild {GUILD_ID}: {len(synced)}")
        else:
            synced = await bot.tree.sync()
            print(f"[BOOT] Global app commands synced: {len(synced)}")
    except Exception as e:
        print(f"[BOOT] Command sync ERROR: {e}")

    # Üzenet a staff csatornába
    if STAFF_CHANNEL_ID:
        ch = bot.get_channel(STAFF_CHANNEL_ID)
        if ch:
            try:
                await ch.send("✅ ISERO felállt, hallak titeket.")
            except Exception as e:
                print(f"[BOOT] Staff notify send ERROR: {e}")
        else:
            print(f"[BOOT] Staff channel not found: {STAFF_CHANNEL_ID}")

@bot.event
async def setup_hook():
    await load_cogs()

# Gyors /ping teszt, hogy biztos lásd: parancsok élnek
@bot.tree.command(name="ping", description="Gyors életjel teszt.")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong 🏓", ephemeral=True)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN hiányzik.")
    bot.run(DISCORD_TOKEN)
