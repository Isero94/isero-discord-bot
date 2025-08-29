import os
import re
import logging
from typing import List, Tuple

import discord
from discord.ext import commands

from cogs.tickets.tickets import post_ticket_hub, cleanup_ticket_hub  # megosztott helpers

log = logging.getLogger("bot")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
WAKE_WORDS = [w.strip().lower() for w in os.getenv("WAKE_WORDS", "isero, isszero").split(",") if w.strip()]

def _is_owner(msg: discord.Message) -> bool:
    return msg.author.id == OWNER_ID

def _woke(msg: discord.Message) -> bool:
    text = (msg.content or "").lower()
    return any(w in text for w in WAKE_WORDS)

def _clean(text: str) -> str:
    t = text.lower()
    for w in WAKE_WORDS:
        t = t.replace(w, "")
    return t.strip()


class AgentGate(commands.Cog):
    """Owner-only természetes nyelv → bot műveletek kapu.
    Nem szivárogtat belső infókat másokra.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- Alap státusz parancs csak tulajnak ----
    async def _owner_status(self, channel: discord.abc.MessageableChannel):
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        loaded = ", ".join(sorted(self.bot.extensions.keys()))
        await channel.send(
            f"✅ **OK** — model: `{model}`, cogs: {loaded or 'n/a'}."
        )

    # ---- Intentek: minták magyar/angol ----
    def _route(self, text: str) -> Tuple[str, dict]:
        t = _clean(text)

        # cleanup hub
        if re.search(r"(cleanup|takar|töröld|törölj|remove).*(hub|gomb|ticket)", t):
            return "cleanup_hub", {}

        if re.search(r"(post|rakd|rakj|tedd|írj|add).*(hub|gomb|ticket)", t):
            return "post_hub", {}

        if re.search(r"(sync|szinkron|parancs.*sync|tree)", t):
            return "sync_tree", {}

        if re.search(r"(státusz|status|health|állapot)", t):
            return "status", {}

        return "none", {}

    # ---- Message listener ----
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        # ne reagáljon saját magára / DM-ek is mehetnek
        if msg.author.bot:
            return

        # csak OWNER és wake-word esetén
        if not (_is_owner(msg) and _woke(msg)):
            return

        # csak guildben cselekszünk ticket-hub műveleteket
        if isinstance(msg.channel, discord.DMChannel):
            await msg.channel.send("👋 Mondd: *isero* „rakd ki a hubot itt” / „takarítsd a hubot itt”. DM-ben csak alap státuszt tudok mondani.")
            return

        cmd, params = self._route(msg.content)

        try:
            if cmd == "cleanup_hub":
                if isinstance(msg.channel, discord.TextChannel):
                    deleted = await cleanup_ticket_hub(msg.channel)
                    await msg.reply(f"🧹 Hub cleanup done. Deleted: **{deleted}** msg.", mention_author=False)
                else:
                    await msg.reply("Csak szövegcsatornában tudok takarítani.", mention_author=False)

            elif cmd == "post_hub":
                if isinstance(msg.channel, discord.TextChannel):
                    m = await post_ticket_hub(msg.channel)
                    await msg.reply(f"🟣 TicketHub posted: {m.jump_url}", mention_author=False)
                else:
                    await msg.reply("Csak szövegcsatornába tudok hubot kirakni.", mention_author=False)

            elif cmd == "sync_tree":
                # gyors helyi sync a guildre
                try:
                    if GUILD_ID:
                        await self.bot.tree.sync(guild=discord.Object(id=GUILD_ID))
                    else:
                        await self.bot.tree.sync()
                    await msg.reply("🌿 Slash parancsok szinkronban.", mention_author=False)
                except Exception as e:
                    await msg.reply(f"❌ Tree sync hiba: `{e}`", mention_author=False)

            elif cmd == "status":
                await self._owner_status(msg.channel)

            else:
                # Owner + wake word, de nem ismerte fel → súgó röviden
                await msg.reply(
                    "Parancsok: *cleanup hub*, *post hub*, *sync tree*, *status*.\n"
                    "Példa: `isero takarítsd a ticket hubot`",
                    mention_author=False,
                )

        except Exception as e:
            log.exception("Owner gateway error")
            await msg.reply(f"⚠️ Hiba történt: `{e}`", mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
