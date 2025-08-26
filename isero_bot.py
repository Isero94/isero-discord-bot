# isero_bot.py
import os
import asyncio
import logging
import discord
from discord.ext import commands

# ---- Alap beállítások ----
COMMAND_PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.presences = True

# Token környezeti változóból (Render → Environment → DISCORD_TOKEN)
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("A DISCORD_TOKEN környezeti változó hiányzik.")

# Opcionális: ha gyors slash-sync kell egy szerverre
GUILD_ID = os.getenv("GUILD_ID")  # pl. 123456789012345678 vagy üresen hagyod

# Logok
logging.basicConfig(level=logging.INFO)

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=INTENTS)

# ---- Események ----
@bot.event
async def on_ready():
    logging.info(f"[ISERO] Bejelentkezve mint {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Serving the ISERO community"))

@bot.event
async def on_member_join(member: discord.Member):
    """Új tag érkezett: privát üdvözlő DM (ha fogad DMet)."""
    try:
        await member.send(
            f"Üdv a(z) **{member.guild.name}** szerveren, {member.mention}! "
            "Olvasd el a szabályokat és vedd fel a szerepeket a #server-guide csatornában. 🙂"
        )
    except Exception:
        logging.info("[ISERO] Nem tudtam DM-et küldeni (valszeg zárt DM).")

# ---- Cogs betöltése ----
INITIAL_EXTENSIONS = [
    "cogs.utility",
    "cogs.moderation",
    "cogs.fun",
]

async def load_extensions():
    for ext in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(ext)
            logging.info(f"[ISERO] Betöltve: {ext}")
        except Exception as e:
            logging.exception(f"[ISERO] Hiba a {ext} betöltésekor: {e}")

@bot.event
async def setup_hook():
    # cogs
    await load_extensions()

    # Slash parancsok szinkronizálása
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            await bot.tree.sync(guild=guild)
            logging.info("[ISERO] Slash parancsok szinkronizálva a megadott guildre.")
        else:
            await bot.tree.sync()
            logging.info("[ISERO] Slash parancsok globálisan szinkronizálva (pár perc lehet).")
    except Exception as e:
        logging.exception(f"[ISERO] Slash sync hiba: {e}")

def main():
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
