# cogs/tickets/forms.py
from __future__ import annotations

import datetime as dt
import discord

NSFW_ROLE_NAME = "NSFW 18+"

# ---------- Embedek (Hub és lépései) ----------

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

# ---------- Thread-kezdő gombok (Én írom / ISERO írja) ----------

class ThreadStartView(discord.ui.View):
    """
    A privát thread első üzenetéhez csatolt view:
    - Én írom meg → 800 karakteres modal + max 4 kép workflow
    - ISERO írja meg → kategóriafüggő kérdések indítása
    """
    def __init__(self, runtime: "TicketsRuntime", *, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.runtime = runtime

    @discord.ui.button(label="Én írom meg", style=discord.ButtonStyle.primary, emoji="📝", custom_id="isero:thread:self")
    async def btn_self(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.runtime.start_self_flow(interaction)

    @discord.ui.button(label="ISERO írja meg", style=discord.ButtonStyle.secondary, emoji="🤖", custom_id="isero:thread:isero")
    async def btn_isero(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.runtime.start_isero_flow(interaction)

# 800 karakteres leírás modal – callbacket a runtime adja
class OrderModal(discord.ui.Modal, title="Rendelés részletei (max 800 karakter)"):
    def __init__(self, on_submit_cb):
        super().__init__(timeout=180)
        self.on_submit_cb = on_submit_cb
        self.desc = discord.ui.TextInput(
            label="Mit szeretnél?",
            style=discord.TextStyle.paragraph,
            max_length=800,
            required=True,
        )
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        await self.on_submit_cb(interaction, str(self.desc.value))

# ---------- Hub view-k (Open Ticket → kategória → NSFW gate) ----------

class OpenTicketView(discord.ui.View):
    """A Hub üzenetre rátűzhető (akár perzisztens) gomb."""
    def __init__(self, runtime: "TicketsRuntime"):
        super().__init__(timeout=None)
        self.runtime = runtime

    @discord.ui.button(style=discord.ButtonStyle.success, label="Open Ticket",
                       custom_id="isero:open_ticket")
    async def on_open_clicked(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=categories_embed(),
            view=CategoryView(self.runtime),
            ephemeral=True
        )

class CategoryView(discord.ui.View):
    """Csak annak látszik, aki megnyomta az Open Ticketet (ephemeral)."""
    def __init__(self, runtime: "TicketsRuntime"):
        super().__init__(timeout=120)
        self.runtime = runtime

        self.add_item(discord.ui.Button(label="Mabinu", style=discord.ButtonStyle.secondary, emoji="🧩",
                                        custom_id="isero:cat:mabinu"))
        self.add_item(discord.ui.Button(label="Commission", style=discord.ButtonStyle.primary, emoji="🧾",
                                        custom_id="isero:cat:commission"))
        self.add_item(discord.ui.Button(label="NSFW 18+", style=discord.ButtonStyle.danger, emoji="🔞",
                                        custom_id="isero:cat:nsfw"))
        self.add_item(discord.ui.Button(label="General Help", style=discord.ButtonStyle.success, emoji="💬",
                                        custom_id="isero:cat:general"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ephemerálnál elvileg nem szükséges, de hagyjuk bent
        return True

    @discord.ui.button(label="Mabinu", style=discord.ButtonStyle.secondary, emoji="🧩")
    async def _mabinu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.runtime.open_ticket_for(interaction, "Mabinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.primary, emoji="🧾")
    async def _commission(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.runtime.open_ticket_for(interaction, "Commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger, emoji="🔞")
    async def _nsfw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=nsfw_confirm_embed(),
            view=AgeGateView(self.runtime),
            ephemeral=True
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success, emoji="💬")
    async def _general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.runtime.open_ticket_for(interaction, "General Help")

class AgeGateView(discord.ui.View):
    def __init__(self, runtime: "TicketsRuntime"):
        super().__init__(timeout=90)
        self.runtime = runtime

    @discord.ui.button(label="Yes, I'm 18+", style=discord.ButtonStyle.danger, emoji="✅",
                       custom_id="isero:age:yes")
    async def _confirm_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        await self.runtime.open_ticket_for(interaction, "NSFW 18+")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, emoji="🚫",
                       custom_id="isero:age:no")
    async def _confirm_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Understood. You can choose another category from the menu.",
            ephemeral=True
        )

# ---------- A runtime felület, amit a tickets.py valósít meg ----------

class TicketsRuntime:
    """
    Csak egy „interface” típusjelzés a type hinthez. A tényleges implementáció a cogs/tickets/tickets.py-ben van.
    """
    async def open_ticket_for(self, interaction: discord.Interaction, category_label: str): ...
    async def start_self_flow(self, interaction: discord.Interaction): ...
    async def start_isero_flow(self, interaction: discord.Interaction): ...
