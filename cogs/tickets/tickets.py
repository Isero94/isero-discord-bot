from __future__ import annotations

import re
import time
import asyncio
import typing as T
import os
import datetime as dt
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import settings
from cogs.tickets.mebinu_flow import MebinuSession, QUESTIONS, start_flow, extract_signals
from cogs.utils.ticket_kb import load_ticket_kb

TICKET_HUB_CHANNEL_ID = settings.CHANNEL_TICKET_HUB
TICKETS_CATEGORY_ID   = settings.CATEGORY_TICKETS
ARCHIVE_CATEGORY_ID   = settings.ARCHIVE_CATEGORY_ID
TICKET_COOLDOWN_SEC   = settings.TICKET_COOLDOWN_SECONDS

NSFW_ROLE_NAME        = settings.NSFW_ROLE_NAME
MAX_ATTACH            = 4  # self-flowban ennyi referencia kép engedett
LEGACY_HINT_BLOCK     = "Please list product, quantity, style, deadline, budget and references."

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
        # region ISERO PATCH agent-sessions
        self.mebinu_agent_openers: dict[int, int] = {}
        # endregion
        # persistent views
        self.bot.add_view(OpenTicketView(self))
        self.bot.add_view(CloseTicketView(self))
        # region ISERO PATCH ticket-kb-init
        kb_dir = os.getenv("TICKET_KB_DIR", "config/tickets")
        try:
            self.kb = load_ticket_kb(kb_dir)
        except Exception:
            self.kb = {}
        self.default_sla_days = int(os.getenv("TICKET_DEFAULT_SLA_DAYS", "3") or "3")
        # endregion ISERO PATCH ticket-kb-init
        # region ISERO PATCH ticket-perms/init
        self.log = logging.getLogger("ISERO.Tickets")
        try:
            self.staff_role_id = int(os.getenv("STAFF_ROLE_ID", "0") or "0")
        except Exception:
            self.staff_role_id = 0
        extras = [x.strip() for x in (os.getenv("STAFF_EXTRA_ROLE_IDS", "") or "").split(",") if x.strip()]
        self.staff_extra_role_ids = []
        for x in extras:
            try:
                self.staff_extra_role_ids.append(int(x))
            except Exception:
                pass
        # endregion

        # region ISERO PATCH order-log/init
        try:
            self.mod_queue_id = int(os.getenv("CHANNEL_MOD_QUEUE", "0") or "0")
        except Exception:
            self.mod_queue_id = 0
        try:
            self.mod_logs_id = int(os.getenv("CHANNEL_MOD_LOGS", "0") or "0")
        except Exception:
            self.mod_logs_id = 0
        # endregion

        # region ISERO PATCH legacy-flags
        def _envb(name: str, default: str = "false") -> bool:
            return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")
        self._suppress_always = _envb("MEBINU_SUPPRESS_LEGACY_ALWAYS", "true")
        self._legacy_visible = _envb("MEBINU_LEGACY_HINT_VISIBLE", "false")
        self._legacy_enabled = (self._legacy_visible and not self._suppress_always)
        self._legacy_keys = (
            "Melyik termék vagy téma?", "Mennyiség, ritkaság, színvilág?", "Határidő", "Keret (HUF/EUR)?",
            "Van 1-4 referencia kép?", "max 800", "Which product/variant", "quantity", "deadline", "budget", "reference image",
        )
        # endregion

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

    # region ISERO PATCH post-welcome
    async def post_welcome_and_sla(self, channel: discord.TextChannel, kind: str, opener: discord.Member):
        """Küld egy üdvözlő embedet és jelzi a ~3 napos (env) céldátumot."""
        await self.ensure_ticket_perms(channel, opener)
        try:
            now = dt.datetime.utcnow()
            due = now + dt.timedelta(days=self.default_sla_days)
            due_str = due.strftime("%Y-%m-%d %H:%M UTC")
            e = discord.Embed(
                title=f"Welcome — {kind.capitalize()}",
                description=(
                    f"Szia {opener.mention}! Ez egy privát ticket csatorna.\n\n"
                    f"**Céldátum (≈ puha határidő):** {due_str}\n"
                    f"Írj rövid leírást, vagy kattints a gombra, hogy **ISERO** vezesse a beszélgetést."
                ),
                color=discord.Color.green(),
            )
            e.set_footer(text=f"SLA ≈ {self.default_sla_days} nap • ISERO")
            view = None
            try:
                await channel.send(embed=e, view=view)
            except Exception:
                await channel.send(embed=e)
            self.log.info("Welcome embed posted: ch=%s kind=%s opener=%s", channel.id, kind, opener.id)
        except Exception as e:
            self.log.warning("post_welcome_and_sla failed: ch=%s err=%r", getattr(channel,'id',None), e)
    # endregion ISERO PATCH post-welcome

    # region ISERO PATCH order-log/helpers
    def _make_order_id(self, seed: int) -> str:
        return f"ORD-{seed}-{int(time.time())}"

    def build_order_embed(self, *, kind: str, opener: discord.Member, items_text: str, total_usd: float, due_utc: dt.datetime) -> discord.Embed:
        order_id = self._make_order_id(opener.guild.id if opener and opener.guild else 0)
        due_str = due_utc.strftime("%Y-%m-%d %H:%M UTC")
        e = discord.Embed(
            title=f"Megrendelés — {kind.capitalize()}",
            description=f"Rendelő: {opener.mention}\nAzonosító: `{order_id}`",
            color=discord.Color.blue(),
        )
        e.add_field(name="Tételek", value=items_text[:1024] or "—", inline=False)
        e.add_field(name="Végösszeg (USD)", value=f"${total_usd:.2f}", inline=True)
        e.add_field(name="Céldátum (≈ puha határidő)", value=due_str, inline=True)
        e.set_footer(text="ISERO • OrderLog")
        return e

    async def post_order_log(self, *, channel: discord.TextChannel, embed: discord.Embed):
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
        target = None
        if self.mod_queue_id:
            target = channel.guild.get_channel(self.mod_queue_id)
        if not target and self.mod_logs_id:
            target = channel.guild.get_channel(self.mod_logs_id)
        if target:
            try:
                await target.send(embed=embed)
                self.log.info("Order posted to mod channel: ch=%s target=%s", channel.id, target.id)
            except Exception as e:
                self.log.warning("Order post failed: ch=%s target=%s err=%r", channel.id, getattr(target,'id',None), e)
    # endregion

    # region ISERO PATCH ticket-perms/helpers
    def _ticket_overwrites(self, guild: discord.Guild, opener: discord.Member):
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
            opener: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True),
        }
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True, embed_links=True, attach_files=True)
        if self.staff_role_id:
            r = guild.get_role(self.staff_role_id)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        for rid in getattr(self, "staff_extra_role_ids", []):
            r = guild.get_role(rid)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        return overwrites

    async def ensure_ticket_perms(self, channel: discord.TextChannel, opener: discord.Member):
        """Garantálja, hogy az opener lát és ír a ticketben (channel unavailable fix)."""
        try:
            ow = channel.overwrites_for(opener)
            need = (not ow.view_channel) or (not ow.send_messages)
            if need:
                await channel.set_permissions(opener, view_channel=True, send_messages=True, attach_files=True, embed_links=True)
                self.log.info("Ticket perms fixed for opener id=%s in channel id=%s", opener.id, channel.id)
        except Exception as e:
            self.log.warning("ensure_ticket_perms failed: ch=%s opener=%s err=%r", getattr(channel,'id',None), getattr(opener,'id',None), e)
    # endregion

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
        overwrites = self._ticket_overwrites(guild, user)

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
        # region ISERO PATCH MEBINU_hide_legacy_when_dialog_on
        from utils import policy as _policy
        if not (_policy.getbool("FEATURES_MEBINU_DIALOG_V1", default=False) or _policy.feature_on("mebinu_dialog_v1")):
            await ch.send(LEGACY_HINT_BLOCK)
        # endregion ISERO PATCH MEBINU_hide_legacy_when_dialog_on
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
        if not message.guild:
            return

        ch = message.channel

        # region ISERO PATCH legacy-sweeper (bot messages)
        if message.author.bot:
            try:
                if isinstance(ch, discord.TextChannel) and hasattr(ch, "topic") and "type=mebinu" in (ch.topic or ""):
                    gate = self.bot.get_cog("AgentGate")
                    if (not self._legacy_enabled) or (gate and getattr(gate, "is_active", lambda _ch: False)(ch.id)):
                        txt = (message.content or "")
                        if any(k in txt for k in self._legacy_keys):
                            try:
                                await message.delete()
                                self.log.info("Legacy prompt auto-removed msg_id=%s in #%s", message.id, ch.id)
                            except Exception:
                                pass
            except Exception:
                pass
            return
        # endregion

        # region ISERO PATCH kill-legacy-hints
        if isinstance(ch, discord.TextChannel) and hasattr(ch, "topic") and "type=mebinu" in (ch.topic or ""):
            gate = self.bot.get_cog("AgentGate")
            if (not self._legacy_enabled) or (gate and getattr(gate, "is_active", lambda _ch: False)(ch.id)):
                try:
                    async for m in ch.history(limit=6):
                        if not m.author.bot:
                            continue
                        txt = (m.content or "")
                        if any(k in txt for k in self._legacy_keys):
                            try:
                                await m.delete()
                            except Exception:
                                pass
                except Exception:
                    pass
                return
        # endregion

        # 1) SELF-FLOW képfogás
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

        # region ISERO PATCH mebinu-agent-signal
        opener_id = self.mebinu_agent_openers.get(ch.id)
        if opener_id and message.author.id == opener_id and message.content:
            qty, budget, style = extract_signals(message.content)
            if qty is not None or budget is not None or style is not None:
                if os.getenv("PLAYER_CARD_ENABLED", "false").lower() == "true":
                    ag = self.bot.get_cog("AgentGate")
                    pcog = getattr(ag, "db", None)
                    if pcog and hasattr(pcog, "set_fields"):
                        updates = {}
                        if qty is not None:
                            updates["last_qty"] = qty
                        if budget is not None:
                            updates["last_budget"] = budget
                        if style is not None:
                            updates["last_style"] = style
                        try:
                            await pcog.set_fields(message.author.id, **updates)
                        except Exception:
                            pass
        # endregion

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

    # region ISERO PATCH ticket-deadline-cmd
    @commands.hybrid_command(name="deadline", description="Mutatja a ticket puha határidejét.")
    async def deadline(self, ctx: commands.Context):
        days = self.default_sla_days
        due = dt.datetime.utcnow() + dt.timedelta(days=days)
        await ctx.reply(f"Puha határidő: <t:{int(due.timestamp())}:R> (≈ {days} nap)")
    # endregion ISERO PATCH ticket-deadline-cmd

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
