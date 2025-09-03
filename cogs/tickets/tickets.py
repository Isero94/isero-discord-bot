from __future__ import annotations

import re
import time
import asyncio
import typing as T

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import settings
from cogs.tickets.mebinu_flow import MebinuSession, QUESTIONS, start_flow

TICKET_HUB_CHANNEL_ID = settings.CHANNEL_TICKET_HUB
TICKETS_CATEGORY_ID   = settings.CATEGORY_TICKETS
ARCHIVE_CATEGORY_ID   = settings.ARCHIVE_CATEGORY_ID
STAFF_ROLE_ID         = settings.STAFF_ROLE_ID
TICKET_COOLDOWN_SEC   = settings.TICKET_COOLDOWN_SECONDS

NSFW_ROLE_NAME        = settings.NSFW_ROLE_NAME
MAX_ATTACH            = 4  # self-flowban ennyi referencia kép engedett

# ---- channel topic marker / helpers ----
def owner_marker(user_id: int) -> str:
    return f"owner:{user_id}"

def slugify(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9\-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "ticket"

def kind_from_topic(topic: str | None) -> str:
    # topic pl.: "owner:123 | type:commission"
    if not topic:
        return "general-help"
    m = re.search(r"type:([a-z0-9\- ]+)", topic)
    return (m.group(1) if m else "general-help").strip()

def owner_from_topic(topic: str | None) -> int | None:
    if not topic:
        return None
    m = re.search(r"owner:(\d+)", topic)
    return int(m.group(1)) if m else None

# ------- Views -------

class OpenTicketView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=None)  # persistent
        self.cog = cog

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.category_embed(),
            view=CategoryView(self.cog),
            ephemeral=True
        )

