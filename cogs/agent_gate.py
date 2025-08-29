# cogs/agent_gate.py
import os, time, re, asyncio
from typing import Dict, List, Optional

import discord
from discord.ext import commands, tasks
from discord import ui, ButtonStyle, TextStyle

# --- Konfig + ENV fallback ---
from config import (
    OPENAI_API_KEY as CFG_OPENAI_API_KEY,
    OPENAI_MODEL as CFG_OPENAI_MODEL,
    STAFF_CHANNEL_ID as CFG_STAFF_CHANNEL_ID,
    TICKET_HUB_CHANNEL_ID as CFG_TICKET_HUB_CHANNEL_ID,
    TICKET_USER_MAX_MSG as CFG_TU_MAX,
    TICKET_MSG_CHAR_LIMIT as CFG_CHARLIM,
    TICKET_IDLE_SECONDS as CFG_IDLE,
    WAKE_WORDS as CFG_WWS,
    ALLOW_STAFF_FREESPEECH as CFG_ALLOW,
)

# ----------------------------

def as_bool(x):
    return str(x).strip().lower() in ("1","true","yes","y","on")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", CFG_OPENAI_API_KEY)
OPENAI_MODEL   = os.getenv("OPENAI_MODEL",   CFG_OPENAI_MODEL or "gpt-4o-mini")
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", str(CFG_STAFF_CHANNEL_ID or 0)) or 0)
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", str(CFG_TICKET_HUB_CHANNEL_ID or 0)) or 0)
TICKET_USER_MAX_MSG = int(os.getenv("TICKET_USER_MAX_MSG", str(CFG_TU_MAX or 5)))
TICKET_MSG_CHAR_LIMIT = int(os.getenv("TICKET_MSG_CHAR_LIMIT", str(CFG_CHARLIM or 800)))
TICKET_IDLE_SECONDS = int(os.getenv("TICKET_IDLE_SECONDS", str(CFG_IDLE or 600)))
ALLOW_STAFF_FREESPEECH = as_bool(os.getenv("ALLOW_STAFF_FREESPEECH", CFG_ALLOW))
WAKE_WORDS = [w.strip() for w in os.getenv("WAKE_WORDS", ",".join(CFG_WWS or ["isero"])).split(",") if w.strip()]

# Wizard beállítások
DESC_LIMIT = min(300, TICKET_MSG_CHAR_LIMIT)  # első leírás 300 max
REF_MAX = 4

print(f"[DEBUG] OPENAI_API_KEY present? {bool(OPENAI_API_KEY)}")
print(f"[DEBUG] OPENAI_MODEL = {OPENAI_MODEL}")
print(f"[DEBUG] STAFF_CHANNEL_ID = {STAFF_CHANNEL_ID}")
print(f"[DEBUG] ALLOW_STAFF_FREESPEECH = {ALLOW_STAFF_FREESPEECH}")
print(f"[DEBUG] WAKE_WORDS = {WAKE_WORDS}")

# ----------------------------
# Állapotok
# ----------------------------

CATEGORIES = [
    ("General help", "general"),
    ("Commission", "commission"),
    ("Mebinu", "mebinu"),
    ("NSFW commission", "nsfw"),
    ("Other", "other"),
]

CLOSE_KEYWORDS = [
    "zárd le", "zarjuk le", "lezárás", "lezár", "lezar", "close ticket", "close", "archive",
]

class TicketState:
    def __init__(self, thread: discord.Thread, user: discord.Member, cat_key: str):
        self.thread = thread
        self.user = user
        self.cat_key = cat_key
        self.last_activity = time.time()
        self.closed = False

        # wizard
        self.desc: Optional[str] = None
        self.wants_ai: Optional[bool] = None
        self.refs: List[str] = []
        self.collecting_refs: bool = False

    def touch(self):
        self.last_activity = time.time()

