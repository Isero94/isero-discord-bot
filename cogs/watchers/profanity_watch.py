from __future__ import annotations

from typing import List, Tuple
import os

import discord
from discord.ext import commands

from utils import policy, throttling, text as textutil, logsetup
from cogs.utils import context as ctx

# region ISERO PATCH tolerant_import
try:
    import regex as re  # supports \p{L}, (?V1), etc.
    _HAS_REGEX = True
except Exception:  # fallback to stdlib re (less precise)
    import re  # type: ignore
    _HAS_REGEX = False
# endregion ISERO PATCH tolerant_import

log = logsetup.get_logger(__name__)

# region ISERO PATCH sep_and_mask
# Megengedett elválasztók a betűk között: szóköz, NBSP, újsor, írásjelek, számjegy, aláhúzás – max 3 hossz
# ISERO PATCH: megengedő szeparátor (space, NBSP, nem-betű, szám), max 3
SEP = r"[\s\N{NO-BREAK SPACE}\W\d_]{0,3}" if _HAS_REGEX else r"[\s\W\d_]{0,3}"

# Word-boundary közelítés: regex esetén \p{L}-t használunk, stdlib re esetén [^\W\d_] a „betű” közelítés.
_BOUND_L = r"(?<!\p{L})" if _HAS_REGEX else r"(?<![^\W\d_])"
_BOUND_R = r"(?!\p{L})" if _HAS_REGEX else r"(?![^\W\d_])"

def _mask_preserving_separators(s: str) -> str:
    """Csillagozza a betű/szám karaktereket, de meghagyja az elválasztókat."""
    out = []
    for ch in s:
        out.append('*' if ch.isalnum() else ch)
    return ''.join(out)
# endregion ISERO PATCH sep_and_mask

def soft_censor_text(text: str, pat: re.Pattern) -> Tuple[str, int]:
    matches = list(pat.finditer(text))
    out = text
    for m in reversed(matches):
        out = out[: m.start()] + _mask_preserving_separators(m.group(0)) + out[m.end():]
    return out, len(matches)


class ProfanityWatcher(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.echo_ttl = policy.getint("PROFANITY_ECHO_TTL_S", 30)
        self.free_per_msg = policy.getint("PROFANITY_FREE_WORDS_PER_MSG", 2)
        self.lvl1 = policy.getint("PROFANITY_LVL1_THRESHOLD", 5)
        self.lvl2 = policy.getint("PROFANITY_LVL2_THRESHOLD", 8)
        self.lvl3 = policy.getint("PROFANITY_LVL3_THRESHOLD", 10)
        self.tout1 = policy.getint("PROFANITY_TIMEOUT_MIN_LVL1", 40)
        self.tout2 = policy.getint("PROFANITY_TIMEOUT_MIN_LVL2", 480)
        self.tout3 = policy.getint("PROFANITY_TIMEOUT_MIN_LVL3", 0)
        self.per_user_throttle = throttling.PerUserChannelTTL(self.echo_ttl)
        self.audit_channel_id = policy.getint("CHANNEL_MOD_LOGS", default=0)
        self.words_cfg = textutil.load_profanity_words()
        self.exempt_ids = {
            *{int(x) for x in os.getenv("PROFANITY_EXEMPT_USER_IDS", "").split(",") if x.strip()},
        }
        self._compiled: List[Tuple[str, re.Pattern]] = []
        self._compile_patterns()

    # region ISERO PATCH compile_patterns
    def _compile_patterns(self) -> None:
        """Szavak → toleráns regex minta."""
        def var(ch: str) -> str:
            m = {
                'a': '[aá@]',
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

        def build(word: str) -> re.Pattern:
            parts = []
            for ch in word:
                parts.append(f"{var(ch)}+")
            core = SEP.join(parts)
            pat = rf"{_BOUND_L}{core}{_BOUND_R}"
            return re.compile(pat, flags=re.DOTALL | re.IGNORECASE)

        self._compiled.clear()
        for w in self.words_cfg:
            self._compiled.append((w, build(w)))
        for w in ["bazdmeg", "seggfej", "anyád", "anyad"]:
            self._compiled.append((w, build(w)))
    # endregion ISERO PATCH compile_patterns

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        owner_id = policy.getint("OWNER_ID", default=0)
        is_owner = message.author.id == owner_id
        is_bot_self = message.author.id == getattr(self.bot.user, "id", None)

        content = message.content or ""
        if not content:
            return

        is_nsfw = policy.is_nsfw(message.channel)
        matches: List[Tuple[str, Tuple[int, int]]] = []
        for name, pat in self._compiled:
            for m in pat.finditer(content):
                matches.append((m.group(0), m.span()))
        if not matches:
            return

        redacted = content
        for s, (a, b) in sorted(matches, key=lambda x: x[1][0], reverse=True):
            redacted = redacted[:a] + _mask_preserving_separators(s) + redacted[b:]

        try:
            await textutil.send_audit(self.bot, self.audit_channel_id, message, reason="profanity", original=content, redacted=redacted)
        except Exception:
            log.exception("audit send failed")

        if is_owner or is_bot_self:
            try:
                if self.per_user_throttle.allow(message.author.id, message.channel.id):
                    await textutil.safe_echo(self.bot, message.channel, redacted, mimic_webhook=policy.getbool("USE_WEBHOOK_MIMIC", default=True), author=message.author)
            except Exception:
                log.exception("echo (owner/bot) failed")
            return

        if is_nsfw:
            return

        ctx.mark(message, moderated_hidden=True)
        try:
            await message.delete()
        except Exception:
            log.debug("delete failed", exc_info=True)
        try:
            if self.per_user_throttle.allow(message.author.id, message.channel.id):
                await textutil.echo_masked(self.bot, message, redacted, ttl_s=self.echo_ttl)
        except Exception:
            log.exception("echo failed")

        bad_count = len(matches)
        over = max(0, bad_count - self.free_per_msg)
        penalize = message.author.id not in self.exempt_ids
        if penalize and over > 0:
            key = f"profanity:{message.guild.id}:{message.author.id}"
            total = throttling.add_points(key, over, ttl=policy.getint("RECHECK_WINDOW_SECONDS", 180))
            if total >= self.lvl3:
                await textutil.timeout_member(message, self.tout3)
            elif total >= self.lvl2:
                await textutil.timeout_member(message, self.tout2)
            elif total >= self.lvl1:
                await textutil.timeout_member(message, policy.getint("PROFANITY_TIMEOUT_MIN_LVL2", 40))
        return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfanityWatcher(bot))


# backwards compat
ProfanityGuard = ProfanityWatcher


def build_tolerant_pattern(words: List[str]) -> re.Pattern:
    def var(ch: str) -> str:
        m = {
            'a': '[aá@]',
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

    patterns = []
    for word in words:
        parts = [f"{var(ch)}+" for ch in word]
        patterns.append(SEP.join(parts))
    core = "|".join(patterns) or r"$^"
    boundary = rf"{_BOUND_L}(?:{core}){_BOUND_R}"
    return re.compile(boundary, flags=re.DOTALL | re.IGNORECASE)
