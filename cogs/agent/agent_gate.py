import os
from typing import List

import discord
from discord.ext import commands

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
WAKE_WORDS: List[str] = [w.strip().lower() for w in os.getenv("WAKE_WORDS", "Isero,isero").split(",")]
HUB_CH_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0"))

class AgentGate(commands.Cog):
    """Természetes nyelvű 'Isero' feladatok – ownernek teljes hozzáféréssel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # --- helper: jogosultság + wake szó felismerés ---
    def _is_owner(self, user: discord.abc.User) -> bool:
        return OWNER_ID and user.id == OWNER_ID

    def _woke(self, content: str) -> bool:
        c = content.lower()
        return any(w in c for w in WAKE_WORDS)

    # --- owner NATURÁL parancsok ---
    async def _owner_cleanup_and_setup(self, source_message: discord.Message):
        """Hub takarítás + újraposztolás. Tickets cog metódusait hívja."""
        tickets = self.bot.get_cog("Tickets")
        if not tickets:
            await source_message.channel.send("Tickets cog nincs betöltve.")
            return

        # célcsatorna: env alapján, különben az aktuális csatorna
        target = self.bot.get_channel(HUB_CH_ID) if HUB_CH_ID else source_message.channel

        # vedd elő a két publikus metódust a Tickets-ből
        cleanup = getattr(tickets, "cleanup_hub_messages", None)
        posthub = getattr(tickets, "post_hub", None)

        if callable(cleanup) and callable(posthub):
            deleted = await cleanup(target)
            await posthub(target)
            await source_message.channel.send(f"Hub frissítve. Törölve: {deleted} üzenet. Csatorna: {target.mention}")
        else:
            # Ha régi tickets.py van, ahol ezek nincsenek, esés vissza
            await source_message.channel.send(
                "Hub üzenet nem posztolható automatikusan. "
                "Futtasd a `/ticket_hub_setup` vagy `/ticket_hub_cleanup` parancsot."
            )

    async def _owner_status(self, channel: discord.abc.Messageable):
        guilds = len(self.bot.guilds)
        users = sum(g.member_count or 0 for g in self.bot.guilds)
        await channel.send(f"**Isero státusz**: guilds={guilds}, members~={users}")

    # --- üzenet figyelő ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        content = message.content.strip()
        if not content:
            return

        # csak OWNER – teljes hozzáférés
        if not self._is_owner(message.author):
            return

        # “Isero …” jellegű kérések
        if self._woke(content):

            # takarítás + újraposztolás kulcsszavak
            if any(k in content.lower() for k in [
                "takarítsd a hubot",
                "cleanup hub",
                "hub cleanup",
                "hub setup",
                "frissítsd a hubot",
            ]):
                await self._owner_cleanup_and_setup(message)
                return

            # státusz
            if any(k in content.lower() for k in ["status", "státusz", "állapot"]):
                await self._owner_status(message.channel)
                return

            # ha ide jutunk, default válasz (ne legyen csend)
            await message.channel.send("Parancs értve. Mondd: *takarítsd a hubot* vagy *status*.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