states: Dict[int, TicketState] = {}          # thread_id -> state
open_by_user: Dict[int, int] = {}            # user_id -> thread_id (1 aktív ticket / user)

# ----------------------------
# Helpers
# ----------------------------

def short(txt: str, n: int = 300):
    return txt if len(txt) <= n else txt[: n-3] + "…"

async def archive_and_lock(thread: discord.Thread):
    try:
        await thread.edit(archived=True, locked=True)
    except Exception:
        pass

# ----------------------------
# Views & Modals
# ----------------------------

class TicketInitModal(ui.Modal, title="Új ticket – rövid leírás"):
    def __init__(self, cat_key: str):
        super().__init__(timeout=180)
        self.cat_key = cat_key
        self.desc = ui.TextInput(
            label=f"Mit szeretnél? (≤ {DESC_LIMIT} karakter)",
            style=TextStyle.long,
            required=True,
            max_length=DESC_LIMIT,
            placeholder="Írd le röviden a kérést…",
        )
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=False)
        bot: commands.Bot = interaction.client  # type: ignore

        # hub csatorna szükséges
        hub = bot.get_channel(TICKET_HUB_CHANNEL_ID)
        if not isinstance(hub, (discord.TextChannel,)):
            return await interaction.followup.send("Hiba: nincs beállítva a ticket-hub csatorna.", ephemeral=True)

        # egy aktív ticket / user
        if interaction.user.id in open_by_user:
            th_id = open_by_user[interaction.user.id]
            th = bot.get_channel(th_id)
            if isinstance(th, discord.Thread):
                return await interaction.followup.send(f"Már van nyitott ticketed: {th.mention}", ephemeral=True)
            else:
                # rendrakás
                open_by_user.pop(interaction.user.id, None)

        name = f"ticket-{interaction.user.display_name}-{self.cat_key.capitalize()}"
        thread = await hub.create_thread(
            name=short(name, 90),
            type=discord.ChannelType.private_thread,
            invitable=True,
        )
        await thread.add_user(interaction.user)

        st = TicketState(thread, interaction.user, self.cat_key)
        st.desc = str(self.desc.value).strip()
        states[thread.id] = st
        open_by_user[interaction.user.id] = thread.id

        await thread.send(
            f"📩 **Ticket nyitva:** <@{interaction.user.id}> — *{self.cat_key}*\n"
            f"**Leírás (≤{DESC_LIMIT}):** {st.desc}\n\n"
            f"Szeretnéd, hogy **ISERO megírja helyetted** a megrendelést?\n",
            view=YesNoWriteView()
        )
        await interaction.followup.send(f"Kész! Nyitottam egy ticketet: {thread.mention}", ephemeral=True)

class TicketStartView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # egy sorba tesszük a gombokat
        for label, key in CATEGORIES:
            self.add_item(TicketButton(label=label, key=key))

class TicketButton(ui.Button):
    def __init__(self, label: str, key: str):
        super().__init__(label=label, style=ButtonStyle.primary, custom_id=f"ticket_open_{key}")
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        # csak guildben
        if not interaction.guild:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)

        # Modal a leíráshoz
        await interaction.response.send_modal(TicketInitModal(self.key))

class YesNoWriteView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(ui.Button(label="Igen, írd meg te", style=ButtonStyle.success, custom_id="wiz_write_yes"))
        self.add_item(ui.Button(label="Nem, majd én írom", style=ButtonStyle.secondary, custom_id="wiz_write_no"))

    async def interaction_check(self, interaction: discord.Interaction):
        # csak ticket tulaj válaszolhat
        st = states.get(interaction.channel.id if interaction.channel else 0)
        return bool(st and interaction.user.id == st.user.id)

    @ui.button(label="dummy", style=ButtonStyle.secondary, disabled=True)  # placeholder, nem látszik
    async def _dummy(self, *_): pass

