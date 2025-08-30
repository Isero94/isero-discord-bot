import os
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# === ENV / CONFIG ===
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Színek
COLOR_INFO = discord.Color.blurple()
COLOR_OK = discord.Color.green()
COLOR_WARN = discord.Color.orange()

# ---- Helper: jogosultság a setup/cleanup-hoz ----
def _is_owner_or_manage_guild(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator


# === VIEWS ===
class OpenTicketView(discord.ui.View):
    """Persistent view: a hub üzeneten egyetlen 'Open Ticket' gomb."""
    def __init__(self):
        super().__init__(timeout=None)
        # Custom ID fixen hagyjuk, hogy persistáljon restart után is
        self.open_btn = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="Open Ticket",
            custom_id="ticket:open"
        )
        self.open_btn.callback = self.on_open_clicked
        self.add_item(self.open_btn)

    async def on_open_clicked(self, interaction: discord.Interaction):
        """Ephemeral kategóriaválasztó + ismertető."""
        embed = discord.Embed(
            title="Choose a category",
            description=(
                "Pick what you need:\n"
                "• **Mebinu** — collectible figure requests, variants, codes, rarity.\n"
                "• **Commission** — paid, custom art requests (scope, budget, deadline).\n"
                "• **NSFW 18+** — 18+ only; stricter rules & review.\n"
                "• **General Help** — quick Q&A, guidance."
            ),
            color=COLOR_INFO,
        )
        view = CategorySelectView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CategorySelectView(discord.ui.View):
    """Ephemeral gombsor a kategóriákhoz."""
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.secondary, custom_id="ticket:cat_mebinu")
    async def mebinu_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await start_ticket(interaction, category="MEBINU")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary, custom_id="ticket:cat_commission")
    async def commission_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await start_ticket(interaction, category="COMMISSION")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, custom_id="ticket:cat_nsfw")
    async def nsfw_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        # age-gate: külön view Yes/No
        view = NSFWConfirmView()
        embed = discord.Embed(
            title="Age confirmation required",
            description="This section is **18+ only**. Are you 18 years old or older?",
            color=COLOR_WARN,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, custom_id="ticket:cat_help")
    async def help_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await start_ticket(interaction, category="GENERAL HELP")


class NSFWConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Yes, I'm 18+", style=discord.ButtonStyle.danger, custom_id="ticket:age_yes")
    async def yes_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await start_ticket(interaction, category="NSFW 18+")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, custom_id="ticket:age_no")
    async def no_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Understood. You can't open an NSFW ticket. Choose another category from the hub.",
            ephemeral=True
        )


# === TICKET MŰVELETEK ===
async def start_ticket(interaction: discord.Interaction, *, category: str):
    """Privát thread indítása a hub csatornában, user hozzáadása, nyitó üzenet."""
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message("Guild context missing.", ephemeral=True)

    hub_ch: Optional[discord.TextChannel] = guild.get_channel(TICKET_HUB_CHANNEL_ID)  # type: ignore
    if not isinstance(hub_ch, discord.TextChannel):
        return await interaction.response.send_message("Ticket hub channel is misconfigured.", ephemeral=True)

    # Thread név
    thread_name = f"{category} | {interaction.user.display_name}"

    try:
        thread = await hub_ch.create_thread(
            name=thread_name,
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        # user hozzáadása
        await thread.add_user(interaction.user)

        # nyitó üzenet
        open_text = (
            f"Welcome {interaction.user.mention}! This is your **{category}** private thread.\n"
            "Share the details; staff will follow up here.\n"
            "_Only invited members and staff can see this thread._"
        )
        await thread.send(open_text)

        # válasz a usernek linkkel
        embed = discord.Embed(
            title="Ticket opened",
            description=f"Your private thread is ready: {thread.mention}",
            color=COLOR_OK
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    except discord.Forbidden:
        msg = "I don't have permission to create private threads in the ticket hub."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        msg = f"Opening failed: `{type(e).__name__}: {e}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# === COG ===
class Tickets(commands.Cog, name="tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        # Register persistent views on startup
        self.bot.add_view(OpenTicketView())

    # ----- /ticket_hub_setup -----
    @app_commands.command(name="ticket_hub_setup", description="Create or refresh the Ticket Hub message.")
    async def ticket_hub_setup(self, interaction: discord.Interaction):
        if not _is_owner_or_manage_guild(interaction):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Guild context missing.", ephemeral=True)

        hub_ch: Optional[discord.TextChannel] = guild.get_channel(TICKET_HUB_CHANNEL_ID)  # type: ignore
        if not isinstance(hub_ch, discord.TextChannel):
            return await interaction.response.send_message("Ticket hub channel is misconfigured.", ephemeral=True)

        # (Opcionális light cleanup: csak a saját korábbi hub üzeneteinket próbáljuk leszedni.)
        removed = 0
        try:
            async for msg in hub_ch.history(limit=200):
                if msg.author == self.bot.user:
                    # Kerüljük a rate limitet
                    try:
                        await msg.delete()
                        removed += 1
                        await asyncio.sleep(0.35)
                    except:
                        pass
        except:
            pass

        # Új hub kártya + egyetlen „Open Ticket” gomb
        embed = discord.Embed(
            title="🎫 Ticket Hub",
            description="Click the button below to open a ticket. You will choose a category in the next step.",
            color=COLOR_INFO
        )
        embed.set_footer(text="Hub is clean. Old messages removed: {}".format(removed))
        await hub_ch.send(embed=embed, view=OpenTicketView())

        await interaction.response.send_message("Ticket Hub deployed.", ephemeral=True)

    # ----- /ticket_hub_cleanup [deep] -----
    @app_commands.command(name="ticket_hub_cleanup", description="Clean the ticket hub channel; deep=true also deletes old threads.")
    @app_commands.describe(deep="If true, attempt to delete old private threads too.")
    async def ticket_hub_cleanup(self, interaction: discord.Interaction, deep: Optional[bool] = False):
        if not _is_owner_or_manage_guild(interaction):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Guild context missing.", ephemeral=True)

        hub_ch: Optional[discord.TextChannel] = guild.get_channel(TICKET_HUB_CHANNEL_ID)  # type: ignore
        if not isinstance(hub_ch, discord.TextChannel):
            return await interaction.response.send_message("Ticket hub channel is misconfigured.", ephemeral=True)

        removed_msgs = 0
        removed_threads = 0

        # Üzenetek takarítása (csak bot üzenetek)
        async for msg in hub_ch.history(limit=None):
            if msg.author == self.bot.user:
                try:
                    await msg.delete()
                    removed_msgs += 1
                    await asyncio.sleep(0.35)
                except:
                    pass

        # Thread takarítás, ha kérik
        if deep:
            # Aktív privát threadek
            for th in hub_ch.threads:
                try:
                    await th.delete()
                    removed_threads += 1
                    await asyncio.sleep(0.5)
                except:
                    pass

            # Archivált threadek (async iterator)
            try:
                async for th in hub_ch.archived_threads(limit=200, private=True):
                    try:
                        await th.delete()
                        removed_threads += 1
                        await asyncio.sleep(0.5)
                    except:
                        pass
            except:
                pass

        # Napló / visszajelzés
        await interaction.response.send_message(
            f"Cleanup done. Removed messages: **{removed_msgs}**."
            + (f" Removed threads: **{removed_threads}**." if deep else ""),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
