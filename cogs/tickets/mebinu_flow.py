import os
import discord
from discord.ext import commands

class MebinuFlow(commands.Cog):
    """Mebinu ticket flow: start ISERO agent and purge legacy prompt."""

    def __init__(self, bot):
        self.bot = bot
        self._legacy_markers = [
            "Melyik termék vagy téma?",
            "Mennyiség, ritkaság, színvilág?",
            "Határidő",
            "Keret (HUF/EUR)?",
            "Van 1-4 referencia",
            "max 800 karakter",
        ]

    async def start_flow(self, channel: discord.TextChannel, opener: discord.Member):
        tickets = self.bot.get_cog("Tickets")
        if tickets and hasattr(tickets, "post_welcome_and_sla"):
            await tickets.post_welcome_and_sla(channel, "mebinu", opener)
        await self._sweep_legacy(channel)
        if os.getenv("MEBINU_USE_AGENT", "true").lower() == "true":
            agent = self.bot.get_cog("AgentGate")
            if agent:
                sys = (
                    "You are ISERO, a witty, sales-savvy Discord agent. "
                    "Goal: close the sale for Mebinu customs politely, upsell gently. "
                    "Keep replies 1–3 sentences. Ask exactly one focused question each turn. "
                    "Pricing: $30 per Mebinu, 4+ → -$5 each. SLA ≈ 3 days. "
                    "Detect budget/quantity/style hints; confirm and move forward."
                )
                try:
                    await agent.start_session(
                        channel=channel,
                        system_prompt=sys,
                        prefer_heavy=True,
                        ttl_seconds=int(os.getenv("AGENT_DEDUP_TTL_SECONDS", "120") or "120"),
                    )
                    await channel.send(
                        "ISERO bekapcsolt. Kezdjük a briefet! 😉 Mi lenne az első elképzelésed?"
                    )
                    return
                except Exception:
                    pass

    async def _sweep_legacy(self, channel: discord.TextChannel):
        try:
            async for m in channel.history(limit=25):
                if m.author.bot and any(k in (m.content or "") for k in self._legacy_markers):
                    try:
                        await m.delete()
                    except Exception:
                        pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot and any(k in (message.content or "") for k in self._legacy_markers):
            try:
                await message.delete()
            except Exception:
                pass