class RefCollectView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ui.Button(label="Kész – folytatás", style=ButtonStyle.success, custom_id="wiz_refs_done"))
        self.add_item(ui.Button(label="Kihagyom", style=ButtonStyle.secondary, custom_id="wiz_refs_skip"))

    async def interaction_check(self, interaction: discord.Interaction):
        st = states.get(interaction.channel.id if interaction.channel else 0)
        return bool(st and interaction.user.id == st.user.id)

class ConfirmFinishView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ui.Button(label="Minden oké ✅", style=ButtonStyle.success, custom_id="wiz_confirm_ok"))
        self.add_item(ui.Button(label="Még szerkesztenék", style=ButtonStyle.secondary, custom_id="wiz_confirm_edit"))
        self.add_item(ui.Button(label="Ticket lezárása", style=ButtonStyle.danger, custom_id="wiz_close_now"))

    async def interaction_check(self, interaction: discord.Interaction):
        st = states.get(interaction.channel.id if interaction.channel else 0)
        # staff is kezelheti
        if st and (interaction.user.id == st.user.id or interaction.user.guild_permissions.manage_channels):
            return True
        return False

# ----------------------------
# Cog
# ----------------------------

class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.idle_checker.start()

    def cog_unload(self):
        self.idle_checker.cancel()

    # ------- setup_hook-ból hívódik: persistent view
    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.bot.add_view(TicketStartView())
        except Exception:
            pass

    # ------- interakciók (buttons)
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.type == discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id") if isinstance(interaction.data, dict) else None
        if not cid:
            return

        # Write yes/no
        if cid in ("wiz_write_yes", "wiz_write_no"):
            st = states.get(interaction.channel.id if interaction.channel else 0)
            if not st or st.closed:
                return await interaction.response.send_message("Ticket állapot nem található.", ephemeral=True)
            st.wants_ai = (cid == "wiz_write_yes")
            await interaction.response.send_message(
                "Oké! Most **referenciaképeket** adhatsz (max 4, képet csatolj üzenetként). "
                "Ha kész vagy, nyomd meg a zöld gombot.",
                ephemeral=True
            )
            st.collecting_refs = True
            await st.thread.send("📎 **Referenciák**: küldj képeket (max 4).", view=RefCollectView())
            st.touch()
            return

        # Refs done / skip
        if cid in ("wiz_refs_done", "wiz_refs_skip"):
            st = states.get(interaction.channel.id if interaction.channel else 0)
            if not st or st.closed:
                return await interaction.response.send_message("Ticket állapot nem található.", ephemeral=True)
            st.collecting_refs = False
            await interaction.response.defer(ephemeral=True, thinking=False)
            await self._post_summary(st)
            return

        # Confirm
        if cid == "wiz_confirm_ok":
            st = states.get(interaction.channel.id if interaction.channel else 0)
            if not st or st.closed:
                return await interaction.response.send_message("Ticket állapot nem található.", ephemeral=True)
            await interaction.response.send_message("Rögzítve. A staff hamarosan ránéz. ✅", ephemeral=True)
            st.touch()
            return

        if cid == "wiz_confirm_edit":
            st = states.get(interaction.channel.id if interaction.channel else 0)
            if not st or st.closed:
                return await interaction.response.send_message("Ticket állapot nem található.", ephemeral=True)
            await interaction.response.send_message(
                "Írd le pontosan, mit módosítanál vagy egészítenél ki (≤ 300 karakter).", ephemeral=True
            )
            st.touch()
            return

        if cid == "wiz_close_now":
            st = states.get(interaction.channel.id if interaction.channel else 0)
            if not st:
                return await interaction.response.send_message("Ticket állapot nem található.", ephemeral=True)
            await interaction.response.defer(ephemeral=True, thinking=False)
            await self._close_ticket(st, reason="Felhasználói kérésre lezárva.")
            return

    # ------- üzenet figyelés
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # természetes nyelvű lezárás
        if isinstance(message.channel, discord.Thread):
            st = states.get(message.channel.id)
            if st and not st.closed:
                st.touch()

                # ha referenciát gyűjtünk és a user képet küld
                if st.collecting_refs and message.author.id == st.user.id:
                    if message.attachments:
                        for a in message.attachments:
                            if a.content_type and a.content_type.startswith("image/"):
                                if len(st.refs) < REF_MAX:
                                    st.refs.append(a.url)
                        await message.channel.send(f"✅ Referencia számláló: {len(st.refs)}/{REF_MAX}")
                    return

                low = message.content.lower()
                if any(k in low for k in CLOSE_KEYWORDS) and (message.author.id == st.user.id or message.author.guild_permissions.manage_channels):
                    await self._close_ticket(st, reason="Felhasználói kérésre lezárva.")
                    return

        # staff free speech CSAK staff csatornában
        if (
            ALLOW_STAFF_FREESPEECH and message.guild
            and STAFF_CHANNEL_ID and message.channel.id == STAFF_CHANNEL_ID
        ):
            # Egyszerű echo helyett ne okoskodjon a posthubbal itt
            # A konkrét AI hívás nálad volt; most a wizard megoldja a ticketet,
            # így itt nem felelünk parancsokra.
            return

    # ------- összegzés
    async def _post_summary(self, st: TicketState):
        want = "Igen" if st.wants_ai else "Nem"
        refs_txt = "\n".join(f"- {u}" for u in st.refs) if st.refs else "nincs megadva"

        embed = discord.Embed(
            title="Ticket összefoglaló",
            description=(
                f"**Kategória:** {st.cat_key}\n"
                f"**Leírás:** {st.desc}\n"
                f"**Megírja az ISERO?** {want}\n"
                f"**Referenciák (max 4):**\n{refs_txt}"
            ),
            color=discord.Color.blurple()
        )
        await st.thread.send(embed=embed, view=ConfirmFinishView())

    # ------- ticket zárás
    async def _close_ticket(self, st: TicketState, reason: str = ""):
        st.closed = True
        await st.thread.send(f"🔒 Ticket lezárva. {reason}")
        await archive_and_lock(st.thread)
        # takarítás
        states.pop(st.thread.id, None)
        open_by_user.pop(st.user.id, None)

    # ------- idle auto-nudge (nem auto-close, csak értesítés + zár)
    @tasks.loop(seconds=30)
    async def idle_checker(self):
        now = time.time()
        for st in list(states.values()):
            if st.closed:
                continue
            if now - st.last_activity > TICKET_IDLE_SECONDS:
                try:
                    await st.thread.send(
                        "⏳ 10 perc válasz nélkül.\n"
                        "- Rövid leírás (≤ 300)\n"
                        "- Határidő\n"
                        "- Max 4 referencia link / kép\n"
                        "Ha kész, írd: **zárd le**."
                    )
                except Exception:
                    pass
                st.closed = True
                try:
                    await archive_and_lock(st.thread)
                except Exception:
                    pass
                states.pop(st.thread.id, None)
                open_by_user.pop(st.user.id, None)

    # ------- /posthub (régi duplikátumok törlése)
    @commands.hybrid_command(name="posthub", description="Ticket gombok kirakása a hubba (csak staff).")
    @commands.has_permissions(manage_channels=True)
    async def posthub(self, ctx: commands.Context):
        if ctx.channel.id != TICKET_HUB_CHANNEL_ID:
            return await ctx.reply("A hub csatornában használd ezt a parancsot.", mention_author=False)

        # töröljük a régi bot-üzeneteket ebből a csatornából (utolsó 100)
        try:
            async for m in ctx.channel.history(limit=100):
                if m.author == ctx.me and m.components:
                    await m.delete()
        except Exception:
            pass

        await ctx.send("Válassz kategóriát:", view=TicketStartView())

    # ------- /close (és !close)
    @commands.hybrid_command(name="close", description="Ticket lezárása (threadben).")
    async def close_cmd(self, ctx: commands.Context):
        if not isinstance(ctx.channel, discord.Thread):
            return await ctx.reply("Ezt a parancsot a ticket threadben használd.", mention_author=False)
        st = states.get(ctx.channel.id)
        if not st:
            return await ctx.reply("Nem találom a ticket állapotot (már lehet zárva).", mention_author=False)
        if ctx.author.id != st.user.id and not ctx.author.guild_permissions.manage_channels:
            return await ctx.reply("Nincs jogod lezárni ezt a ticketet.", mention_author=False)
        await self._close_ticket(st, reason="Parancsra lezárva.")
        await ctx.reply("Lezárva.", mention_author=False)

