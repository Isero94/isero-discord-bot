FEATURE_NAME = "ticket_hub"

import discord, time, asyncio
from typing import Optional, List, Dict

from discord.ext import commands
from loguru import logger

from bot.config import (
    CATEGORIES, PRECHAT_TURNS, PRECHAT_MSG_CHAR_LIMIT,
    TICKET_TEXT_MAXLEN, TICKET_IMG_MAX, NSFW_AGEGATE_REQUIRED,
    TICKET_HUB_CHANNEL_ID, ARCHIVES_CHANNEL_ID
)
from cogs.utils.ai import short_reply

# ---- Ticket state ----
class TicketState:
    def __init__(self, thread: discord.Thread, user: discord.Member, cat_key: str):
        self.thread = thread
        self.user = user
        self.cat_key = cat_key  # 'mebinu' | 'commission' | 'nsfw' | 'general'
        self.closed = False
        # Pre-chat counters
        self.user_turns = 0
        self.agent_turns = 0
        # Final data
        self.final_text: Optional[str] = None
        self.attachments: List[str] = []
        # NSFW flag
        self.age_ok: bool = (cat_key != "nsfw")

    def touch(self):
        pass

# Simplified in-memory store for demo
states: Dict[int, TicketState] = {}  # thread_id -> state

# ---- Views ----
class TicketHubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(StartTicketButton())

class StartTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Start ticket", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=CategoryView(), ephemeral=True)

class CategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        for label in CATEGORIES:
            key = label.lower().split()[0]  # "Mebinu"->mebinu, "NSFW 18+"->nsfw
            self.add_item(CategoryButton(label=label, key="nsfw" if "nsfw" in key else key))
        self.add_item(DetailsButton())

class DetailsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Details", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        desc = {
            "Mebinu": "Collectible figure requests, variants, codes, rarity.",
            "Commission": "Paid custom art request; scope, budget, deadline.",
            "NSFW 18+": "18+ commissions; stricter policy & review.",
            "General Help": "Quick Q&A and guidance.",
        }
        lines = [f"**{k}** — {v}" for k, v in desc.items()]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

class CategoryButton(discord.ui.Button):
    def __init__(self, label: str, key: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.key = key  # mebinu|commission|nsfw|general

    async def callback(self, interaction: discord.Interaction):
        if self.key == "nsfw" and NSFW_AGEGATE_REQUIRED:
            await interaction.response.send_message(
                "Please confirm you are 18+ to proceed.", view=AgeGateView(), ephemeral=True
            )
            return

        await open_prechat_thread(interaction, self.key)

class AgeGateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(AgeConfirmButton())

class AgeConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="I am 18+", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        await open_prechat_thread(interaction, "nsfw", age_ok=True)

# ---- Helpers ----
async def open_prechat_thread(interaction: discord.Interaction, key: str, age_ok: bool=False):
    # Create a thread in the configured Ticket Hub channel or current channel
    parent = interaction.client.get_channel(TICKET_HUB_CHANNEL_ID) or interaction.channel
    th = await parent.create_thread(name=f"{key.upper()} | {interaction.user.display_name}")
    st = TicketState(thread=th, user=interaction.user, cat_key=key)
    if key == "nsfw":
        st.age_ok = age_ok
    states[th.id] = st
    await th.send(
        f"Opened pre-chat for **{key.upper()}**.
"
        f"Each message must be ≤ {PRECHAT_MSG_CHAR_LIMIT} characters. "
        f"Up to {PRECHAT_TURNS} rounds (you ↔ Isero)."
    )
    await interaction.response.send_message(f"Thread opened: {th.mention}", ephemeral=True)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ticket_hub")
    async def ticket_hub(self, ctx: commands.Context):
        """Post a TicketHub with Start button"""
        await ctx.send("TicketHub ready. Click to start.", view=TicketHubView())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Only watch thread messages with an active state
        if message.author.bot:
            return
        channel = message.channel
        if not isinstance(channel, discord.Thread):
            return
        st = states.get(channel.id)
        if not st or st.closed:
            return
        if message.author.id != st.user.id:
            return  # only count user's pre-chat messages

        # Enforce 300-char limit for user messages
        if len(message.content) > PRECHAT_MSG_CHAR_LIMIT:
            await message.reply(f"Please keep messages ≤ {PRECHAT_MSG_CHAR_LIMIT} characters.")
            return

        # Count user turn
        st.user_turns += 1

        # Isero reply (clamped)
        reply = await short_reply(message.content, max_chars=PRECHAT_MSG_CHAR_LIMIT)
        await channel.send(reply[:PRECHAT_MSG_CHAR_LIMIT])
        st.agent_turns += 1

        # Check limit
        if st.user_turns >= PRECHAT_TURNS or st.agent_turns >= PRECHAT_TURNS:
            await channel.send("We reached the pre-chat limit. Let's finalize your commission.", view=DecisionView())
            return

class DecisionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(WriteSelfButton())
        self.add_item(WriteIseroButton())

class WriteSelfButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="I will write it", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CommissionModal(author="user"))

class WriteIseroButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Let Isero write it", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        # Simple draft from last user message(s) – clamped to TICKET_TEXT_MAXLEN
        th = interaction.channel
        if not isinstance(th, discord.Thread):
            await interaction.response.send_message("Not in a thread.", ephemeral=True)
            return
        st = states.get(th.id)
        if not st:
            await interaction.response.send_message("No ticket state found.", ephemeral=True)
            return
        # Aggregate last ~5 user messages as draft (very simple baseline)
        history = []
        async for m in th.history(limit=20):
            if m.author.id == st.user.id:
                history.append(m.content.strip())
                if len(history) >= 5:
                    break
        history = list(reversed(history))
        draft = " ".join(history)[:TICKET_TEXT_MAXLEN]
        st.final_text = draft
        await interaction.response.send_message(
            "Draft prepared by Isero (you can Edit or Attach references):",
            view=RefsView(), ephemeral=True
        )
        await th.send(f"**Draft** (Isero): {draft}")

class CommissionModal(discord.ui.Modal, title="Commission"):
    def __init__(self, author: str):
        super().__init__()
        self.author = author
        self.input = discord.ui.TextInput(
            label=f"Describe your request (≤ {TICKET_TEXT_MAXLEN} chars)",
            style=discord.TextStyle.long,
            max_length=TICKET_TEXT_MAXLEN,
            required=True
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        th = interaction.channel
        if not isinstance(th, discord.Thread):
            await interaction.response.send_message("Not in a thread.", ephemeral=True)
            return
        st = states.get(th.id)
        if not st:
            await interaction.response.send_message("No ticket state found.", ephemeral=True)
            return
        st.final_text = str(self.input.value)[:TICKET_TEXT_MAXLEN]
        await interaction.response.send_message("Text saved. Attach references or submit.", view=RefsView(), ephemeral=True)
        await th.send(f"**Text** ({self.author}): {st.final_text}")

class RefsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(AttachRefsButton())
        self.add_item(SkipRefsButton())
        self.add_item(SubmitButton())
        self.add_item(EditButton())

class AttachRefsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Attach references", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Upload up to {TICKET_IMG_MAX} images in this thread. They will be detected automatically.",
            ephemeral=True
        )

class SkipRefsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Skip", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Skipping references. You can still submit.", ephemeral=True)

class EditButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Edit", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CommissionModal(author="user (edit)"))

class SubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Submit", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        th = interaction.channel
        if not isinstance(th, discord.Thread):
            await interaction.response.send_message("Not in a thread.", ephemeral=True)
            return
        st = states.get(th.id)
        if not st or not st.final_text:
            await interaction.response.send_message("Missing text. Please write or let Isero draft.", ephemeral=True)
            return
        # collect current attachments from the thread (recent messages)
        urls = []
        async for m in th.history(limit=50):
            for a in m.attachments:
                if a.content_type and a.content_type.startswith("image/"):
                    urls.append(a.url)
        urls = urls[:TICKET_IMG_MAX]

        st.attachments = urls
        st.closed = True

        # Emit summary to archives channel if configured
        out = (
            f"**Category:** {st.cat_key.upper()}\n"
            f"**User:** {st.user.mention} ({st.user.id})\n"
            f"**Text:** {st.final_text}\n"
            f"**Images:** {len(urls)}"
        )
        if ARCHIVES_CHANNEL_ID:
            ch = interaction.client.get_channel(ARCHIVES_CHANNEL_ID)
            if ch:
                await ch.send(out)
                for u in urls:
                    await ch.send(u)

        await th.send("Commission submitted. Thank you!")
        await interaction.response.send_message("Submitted.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
