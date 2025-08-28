import asyncio, time
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_MODEL_SMART, STAFF_CHANNEL_ID, TICKET_HUB_CHANNEL_ID, TICKET_USER_MAX_MSG, TICKET_MSG_CHAR_LIMIT, TICKET_IDLE_SECONDS

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

TICKET_CATEGORIES = ["General help","Commission","Mebinu","Other"]

def short(txt: str, n=300):
    return txt if len(txt) <= n else txt[: n-3] + "..."

class TicketStart(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for i,cat in enumerate(TICKET_CATEGORIES):
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

states = {}

class AgentGate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.idle_checker.start()

    def cog_unload(self):
        self.idle_checker.cancel()

    @tasks.loop(seconds=30)
    async def idle_checker(self):
        now = time.time()
        for state in list(states.values()):
            if state.closed: continue
            if now - state.last_activity > TICKET_IDLE_SECONDS:
                try:
                    await state.thread.send(f"""⏳ 10 minutes passed without reply.
**Please fill this mini form:**
- What do you need? (≤ 800 chars)
- Deadline (if any)
- Up to 4 references (links)
Once sent, staff will review. Thanks!""")
                except Exception: pass
                state.closed = True

    @commands.hybrid_command(name="posthub", description="Post ticket hub buttons in current channel")
    @commands.has_permissions(manage_channels=True)
    async def posthub(self, ctx: commands.Context):
        await ctx.send("Click a button to open a private ticket thread with the assistant.", view=TicketStart())

    @commands.Cog.listener("on_interaction")
    async def open_ticket_on_click(self, interaction: discord.Interaction):
        if not isinstance(interaction.data, dict): return
        cid = str(interaction.data.get("custom_id",""))
        if not cid.startswith("ticket_"): return
        idx = int(cid.split("_")[1])
        category = TICKET_CATEGORIES[idx] if 0 <= idx < len(TICKET_CATEGORIES) else "Other"
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Only in text channels.", ephemeral=True); return
        thread = await interaction.channel.create_thread(name=f"ticket-{interaction.user.display_name}", type=discord.ChannelType.private_thread, invitable=False)
        await thread.add_user(interaction.user)
        state = TicketThreadState(thread, interaction.user, category)
        states[thread.id] = state
        await interaction.response.send_message(f"Created {thread.mention} for you. Let's talk!", ephemeral=True)
        await thread.send(f"Hi {interaction.user.mention}! Category: **{category}**. Describe your request. Max {TICKET_MSG_CHAR_LIMIT} chars; up to {TICKET_USER_MAX_MSG} turns.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not isinstance(message.channel, discord.Thread):
            return
        state = states.get(message.channel.id)
        if not state or state.closed: return
        if message.author.id != state.user.id:
            return

        if len(message.content) > TICKET_MSG_CHAR_LIMIT:
            await message.reply(f"Please keep it under {TICKET_MSG_CHAR_LIMIT} characters.")
            return
        state.user_turns += 1
        state.last_activity = time.time()

        if state.user_turns > TICKET_USER_MAX_MSG:
            await message.reply("Turn limit reached. I'll draft a ticket from what we have.")
            await self.finish_with_summary(state); return

        reply = await self.agent_reply_short(message.content, state)
        try:
            await message.channel.send(short(reply, TICKET_MSG_CHAR_LIMIT))
        except Exception: pass
        state.agent_turns += 1
        if state.agent_turns >= TICKET_USER_MAX_MSG:
            await self.finish_with_summary(state)

    async def finish_with_summary(self, state: "TicketThreadState"):
        messages = []
        async for m in state.thread.history(limit=50, oldest_first=True):
            if m.author.bot: continue
            messages.append(f"{m.author.display_name}: {m.content}")
        
        system_prompt = "You are Isero, a highly skilled hacker and marketing strategist. You are writing a ticket summary for your staff. Be concise, professional, and formal."
        user_prompt = "Summarize the user's request in <=800 chars. Include key requirements and up to 4 reference URLs if present.\n\n" + "\n".join(messages[-20:])
        summary = await self.call_openai(user_prompt, system_prompt=system_prompt)
        
        try:
            await state.thread.send("✅ Thanks! Here's the ticket summary for staff:\n" + summary)
        except Exception: pass
        state.closed = True

    async def agent_reply_short(self, user_text: str, state: "TicketThreadState") -> str:
        if not OPENAI_API_KEY:
            return "OpenAI key not configured."
        
        system_prompt = "You are Isero, a mysterious and sarcastic hacker/marketing strategist. Your goal is to keep the conversation brief, to get the point, and to get the user's request. You are a professional, but your wit shines through. Short answers only (<=300 chars)."
        user_prompt = f"Category: {state.category}. User says: {user_text}"
        
        return await self.call_openai(user_prompt, system_prompt=system_prompt)

    async def call_openai(self, user_prompt: str, system_prompt: str) -> str:
        if not client:
            return "OpenAI not configured."
        try:
            rsp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role":"system","content":system_prompt},
                          {"role":"user","content":user_prompt}],
                temperature=0.7,
                max_tokens=400
            )
            return rsp.choices[0].message.content.strip()
        except Exception as e:
            return f"(AI error: {e})"

    @app_commands.command(name="ask", description="Ask the ISERO agent (staff only).")
    async def ask(self, interaction: discord.Interaction, prompt: str):
        if STAFF_CHANNEL_ID and interaction.channel_id != STAFF_CHANNEL_ID:
            await interaction.response.send_message("Use this in the staff channel.", ephemeral=True); return
        if not OPENAI_API_KEY:
            await interaction.response.send_message("OpenAI key not set.", ephemeral=True); return
        await interaction.response.defer(thinking=True, ephemeral=False)

        system_prompt = "You are Isero, a highly skilled and professional AI assistant for staff. You are concise, respectful, and detail-oriented. Answer with comprehensive knowledge."
        ans = await self.call_openai(prompt, system_prompt=system_prompt)
        await interaction.followup.send(ans)

async def setup(bot):
    await bot.add_cog(AgentGate(bot))
