from __future__ import annotations

"""Unicode-toleráns profanitás figyelő csillagozott echo-val."""

try:  # Unicode regex, fallback stdlib re-re
    import regex as re
    _HAS_REGEX = True
except Exception:  # pragma: no cover - stdlib re fallback
    import re  # type: ignore
    _HAS_REGEX = False

import discord
from discord import Forbidden, NotFound
from discord.ext import commands

from utils import policy, throttling, text as textutil, logsetup
from cogs.utils import context as ctxutil

log = logsetup.get_logger(__name__)

# szeparátor: szóköz, NBSP, nem-betű, szám, aláhúzás – max 3 egymás után
SEP = r"(?:\s|\N{NO-BREAK SPACE}|[^\w]|[\d_]){0,3}"


class ProfanityWatcher(commands.Cog):
    """Toleráns profanitás figyelő, csillagozott echo-val."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mode = policy.getstr("PROFANITY_MODE", default="echo_star").lower()
        self.free_per_msg = policy.getint("PROFANITY_FREE_WORDS_PER_MSG", default=2)
        self.echo_ttl = policy.getint("PROFANITY_ECHO_TTL_S", default=30)
        self.exempt_ids = {
            int(x.strip())
            for x in policy.getstr("PROFANITY_EXEMPT_USER_IDS", default="").split(",")
            if x.strip().isdigit()
        }
        self.l1 = policy.getint("PROFANITY_LVL1_THRESHOLD", 5)
        self.l2 = policy.getint("PROFANITY_LVL2_THRESHOLD", 8)
        self.l3 = policy.getint("PROFANITY_LVL3_THRESHOLD", 11)
        self.tmo2 = policy.getint("PROFANITY_TIMEOUT_MIN_LVL2", 40)
        self.tmo3 = policy.getint("PROFANITY_TIMEOUT_MIN_LVL3", 0)
        self.per_user_throttle = throttling.PerUserChannelTTL(self.echo_ttl)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # botok, DM-ek, self és exempt lista
        if message.author.bot or not message.guild:
            return
        if message.author.id in self.exempt_ids:
            return
        # már moderált? továbblépünk
        if ctxutil.is_flagged(message, "moderated_hidden"):
            return

        txt = message.content or ""
        if not txt:
            return

        # profán találatok
        hits = textutil.find_profanities(txt)
        if not hits:
            return

        excess = max(0, len(hits) - self.free_per_msg)
        if excess > 0:
            throttling.bump_score(
                scope=("profanity", message.guild.id, message.author.id),
                inc=excess,
                ttl_seconds=policy.getint("AGENT_SESSION_WINDOW_SECONDS", 120),
            )

        score = throttling.get_score(("profanity", message.guild.id, message.author.id))
        level = 0
        if score >= self.l3:
            level = 3
        elif score >= self.l2:
            level = 2
        elif score >= self.l1:
            level = 1

        starred = textutil.star_out(txt, hits)

        is_nsfw = policy.is_nsfw(message.channel)
        if is_nsfw:
            await textutil.modlog_profanity(message, original=txt, starred=starred, hits=hits, level=level)
            return

        if self.mode == "echo_star":
            ctxutil.flag(message, "moderated_hidden", True)
            try:
                await message.delete()
            except (Forbidden, NotFound, AttributeError):
                pass
            if self.per_user_throttle.allow(message.author.id, message.channel.id):
                try:
                    await textutil.webhook_echo(
                        channel=message.channel,
                        author=message.author,
                        content=starred,
                        ttl_seconds=self.echo_ttl,
                    )
                except Exception:
                    log.exception("Webhook echo failed, fallback send")
                    await message.channel.send(f"{message.author.mention}: {starred}")

        await textutil.modlog_profanity(message, original=txt, starred=starred, hits=hits, level=level)

        if level == 2 and self.tmo2 > 0:
            await textutil.timeout_member(message.author, minutes=self.tmo2, reason="Profanity L2")
        if level == 3:
            await textutil.timeout_member(message.author, minutes=self.tmo3, reason="Profanity L3")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfanityWatcher(bot))

# backwards compat
ProfanityGuard = ProfanityWatcher


def build_tolerant_pattern(words: list[str]) -> re.Pattern:
    def var(ch: str) -> str:
        m = {
            'a': '[aá@4]',
            'e': '[eé3]',
            'i': '[ií1l!]',
            'o': '[oóöő0]',
            'u': '[uúüűv]',
            'c': '(?:c(?:h)?)',
            's': '[s$5]',
            'z': '[z2]',
            'g': '[g9]',
            'b': '[b8]',
        }
        return m.get(ch.lower(), re.escape(ch))
    parts = []
    for w in words:
        letters = [f"{var(ch)}+" for ch in w]
        parts.append(SEP.join(letters))
    core = "|".join(parts) or r"$^"
    bound_l = r"(?<!\p{L})" if _HAS_REGEX else r"(?<![^\W\d_])"
    bound_r = r"(?!\p{L})" if _HAS_REGEX else r"(?![^\W\d_])"
    return re.compile(rf"{bound_l}(?:{core}){bound_r}", re.IGNORECASE | re.DOTALL)


def soft_censor_text(text: str, pat: re.Pattern) -> tuple[str, int]:
    matches = list(pat.finditer(text))
    out = text
    for m in reversed(matches):
        sub = textutil.star_out(m.group(0), [(0, len(m.group(0)))])
        out = out[: m.start()] + sub + out[m.end():]
    return out, len(matches)