async def setup(bot):
    await bot.add_cog(AgentGate(bot))
import os, time
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
    TICKET_USER_MAX_MSG as CFG_TU_MAX,
    TICKET_MSG_CHAR_LIMIT as CFG_CHARLIM,
    TICKET_IDLE_SECONDS as CFG_IDLE,
    WAKE_WORDS as CFG_WWS,
    ALLOW_STAFF_FREESPEECH as CFG_ALLOW,
)

def as_bool(x):
    return str(x).strip().lower() in ("1", "true", "yes", "y", "on")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", CFG_OPENAI_API_KEY)
OPENAI_MODEL   = os.getenv("OPENAI_MODEL",   CFG_OPENAI_MODEL or "gpt-4o-mini")
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", str(CFG_STAFF_CHANNEL_ID or 0)) or 0)
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", str(CFG_TICKET_HUB_CHANNEL_ID or 0)) or 0)
TICKET_USER_MAX_MSG = int(os.getenv("TICKET_USER_MAX_MSG", str(CFG_TU_MAX or 5)))
TICKET_MSG_CHAR_LIMIT = int(os.getenv("TICKET_MSG_CHAR_LIMIT", str(CFG_CHARLIM or 800)))
TICKET_IDLE_SECONDS = int(os.getenv("TICKET_IDLE_SECONDS", str(CFG_IDLE or 600)))
ALLOW_STAFF_FREESPEECH = as_bool(os.getenv("ALLOW_STAFF_FREESPEECH", CFG_ALLOW))
WAKE_WORDS = [w.strip() for w in os.getenv("WAKE_WORDS", ",".join(CFG_WWS or ["isero"])).split(",") if w.strip()]

