import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict

import discord
from discord.ext import commands

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ALLOW_STAFF_FREESPEECH = (os.getenv("ALLOW_STAFF_FREESPEECH", "false").lower() == "true")
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0") or 0)
STAFF_EXTRA_ROLE_IDS = [int(x) for x in (os.getenv("STAFF_EXTRA_ROLE_IDS", "") or "").split(",") if x.strip().isdigit()]

CHANNEL_GENERAL_LOGS = int(os.getenv("CHANNEL_GENERAL_LOGS", "0") or 0)
CHANNEL_MOD_LOGS = int(os.getenv("CHANNEL_MOD_LOGS", "0") or 0)

# minimál magyar/angol lista – később bővíthető .yml-ből
BAD_WORDS = [
    "kurva", "kurvára", "kurvanyád", "picsa", "picsába", "fasz", "fasza", "geci",
    "baszd", "baszod", "baszki", "kibaszott", "fuck", "shit"
]
BAD_RE = re.compile(r"(?i)\b(" + "|".join(re.escape(w) for w in BAD_WORDS) + r")\b")

def has_staff_role(member: discord.Member) -> bool:
    rids = {r.id for r in getattr(member, "roles", [])}
    if STAFF_ROLE_ID and STAFF_ROLE_ID in rids:
        return True
    return any(rid in rids for rid in STAFF_EXTRA_ROLE_IDS)

def count_bonus_points(content: str) -> int:
    """2 szó még oké; 3. és afölött: pontok"""
    n = len(BAD_RE.findall(content or ""))
    return max(0, n - 2)

class ProfanityGuard(commands.Cog):
    """Pontozás + háromszintű szankció. Bot NEM banol, csak timeoutol."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> dict(stage, points)
        self.state: Dict[int, Dict[str, int]] = {}

    def _exempt_here(self, channel_id: int) -> bool:
        # log csatornákon NINCS intézkedés
        return channel_id in {CHANNEL_GENERAL_LOGS, CHANNEL_MOD_LOGS}

    async def _timeout(self, member: discord.Member, minutes: int | None):
        try:
            if minutes is None:
                until = None  # feloldásig
            else:
                until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            await member.edit(timed_out_until=until, reason="ProfanityGuard")
        except discord.Forbidden:
            pass

    async def _log(self, guild: discord.Guild, message: discord.Message, text: str):
        ch = guild.get_channel(CHANNEL_MOD_LOGS) or guild.get_channel(CHANNEL_GENERAL_LOGS)
        if not ch:
            return
        try:
            await ch.send(f"[Profanity] {text}\n↳ by {message.author.mention} in {message.channel.mention}\n```{message.content}```")
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if self._exempt_here(message.channel.id):
            return
        if message.author.id == OWNER_ID:
            return  # Owner mentes
        if ALLOW_STAFF_FREESPEECH and isinstance(message.author, discord.Member) and has_staff_role(message.author):
            return

        pts = count_bonus_points(message.content)
        if pts <= 0:
            return  # 0 pont – nem történik semmi

        s = self.state.setdefault(message.author.id, {"stage": 1, "points": 0})
        s["points"] += pts

        # küszöbök: 5 -> 40 perc, +3 -> 1 nap, +2 -> végleges
        action = None
        if s["stage"] == 1 and s["points"] >= 5:
            action = ("40 perc timeout", 40)
            s["stage"] = 2
            s["points"] = 0
        elif s["stage"] == 2 and s["points"] >= 3:
            action = ("1 nap timeout", 60 * 24)
            s["stage"] = 3
            s["points"] = 0
        elif s["stage"] == 3 and s["points"] >= 2:
            action = ("feloldásig timeout", None)
            # stage maradhat 3-on; feloldás kézzel

        if action:
            label, minutes = action
            if isinstance(message.author, discord.Member):
                await self._timeout(message.author, minutes)
            await self._log(message.guild, message, f"{label} – összegyűlt pont: +{pts}")
        else:
            # csak logolunk pontgyűjtést
            await self._log(message.guild, message, f"+{pts} pont (össz: {s['points']}, stage: {s['stage']})")


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
