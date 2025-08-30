# cogs/tickets/tickets.py
# Discord.py 2.4.x
import os
import asyncio
import logging
import datetime
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("bot")

def _int_env(name: str, default: int | None = None) -> int | None:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default

OWNER_ID = _int_env("OWNER_ID", 0)
GUILD_ID = _int_env("GUILD_ID")
TICKET_HUB_CHANNEL_ID = _int_env("TICKET_HUB_CHANNEL_ID")

def owner_or_manage_guild():
    async def predicate(interaction: discord.Interaction) -> bool:
        if OWNER_ID and interaction.user.id == OWNER_ID:
            return True
        return getattr(interaction.user.guild_permissions, "manage_guild", False)
    return app_commands.check(predicate)

# -------------------- Views --------------------

class OpenTicketView(discord.ui.View):
    """Persistent view: only the single 'Open Ticket' button appears in channel."""
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Open Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="tickets:open")  # persistent across restarts
    async def open_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        """Show the category chooser EPHEMERALLY (csak a kattintónak látszik)."""
        embed = discord.Embed(
            title="Choose a category",
            description=(
                "**Mebinu** — Collectible figure requests, variants, codes, rarities.\n"
                "**Commission** — Paid, one-off art jobs (scope, budget, deadline).\n"
                "**NSFW 18+** — Adults only; stricter rules & review.\n"
                "**General Help** — Quick Q&A, guidance, instructions."
            ),
            colour=discord.Colour.blurple()
        )
        embed.set_footer(text="Your choice opens a private thread that only you and staff can see.")
        await interaction.response.send_message(
            embed=embed,
            view=CategoryButtons(self.cog),
            ephemeral=True
        )

class CategoryButtons(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.success, custom_id="tickets:cat_mebinu")
    async def mebinu(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.create_ticket(interaction, "MEBINU")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary, custom_id="tickets:cat_commission")
    async def commission(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.create_ticket(interaction, "COMMISSION")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="tickets:cat_nsfw")
    async def nsfw(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "This section is **18+ only**. Are you 18 or older?",
            view=AgeConfirmView(self.cog),
            ephemeral=True
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.secondary, custom_id="tickets:cat_general")
    async def general(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.create_ticket(interaction, "GENERAL HELP")

class AgeConfirmView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes, I'm 18+", style=discord.ButtonStyle.success, custom_id="tickets:age_yes")
    async def yes(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.create_ticket(interaction, "NSFW 18+")
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="tickets:age_no")
    async def no(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Understood — cannot open NSFW tickets.", ephemeral=True)
        self.stop()

# -------------------- Cog --------------------

class Tickets(commands.Cog, name="tickets"):
    """Ticket hub with a single public 'Open Ticket' button and private category chooser."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_id = GUILD_ID
        self.hub_channel_id = TICKET_HUB_CHANNEL_ID

    async def cog_load(self):
        # Ensure the persistent 'Open Ticket' button survives restarts
        self.bot.add_view(OpenTicketView(self))
        log.info("Tickets cog ready (guild=%s, hub_channel=%s)", self.guild_id, self.hub_channel_id)

    # -------- Helpers --------

    def _fmt_thread_name(self, category: str, user: discord.abc.User) -> str:
        uname = f"{user.global_name or user.display_name or user.name}".strip()
        # Keep names short; Discord thread name max is 100 chars.
        uname = uname[:48]
        return f"{category} | {uname}"

    async def _get_hub_channel(self, interaction: discord.Interaction) -> discord.TextChannel:
        ch_id = self.hub_channel_id
        if ch_id is None:
            # fall back to current channel
            ch = interaction.channel
            if isinstance(ch, discord.TextChannel):
                return ch
            raise RuntimeError("Hub channel is not a text channel.")
        ch = interaction.client.get_channel(ch_id)
        if isinstance(ch, discord.TextChannel):
            return ch
        # final fallback: fetch
        fetched = await interaction.client.fetch_channel(ch_id)
        if not isinstance(fetched, discord.TextChannel):
            raise RuntimeError("Configured TICKET_HUB_CHANNEL_ID is not a text channel.")
        return fetched

    async def create_ticket(self, interaction: discord.Interaction, category: str):
        """Create private thread in the hub channel and invite the requester."""
        hub = await self._get_hub_channel(interaction)
        thread_name = self._fmt_thread_name(category, interaction.user)
        # Create a private thread so only user + staff sees it
        thread = await hub.create_thread(
            name=thread_name,
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=10080  # 7 days
        )
        try:
            await thread.add_user(interaction.user)
        except discord.HTTPException:
            pass

        # First message in the thread
        header = f"Welcome {interaction.user.mention}! This is your private thread for **{category}**."
        body = (
            "Share the details and attach references/screenshots as needed.\n"
            "Staff will pick this up shortly. Use `@here` only if urgent."
        )
        if category == "NSFW 18+":
            body += "\n**Reminder:** NSFW content must follow Discord ToS and server rules."

        await thread.send(f"{header}\n\n{body}")
        await interaction.response.send_message(
            f"Ticket created: {thread.mention}", ephemeral=True
        )

    # -------- Slash commands --------

    @app_commands.command(
        name="ticket_hub_setup",
        description="Post the Ticket Hub card with a single 'Open Ticket' button (English)."
    )
    @owner_or_manage_guild()
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        hub = await self._get_hub_channel(interaction)

        embed = discord.Embed(
            title="Ticket Hub",
            description="Open a ticket using the button below. You will choose the category in the next step.",
            colour=discord.Colour.dark_theme()
        )
        embed.set_footer(text="Private threads are visible only to you and staff.")

        view = OpenTicketView(self)
        await hub.send(embed=embed, view=view)
        await interaction.response.send_message("Hub card posted.", ephemeral=True)

    @app_commands.command(
        name="ticket_hub_cleanup",
        description="Clean the hub: delete the bot’s previous hub messages and (optionally) threads."
    )
    @app_commands.describe(
        deep="If true, also delete active threads created by the bot under this channel."
    )
    @owner_or_manage_guild()
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: bool = False):
        hub = await self._get_hub_channel(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)

        deleted_msgs = 0
        # delete only bot-authored messages to be safe
        async for msg in hub.history(limit=None, oldest_first=False):
            if msg.author.id == interaction.client.user.id:
                try:
                    await msg.delete()
                    deleted_msgs += 1
                    await asyncio.sleep(0.6)  # be gentle to avoid 429
                except discord.HTTPException as e:
                    if getattr(e, "status", None) == 429:
                        await asyncio.sleep(2.0)
                    else:
                        log.warning("Failed deleting msg %s: %s", msg.id, e)

        deleted_threads = 0
        if deep:
            for th in hub.threads:
                try:
                    # delete only threads the bot owns/created
                    if th.owner_id == interaction.client.user.id:
                        await th.delete()
                        deleted_threads += 1
                        await asyncio.sleep(0.8)
                except discord.HTTPException as e:
                    log.warning("Failed deleting thread %s: %s", th.id, e)

        await interaction.followup.send(
            f"Cleanup finished.\n• Deleted messages: **{deleted_msgs}**"
            + (f"\n• Deleted threads: **{deleted_threads}**" if deep else ""),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
