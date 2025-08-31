# cogs/agent/agent_gate.py
from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import httpx
from openai import OpenAI

import config
from . import policy

class AgentGate(commands.Cog):
    """
    - @említésre, 'isero' kulcsszóra vagy DM-ben válaszol.
    - OWNER-nek mindig válaszol.
    - Modell futás közben váltható (admin parancs).
    - Stílus: policy.SYSTEM_PROMPT (szarkasztikus, száraz).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.model: str = config.OPENAI_MODEL
        self.daily_limit = int(config.AGENT_DAILY_TOKEN_LIMIT or 20000)
        self.used_tokens = 0

        # csatorna korlátozás (ha üres -> minden csatorna)
        self.allowed_channels = set(getattr(config, "AGENT_ALLOWED_CHANNELS", []) or [])

        # OpenAI kliens
        self.client = OpenAI(api_key=config.OPENAI_API_KEY, http_client=httpx.Client(timeout=20.0))

        # egy munkameneti lock, hogy ne jöjjön rá több hívás egyszerre
        self._lock = asyncio.Lock()

    # --------------------------- belső ---------------------------

    def _should_reply(self, message: discord.Message) -> bool:
        if not message.guild:
            return True  # DM-ben mindig

        if self.allowed_channels:
            if message.channel.id not in self.allowed_channels:
                return False

        # OWNER-nek mindig
        if config.OWNER_ID and message.author.id == config.OWNER_ID:
            return True

        # említ vagy név szerint szólít
        content_low = message.content.lower()
        bot_mentioned = any(u.id == self.bot.user.id for u in message.mentions) if self.bot.user else False
        name_called = "isero" in content_low or "isero a" in content_low
        return bot_mentioned or name_called

    def _build_messages(self, user_text: str, author: discord.Member) -> list:
        sys = policy.SYSTEM_PROMPT
        user = f"{author.display_name}: {user_text}"
        return [
            {"role": "system", "content": sys},
            {"role": "user", "content": user}
        ]

    def _chat_blocking(self, msgs: list) -> tuple[str, int]:
        """Szinkron hívás külön szálban futtatva – vissza: (válasz, felhasznált_tok.)"""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=msgs,
            temperature=0.6,
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        used = int(getattr(resp.usage, "total_tokens", 0) or 0)
        return text, used

    async def _chat(self, user_text: str, author: discord.Member) -> tuple[str, int]:
        msgs = self._build_messages(user_text, author)
        # blokkolót külön threadben
        return await asyncio.to_thread(self._chat_blocking, msgs)

    # --------------------------- események ---------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not self._should_reply(message):
            return

        async with self._lock:
            if self.used_tokens >= self.daily_limit:
                return  # némán elengedjük, ha kifutna a napi keret

            try:
                reply, used = await self._chat(message.content, message.author)
            except Exception as e:
                # ne pukkadjunk – rövid száraz hiba
                await message.channel.send("Valami elfüstölt a háttérben. Próbáld újra később.")
                return

            self.used_tokens += used
            if reply:
                await message.reply(reply)

    # --------------------------- admin / model ---------------------------

    group = app_commands.Group(name="agent", description="Agent beállítások")

    @group.command(name="model", description="Modell lekérdezése/beállítása")
    @app_commands.describe(name="Új modell neve (pl. gpt-4o, gpt-4o-mini). Üresen: csak megmutatja.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def model_cmd(self, interaction: discord.Interaction, name: Optional[str] = None):
        if name:
            self.model = name.strip()
            await interaction.response.send_message(f"Oké. Új modell: **{self.model}**", ephemeral=True)
        else:
            await interaction.response.send_message(f"Jelenlegi modell: **{self.model}**", ephemeral=True)

    @group.command(name="usage", description="Mai tokenhasználat")
    async def usage_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Ma felhasznált: **{self.used_tokens} / {self.daily_limit}** token.", ephemeral=True
        )

    @group.command(name="allow", description="Megengedett csatorna hozzáadása/eltávolítása (ha üres lista, mindenhol válaszol).")
    @app_commands.describe(action="add|remove|list", channel="Csatorna (add/remove esetén)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def allow_cmd(self, interaction: discord.Interaction, action: str, channel: Optional[discord.TextChannel] = None):
        action = action.lower()
        if action == "list":
            if not self.allowed_channels:
                await interaction.response.send_message("Jelenleg **minden** csatornán válaszolok.", ephemeral=True)
            else:
                items = ", ".join(f"<#{cid}>" for cid in self.allowed_channels)
                await interaction.response.send_message(f"Megengedett csatornák: {items}", ephemeral=True)
            return

        if channel is None:
            await interaction.response.send_message("Adj meg csatornát.", ephemeral=True)
            return

        if action == "add":
            self.allowed_channels.add(channel.id)
            await interaction.response.send_message(f"Hozzáadva: {channel.mention}", ephemeral=True)
        elif action == "remove":
            self.allowed_channels.discard(channel.id)
            await interaction.response.send_message(f"Eltávolítva: {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("Használat: action = add|remove|list", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
    try:
        if config.GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=config.GUILD_ID))
        else:
            await bot.tree.sync()
    except Exception:
        pass
