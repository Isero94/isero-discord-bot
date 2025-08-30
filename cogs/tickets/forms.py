# cogs/tickets/forms.py
from __future__ import annotations

import asyncio
import datetime as dt
import discord
from discord.ext import commands

NSFW_ROLE_NAME = "NSFW 18+"

def hub_header_embed() -> discord.Embed:
    e = discord.Embed(
        title="ISERO Ticket Hub",
        description=(
            "**Welcome!** Click **Open Ticket** to start.\n\n"
            "After clicking, you'll see these options:\n"
            "• **Mabinu** – Project / collaboration with Mabinu.\n"
            "• **Commission** – Request a paid commission.\n"
            "• **NSFW 18+** – Age-restricted support or requests (confirmation required).\n"
            "• **General Help** – Any other questions or assistance.\n"
        ),
        colour=discord.Colour.blurple()
    )
    e.set_footer(text="ISERO • clean, minimal, English-only UI")
    return e

def categories_embed() -> discord.Embed:
    e = discord.Embed(
        title="Choose a Category",
        description=(
            "Pick the ticket type that best matches your request:\n\n"
            "• **Mabinu** — Project / collaboration with Mabinu\n"
            "• **Commission** — Paid work request (art/design/dev/etc.)\n"
            "• **NSFW 18+** — 18+ content or assistance (age check required)\n"
            "• **General Help** — Anything else\n"
        ),
        colour=discord.Colour.green()
    )
    return e

def nsfw_confirm_embed() -> discord.Embed:
    e = discord.Embed(
        title="Age Confirmation Required (18+)",
        description=(
            "You selected **NSFW 18+**.\n\n"
            "Please confirm that you are **18 years or older** to proceed."
        ),
        colour=discord.Colour.red()
    )
    return e

def ticket_opened_embed(category_label: str) -> discord.Embed:
    e = discord.Embed(
        title=f"{category_label} Ticket Created",
        description="A private ticket thread has been opened for you in this channel.",
        colour=discord.Colour.blue()
    )
    return e

class OpenTicketView(discord.ui.View):
    """Persistent view attached to the Hub message."""
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=None)
        self.cog = cog
        btn = discord.ui.Button(
            style=discord.ButtonStyle.success,
            label="Open Ticket",
            custom_id="isero:open_ticket"
        )
        btn.callback = self.on_open_clicked  # type: ignore
        self.add_item(btn)

    async def on_open_clicked(self, interaction: discord.Interaction):
        view = CategoryView(self.cog)
        await interaction.response.send_message(
            embed=categories_embed(),
            view=view,
            ephemeral=True
        )

class CategoryView(discord.ui.View):
    """Ephemeral category picker; only visible to the user who clicked Open Ticket."""
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=120)
        self.cog = cog

        b1 = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Mabinu",
            custom_id="isero:cat:mabinu",
            emoji="🧩"
        )
        b1.callback = self._wrap_handler("Mabinu")
        self.add_item(b1)

        b2 = discord.ui.Button(
            style=discord.ButtonStyle.primary,  # SZÍN: blurple
            label="Commission",
            custom_id="isero:cat:commission",
            emoji="🧾"
        )
        b2.callback = self._wrap_handler("Commission")
        self.add_item(b2)

        b3 = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="NSFW 18+",
            custom_id="isero:cat:nsfw",
            emoji="🔞"
        )
        b3.callback = self._nsfw_gate
        self.add_item(b3)

        b4 = discord.ui.Button(
            style=discord.ButtonStyle.success,
            label="General Help",
            custom_id="isero:cat:general",
            emoji="💬"
        )
        b4.callback = self._wrap_handler("General Help")
        self.add_item(b4)

    def _wrap_handler(self, category_label: str):
        async def handler(interaction: discord.Interaction):
            await self.cog.open_ticket_for(interaction, category_label)
        return handler

    async def _nsfw_gate(self, interaction: discord.Interaction):
        view = AgeGateView(self.cog)
        await interaction.response.send_message(
            embed=nsfw_confirm_embed(),
            view=view,
            ephemeral=True
        )

class AgeGateView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=90)
        self.cog = cog

        yes = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="Yes, I'm 18+",
            custom_id="isero:age:yes",
            emoji="✅"
        )
        no = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="No",
            custom_id="isero:age:no",
            emoji="🚫"
        )
        yes.callback = self._confirm_yes  # type: ignore
        no.callback = self._confirm_no   # type: ignore
        self.add_item(yes)
        self.add_item(no)

    async def _confirm_yes(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        assert guild is not None

        role = discord.utils.get(guild.roles, name=NSFW_ROLE_NAME)
        if role is None:
            try:
                role = await guild.create_role(name=NSFW_ROLE_NAME, reason="ISERO NSFW access")
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I don't have permission to create roles. Please grant me `Manage Roles`.",
                    ephemeral=True
                )
                return

        member = guild.get_member(user.id) or await guild.fetch_member(user.id)
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="ISERO 18+ self-confirmation")
            except discord.Forbidden:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "I couldn't assign the `NSFW 18+` role (missing `Manage Roles`).",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "I couldn't assign the `NSFW 18+` role (missing `Manage Roles`).",
                        ephemeral=True
                    )
                return

        await self.cog.open_ticket_for(interaction, "NSFW 18+")

    async def _confirm_no(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Understood. You can choose another category from the menu.",
            ephemeral=True
        )

class TicketsCog(commands.Cog):
    """Interface the View-ek hívásához; a tényleges Cog a tickets.py-ben van."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def open_ticket_for(self, interaction: discord.Interaction, category_label: str):
        """Privát thread létrehozása a Hub csatornában a kattintó usernek."""
        # >>> FONTOS: előbb válasz/defer, hogy a followup használható legyen
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True, thinking=False)
            except Exception:
                pass

        channel = interaction.channel
        user = interaction.user
        guild = interaction.guild

        if guild is None or channel is None or not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "This must be used in a standard **text channel**.",
                ephemeral=True
            )
            return

        perms = channel.permissions_for(guild.me)
        if not (perms.create_private_threads and perms.send_messages):
            await interaction.followup.send(
                "I need `Create Private Threads` and `Send Messages` permissions here.",
                ephemeral=True
            )
            return

        now = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        safe_name = f"{category_label} • {user.name} • {now}"[:95]

        try:
            thread = await channel.create_thread(
                name=safe_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=1440
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to create private threads here.",
                ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "Couldn't create a private thread due to a Discord error. Please try again.",
                ephemeral=True
            )
            return

        try:
            await thread.add_user(user)
        except discord.HTTPException:
            pass

        intro = (
            f"Hello {user.mention}! This is your private **{category_label}** ticket.\n"
            "Please describe your request. A team member will join shortly."
        )
        await thread.send(intro)

        await interaction.followup.send(
            embed=ticket_opened_embed(category_label),
            ephemeral=True
        )
