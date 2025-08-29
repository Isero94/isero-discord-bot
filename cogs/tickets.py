import os
import time
from typing import Dict, List, Optional

import discord
from discord.ext import commands, tasks
from discord import ui, ButtonStyle, app_commands
from openai import OpenAI

# --- Konfig + ENV fallback ---
from config import (
    OPENAI_API_KEY as CFG_OPENAI_API_KEY,
    OPENAI_MODEL as CFG_OPENAI_MODEL,
    STAFF_CHANNEL_ID as CFG_STAFF_CHANNEL_ID,
    TICKET_HUB_CHANNEL_ID as CFG_TICKET_HUB_CHANNEL_ID,
    TICKET_MSG_CHAR_LIMIT as CFG_CHARLIM,
    TICKET_IDLE_SECONDS as CFG_IDLE,
)

def as_int(x, default):
    try: return int(x)
    except: return default

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", CFG_OPENAI_API_KEY)
OPENAI_MODEL   = os.getenv("OPENAI_MODEL",   CFG_OPENAI_MODEL or "gpt-4o-mini")
STAFF_CHANNEL_ID = as_int(os.getenv("STAFF_CHANNEL_ID", str(CFG_STAFF_CHANNEL_ID or 0)), 0)
TICKET_HUB_CHANNEL_ID = as_int(os.getenv("TICKET_HUB_CHANNEL_ID", str(CFG_TICKET_HUB_CHANNEL_ID or 0)), 0)
TICKET_MSG_CHAR_LIMIT = as_int(os.getenv("TICKET_MSG_CHAR_LIMIT", str(CFG_CHARLIM or 300)), 300)
TICKET_IDLE_SECONDS   = as_int(os.getenv("TICKET_IDLE_SECONDS", str(CFG_IDLE or 600)), 600)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

CATEGORIES = [
    ("General help", "general"),
    ("Commission", "commission"),
    ("NSFW commission", "nsfw_commission"),
    ("Mebinu", "mebinu"),
    ("Other", "other"),
]

OPEN_COOLDOWN_SECONDS = 30  # user spam védelem

def short(txt: str, n: int = 300):
    return txt if len(txt) <= n else txt[: n-3] + "…"

class TicketState:
    def __init__(self, thread: discord.Thread, user: discord.Member, category_key: str):
        self.thread = thread
        self.user = user
        self.category_key = category_key
        self.created = time.time()
        self.last_activity = time.time()
        self.closed = False
        self.attach_urls: List[str] = []  # max 4
        self.cooldown_until = 0.0

states: Dict[int, TicketState] = {}          # thread_id -> state
user_open: Dict[int, Dict[str, int]] = {}    # user_id -> {category_key: thread_id}
user_last_open: Dict[int, float] = {}        # user_id -> last open ts

# ---------------- Views / UI ----------------

class TicketHubView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for label, key in CATEGORIES:
            self.add_item(ui.Button(label=f"Open a ticket: {label}", style=ButtonStyle.primary, custom_id=f"ticket_open:{key}"))

class TicketThreadView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Button(label="Isero írja meg (űrlap)", style=ButtonStyle.success, custom_id="ticket:fill_form"))
        self.add_item(ui.Button(label="Feltöltök referenciát", style=ButtonStyle.secondary, custom_id="ticket:add_refs"))
        self.add_item(ui.Button(label="Összefoglalás", style=ButtonStyle.secondary, custom_id="ticket:summary"))
        self.add_item(ui.Button(label="Bezárás", style=ButtonStyle.danger, custom_id="ticket:close"))

# -------------- Modals ----------------

class OrderFormModal(ui.Modal, title="Megrendelés űrlap"):
    want = ui.TextInput(label="Mit szeretnél? (≤300)", style=discord.TextStyle.paragraph, max_length=300, required=True)
    deadline = ui.TextInput(label="Határidő (pl. 2025-09-15 vagy 'rugalmas')", max_length=60, required=False)
    extras = ui.TextInput(label="Extra megjegyzés (opcionális)", style=discord.TextStyle.paragraph, max_length=300, required=False)

    def __init__(self, cog: "TicketsCog", st: TicketState):
        super().__init__()
        self.cog = cog
        self.st = st

    async def on_submit(self, interaction: discord.Interaction):
        if self.st.closed:
            await interaction.response.send_message("Ez a ticket már zárva van.", ephemeral=True); return
        self.st.last_activity = time.time()
        lines = [
            f"**Űrlap – összefoglalás:**",
            f"- Kérés: {self.want.value}",
            f"- Határidő: {self.deadline.value or '—'}",
            f"- Megjegyzés: {self.extras.value or '—'}",
            "",
            "Ha szeretnél, tölts fel **max 4** referencia képet (csatolmányként).",
        ]
        await interaction.response.send_message("\n".join(lines))
        try:
            await self.st.thread.send(view=TicketThreadView())
        except: pass

