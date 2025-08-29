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

print(f"[DEBUG] OPENAI_API_KEY present? {bool(OPENAI_API_KEY)}")
print(f"[DEBUG] OPENAI_MODEL = {OPENAI_MODEL}")
print(f"[DEBUG] STAFF_CHANNEL_ID = {STAFF_CHANNEL_ID}")
print(f"[DEBUG] ALLOW_STAFF_FREESPEECH = {ALLOW_STAFF_FREESPEECH}")
print(f"[DEBUG] WAKE_WORDS = {WAKE_WORDS}")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def short(txt: str, n: int = 300):
    return txt if len(txt) <= n else txt[: n-3] + "…"

TICKET_CATEGORIES = ["General help", "Commission", "Mebinu", "Other"]

class TicketStart(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for i, cat in enumerate(TICKET_CATEGORIES):
            self.add_item(ui.Button(label=f"Open a ticket: {cat}", style=ButtonStyle.primary, custom_id=f"ticket_{i}"))

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

            # Wakey-wakey
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

            # parancs kiszedés
            cmd = None
            lines = [l for l in ans.splitlines() if l.strip()]
            if lines and lines[0].lower().startswith("cmd:"):
                cmd = lines[0][4:].strip()
                ans = "
".join(lines[1:]).strip()

            if cmd and cmd.lower() != "none":
                if cmd.startswith("/posthub") and message.author.guild_permissions.manage_channels:
                    # Run the hybrid command path
                    try:
                        ctx = await self.bot.get_context(message)
                        await self.posthub(ctx)  # type: ignore
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
                    await message.reply(f"Kérlek maradj {TICKET_MSG_CHAR_LIMIT} karakternél."); return
                st.user_turns += 1
                st.last_activity = time.time()
                if st.user_turns > TICKET_USER_MAX_MSG:
                    await message.reply("Kör limit elérve, összefoglalok."); await self.finish_with_summary(st); return

                sp = ("You are Isero, a terse but helpful assistant. "
                      "Answer under 300 chars, get to the point.")
                rr = await self.call_openai(f"Category: {st.category}. User: {message.content}", sp)
                await message.channel.send(short(rr, TICKET_MSG_CHAR_LIMIT))
                st.agent_turns += 1
                if st.agent_turns >= TICKET_USER_MAX_MSG:
                    await self.finish_with_summary(st)

        # Let hybrid commands like !ask work
        await self.bot.process_commands(message)

    async def finish_with_summary(self, st: TicketThreadState):
        items = []
        async for m in st.thread.history(limit=50, oldest_first=True):
            if m.author.bot: continue
            items.append(f"{m.author.display_name}: {m.content}")
        sp = ("You are Isero. Create a concise ticket summary for staff (<=800 chars). "
              "Include key requirements and up to 4 links if present.")
        up = "
".join(items[-20:])
        summ = await self.call_openai(up, sp)
        await st.thread.send("✅ Summary for staff:
" + summ)
        st.closed = True

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
                        "- Mit szeretnél? (≤ 800 char)\n"
                        "- Határidő\n"
                        "- Max 4 referencia link\n"
                        "Staff hamarosan ránéz. Köszi!"
                    )
                except Exception: pass
                st.closed = True

    # --- /posthub ---  (hybrid, slash + !posthub)
    @commands.hybrid_command(name="posthub", description="Ticket gombok kirakása")
    @commands.has_permissions(manage_channels=True)
    async def posthub(self, ctx: commands.Context):
        await ctx.send("Válassz kategóriát:", view=TicketStart())

    # --- /ask és !ask --- (hybrid, hogy biztos menjen)
    @commands.hybrid_command(name="ask", description="Kérdezd az ISERO-t (staff).")
    async def ask_hybrid(self, ctx: commands.Context, *, prompt: str):
        if STAFF_CHANNEL_ID and ctx.channel and ctx.channel.id != STAFF_CHANNEL_ID:
            await ctx.reply("Használd a staff csatornában.", mention_author=False); return
        if not OPENAI_API_KEY:
            await ctx.reply("OpenAI key hiányzik."); return
        await ctx.defer(ephemeral=False)
        sp = "You are ISERO, the staff assistant. Answer HU/EN precisely and helpfully."
        ans = await self.call_openai(prompt, sp)
        await ctx.reply(ans, mention_author=False)

async def setup(bot):
    await bot.add_cog(AgentGate(bot))