print(f"[DEBUG] OPENAI_API_KEY present? {bool(OPENAI_API_KEY)}")
print(f"[DEBUG] OPENAI_MODEL = {OPENAI_MODEL}")
print(f"[DEBUG] STAFF_CHANNEL_ID = {STAFF_CHANNEL_ID}")
print(f"[DEBUG] ALLOW_STAFF_FREESPEECH = {ALLOW_STAFF_FREESPEECH}")
print(f"[DEBUG] WAKE_WORDS = {WAKE_WORDS}")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def short(txt: str, n: int = 300):
    return txt if len(txt) <= n else txt[: n-3] + "…"

TICKET_CATEGORIES = ["General help", "Commission", "Mebinu", "Other"]

class TicketThreadState:
    def __init__(self, thread: discord.Thread, user: discord.Member, category: str):
        self.thread = thread
        self.user = user
        self.category = category
        self.user_turns = 0
        self.agent_turns = 0
        self.last_activity = time.time()
        self.closed = False

states: dict[int, TicketThreadState] = {}

class TicketStart(ui.View):
    """Gombok a ticket nyitáshoz – callbackekkel."""
    def __init__(self):
        super().__init__(timeout=None)
        for cat in TICKET_CATEGORIES:
            btn = ui.Button(
                label=f"Open a ticket: {cat}",
                style=ButtonStyle.primary,
                custom_id=f"ticket:{cat}"
            )
            btn.callback = self._make_callback(cat)
            self.add_item(btn)

    def _make_callback(self, category: str):
        async def cb(interaction: discord.Interaction):
            user = interaction.user
            ch = interaction.channel

            if not isinstance(ch, discord.TextChannel):
                await interaction.response.send_message("Nem tudok itt ticketet nyitni (nem text channel).", ephemeral=True)
                return

            # Őrszem: ha nem a hubban vagyunk, de van HUB ID, jelezzünk
            if TICKET_HUB_CHANNEL_ID and ch.id != TICKET_HUB_CHANNEL_ID:
                await interaction.response.send_message("A ticket gombokat a hub csatornában használd.", ephemeral=True)
                return

            name = f"ticket-{user.display_name}-{category}".replace(" ", "-")[:95]
            # Próbáljunk privát threadet, ha nem megy, publikus
            try:
                thread = await ch.create_thread(
                    name=name,
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=1440,
                )
            except Exception:
                thread = await ch.create_thread(
                    name=name,
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=1440,
                )

            try:
                await thread.add_user(user)
            except Exception:
                pass

            states[thread.id] = TicketThreadState(thread, user, category)

            await interaction.response.send_message(f"🎫 Nyitottam egy ticketet: {thread.mention}", ephemeral=True)
            await thread.send(
                f"🎫 **Ticket nyitva:** {user.mention} — *{category}*\n"
                f"Kérlek írd le röviden, mit szeretnél (≤ {TICKET_MSG_CHAR_LIMIT} karakter)."
            )
        return cb

