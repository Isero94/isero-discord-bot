from __future__ import annotations

import regex as re
from typing import List, Tuple

import discord
from discord.ext import commands

from utils import policy, throttling, text as textutil, logsetup

log = logsetup.get_logger(__name__)

# region ISERO PATCH sep_and_mask
# Megengedett elválasztók a betűk között: szóköz, NBSP, újsor, írásjelek, számjegy, aláhúzás – max 3 hossz
SEP = r"(?:[\s\N{NO-BREAK SPACE}\W\d_]{0,3})"

def _mask_preserving_separators(s: str) -> str:
    """Csillagozza a betű/szám karaktereket, de meghagyja az elválasztókat."""
    out = []
    for ch in s:
        out.append('*' if ch.isalnum() else ch)
    return ''.join(out)
# endregion ISERO PATCH sep_and_mask


def censor_token(token: str) -> str:
    if len(token) <= 2:
        return '*' * len(token)
    return token[0] + ('*' * (len(token) - 2)) + token[-1]


def soft_censor_text(text: str, pat: re.Pattern) -> Tuple[str, int]:
    matches = list(pat.finditer(text))
    out = text
    for m in reversed(matches):
        out = out[: m.start()] + _mask_preserving_separators(m.group(0)) + out[m.end():]
    return out, len(matches)


class ProfanityWatcher(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.echo_ttl = policy.getint("PROFANITY_ECHO_TTL_S", default=30)
        self.free_per_msg = policy.profanity_free_per_message()
        self.lvl1, self.lvl2, self.lvl3 = policy.profanity_thresholds()
        self.tout1, self.tout2, self.tout3 = policy.profanity_timeouts_minutes()
        self.per_user_throttle = throttling.PerUserChannelTTL(self.echo_ttl)
        self.audit_channel_id = policy.getint("CHANNEL_MOD_LOGS", default=0)
        self.words_cfg = textutil.load_profanity_words()
        self._compiled: List[Tuple[str, re.Pattern]] = []
        self._compile_patterns()

    async def log(self, guild, text):
        log.info(text)

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
                'r': '[r4]',
                't': '[t7]',
            }
            return m.get(ch.lower(), re.escape(ch))

        def build(word: str) -> re.Pattern:
            parts = []
            for ch in word:
                parts.append(f"{var(ch)}+")
            core = SEP.join(parts)
            pat = rf"(?V1)(?i)(?<!\p{{L}}){core}(?!\p{{L}})"
            return re.compile(pat, flags=re.DOTALL)

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
                    await message.channel.send(f"{message.author.mention} figyelj a szóhasználatra.")
            except Exception:
                log.exception("echo (owner/bot) failed")
            return

        if is_nsfw:
            await self.log(message.guild, f"NSFW profanity by {message.author} in {message.channel.mention}: {content}")
            return

        try:
            await message.delete()
        except Exception:
            log.debug("delete failed", exc_info=True)
        try:
            if self.per_user_throttle.allow(message.author.id, message.channel.id):
                await textutil.safe_echo(self.bot, message.channel, redacted, mimic_webhook=policy.getbool("USE_WEBHOOK_MIMIC", default=True), author=message.author)
                await message.channel.send(f"{message.author.mention} figyelj a szóhasználatra.")
        except Exception:
            log.exception("echo failed")

        bad_count = len(matches)
        free = max(0, self.free_per_msg)
        add_points = max(0, bad_count - free)
        if add_points > 0:
            total = await textutil.add_profanity_points(self.bot, message.author.id, add_points)
            if total >= self.lvl3:
                minutes = self.tout3
                await textutil.apply_timeout(self.bot, message.author, minutes, reason=f"Profanity L3 (total={total})")
            elif total >= self.lvl2:
                minutes = self.tout2
                await textutil.apply_timeout(self.bot, message.author, minutes, reason=f"Profanity L2 (total={total})")
            elif total >= self.lvl1:
                minutes = self.tout1
                await textutil.apply_timeout(self.bot, message.author, minutes, reason=f"Profanity L1 (total={total})")
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
            'r': '[r4]',
            't': '[t7]',
        }
        return m.get(ch.lower(), re.escape(ch))

    patterns = []
    for word in words:
        parts = [f"{var(ch)}+" for ch in word]
        patterns.append(SEP.join(parts))
    core = "|".join(patterns) or r"$^"
    boundary = rf"(?V1)(?i)(?<!\p{{L}})(?:{core})(?!\p{{L}})"
    return re.compile(boundary, flags=re.DOTALL)
