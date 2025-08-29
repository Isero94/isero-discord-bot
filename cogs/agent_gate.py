import time
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
from openai import OpenAI
from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    STAFF_CHANNEL_ID, TICKET_HUB_CHANNEL_ID,
    TICKET_USER_MAX_MSG, TICKET_MSG_CHAR_LIMIT, TICKET_IDLE_SECONDS,
    WAKE_WORDS, ALLOW_STAFF_FREESPEECH
)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

TICKET_CATEGORIES = ["General help", "Commission", "Mebinu", "Other"]

def short(txt: str, n=300):
    return txt if len(txt) <= n else txt[: n-3] + "..."

class TicketStart(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for i, cat in enumerate(TICKET_CATEGORIES):
            self.add_item(
                ui.Button(label=f"Open a ticket: {cat}",
                          style=ButtonStyle.primary,
                          custom_id=f"ticket_{i}")
            )

class TicketThreadState:
    def __init__(self, thread: discord.Thread, user: discord.Member, category: str):
        self.thread = thread
        self.user = user
        self.category = category
        self.user_turns = 0
        self.agent_turns = 0
        self.last_activity = time.time()
        self.closed = False

states = {}

class AgentGate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.idle_checker.start()

    def cog_unload(self):
        self.idle_checker.cancel()

    async def call_openai(self, user_prompt: str, system_prompt: str) -> str:
        if not client:
            return "OpenAI nincs beállítva."
        try:
            rsp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=600,
            )
            return (rsp.choices[0].message.content or "").strip()
        except Exception as e:
            return f"(AI error: {e})"

    # ----------------- FŐ ÜZENET FIGYELŐ (staff + ticket) -----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # DEBUG: log minden üzenetről
        try:
            print(f"[MSG] ch={message.channel.id} author={message.author} -> {message.content[:120]}")
        except Exception:
            pass

        # 1) STAFF csatorna: szabad beszéd GPT-vel
        if ALLOW_STAFF_FREESPEECH and message.guild and STAFF_CHANNEL_ID and message.channel.id == STAFF_CHANNEL_ID:
            print("[STAFF] message matched staff channel")
            content = (message.content or "").strip()
            if content:
                # mention / wake-word vágás (nem kötelező, mindenre válaszolunk)
                if self.bot.user and content.startswith(f"<@{self.bot.user.id}>"):
                    content = content.split(">", 1)[1].strip() if ">" in content else content
                else:
                    low = content.lower()
                    for w in WAKE_WORDS:
                        if low.startswith(w + " "):
                            content = content[len(w):].strip()
                            break

                sys = (
                    "You are ISERO, the staff assistant. You understand and respond in Hungarian and English, "