# -------------- COG ----------------

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # persistent view a hub gombokhoz
        self.bot.add_view(TicketHubView())
        self.idle_checker.start()

    def cog_unload(self):
        self.idle_checker.cancel()

    async def call_openai(self, prompt: str, system: str) -> str:
        if not client:
            return "(AI off)"
        try:
            rsp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
                temperature=0.7,
                max_tokens=600,
            )
            return (rsp.choices[0].message.content or "").strip()
        except Exception as e:
            return f"(AI error: {e})"

    # ---------- /posthub ----------
    @app_commands.command(name="posthub", description="Ticket gombok kirakása a hub csatornában")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def posthub(self, interaction: discord.Interaction):
        if not TICKET_HUB_CHANNEL_ID:
            await interaction.response.send_message("TICKET_HUB_CHANNEL_ID nincs beállítva.", ephemeral=True); return
        if interaction.channel_id != TICKET_HUB_CHANNEL_ID:
            await interaction.response.send_message("Használd a kijelölt hub csatornában.", ephemeral=True); return

        await interaction.response.defer(ephemeral=True)

        # régi hub üzenetek takarítása (bot-tól, komponensekkel)
        try:
            chan = interaction.channel  # type: ignore
            assert isinstance(chan, (discord.TextChannel, discord.Thread))
            cnt = 0
            async for msg in chan.history(limit=50):
                if msg.author == self.bot.user and msg.components:
                    try:
                        await msg.delete()
                        cnt += 1
                    except: pass
        except Exception as e:
            print(f"[HUB] cleanup error: {e}")

        await interaction.followup.send("Válassz kategóriát:", view=TicketHubView())
        await interaction.followup.send("Kész. Régi hub üzenetek törölve, új gombok kirakva.", ephemeral=True)

    # ---------- Gombhandler: hub ----------
    @commands.Cog.listener()
    async def on_interaction(self, it: discord.Interaction):
        if not it.type == discord.InteractionType.component:
            return
        cid = getattr(it.data, "custom_id", None) if hasattr(it, "data") else None  # type: ignore
        if not cid:
            return

        # Hub -> ticket open
        if str(cid).startswith("ticket_open:"):
            category_key = str(cid).split(":",1)[1]
            await self._handle_open_ticket(it, category_key); return

        # Ticket thread actions
        if str(cid) == "ticket:fill_form":
            await self._handle_modal(it); return
        if str(cid) == "ticket:add_refs":
            await self._handle_add_refs(it); return
        if str(cid) == "ticket:summary":
            await self._handle_summary(it); return
        if str(cid) == "ticket:close":
            await self._handle_close(it); return

    async def _handle_open_ticket(self, it: discord.Interaction, category_key: str):
        # csak hub csatorna
        if it.channel_id != TICKET_HUB_CHANNEL_ID:
            await it.response.send_message("A hub csatornában használd.", ephemeral=True); return
        if not isinstance(it.user, discord.Member):
            await it.response.send_message("Csak szerveren használható.", ephemeral=True); return

        # user spam/cooldown + 1 nyitott ticket ugyanabból a kategóriából
        now = time.time()
        last = user_last_open.get(it.user.id, 0.0)
        if now - last < OPEN_COOLDOWN_SECONDS:
            await it.response.send_message("Kis türelmet! Pár másodpercenként nyiss új ticketet.", ephemeral=True); return
        user_last_open[it.user.id] = now

        existing = user_open.get(it.user.id, {})
        if category_key in existing:
            # ha a meglévő thread még él
            tid = existing[category_key]
            ch = it.guild.get_channel(tid) if it.guild else None  # type: ignore
            if isinstance(ch, discord.Thread) and not ch.archived:
                await it.response.send_message(f"Már van nyitott ticketed ebben a kategóriában: {ch.mention}", ephemeral=True)
                return
            else:
                # eltávolítjuk a régi hivatkozást
                existing.pop(category_key, None)

        # thread készítés
        name = f"ticket-{it.user.name}-{category_key}"
        parent = it.channel
        assert isinstance(parent, discord.TextChannel)
        th = await parent.create_thread(
            name=name[:90],
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        await th.add_user(it.user)

        # állapot
        st = TicketState(th, it.user, category_key)
        states[th.id] = st
        user_open.setdefault(it.user.id, {})[category_key] = th.id

        # első üzenet + view
        cat_label = next((lbl for lbl,key in CATEGORIES if key == category_key), category_key)
        intro = [
            f"🧾 **Ticket nyitva:** {it.user.mention} — *{cat_label}*",
            f"Írj röviden (≤ **{TICKET_MSG_CHAR_LIMIT}** karakter), és/vagy használd a gombokat:",
            "• **Isero írja meg (űrlap)** – több mezős Modal",
            "• **Feltöltök referenciát** – tölts fel max **4** képet csatolmányként",
            "• **Összefoglalás** – gyors összegzés a staffnak",
            "• **Bezárás** – lezárja a ticketet",
        ]
        await th.send("\n".join(intro), view=TicketThreadView())
        await it.response.send_message(f"Nyitottam egy ticketet: {th.mention}", ephemeral=True)

    async def _handle_modal(self, it: discord.Interaction):
        th = it.channel
        st = states.get(th.id) if isinstance(th, discord.Thread) else None  # type: ignore
        if not st:
            await it.response.send_message("Nem találtam a ticket állapotát.", ephemeral=True); return
        await it.response.send_modal(OrderFormModal(self, st))

    async def _handle_add_refs(self, it: discord.Interaction):
        await it.response.send_message("Küldd el a képeket **csatolmányként** ebbe a ticketbe (max 4).", ephemeral=True)

    async def _handle_summary(self, it: discord.Interaction):
        th = it.channel
        st = states.get(th.id) if isinstance(th, discord.Thread) else None  # type: ignore
        if not st:
            await it.response.send_message("Nem találtam a ticket állapotát.", ephemeral=True); return
        await self.finish_with_summary(st, to_thread=True)
        await it.response.send_message("Összefoglaló elkészült.", ephemeral=True)

    async def _handle_close(self, it: discord.Interaction):
        th = it.channel
        st = states.get(th.id) if isinstance(th, discord.Thread) else None  # type: ignore
        if not st:
            await it.response.send_message("Nem találtam a ticket állapotát.", ephemeral=True); return
        await self.finish_with_summary(st, to_thread=True)
        await self._archive_thread(st.thread)
        await it.response.send_message("Ticket lezárva.", ephemeral=True)

    # ---------- Üzenet figyelés (ticket thread flow) ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return

        st = states.get(message.channel.id)
        if not st or st.closed:
            return
        if message.author.id != st.user.id:
            return

        st.last_activity = time.time()

        # természetes nyelvű lezárás
        low = (message.content or "").lower()
        if any(k in low for k in ["zárd le", "lezárás", "close ticket", "ticket close"]):
            await self.finish_with_summary(st, to_thread=True)
            await self._archive_thread(st.thread)
            return

        # char limit
        if len(message.content) > TICKET_MSG_CHAR_LIMIT:
            await message.reply(f"Kérlek maradj {TICKET_MSG_CHAR_LIMIT} karakternél."); return

        # referenciák gyűjtése
        if message.attachments:
            for at in message.attachments:
                if len(st.attach_urls) >= 4:
                    break
                if at.content_type and at.content_type.startswith("image/"):
                    st.attach_urls.append(at.url)
            await message.channel.send(f"📎 Referenciák: {len(st.attach_urls)}/4 mentve.")

    # ---------- Összefoglaló + lezárás ----------
    async def finish_with_summary(self, st: TicketState, to_thread: bool = True):
        # user + bot üzenetek összegyűjtése
        items: List[str] = []
        async for m in st.thread.history(limit=60, oldest_first=True):
            author = "User" if m.author.id == st.user.id else "Bot"
            txt = m.content or ""
            if txt:
                items.append(f"{author}: {txt}")
        if st.attach_urls:
            items.append("Refs: " + ", ".join(st.attach_urls))

        up = "\n".join(items[-30:])
        sp = ("You are Isero. Create a concise ticket summary for staff (<=600 chars). "
              "Include concrete asks, deadlines, and list up to 4 reference URLs if any.")
        summ = await self.call_openai(up, sp) if up else "No content."
        target = st.thread if to_thread else st.thread.parent
        try:
            await target.send("✅ **Summary for staff:**\n" + summ)  # type: ignore
        except: pass
        st.closed = True

    async def _archive_thread(self, thread: discord.Thread):
        try:
            await thread.edit(archived=True, locked=True)
        except: pass

    # --- idle zárás ---
    @tasks.loop(seconds=30)
    async def idle_checker(self):
        now = time.time()
        for st in list(states.values()):
            if st.closed: continue
            if now - st.last_activity > TICKET_IDLE_SECONDS:
                try:
                    await st.thread.send(
                        "⏳ 10 perc válasz nélkül.\n"
                        f"- Írj röviden (≤ {TICKET_MSG_CHAR_LIMIT} char)\n"
                        "- Határidő\n"
                        "- Max 4 referencia kép\n"
                        "Ha kész, használd az **Összefoglalás** / **Bezárás** gombot."
                    )
                except: pass
                st.closed = True

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