class CategoryView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Mebinu", style=discord.ButtonStyle.primary)
    async def mebinu(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "mebinu")

    @discord.ui.button(label="Commission", style=discord.ButtonStyle.secondary)
    async def commission(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "commission")

    @discord.ui.button(label="NSFW 18+", style=discord.ButtonStyle.danger)
    async def nsfw(self, i: discord.Interaction, _: discord.ui.Button):
        await i.response.send_message(
            "Are you 18 or older?",
            view=AgeView(self.cog),
            ephemeral=True
        )

    @discord.ui.button(label="General Help", style=discord.ButtonStyle.success)
    async def general_help(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.on_category_chosen(i, "general-help")

class AgeView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, i: discord.Interaction, _: discord.ui.Button):
        # NSFW 18+ szerep hozzárendelése – ha nincs, létrehozzuk
        guild = T.cast(discord.Guild, i.guild)
        user  = T.cast(discord.Member, i.user)

        role = discord.utils.get(guild.roles, name=NSFW_ROLE_NAME)
        if role is None:
            try:
                role = await guild.create_role(name=NSFW_ROLE_NAME, reason="ISERO NSFW access")
            except discord.Forbidden:
                await i.response.send_message(
                    "I don't have permission to create roles. Please grant me `Manage Roles`.",
                    ephemeral=True
                )
                return

        if role not in user.roles:
            try:
                await user.add_roles(role, reason="ISERO 18+ self-confirmation")
            except discord.Forbidden:
                await i.response.send_message(
                    f"I couldn't assign the `{NSFW_ROLE_NAME}` role (missing `Manage Roles`).",
                    ephemeral=True
                )
                return

        await self.cog.on_category_chosen(i, "nsfw")

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, _: discord.ui.Button):
        await i.response.send_message("NSFW ticket not created.", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_btn(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.close_current_ticket(i)

# === csatorna-kezdő view (Én írom / ISERO írja) + Modal ===

class ChannelStartView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=600)
        self.cog = cog

    @discord.ui.button(label="Én írom meg", style=discord.ButtonStyle.primary, emoji="📝", custom_id="ticket:self")
    async def self_write(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.start_self_flow(i)

    @discord.ui.button(label="ISERO írja meg", style=discord.ButtonStyle.secondary, emoji="🤖", custom_id="ticket:isero")
    async def isero_write(self, i: discord.Interaction, _: discord.ui.Button):
        await self.cog.start_isero_flow(i)

class OrderModal(discord.ui.Modal, title="Rendelés részletei (max 800 karakter)"):
    def __init__(self, on_submit: T.Callable[[discord.Interaction, str], T.Awaitable[None]]):
        super().__init__(timeout=180)
        self._cb = on_submit
        self.desc = discord.ui.TextInput(
            label="Mit szeretnél?",
            style=discord.TextStyle.paragraph,
            max_length=800,
            required=True,
        )
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, str(self.desc.value))

# region ISERO PATCH MEBINU_DIALOG_V1
class SummaryView(discord.ui.View):
    def __init__(self, cog: "TicketsCog", channel: discord.TextChannel, owner_id: int, summary: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.channel = channel
        self.owner_id = owner_id
        self.summary = summary

    @discord.ui.button(label="Create brief from this", style=discord.ButtonStyle.primary, custom_id="mebinu:summary")
    async def submit(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.defer()
            return

        async def _submit_cb(ia: discord.Interaction, desc: str):
            self.cog.pending[self.channel.id] = {"owner_id": self.owner_id, "desc": desc, "left": MAX_ATTACH}
            await ia.response.send_message(
                f"✅ Leírás rögzítve. Most feltölthetsz **max {MAX_ATTACH}** képet ebbe a csatornába.\nHa kész vagy, írd be: **kész**.",
                ephemeral=True,
            )

        modal = OrderModal(_submit_cb)
        modal.desc.default = self.summary[:800]
        await interaction.response.send_modal(modal)
        self.stop()
# endregion ISERO PATCH MEBINU_DIALOG_V1

# ------- The Cog -------

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_open: dict[int, float] = {}   # cooldown map
        self.pending: dict[int, dict[str, T.Any]] = {}  # ch_id -> {owner_id, desc, left}
        self.mebinu_sessions: dict[int, MebinuSession] = {}
        # persistent views
        self.bot.add_view(OpenTicketView(self))
        self.bot.add_view(CloseTicketView(self))

    # --------- Embeds ----------
    def hub_embed(self) -> discord.Embed:
        e = discord.Embed(title="Ticket Hub")
        e.description = (
            "Press the **Open Ticket** button. In the next step you'll choose a category.\n"
            "Category selection comes next (ephemeral)."
        )
        return e

    def category_embed(self) -> discord.Embed:
        e = discord.Embed(title="Choose a category:")
        e.description = (
            "**• Mebinu** — collectible figures: requests, variants, codes, rarity\n"
            "**• Commission** — paid custom work: scope, budget, deadline\n"
            "**• NSFW 18+** — adult content (confirmation required)\n"
            "**• General Help** — quick Q&A and guidance"
        )
        return e

    def welcome_embed(self, user: discord.User, kind: str) -> discord.Embed:
        title = f"Welcome — {kind.replace('-', ' ').title()}"
        e = discord.Embed(title=title)
        e.description = (
            f"Hello {user.mention}! Ez itt a privát ticket csatornád.\n"
            "Válassz lent: **Én írom meg** vagy **ISERO írja meg**.\n"
            "• *Én írom meg* → rövid leírást adsz (max 800), majd max **4** referencia képet tölthetsz fel.\n"
            "• *ISERO írja meg* → kérdésekben végigvisz a pontosításon.\n\n"
            "*Használd a piros gombot, ha végeztél: Close Ticket.*"
        )
        return e

    # --------- Utilities ----------
    def _cooldown_left(self, user_id: int) -> int:
        now = time.time()
        last = self.last_open.get(user_id, 0.0)
        remain = int(TICKET_COOLDOWN_SEC - (now - last))
        return remain if remain > 0 else 0

    async def _find_existing_ticket(self, guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
        cat = guild.get_channel(TICKETS_CATEGORY_ID) if TICKETS_CATEGORY_ID else None
        if not isinstance(cat, discord.CategoryChannel):
            return None
        for ch in cat.text_channels:
            if ch.topic and owner_marker(user_id) in ch.topic:
                return ch
        return None

    async def create_ticket_channel(self, i: discord.Interaction, key: str) -> discord.TextChannel:
        assert isinstance(i.user, (discord.Member, discord.User))
        guild = T.cast(discord.Guild, i.guild)
        user = T.cast(discord.Member, i.user)

        # category check
        cat: discord.CategoryChannel | None = None
        if TICKETS_CATEGORY_ID:
            x = guild.get_channel(TICKETS_CATEGORY_ID)
            if isinstance(x, discord.CategoryChannel):
                cat = x

        name = slugify(f"{key}-{user.display_name}")
        topic = f"{owner_marker(user.id)} | type:{key}"

        # permission overwrites
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True
            ),
        }
        if STAFF_ROLE_ID:
            role = guild.get_role(STAFF_ROLE_ID)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
                )

        ch = await guild.create_text_channel(
            name=name,
            category=cat,
            topic=topic,
            overwrites=overwrites
        )

        # üdv + kétgombos start + close gomb
        view = ChannelStartView(self)
        # region ISERO PATCH NSFW_SAFE_MODE
        from utils import policy as _policy
        if _policy.is_nsfw(ch):
            for item in list(view.children):
                if getattr(item, "custom_id", "") == "ticket:isero":
                    view.remove_item(item)
                    break
        # endregion ISERO PATCH NSFW_SAFE_MODE
        await ch.send(embed=self.welcome_embed(user, key), view=view)
        await ch.send(view=CloseTicketView(self))
        return ch

    # --------- Category választás ---------
    async def on_category_chosen(self, i: discord.Interaction, key: str):
        remain = self._cooldown_left(i.user.id)
        if remain > 0:
            await i.response.send_message(
                f"Please wait **{remain}s** before creating another ticket.",
                ephemeral=True
            )
            return

        existing = await self._find_existing_ticket(T.cast(discord.Guild, i.guild), i.user.id)
        if existing:
            await i.response.send_message(
                f"You already have an open ticket: {existing.mention}\n"
                "Please close it before opening a new one.",
                ephemeral=True
            )
            return

        await i.response.defer(ephemeral=True)
        ch = await self.create_ticket_channel(i, key)
        self.last_open[i.user.id] = time.time()
        await i.followup.send(f"Your ticket is ready: {ch.mention}", ephemeral=True)

    # --------- Close ---------
    async def close_current_ticket(self, i: discord.Interaction):
        ch = T.cast(discord.TextChannel, i.channel)
        guild = T.cast(discord.Guild, i.guild)

        if ARCHIVE_CATEGORY_ID:
            cat = guild.get_channel(ARCHIVE_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                try:
                    await ch.edit(category=cat)
                except discord.Forbidden:
                    pass

        try:
            ow = ch.overwrites_for(guild.default_role)
            ow.view_channel = True  # keep visible in archive
            ow.send_messages = False
            await ch.set_permissions(guild.default_role, overwrite=ow)
        except discord.Forbidden:
            pass

        await i.response.send_message("Ticket closed & archived.", ephemeral=True)

    # --------- „Én írom” flow ---------
    async def start_self_flow(self, i: discord.Interaction):
        ch = T.cast(discord.TextChannel, i.channel)
        top_owner = owner_from_topic(ch.topic)
        owner_id = top_owner or i.user.id

        async def _submit_cb(ia: discord.Interaction, desc: str):
            self.pending[ch.id] = {"owner_id": owner_id, "desc": desc, "left": MAX_ATTACH}
            await ia.response.send_message(
                f"✅ Leírás rögzítve. Most feltölthetsz **max {MAX_ATTACH}** képet ebbe a csatornába.\n"
                f"Ha kész vagy, írd be: **kész**.",
                ephemeral=True
            )

        await i.response.send_modal(OrderModal(_submit_cb))

    # --------- „ISERO írja” flow (első kérdések) – NEM ephemeral ---------
    async def start_isero_flow(self, i: discord.Interaction):
        ch = T.cast(discord.TextChannel, i.channel)
        k = kind_from_topic(ch.topic)
        from utils import policy as _policy
        if k.startswith("mebinu"):
            # region ISERO PATCH MEBINU_DIALOG_V1
            if (
                _policy.getbool("FEATURES_MEBINU_DIALOG_V1", default=False)
                or _policy.feature_on("mebinu_dialog_v1")
                or getattr(settings, "FEATURES_MEBINU_DIALOG_V1", False)
            ):
                await start_flow(self, i)
                return
            q = "Melyik alcsomag érdekel? (Logo/Branding, Asset pack, Social set, Egyéb) — írd le röviden a célt és a határidőt."
            await i.response.send_message(
                f"{i.user.mention} {q}",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
            return
            # endregion ISERO PATCH MEBINU_DIALOG_V1

        if k.startswith("commission"):
            q = "Kezdjük az alapokkal: stílus, méret, határidő. Van referenciád?"
        elif k in ("nsfw", "nsfw 18+"):
            q = "Röviden írd le a témát és a tiltott dolgokat. (A szabályokat itt is betartjuk.)"
        elif k.startswith("mebinu") and not (
            _policy.getbool("FEATURES_MEBINU_DIALOG_V1", default=False)
            or _policy.feature_on("mebinu_dialog_v1")
            or getattr(settings, "FEATURES_MEBINU_DIALOG_V1", False)
        ):
            q = "Melyik alcsomag érdekel? (Logo/Branding, Asset pack, Social set, Egyéb) — írd le röviden a célt és a határidőt."
        else:
            q = "Mi a célod egy mondatban? Utána adok 2–3 opciót."

        await i.response.send_message(
            f"{i.user.mention} {q}",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
        )

    # --------- Slash commands ----------
    @app_commands.command(name="ticket_hub_setup", description="Post the Ticket Hub here.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_hub_setup(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        channel = T.cast(discord.TextChannel, i.channel)
        await channel.send(embed=self.hub_embed(), view=OpenTicketView(self))
        await i.followup.send("Ticket Hub posted.", ephemeral=True)

    @app_commands.command(name="ticket_hub_cleanup", description="Delete bot messages in this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ticket_hub_cleanup(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        channel = T.cast(discord.TextChannel, i.channel)

        deleted = 0
        async for m in channel.history(limit=200):
            if m.author.id == self.bot.user.id:
                try:
                    await m.delete()
                    deleted += 1
                    await asyncio.sleep(0.2)
                except discord.Forbidden:
                    pass
        await i.followup.send(f"Cleanup done. Deleted messages: **{deleted}**", ephemeral=True)

    # --------- Message listener ---------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # 1) SELF-FLOW képfogás
        ch = message.channel
        if isinstance(ch, discord.TextChannel) and ch.id in self.pending:
            st = self.pending[ch.id]
            owner_id = st.get("owner_id")
            if owner_id and message.author.id != owner_id:
                return
            if message.content.strip().lower() == "kész":
                self.pending.pop(ch.id, None)
                await ch.send("✅ Rendben, rögzítettem a leírást. Hamarosan jelentkezünk.")
                return
            if message.attachments:
                take = min(len(message.attachments), st["left"])
                st["left"] -= take
                await ch.send(f"☑️ {take} kép társítva. Még **{st['left']}** fér el.")
                if st["left"] <= 0:
                    self.pending.pop(ch.id, None)
                    await ch.send("✅ Köszi! Megvan minden. Hamarosan jelentkezünk a részletekkel.")
                return

        # 1/b) MEBINU guided flow
        if settings.FEATURES_MEBINU_DIALOG_V1 and isinstance(ch, discord.TextChannel) and ch.id in self.mebinu_sessions:
            session = self.mebinu_sessions[ch.id]
            owner_id = owner_from_topic(ch.topic)
            if owner_id and message.author.id != owner_id:
                return
            session.record(message.content)
            nxt = session.next_question()
            if nxt:
                # region ISERO PATCH MEBINU
                await ch.send(
                    f"{message.author.mention} {nxt} [{session.step+1}/{len(QUESTIONS)}]"
                )
                # endregion ISERO PATCH MEBINU
            else:
                summary = session.summary()
                owner_id = owner_from_topic(ch.topic) or message.author.id
                view = SummaryView(self, ch, owner_id, summary)
                await ch.send(
                    f"{message.author.mention} Összegzem a válaszaidat – kattints a gombra ha kész vagy.",
                    view=view,
                )
                self.mebinu_sessions.pop(ch.id, None)
            return

        # 2) opcionális text fallback a hub parancsokra
        raw = message.content.strip().lower()
        if raw in ("/ticket_hub_setup", "ticket_hub_setup"):
            perms = message.author.guild_permissions
            if not perms.manage_channels:
                return
            await message.channel.send(embed=self.hub_embed(), view=OpenTicketView(self))
        elif raw in ("/ticket_hub_cleanup", "ticket_hub_cleanup"):
            perms = message.author.guild_permissions
            if not perms.manage_messages:
                return
            deleted = 0
            async for m in message.channel.history(limit=200):
                if m.author.id == self.bot.user.id:
                    try:
                        await m.delete()
                        deleted += 1
                        await asyncio.sleep(0.2)
                    except discord.Forbidden:
                        pass
            await message.channel.send(f"Cleanup done. Deleted: **{deleted}**")

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
