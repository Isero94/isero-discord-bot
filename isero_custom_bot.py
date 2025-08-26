# isero_custom_bot.py
"""
Custom Discord bot for the ISERO server.

This script uses the `discord.py` library to provide a handful of useful and fun
commands tailored for the ISERO community. Features include:

* Automatic welcome messages and optional role assignment for new members.
* A server information command that reports the name and member count.
* A simple role assignment command for self-assignable roles.
* An art prompt generator that returns random creative prompts.
* A generic dice roller for games.
* Latency check and bot status update commands.

Setup (summary):
1) Create an application and bot at https://discord.com/developers/applications
2) Copy the bot token and set it in the environment as DISCORD_TOKEN
3) pip install -r requirements.txt  (discord.py >= 2.3.0)
4) Run: python isero_custom_bot.py
"""

import os
import random
from typing import Optional

import discord
from discord.ext import commands

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# The bot will first check for an environment variable called DISCORD_TOKEN.
# This makes deployment easier because you can inject your secret without
# hard-coding it into the code. If the environment variable is not set,
# it falls back to the placeholder below. The main() function will raise
# an error if the placeholder is still present.
TOKEN: str = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN_HERE")

# Command prefix for classic (prefix) commands, e.g. ?ping
COMMAND_PREFIX: str = "?"

# Roles users are allowed to self-assign via ?assignrole <role>.
# Map the human-readable name (lowercase) to the role ID on your server.
# Replace the IDs below with real ones from your server.
SELF_ASSIGNABLE_ROLES: dict[str, int] = {
    "gamer": 123456789012345678,     # replace with your real role ID
    "artist": 234567890123456789,    # replace with your real role ID
    "streamer": 345678901234567890,  # replace with your real role ID
}

# Creative prompts for the art prompt generator.
ART_PROMPTS: list[str] = [
    "A cyberpunk skyline at sunset",
    "A mythical creature blending two animals",
    "A futuristic vehicle designed for underwater exploration",
    "A portrait in the style of a classic oil painting, but with a modern twist",
    "An abstract interpretation of your favorite song",
    "A cozy reading nook with fantastical elements",
    "A steampunk version of a common household item",
    "A surreal landscape where gravity does not behave normally",
    "A traditional Japanese tea house in a sci-fi setting",
    "An original character inspired by Eastern and Western mythology",
]

# -----------------------------------------------------------------------------
# Bot definition
# -----------------------------------------------------------------------------

intents = discord.Intents.default()
# Required for prefix commands (?ping, etc.)
intents.message_content = True
# Required if you want on_member_join to fire and to manage roles
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------

@bot.event
async def on_ready() -> None:
    """Called when the bot is fully connected and ready."""
    print(f"[ISERO] Connected as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Serving the ISERO community"))

@bot.event
async def on_member_join(member: discord.Member) -> None:
    """Welcome a new user. Optionally assign a default role (commented out)."""
    # Send a welcome DM to the user (may fail if DMs are closed)
    try:
        await member.send(
            f"Welcome to **{member.guild.name}**, {member.mention}!\n"
            "Make sure to read the rules and pick your roles in #server-guide."
        )
    except discord.HTTPException:
        print(f"[ISERO] Could not DM welcome to {member} (DMs likely closed).")

    # Example: auto-assign a default role (replace ID and uncomment)
    # default_role = member.guild.get_role(456789012345678901)  # Member role ID here
    # if default_role is not None:
    #     try:
    #         await member.add_roles(default_role, reason="Auto-assigned on join")
    #     except discord.Forbidden:
    #         print("[ISERO] Missing permission to add default role.")

# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------

def safe_set_thumbnail(embed: discord.Embed, guild: discord.Guild) -> None:
    """Attach guild icon if available."""
    try:
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)  # discord.py 2.x provides .url
    except Exception:
        # If anything goes wrong, skip the thumbnail
        pass

# -----------------------------------------------------------------------------
# Commands (prefix)
# -----------------------------------------------------------------------------

@bot.command(name="help")
async def help_command(ctx: commands.Context) -> None:
    """Displays a help message listing available commands."""
    embed = discord.Embed(title="ISERO Bot Commands", colour=discord.Colour.blue())
    embed.add_field(name="?help", value="Show this message.", inline=False)
    embed.add_field(name="?serverinfo", value="Server name and member count.", inline=False)
    embed.add_field(
        name="?assignrole <role>",
        value="Assign a self-assignable role (e.g. gamer, artist, streamer).",
        inline=False,
    )
    embed.add_field(name="?artprompt", value="Get a random creative prompt.", inline=False)
    embed.add_field(name="?roll <sides>", value="Roll a dice (default 6).", inline=False)
    embed.add_field(name="?ping", value="Check latency.", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="serverinfo")
async def server_info(ctx: commands.Context) -> None:
    """Send server name and member count."""
    guild = ctx.guild
    embed = discord.Embed(title="Server Information", colour=discord.Colour.green())
    embed.add_field(name="Server Name", value=guild.name, inline=False)
    embed.add_field(name="Total Members", value=guild.member_count, inline=False)
    safe_set_thumbnail(embed, guild)
    await ctx.send(embed=embed)

@bot.command(name="assignrole")
async def assign_role(ctx: commands.Context, *, role_name: str) -> None:
    """Assign a role to the user if it is in the self-assignable list."""
    key = role_name.lower().strip()
    if key not in SELF_ASSIGNABLE_ROLES:
        valid = ", ".join(SELF_ASSIGNABLE_ROLES.keys())
        await ctx.reply(f"Unknown role. Available roles: {valid}")
        return

    role_id = SELF_ASSIGNABLE_ROLES[key]
    role = ctx.guild.get_role(role_id)
    if role is None:
        await ctx.reply("Role not found on this server. Please contact an admin.")
        return

    if role in ctx.author.roles:
        await ctx.reply("You already have that role!")
        return

    try:
        await ctx.author.add_roles(role, reason="Self-assigned via bot command")
        await ctx.reply(f"Role **{role.name}** assigned successfully!")
    except discord.Forbidden:
        await ctx.reply("I do not have permission to assign that role.")

@bot.command(name="artprompt")
async def art_prompt(ctx: commands.Context) -> None:
    """Send a random art prompt."""
    prompt = random.choice(ART_PROMPTS)
    await ctx.send(f"🎨 Art Prompt: {prompt}")

@bot.command(name="roll")
async def roll_dice(ctx: commands.Context, sides: Optional[int] = 6) -> None:
    """Roll a dice and return a number between 1 and the specified sides."""
    try:
        sides_int = int(sides)
    except (TypeError, ValueError):
        await ctx.reply("Please provide a valid integer for the number of sides.")
        return

    if sides_int < 2:
        await ctx.reply("The dice must have at least 2 sides.")
        return

    result = random.randint(1, sides_int)
    await ctx.send(f"🎲 You rolled a {result} (1-{sides_int})")

@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    """Respond with the bot's latency."""
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"Pong! 🏓 Latency: {latency_ms} ms")

# -----------------------------------------------------------------------------
# Slash command example (quick test)
# -----------------------------------------------------------------------------

@bot.tree.command(name="ping", description="Pong!")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

@bot.event
async def setup_hook():
    # Global sync: first time can take a bit, but it is fine.
    # If you want instant commands on a test guild, replace with guild sync.
    await bot.tree.sync()

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main() -> None:
    if TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Configure it in your environment on Render."
        )
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
