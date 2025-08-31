import os
import re
import asyncio
import datetime as dt
from typing import Dict, List

import discord
from discord import app_commands
from discord.ext import commands


def _csv_ints(name: str) -> List[int]:
    raw = os.getenv(name, "") or ""
    out = []
    for part in raw.split(","):
        s = part.strip()
        if s.isdigit():
            out.append(int(s))
    return out

def _csv_strs(name: str) -> List[str]:
    raw = os.getenv(name, "") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def _build_regex_piece(word: str) -> str:
    """
    A profanity listában a '*' jokerként szerepelhet a szóban lévő
    nem-betű karakterekre. Példa: 'k*rva' illeszkedik 'k*rva', 'k.rva', 'k rva' stb.
    """
    pieces = []
    for ch in word:
        if ch == "*":
            pieces.append(r"[\W_]*?")
        else:
            pieces.append(re.escape(ch))
    core = "".join(pieces)
    # szóhatár-érzékeny, case-insensitive
    return rf"(?<!\w){core}(?!\w)"


def _star_out(match: re.Match) -> str:
    token = match.group(0)
    # tartsuk meg az első és utolsó alfanumerikus karaktert, a többit csillag
    letters = [c for c in token if c.isalnum()]
    if len(letters) <= 2:
        return "*" * len(token)

    # maszk: első+utolsó betű marad, közte csillagok, a nem-betű karaktereket hagyjuk ott ahol voltak
    res = []
    idx_letter = 0
    first_kept = letters[0]
    last_kept = letters[-1]
    stars_to_use = max(0, len(letters) - 2)

    # felépítjük a maszkot betűnként
    placed_first = False
    placed_stars = 0
    for c in token:
        if c.isalnum():
            if not placed_first:
                res.append(first_kept)
                placed_first = True
            elif placed_stars < stars_to_use:
                res.append("*")
                placed_stars += 1
            else:
                res.append(last_kept)
        else:
            res.append(c)
    return "".join(res)


