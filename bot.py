import os
import sys
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

# prints menjenek ki azonnal
def p(*a): 
    print(*a, flush=True)

p(">>> importing bot.py ...")

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0") or "0")

p(f"[ENV] GUILD_ID={GUILD_ID} STAFF_CHANNEL_ID={STAFF_CHANNEL_ID}")
p(f"[ENV] TOKEN set? {bool(DISCORD_TOKEN)}")

# ---- INTENTS ----
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    try:
        await bot.load_extension("cogs.agent_gate")
        p("[BOOT] cogs.agent_gate loaded ✅")
    except Exception as e:
        p(f"[BOOT] cogs.agent_gate load ERROR: {e}")

@bot.event
async def setup_hook():
    p("[BOOT] setup_hook")
    await load_cogs()

@bot.event
async def on_ready():
    p("=== ISERO ONLINE ===")
    p(f"[BOOT] Bot user: {bot.user} (id={bot.user.id})")
    p(f"[BOOT] Guilds: {[g.name for g in bot.guilds]}")
    p(f"[BOOT] intents.message_content = {bot.intents.message_content}")

    # parancsok sync
    try:
        if GUILD_ID:
            synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            p(f"[BOOT] App commands synced to guild {GUILD_ID}: {len(synced)}")
        else:
            synced = await bot.tree.sync()
            p(f"[BOOT] Global app commands synced: {len(synced)}")
    except Exception as e:
        p(f"[BOOT] Command sync ERROR: {e}")

    # jelentsünk a staff csatornába
    if STAFF_CHANNEL_ID:
        ch = bot.get_channel(STAFF_CHANNEL_ID)
        p(f"[BOOT] staff channel lookup -> {ch}")
        if ch:
            try:
                await ch.send("✅ ISERO felállt, hallak titeket.")
            except Exception as e:
                p(f"[BOOT] staff notify send ERROR: {e}")
        else:
            p(f"[BOOT] Staff channel not found by get_channel: {STAFF_CHANNEL_ID}")

# --------- GYORS TESZT: figyeljük a staff csatornát ----------
@bot.event
async def on_message(message: discord.Message):
    try:
        if not message.guild or message.author.bot:
            return
        if message.channel.id == STAFF_CHANNEL_ID:
            p(f"[MSG] staff <- {message.author} : {message.content!r}")
            # egyszerű teszt: ha "isero" szerepel, válaszol
            if "isero" in message.content.lower():
                try:
                    await message.channel.send("👋 Hallak! (teszt válasz a bot.py-ból)")
                except Exception as e:
                    p(f"[SEND] staff reply ERROR: {e}")
    except Exception as e:
        p(f"[EVENT] on_message ERROR: {e}")
    # engedjük a commandokat/cogokat is futni
    await bot.process_commands(message)

# --------- /ping parancs ----------
@bot.tree.command(name="ping", description="Gyors életjel teszt.")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong 🏓", ephemeral=True)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN hiányzik.")
    p(">>> running bot.run()")
    bot.run(DISCORD_TOKEN)
