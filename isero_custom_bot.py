"""
Custom Discord bot for the ISERO server.

This script uses the `discord.py` library to provide a handful of useful and fun
commands tailored for the ISERO community.  Features include:

* Automatic welcome messages and optional role assignment for new members.
* A server information command that reports the name and member count.
* A simple role assignment command for self‑assignable roles.
* An art prompt generator that returns random creative prompts.
* A generic dice roller for games.
* Latency check and bot status update commands.

To get this bot working you will need to:

1. Create a new application and bot at https://discord.com/developers/applications.
2. Copy the bot token and paste it into the `TOKEN` constant below.
3. Install dependencies with `pip install discord.py` (version 2.3 or newer).
4. Run the script with Python 3.11 or newer: `python isero_custom_bot.py`.

Note: This script is provided as a template.  You should update the role names
and IDs to match those on your server.  Additionally, consider adding
error handling and permission checks for production use.
"""

import asyncio
import os
import random
from typing import Optional

import discord
from discord.ext import commands


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Insert your bot token here.  Never share your bot token publicly!
#
# The bot will first check for an environment variable called ``DISCORD_TOKEN``.
# This makes deployment to cloud platforms easier because you can inject
#your secret without hard‑coding it into the code.  If the environment
variable is not set, it falls back to the placeholder below, which
will cause the program to raise an error in ``main()`` until you
configure it properly.
TOKEN: str = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN_HERE")

# The command prefix tells discord.py how to recognise commands.  You can
# customise this (e.g. to '/'), but a single character prefix is often
# convenient.
COMMAND_PREFIX: str = "?"

# Roles that users are allowed to self‑assign via the `?assignrole` command.
# Map the human readable role name (case insensitive) to the actual role
# identifier on your server (an integer).  You can obtain role IDs in
# Discord by enabling Developer Mode in your settings and right‑clicking a
# role to copy its ID.
SELF_ASSIGNABLE_ROLES: dict[str, int] = {
    "gamer": 123456789012345678,  # replace with your real role ID
    "artist": 234567890123456789,  # replace with your real role ID
    "streamer": 345678901234567890,  # replace with your real role ID
}

# List of creative prompts for the art prompt generator.  Feel free to
# customise this list to suit your community’s tastes.
ART_PROMPTS: list[str] = [
    "A cyberpunk skyline at sunset", 
    "A mythical creature blending two animals",
    "A futuristic vehicle designed for underwater exploration",
    "A portrait in the style of a classic oil painting, but with a modern twist",
    "An abstract interpretation of your favourite song",
    "A cozy reading nook with fantastical elements",
    "A steampunk version of a common household item",
    "A surreal landscape where gravity doesn’t behave normally",
    "A traditional Japanese tea house in a sci‑fi setting",
    "An original character inspired by both Eastern and Western mythology",
]


# -----------------------------------------------------------------------------
# Bot definition
# -----------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True  # required for prefix commands
intents.members = True  # required to handle member join events

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)


@bot.event
async def on_ready() -> None:
    """Called when the bot is fully connected and ready."""
    print(f"Connected to Discord as {bot.user} (ID: {bot.user.id})")
    print("------")
    # Optionally set a custom presence/status
    await bot.change_presence(activity=discord.Game(name="Serving the ISERO community"))


@bot.event
async def on_member_join(member: discord.Member) -> None:
    """Welcomes a new user.  Optionally assign a default role."""
    # Send a welcome DM to the user
    try:
        await member.send(
            f"Welcome to **{member.guild.name}**, {member.mention}!\n"
            "Make sure to read the rules and pick your roles in #server‑guide."
        )
    except discord.HTTPException:
        # It’s possible the user has DMs disabled
        print(f"Failed to send welcome message to {member}")
    # Example: automatically assign the Member role on join (replace with your role ID)
    # default_role = member.guild.get_role(456789012345678901)  # Member role ID here
    # if default_role is not None:
    #     await member.add_roles(default_role, reason="Auto‑assigned on join")


@bot.command(name="help")
async def help_command(ctx: commands.Context) -> None:
    """Displays a help message listing available commands."""
    embed = discord.Embed(title="ISERO Bot Commands", colour=discord.Colour.blue())
    embed.add_field(
        name="?help",
        value="Shows this message.",
        inline=False,
    )
    embed.add_field(
        name="?serverinfo",
        value="Displays information about the server (name, member count).",
        inline=False,
    )
    embed.add_field(
        name="?assignrole <role>",
        value="Assign yourself a self‑assignable role (e.g. gamer, artist, streamer).",
        inline=False,
    )
    embed.add_field(
        name="?artprompt",
        value="Get a random creative prompt to inspire your next piece.",
        inline=False,
    )
    embed.add_field(
        name="?roll <sides>",
        value="Roll a dice with a specified number of sides (defaults to 6).",
        inline=False,
    )
    embed.add_field(
        name="?ping",
        value="Check the bot’s latency.",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="serverinfo")
async def server_info(ctx: commands.Context) -> None:
    """Sends a summary of the server name and member count."""
    guild = ctx.guild
    embed = discord.Embed(title="Server Information", colour=discord.Colour.green())
    embed.add_field(name="Server Name", value=guild.name, inline=False)
    embed.add_field(name="Total Members", value=guild.member_count, inline=False)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else discord.Embed.Empty)
    await ctx.send(embed=embed)


@bot.command(name="assignrole")
async def assign_role(ctx: commands.Context, *, role_name: str) -> None:
    """Assigns a role to the user if it is in the self‑assignable list."""
    role_name_key = role_name.lower()
    if role_name_key not in SELF_ASSIGNABLE_ROLES:
        valid = ", ".join(SELF_ASSIGNABLE_ROLES.keys())
        await ctx.reply(f"Unknown role. Available roles: {valid}")
        return
    role_id = SELF_ASSIGNABLE_ROLES[role_name_key]
    role = ctx.guild.get_role(role_id)
    if role is None:
        await ctx.reply("Role not found on this server. Please contact an admin.")
        return
    if role in ctx.author.roles:
        await ctx.reply("You already have that role!")
        return
    try:
        await ctx.author.add_roles(role, reason="Self‑assigned via bot command")
        await ctx.reply(f"Role **{role.name}** assigned successfully!")
    except discord.Forbidden:
        await ctx.reply("I don't have permission to assign that role.")


@bot.command(name="artprompt")
async def art_prompt(ctx: commands.Context) -> None:
    """Sends a random art prompt."""
    prompt = random.choice(ART_PROMPTS)
    await ctx.send(f"🎨 **Art Prompt:** {prompt}")


@bot.command(name="roll")
async def roll_dice(ctx: commands.Context, sides: Optional[int] = 6) -> None:
    """Rolls a dice and returns a random number between 1 and the specified number of sides."""
    try:
        sides_int = int(sides)
    except ValueError:
        await ctx.reply("Please provide a valid integer for the number of sides.")
        return
    if sides_int < 2:
        await ctx.reply("The dice must have at least 2 sides.")
        return
    result = random.randint(1, sides_int)
    await ctx.send(f"🎲 You rolled a {result} (1-{sides_int})")


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    """Responds with the bot's latency."""
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"Pong! 🏓 Latency: {latency_ms}ms")


def main() -> None:
    """Entry point to run the bot."""
    # It's a good idea to check whether the TOKEN has been set
    if TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Please edit isero_custom_bot.py and set the TOKEN constant to your bot's token."
        )
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
