from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

LOG = logging.getLogger("bot")

TICKET_EMBED_COLOR = 0x5865F2  # Discord blurple
WELCOME_EMBED_COLOR = 0x2B2D31  # dark

# ---------- Views & Buttons ----------

class OpenTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Open Ticket",
            style=discord.ButtonStyle.primary,
            custom_id="tickets:open"  # persistent
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Category selection with a short description header (ephemeral)
        desc = (
            "**Mebinu** — Collectible figure requests, variants, codes, rarity.\n"
            "**Commission** — Paid custom art request: scope, budget, deadline.\n"
            "**NSFW 18+** — Adults only; stricter policy & review.\n"
            "**General Help** — Quick Q&A, guidance."
        )
        embed = discord.Embed(
            title="Choose a category",
            description=desc,
            color=TICKET_EMBED_COLOR
        )
        embed.set_footer(text="Select one to open a private ticket thread.")
        await interaction.response.send_message(
            embed=embed,
            view=CategoryView(),
            ephemeral=True
        )


class OpenTicketView(discord.ui.View):
    """Persistent view for the hub card."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OpenTicketButton())


async def create_private_thread(
    *,
    interaction: discord.Interaction,
    category_label: str,
) -> None:
    """Creates a private thread in the current text channel, invites the user, posts a welcome embed."""
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.followup.send(
            "This command must be used inside a text channel.", ephemeral=True
        )
        return

    thread_name = f"{category_label.upper()} | {interaction.user.display_name}"
    LOG.info("Creating private thread: %s", thread_name)

    thread = await interaction.channel.create_thread(
        name=thread_name,
        type=discord.ChannelType.private_thread,
        invitable=False,
        auto_archive_duration=10080  # 7 days
    )

    try:
        await thread.add_user(interaction.user)
    except discord.HTTPException:
        # If the user is already in / or missing perms, continue.
        pass

    welcome = discord.Embed(
        title=f"{category_label} Ticket",
        description=(
            f"Welcome {interaction.user.mention}!\n\n"
            "A staff member will be with you shortly. "
            "Please describe your request clearly.\n\n"
            "_Only you and staff can see this private thread._"
        ),
        color=WELCOME_EMBED_COLOR
    )
    await thread.send(embed=welcome)
    await interaction.followup.send(
        content=f"Opened a private ticket thread: {thread.mention}",
        ephemeral=True
    )


class AgeConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, I am 18+", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=False)
        await create_private_thread(interaction=interaction, category_label="NSFW 18+")
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Understood. NSFW tickets are only for 18+ users.", ephemeral=True
        )
        self.stop()


class CategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    # Mebinu
    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.primary)
    async def btn_mebinu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=False)
        await create_private_thread(interaction=interaction, category_label="Mebinu")

    # Commission (now NOT grey – set to Primary/blurple)
    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary)
    async def btn_commission(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=False)
        await create_private_thread(interaction=interaction, category_label="Commission")

    # NSFW with age gate
    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def btn_nsfw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please confirm your age to continue:", view=AgeConfirmView(), ephemeral=True
        )

    # General Help
    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def btn_general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=False)
        await create_private_thread(interaction=interaction, category_label="General Help")


# ---------- Cog ----------

class Tickets(commands.Cog, name="tickets"):
    """Ticket Hub: setup card, cleanup, and ticket flow."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Make the Open Ticket button survive restarts
        bot.add_view(OpenTicketView())

    # /ticket_hub_setup
    @app_commands.command(
        name="ticket_hub_setup",
        description="Post the Ticket Hub card with the Open Ticket button in this channel (or the given one)."
    )
    @app_commands.describe(channel="Channel to post the hub card (default: here)")
    @commands.has_permissions(manage_channels=True)
    async def ticket_hub_setup(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None
    ):
        await interaction.response.defer(ephemeral=True, thinking=False)
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.followup.send("Please choose a text channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Ticket Hub",
            description="Open a ticket with the button below. You will pick a category in the next step.",
            color=TICKET_EMBED_COLOR,
        )
        embed.set_footer(text="A private thread will be created for you.")
        view = OpenTicketView()
        await target.send(embed=embed, view=view)

        await interaction.followup.send(
            f"✅ Hub card and button placed in {target.mention}.", ephemeral=True
        )
        LOG.info("Ticket hub card posted in %s", target.id)

    # /ticket_hub_cleanup
    @app_commands.command(
        name="ticket_hub_cleanup",
        description="Clean bot/system messages in this channel. Use to reset the hub."
    )
    @commands.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=False)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Run this inside the hub text channel.", ephemeral=True)
            return

        removed = 0
        async for msg in channel.history(limit=500, oldest_first=False):
            try:
                # remove our bot messages & system thread-openers; skip pinned
                if msg.pinned:
                    continue
                if msg.author == self.bot.user or (msg.is_system() and msg.type is not None):
                    await msg.delete()
                    removed += 1
                    # Be gentle to avoid 429 spam
                    await asyncio.sleep(0.8)
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                # If too old for bulk delete or minor hiccup, keep going slowly
                await asyncio.sleep(1.0)

        # done
        await channel.send(embed=self._hub_status_embed(removed))
        await interaction.followup.send(
            f"✅ Cleanup finished. Deleted messages: **{removed}**.", ephemeral=True
        )
        LOG.info("Ticket hub cleanup removed %s messages in #%s", removed, channel.id)

    # helpers
    @staticmethod
    def _hub_status_embed(removed_count: int) -> discord.Embed:
        e = discord.Embed(color=TICKET_EMBED_COLOR)
        e.title = "Ticket Hub"
        e.description = "Hub card & buttons are available below."
        e.add_field(name="Cleanup", value=f"Deleted messages: **{removed_count}**")
        return e


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