class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.idle_checker.start()

    def cog_unload(self):
        self.idle_checker.cancel()

    async def call_openai(self, user_prompt: str, system_prompt: str) -> str:
        if not client:
            return "OpenAI kulcs hiányzik (client=None)."
        try:
            print("[DEBUG] GPT call attempt")
            rsp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=700,
            )
            content = (rsp.choices[0].message.content or "").strip()
            print("[DEBUG] GPT response OK, len=", len(content))
            return content
        except Exception as e:
            print(f"[DEBUG] GPT error: {e}")
            return f"(AI error: {e})"

    # ----------------- Üzenet figyelés -----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        try:
            print(f"[MSG] in={message.channel.id} staff={STAFF_CHANNEL_ID} author={message.author} -> {message.content[:120]}")
        except Exception:
            pass

        # STAFF szabad beszéd
        if (
            ALLOW_STAFF_FREESPEECH
            and message.guild
            and STAFF_CHANNEL_ID
            and message.channel.id == STAFF_CHANNEL_ID
        ):
            print("[STAFF] matched staff channel")
            content = (message.content or "").strip()

            # Wake words levágása (pl. "isero valami...")
            low = content.lower()
            for w in WAKE_WORDS:
                if low.startswith(w.lower() + " "):
                    content = content[len(w):].strip()
                    break

            if not content:
                return

            sys = (
                "You are ISERO, the staff assistant. You respond in Hungarian or English, "
                "matching the user's language. Be concrete and helpful. "
                "If a Discord slash command is appropriate, put it on the FIRST LINE as 'CMD: /posthub' "
                "or 'CMD: none' if no command exists. After that, reply normally."
            )
            ans = await self.call_openai(content, system_prompt=sys)

            # esetleges 'CMD:' első sorban
            cmd = None
            lines = [l for l in ans.splitlines() if l.strip()]
            if lines and lines[0].lower().startswith("cmd:"):
                cmd = lines[0][4:].strip()
                ans = "\n".join(lines[1:]).strip()

            if cmd and cmd.lower() != "none":
                if cmd.startswith("/posthub") and message.author.guild_permissions.manage_channels:
                    try:
                        ctx = await self.bot.get_context(message)
                        await self.posthub(ctx)  # hibrid parancs hívása
                    except Exception as e:
                        await message.channel.send(f"Parancs hívás hiba: {e}")
                else:
                    await message.channel.send("Nincs ilyen parancs jelenleg vagy nincs jogom lefuttatni.")

            if ans:
                await message.channel.send(ans)

        # Ticket thread flow
        if isinstance(message.channel, discord.Thread):
            st = states.get(message.channel.id)
            if st and not st.closed and message.author.id == st.user.id:
                if len(message.content) > TICKET_MSG_CHAR_LIMIT:
                    await message.reply(f"Kérlek maradj {TICKET_MSG_CHAR_LIMIT} karakternél.")
                    return

                st.user_turns += 1
                st.last_activity = time.time()
                if st.user_turns > TICKET_USER_MAX_MSG:
                    await message.reply("Kör limit elérve, összefoglalok.")
                    await self.finish_with_summary(st)
                    return

                sp = ("You are Isero, a terse but helpful assistant. "
                      "Answer under 300 chars, get to the point.")
                rr = await self.call_openai(f"Category: {st.category}. User: {message.content}", sp)
                await message.channel.send(short(rr, TICKET_MSG_CHAR_LIMIT))
                st.agent_turns += 1
                if st.agent_turns >= TICKET_USER_MAX_MSG:
                    await self.finish_with_summary(st)

        # hibrid parancsok engedése
        await self.bot.process_commands(message)

    async def finish_with_summary(self, st: TicketThreadState):
        items = []
        async for m in st.thread.history(limit=50, oldest_first=True):
            if m.author.bot:
                continue
            items.append(f"{m.author.display_name}: {m.content}")
        sp = ("You are Isero. Create a concise ticket summary for staff (<=800 chars). "
              "Include key requirements and up to 4 links if present.")
        up = "\n".join(items[-20:])
        summ = await self.call_openai(up, sp)
        await st.thread.send("✅ Summary for staff:\n" + summ)
        st.closed = True

    # --- idle zárás ---
    @tasks.loop(seconds=30)
    async def idle_checker(self):
        now = time.time()
        for st in list(states.values()):
            if st.closed:
                continue
            if now - st.last_activity > TICKET_IDLE_SECONDS:
                try:
                    await st.thread.send(
                        "⏳ 10 perc válasz nélkül.\n"
                        "- Mit szeretnél? (≤ 800 char)\n"
                        "- Határidő\n"
                        "- Max 4 referencia link\n"
                        "Staff hamarosan ránéz. Köszi!"
                    )
                except Exception:
                    pass
                st.closed = True

    # --- /posthub --- (hybrid, slash + !posthub)
    @commands.hybrid_command(name="posthub", description="Ticket gombok kirakása")
    @commands.has_permissions(manage_channels=True)
    async def posthub(self, ctx: commands.Context):
        if TICKET_HUB_CHANNEL_ID and ctx.channel and ctx.channel.id != TICKET_HUB_CHANNEL_ID:
            await ctx.reply("A hub csatornában használd a parancsot.", mention_author=False)
            return
        await ctx.send("Válassz kategóriát:", view=TicketStart())

    # --- /ask és !ask --- (hybrid)
    @commands.hybrid_command(name="ask", description="Kérdezd az ISERO-t (staff).")
    async def ask_hybrid(self, ctx: commands.Context, *, prompt: str):
        if STAFF_CHANNEL_ID and ctx.channel and ctx.channel.id != STAFF_CHANNEL_ID:
            await ctx.reply("Használd a staff csatornában.", mention_author=False)
            return
        if not OPENAI_API_KEY:
            await ctx.reply("OpenAI key hiányzik.")
            return
        await ctx.defer(ephemeral=False)
        sp = "You are ISERO, the staff assistant. Answer HU/EN precisely and helpfully."
        ans = await self.call_openai(prompt, sp)
        await ctx.reply(ans, mention_author=False)

async def setup(bot):
    await bot.add_cog(AgentGate(bot))
