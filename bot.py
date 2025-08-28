# bot.py
import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ---- Intents ----
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


# ---- Saját Bot osztály ----
class IseroBot(commands.Bot):
    async def setup_hook(self):
        # COG-ok betöltése
        await load_extensions_and_views(self)

        # Slash parancsok szinkronja
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


# ---- COG + View betöltés ----
INITIAL_EXTENSIONS = [
    "cogs.profiles",
    "cogs.logging",
    "cogs.moderation",
    "cogs.agent_gate",
]

async def load_extensions_and_views(bot: IseroBot):
    for ext in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(ext)
            print(f"[BOOT] Loaded {ext}")
        except Exception as e:
            print(f"[BOOT] Failed to load {ext}: {e}")

    try:
        from cogs.agent_gate import TicketHubView
        bot.add_view(TicketHubView())
        print("[BOOT] TicketHubView added")
    except Exception as e:
        print(f"[BOOT] Failed to add TicketHubView: {e}")


# ---- Események ----
@commands.is_owner()
@commands.command()
async def sync(ctx: commands.Context):
    """Owner-only: slash parancsok szinkronizálása."""
    try:
        bot: IseroBot = ctx.bot
        gid = os.getenv("GUILD_ID")
        if gid:
            guild = discord.Object(id=int(gid))
            await bot.tree.sync(guild=guild)
            await ctx.send(f"✅ Slash parancsok szinkronizálva a guildre: {gid}")
        else:
            await bot.tree.sync()
            await ctx.send("✅ Globális slash parancsok szinkronizálva.")
    except Exception as e:
        await ctx.send(f"❌ Sync hiba: `{e}`")


async def add_owner_commands(bot: IseroBot):
    bot.add_command(sync)


@commands.Cog.listener()
async def on_ready():
    print(f"✅ ISERO online")


# ---- Belépési pont ----
async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing in environment.")

    bot = IseroBot(
        command_prefix=commands.when_mentioned_or("!"),
        intents=intents,
        help_command=None,
    )

    await add_owner_commands(bot)

    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
