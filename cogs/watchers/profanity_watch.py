# cogs/moderation/profanity_guard.py
from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Pattern

import yaml

import discord
from discord.ext import commands
from bot.config import settings
from cogs.utils.throttling import should_redirect

STORAGE = Path("storage")
STORAGE.mkdir(exist_ok=True, parents=True)
SCORES_FILE = STORAGE / "profanity_scores.json"

# YAML alap szókészlet
PROF_YAML = Path("config/profanity.yml")
DEFAULT_WORDS = [
    "kurva",
    "geci",
    "fasz",
    "picsa",
    "buzi",
    "köcsög",
    "szar",
    "anyád",
    "fuck",
    "shit",
    "bitch",
    "dick",
    "asshole",
    "cunt",
]

def load_scores() -> Dict[str, int]:
    if SCORES_FILE.exists():
        try:
            return json.loads(SCORES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_scores(data: Dict[str, int]) -> None:
    try:
        SCORES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)).strip())
    except Exception:
        return default

CHAR_ALTS = {
    "a": ["a", "á", "4", "@"],
    "e": ["e", "é", "3"],
    "i": ["i", "í", "1", "!", "l"],
    "o": ["o", "ó", "ö", "ő", "0"],
    "u": ["u", "ú", "ü", "ű"],
    "c": ["c", "k", "ch"],
    "g": ["g", "9", "q"],
    "s": ["s", "$", "5"],
    "r": ["r", "4"],
    "t": ["t", "7"],
}


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")


def _word_to_pattern(word: str) -> str:
    word = _strip_diacritics(word.lower())
    parts: List[str] = []
    for ch in word:
        alts = CHAR_ALTS.get(ch, [ch])
        # region ISERO PATCH PROFANITY_V2
        # Bővítés: karakternyújtás támogatása (pl. "kuuurva") +? kvantorral
        group = "(?:" + "|".join(re.escape(a) for a in alts) + ")+?"
        parts.append(group)
    # region ISERO PATCH PROFANITY_V2
    # Bővítés: c|ch alternáció már CHAR_ALTS-ban, separator szélesítése + DOTALL
    # Régi [\s\W_] nem engedte a számjegyeket; most bármely nem-betűt elfogadunk
    joiner = r"(?:[^A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{0,2})"
    # endregion ISERO PATCH PROFANITY_V2
    return joiner.join(parts)


def build_tolerant_pattern(words: List[str]) -> Pattern:
    """Build regex pattern tolerant to leetspeak, spacing and diacritics."""
    patterns = [_word_to_pattern(w.strip()) for w in words if w.strip()]
    if not patterns:
        patterns = [_word_to_pattern(w) for w in DEFAULT_WORDS]
    core = "|".join(patterns)
    # region ISERO PATCH PROFANITY_V2
    # Szóhatár-óvatosítás + DOTALL + IGNORECASE
    boundary = rf"(?<![A-Za-zÁÉÍÓÖŐÚÜŰ0-9])(?:{core})(?![A-Za-zÁÉÍÓÖŐÚÜŰ0-9])"
    return re.compile(boundary, re.IGNORECASE | re.DOTALL)
    # endregion ISERO PATCH PROFANITY_V2

def censor_token(token: str) -> str:
    if len(token) <= 2:
        return "*" * len(token)
    return token[0] + ("*" * (len(token) - 2)) + token[-1]

def soft_censor_text(text: str, pat: re.Pattern) -> (str, int):
    """Csillagozza a trágár tokeneket, visszaadja az előfordulások számát."""
    matches = list(pat.finditer(text))
    if not matches:
        return text, 0

    # tokenenként cserél
    result = []
    last = 0
    for m in matches:
        result.append(text[last:m.start()])
        result.append(censor_token(m.group(0)))
        last = m.end()
    result.append(text[last:])
    return "".join(result), len(matches)