class ProfanityGuard(commands.Cog):
    """Cenzúra + pontozás + timeout/mute."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # --- Env
        self.owner_id = int(os.getenv("OWNER_ID", "0"))
        self.staff_role_id = int(os.getenv("STAFF_ROLE_ID", "0"))
        self.staff_extra_roles = _csv_ints("STAFF_EXTRA_ROLE_IDS")

        self.allow_staff_freespeech = (os.getenv("ALLOW_STAFF_FREESPEECH", "false").lower() == "true")

        self.free_words_per_msg = int(os.getenv("PROFANITY_FREE_WORDS_PER_MSG", "2"))
        self.lvl1_threshold = int(os.getenv("PROFANITY_LVL1_THRESHOLD", "5"))
        self.lvl2_threshold = int(os.getenv("PROFANITY_LVL2_THRESHOLD", "8"))
        self.lvl3_threshold = int(os.getenv("PROFANITY_LVL3_THRESHOLD", "11"))

        self.timeout_lvl2_min = int(os.getenv("PROFANITY_TIMEOUT_MIN_LVL2", "40"))
        self.timeout_lvl3_min = int(os.getenv("PROFANITY_TIMEOUT_MIN_LVL3", "0"))  # 0 => végleges (Muted szerep)

        self.mute_role_id = int(os.getenv("MUTE_ROLE_ID", "0"))  # új env!

        self.mod_logs_id = int(os.getenv("CHANNEL_MOD_LOGS", "0"))
        self.general_logs_id = int(os.getenv("CHANNEL_GENERAL_LOGS", "0"))

        self.use_webhook_mimic = (os.getenv("USE_WEBHOOK_MIMIC", "true").lower() == "true")

        # Szavak + regexek
        words = _csv_strs("PROFANITY_WORDS")
        self.patterns = [re.compile(_build_regex_piece(w), re.IGNORECASE) for w in words]

        # Egyszerű ponttábla memóriában (user_id -> pont)
        self.points: Dict[int, int] = {}

    # ---------- Helpers

    def _is_staff(self, member: discord.Member) -> bool:
        if member.guild.owner_id == member.id or member.id == self.owner_id:
            return True
        role_ids = {r.id for r in member.roles}
        if self.staff_role_id and self.staff_role_id in role_ids:
            return True
        if any(rid in role_ids for rid in self.staff_extra_roles):
            return True
        return False

    async def _get_webhook(self, channel: discord.TextChannel) -> discord.Webhook | None:
        try:
            hooks = await channel.webhooks()
            for h in hooks:
                if h.name == "ISERO Censor":
                    return h
            return await channel.create_webhook(name="ISERO Censor", reason="Censor webhook")
        except discord.Forbidden:
            return None

    def _censor_and_count(self, content: str) -> tuple[str, int]:
        hits = 0
        censored = content
        for pat in self.patterns:
            # count találatok
            for _ in pat.finditer(censored):
                hits += 1
            # csillagozás
            censored = pat.sub(_star_out, censored)
        return censored, hits

    async def _log(self, guild: discord.Guild, text: str):
        if self.mod_logs_id:
            ch = guild.get_channel(self.mod_logs_id)
            if isinstance(ch, discord.TextChannel):
                await ch.send(text)

    async def _timeout_member(self, member: discord.Member, minutes: int, reason: str):
        try:
            until = discord.utils.utcnow() + dt.timedelta(minutes=minutes)
            await member.timeout(until, reason=reason)
        except discord.Forbidden:
            pass

    async def _mute_member_forever(self, member: discord.Member, reason: str):
        if not self.mute_role_id:
            # ha nincs megadva mute szerep, fallback egy hosszú timeoutjára (28 nap a max)
            await self._timeout_member(member, 28 * 24 * 60, reason)
            return
        role = member.guild.get_role(self.mute_role_id)
        if role:
            try:
                await member.add_roles(role, reason=reason)
            except discord.Forbidden:
                pass

    # ---------- Events

    @commands.Cog.listener("on_message")
    async def guard_message(self, message: discord.Message):
        # ne fussunk DM-ben vagy webhook-üzeneten
        if not message.guild or message.webhook_id:
            return

        # saját üzenet: csak szerkesztünk (nincs törlés-webhook)
        if message.author == self.bot.user:
            new, hits = self._censor_and_count(message.content)
            if hits > 0 and new != message.content:
                try:
                    await message.edit(content=new)
                except discord.Forbidden:
                    pass
            return

        # ha nincs tartalom, kilépünk
        if not message.content:
            return

        censored, hits = self._censor_and_count(message.content)
        if hits == 0:
            return

        member: discord.Member = message.author  # type: ignore
        guild = message.guild

        # --- Cenzúra megjelenítése a csatornában
        if self.use_webhook_mimic and isinstance(message.channel, discord.TextChannel):
            wh = await self._get_webhook(message.channel)
            if wh:
                try:
                    await wh.send(
                        content=censored,
                        username=member.display_name,
                        avatar_url=member.display_avatar.with_size(128).url if member.display_avatar else None,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    await message.delete()
                except discord.Forbidden:
                    # ha nincs jog törölni, legalább reagáljunk
                    pass

        # --- Pontszámítás
        add_points = max(0, hits - self.free_words_per_msg)

        is_staff = self._is_staff(member)
        exempt_from_punish = (is_staff and self.allow_staff_freespeech) or member.bot

        if add_points > 0 and not exempt_from_punish:
            total = self.points.get(member.id, 0) + add_points
            self.points[member.id] = total

            await self._log(guild, f"⚠️ **{member}** kapott **{add_points}** pontot (össz: {total}) a trágárságért.")

            # Szintek
            if total >= self.lvl3_threshold:
                # LVL3 – végleges mute (ha 0 perc a lvl3 env)
                if self.timeout_lvl3_min <= 0:
                    await self._mute_member_forever(member, reason="Profanity Level 3 – manual unmute required")
                    await self._log(guild, f"⛔ **{member}** LVL3 – végleges némítás (Muted szerep). Feloldás kézzel /unmute.")
                else:
                    await self._timeout_member(member, self.timeout_lvl3_min, "Profanity Level 3")
                    await self._log(guild, f"⛔ **{member}** LVL3 – timeout {self.timeout_lvl3_min} perc.")
            elif total >= self.lvl2_threshold:
                await self._timeout_member(member, self.timeout_lvl2_min, "Profanity Level 2")
                await self._log(guild, f"🚫 **{member}** LVL2 – timeout {self.timeout_lvl2_min} perc.")
            elif total >= self.lvl1_threshold:
                await self._log(guild, f"⚠️ **{member}** LVL1 – figyelmeztetés.")

    # ---------- Commands

    @app_commands.command(name="unmute", description="Feloldja a végleges némítást (PG LVL3).")
    @app_commands.describe(user="Kit oldjunk fel?")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.manage_channels and not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message("Nincs jogod ehhez.", ephemeral=True)

        removed = False
        if self.mute_role_id:
            role = interaction.guild.get_role(self.mute_role_id) if interaction.guild else None
            if role and role in user.roles:
                try:
                    await user.remove_roles(role, reason="Manual unmute")
                    removed = True
                except discord.Forbidden:
                    pass

        try:
            await user.timeout(None, reason="Manual unmute")
            removed = True
        except discord.Forbidden:
            pass

        if removed:
            await interaction.response.send_message(f"Feloldva: {user.mention}", ephemeral=True)
            if interaction.guild:
                await self._log(interaction.guild, f"✅ **{user}** unmute (kézi).")
        else:
            await interaction.response.send_message("Nem sikerült feloldani (hiányzó jog?).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
