import os
import time
import discord
from discord.ext import commands
from discord import app_commands
from openai import OpenAI

# --- Konfig + ENV fallback ---
from config import (
    OPENAI_API_KEY as CFG_OPENAI_API_KEY,
    OPENAI_MODEL as CFG_OPENAI_MODEL,
    STAFF_CHANNEL_ID as CFG_STAFF_CHANNEL_ID,
    ALLOW_STAFF_FREESPEECH as CFG_ALLOW,
    WAKE_WORDS as CFG_WWS,
)

def as_bool(x):
    return str(x).strip().lower() in ("1","true","yes","y","on")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", CFG_OPENAI_API_KEY)
OPENAI_MODEL   = os.getenv("OPENAI_MODEL",   CFG_OPENAI_MODEL or "gpt-4o-mini")
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", str(CFG_STAFF_CHANNEL_ID or 0)) or 0)
ALLOW_STAFF_FREESPEECH = as_bool(os.getenv("ALLOW_STAFF_FREESPEECH", CFG_ALLOW))
WAKE_WORDS = [w.strip() for w in os.getenv("WAKE_WORDS", ",".join(CFG_WWS or ["isero"])).split(",") if w.strip()]

print(f"[DEBUG] OPENAI_API_KEY present? {bool(OPENAI_API_KEY)}")
print(f"[DEBUG] OPENAI_MODEL = {OPENAI_MODEL}")
print(f"[DEBUG] STAFF_CHANNEL_ID = {STAFF_CHANNEL_ID}")
print(f"[DEBUG] ALLOW_STAFF_FREESPEECH = {ALLOW_STAFF_FREESPEECH}")
print(f"[DEBUG] WAKE_WORDS = {WAKE_WORDS}")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def call_openai(self, user_prompt: str, system_prompt: str) -> str:
        if not client:
            return "OpenAI kulcs hiányzik (client=None)."
        try:
            rsp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=700,
            )
            return (rsp.choices[0].message.content or "").strip()
        except Exception as e:
            return f"(AI error: {e})"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # csak staff free-speech
        if message.author.bot:
            return
        if not (ALLOW_STAFF_FREESPEECH and message.guild and STAFF_CHANNEL_ID and message.channel.id == STAFF_CHANNEL_ID):
            return

        content = (message.content or "").strip()
        if not content:
            return

        low = content.lower()
        for w in WAKE_WORDS:
            if low.startswith(w.lower() + " "):
                content = content[len(w):].strip()
                break
        if not content:
            return

        sys = (
            "You are ISERO, the staff assistant. Respond in Hungarian or English to match the user. "
            "Be concise and helpful. If a Discord slash command would help, put it on the FIRST LINE as "
            "'CMD: /posthub' etc., or 'CMD: none' if no command. Then answer normally."
        )
        ans = await self.call_openai(content, sys)

        cmd = None
        lines = [l for l in ans.splitlines() if l.strip()]
        if lines and lines[0].lower().startswith("cmd:"):
            cmd = lines[0][4:].strip()
            ans = "\n".join(lines[1:]).strip()

        if cmd and cmd.lower() != "none":
            await message.channel.send(f"(Javasolt parancs) {cmd}")

        if ans:
            await message.channel.send(ans)

    # --- /ask (slash + !ask hybrid) ---
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