class ProfanityGuard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scores: Dict[str, int] = load_scores()
        path = Path(os.getenv("PROFANITY_CONFIG_PATH", "config/profanity.yml"))
        words_env = os.getenv("PROFANITY_WORDS", "")
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                words = data.get("words", DEFAULT_WORDS)
                self.source = f"yaml:{path}"
            except Exception:
                words = DEFAULT_WORDS
                self.source = "default"
        elif words_env.strip():
            words = [w.strip() for w in words_env.split(",")]
            self.source = "env"
        else:
            words = DEFAULT_WORDS
            self.source = "default"
        self.word_pat = build_tolerant_pattern(words)

        self.free_per_msg = get_env_int("PROFANITY_FREE_WORDS_PER_MSG", 0)
        self.lvl1 = get_env_int("PROFANITY_LVL1_THRESHOLD", 3)
        self.lvl2 = get_env_int("PROFANITY_LVL2_THRESHOLD", 5)
        self.lvl3 = get_env_int("PROFANITY_LVL3_THRESHOLD", 8)
        self.to_min_l2 = get_env_int("PROFANITY_TIMEOUT_MIN_LVL2", 10)
        self.to_min_l3 = get_env_int("PROFANITY_TIMEOUT_MIN_LVL3", 60)

        self.allow_staff_freespeech = os.getenv("ALLOW_STAFF_FREESPEECH", "false").lower() == "true"
        self.owner_id = int(os.getenv("OWNER_ID", "0") or "0")
        self.use_webhook = os.getenv("USE_WEBHOOK_MIMIC", "true").lower() == "true"

        self.log_ch_id = int(os.getenv("CHANNEL_MOD_LOGS", "0") or "0")
        self._webhooks: Dict[int, discord.Webhook] = {}

    # ---------- belső segédek ----------

    def _score_key(self, guild_id: int, user_id: int) -> str:
        return f"{guild_id}:{user_id}"

    def add_points(self, guild_id: int, user_id: int, points: int) -> int:
        key = self._score_key(guild_id, user_id)
        cur = self.scores.get(key, 0) + points
        self.scores[key] = cur
        save_scores(self.scores)
        return cur

    async def get_or_create_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        if not self.use_webhook:
            return None
        if channel.id in self._webhooks and self._webhooks[channel.id].token:
            return self._webhooks[channel.id]
        try:
            hooks = await channel.webhooks()
            hook = next((h for h in hooks if h.name == "ISERO Relay"), None)
            if hook is None:
                hook = await channel.create_webhook(name="ISERO Relay", reason="Profanity relay")
            self._webhooks[channel.id] = hook
            return hook
        except Exception:
            return None

    def exempt_from_punish(self, member: discord.Member) -> bool:
        # te + bot + staff -> NINCS pont (de csillagozás marad, ha ALLOW_STAFF_FREESPEECH=false)
        if member.bot:
            return True
        if self.owner_id and member.id == self.owner_id:
            return True
        if member.guild_permissions.manage_guild or member.top_role.permissions.manage_guild:
            return True
        return False

    async def log(self, guild: discord.Guild, text: str, *, embed: Optional[discord.Embed] = None):
        if not self.log_ch_id:
            return
        ch = guild.get_channel(self.log_ch_id)
        if ch:
            try:
                await ch.send(text, embed=embed)
            except Exception:
                pass

    # ---------- esemény ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # saját, DM, botok kimaradnak
        if not message.guild or message.author.bot:
            return

        # a botnak kell 'Manage Messages'
        me: discord.Member = message.guild.me  # type: ignore
        if not me.guild_permissions.manage_messages:
            return

        original = message.content or ""
        censored, count = soft_censor_text(original, self.word_pat)
        if count == 0:
            return  # nincs mit tenni

        is_nsfw_ch = getattr(message.channel, "is_nsfw", lambda: False)() or (
            message.channel.id in settings.nsfw_channels
        )
        if is_nsfw_ch:
            await self.log(
                message.guild,
                f"📝 NSFW profanity by {message.author} in {message.channel.mention}: {original}\n{message.jump_url}",
            )
            return

        # üzenet törlése + repost csillagozva
        try:
            await message.delete()
        except Exception:
            try:
                await message.channel.send(f"{message.author.mention} {censored}")
            finally:
                return

        do_echo = True
        key = f"echo:{message.guild.id}:{message.channel.id}:{message.author.id}"
        do_echo = should_redirect(key, ttl=30)

        if do_echo:
            try:
                hook = await self.get_or_create_webhook(message.channel)  # type: ignore
                files = []
                for a in message.attachments:
                    try:
                        fp = await a.to_file()
                        files.append(fp)
                    except Exception:
                        pass

                content_to_send = censored
                if hook:
                    await hook.send(
                        content=content_to_send,
                        username=message.author.display_name,
                        avatar_url=message.author.display_avatar.url,
                        allowed_mentions=discord.AllowedMentions.none(),
                        files=files or None,
                    )
                else:
                    await message.channel.send(
                        f"**{message.author.display_name}:** {content_to_send}",
                        allowed_mentions=discord.AllowedMentions.none(),
                        files=files or None,
                    )
                await message.channel.send(
                    f"{message.author.mention} figyelj a szóhasználatra.",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                    delete_after=10,
                )
            except Exception:
                pass

        await self.log(
            message.guild,
            f"⚠️ Profanity by {message.author} in {message.channel.mention}: {original}\n{message.jump_url}",
        )

        # pontozás (INGYENES keret levonása)
        effective = max(0, count - self.free_per_msg)

        member: discord.Member = message.author  # type: ignore
        exempt = self.exempt_from_punish(member)

        # ha staff free speech engedélyezve, teljesen kihagyjuk (se csillag, se pont) – de te ezt FALSE-ra állítod
        if self.allow_staff_freespeech and exempt:
            return

        # te és staff: NINCS pont, csak csillag
        if exempt:
            await self.log(
                message.guild,
                f"ℹ️ Csillagozva (staff/owner kivétel): {member} in #{message.channel} — {count} találat."
            )
            return

        if effective <= 0:
            await self.log(
                message.guild,
                f"ℹ️ Csillagozva (ingyenkeret): {member} in #{message.channel} — {count} találat."
            )
            return

        total = self.add_points(message.guild.id, member.id, effective)

        # szintek
        lvl = 0
        if effective >= self.lvl3 or total >= self.lvl3:
            lvl = 3
        elif effective >= self.lvl2 or total >= self.lvl2:
            lvl = 2
        elif effective >= self.lvl1 or total >= self.lvl1:
            lvl = 1

        # akciók
        note = f"🔹 {member.mention} kapott **+{effective}** pontot (össz: **{total}**)."
        if lvl == 1:
            warn = f"⚠️ **Figyelmeztetés (1. szint)**: visszafogottabban."
            await self.log(message.guild, f"{note} {warn}")
        elif lvl == 2:
            minutes = max(1, self.to_min_l2)
            try:
                await member.timeout(timedelta(minutes=minutes), reason="Profanity L2")
                await self.log(message.guild, f"{note} ⛔ **Timeout {minutes} perc (2. szint)**")
            except Exception:
                await self.log(message.guild, f"{note} (2. szint) — timeout sikertelen, nincs jog?")
        elif lvl == 3:
            minutes = max(1, self.to_min_l3)
            try:
                await member.timeout(timedelta(minutes=minutes), reason="Profanity L3")
                await self.log(message.guild, f"{note} ⛔ **Timeout {minutes} perc (3. szint)**")
            except Exception:
                await self.log(message.guild, f"{note} (3. szint) — timeout sikertelen, nincs jog?")
        else:
            await self.log(message.guild, note)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
