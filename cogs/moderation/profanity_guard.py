import os
import re
import asyncio
from datetime import timedelta, datetime, timezone
from typing import Dict, List, Optional, Tuple

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

# ======= ENV =======
DATABASE_URL               = os.getenv("DATABASE_URL", "")
OWNER_ID                  = int(os.getenv("OWNER_ID", "0"))
STAFF_ROLE_ID             = int(os.getenv("STAFF_ROLE_ID", "0"))
STAFF_EXTRA_ROLE_IDS      = [int(x) for x in os.getenv("STAFF_EXTRA_ROLE_IDS", "").split(",") if x.strip().isdigit()]

CHANNEL_GENERAL_LOGS      = int(os.getenv("CHANNEL_GENERAL_LOGS", "0") or 0)
CHANNEL_MOD_LOGS          = int(os.getenv("CHANNEL_MOD_LOGS", "0") or 0)

PROFANITY_FREE_PER_MSG    = int(os.getenv("PROFANITY_FREE_WORDS_PER_MSG", "2") or 2)

# ÚJ küszöbök – a kérés szerint: L1=5, L2=8, L3=11
PROF_L1_THRESHOLD         = int(os.getenv("PROFANITY_LVL1_THRESHOLD", "5") or 5)
PROF_L2_THRESHOLD         = int(os.getenv("PROFANITY_LVL2_THRESHOLD", "8") or 8)
PROF_L3_THRESHOLD         = int(os.getenv("PROFANITY_LVL3_THRESHOLD", "11") or 11)

# L2: 40 perc timeout | L3: 0 => manuális feloldásig (Muted role)
PROF_TIMEOUT_L2_MIN       = int(os.getenv("PROFANITY_TIMEOUT_MIN_LVL2", "40") or 40)
PROF_TIMEOUT_L3_MIN       = int(os.getenv("PROFANITY_TIMEOUT_MIN_LVL3", "0") or 0)

USE_WEBHOOK_MIMIC         = os.getenv("USE_WEBHOOK_MIMIC", "true").lower() == "true"

# PROFANITY_WORDS: vesszővel elválasztott lista ENV-ben.
# Ha üres, itt egy default baseline lista (HU+EN, szándékosan nem teljes).
DEFAULT_WORDS = [
    # HU
    "kurva","kurvázik","geci","fasz","faszom","picsa","pina","anyád","buzi","bazdmeg","szar","kibaszott",
    "csicska","kúr","k*rva","f@sz","f*sz","faszfej","segg","seggfej","szopd",
    # EN
    "fuck","fucking","fucked","shit","bitch","dick","asshole","ass","bastard","cunt","pussy","jerk","bullshit",
]
PROFANITY_WORDS           = [w.strip().lower() for w in (os.getenv("PROFANITY_WORDS", "") or "").split(",") if w.strip()] or DEFAULT_WORDS

# ======= UTIL =======

def _charclass(c: str) -> str:
    """Leetspeak/ékezet variációkhoz karakterosztály."""
    mapping = {
        "a": "[aá4@]",
        "e": "[eé3]",
        "i": "[ií1!]",
        "o": "[oóöő0]",
        "u": "[uúüű]",
        "s": "[s$5]",
        "c": "[c(]",
        "z": "[z2]",
        "g": "[g69]",
        "b": "[b68]",
        "t": "[t7+]",
        "k": "[k]+",
        "r": "[r]+",
        "f": "[f]+",
        "n": "[n]+",
        "y": "[y]+",
        "d": "[d]+",
        "l": "[l1]+",
        "h": "[h]+",
        "p": "[p]+",
        "m": "[m]+",
        "v": "[v]+",
        "x": "[x]+",
        # egyéb betűk: maguk
    }
    base = c.lower()
    return mapping.get(base, re.escape(c))

def build_word_pattern(word: str) -> str:
    # közé rakott pont, szóköz, aláhúzás, kötőjel stb. megengedése
    sep = r"[\W_]*"
    parts = [ _charclass(ch) for ch in word ]
    return r"\b" + sep.join(parts) + r"\b"

def compile_profanity_regex(words: List[str]) -> re.Pattern:
    alts = [build_word_pattern(w) for w in words if w]
    pattern = "(" + "|".join(alts) + ")"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)

PROF_RE = compile_profanity_regex(PROFANITY_WORDS)

def mask_word(w: str) -> str:
    # első és utolsó betűt meghagyjuk, a többi * – min. 1 csillag
    s = re.sub(r"^\W+|\W+$", "", w)  # a szélek jeleit levesszük maszkoláshoz
    if len(s) <= 2:
        masked = "*" * max(1, len(s))
    else:
        masked = s[0] + ("*" * (len(s)-2)) + s[-1]
    # a környező jeleket visszaragasztjuk
    prefix = w[:len(w)-len(w.lstrip())]
    suffix = w[len(w.rstrip()):]
    return prefix + masked + suffix

def mask_content(text: str) -> Tuple[str, int]:
    """Visszaadja a maszkolt szöveget és a találatok számát."""
    matches = list(PROF_RE.finditer(text))
    if not matches:
        return text, 0

    # darabolás helyett a találati szeletekből építjük újra
    result = []
    last = 0
    for m in matches:
        result.append(text[last:m.start()])
        result.append(mask_word(m.group(0)))
        last = m.end()
    result.append(text[last:])
    return "".join(result), len(matches)

def allowed_mentions_none() -> discord.AllowedMentions:
    return discord.AllowedMentions(roles=False, users=False, everyone=False)

async def ensure_pool() -> Optional[asyncpg.Pool]:
    if not DATABASE_URL:
        return None
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS profanity_strikes (
            guild_id BIGINT NOT NULL,
            user_id  BIGINT NOT NULL,
            points   INTEGER NOT NULL DEFAULT 0,
            level    SMALLINT NOT NULL DEFAULT 0,
            manual_mute BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (guild_id, user_id)
        );
        """)
    return pool

async def get_row(pool: asyncpg.Pool, guild_id: int, user_id: int) -> asyncpg.Record:
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT points, level, manual_mute FROM profanity_strikes WHERE guild_id=$1 AND user_id=$2",
            guild_id, user_id
        )
        if row is None:
            await con.execute(
                "INSERT INTO profanity_strikes (guild_id,user_id,points,level,manual_mute) VALUES ($1,$2,0,0,FALSE)",
                guild_id, user_id
            )
            return asyncpg.Record(points=0, level=0, manual_mute=False)
        return row

async def add_points_and_get_level(pool: asyncpg.Pool, guild_id: int, user_id: int, add_pts: int) -> Tuple[int,int,bool]:
    """Visszaadja (points, level, manual_mute)."""
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT points, level, manual_mute FROM profanity_strikes WHERE guild_id=$1 AND user_id=$2",
            guild_id, user_id
        )
        if row is None:
            points = add_pts
            level = 0
            manual = False
            await con.execute(
                "INSERT INTO profanity_strikes (guild_id,user_id,points,level,manual_mute) VALUES ($1,$2,$3,$4,$5)",
                guild_id, user_id, points, level, manual
            )
        else:
            points = row["points"] + add_pts
            level = row["level"]
            manual = row["manual_mute"]

            # szint meghatározás az új pontszám alapján
            new_level = level
            if points >= PROF_L3_THRESHOLD:
                new_level = 3
            elif points >= PROF_L2_THRESHOLD:
                new_level = 2
            elif points >= PROF_L1_THRESHOLD:
                new_level = 1

            if new_level != level:
                level = new_level

            await con.execute(
                "UPDATE profanity_strikes SET points=$3, level=$4 WHERE guild_id=$1 AND user_id=$2",
                guild_id, user_id, points, level
            )
    return points, level, manual

async def set_manual_mute(pool: asyncpg.Pool, guild_id: int, user_id: int, manual: bool):
    async with pool.acquire() as con:
        await con.execute(
            "UPDATE profanity_strikes SET manual_mute=$3 WHERE guild_id=$1 AND user_id=$2",
            guild_id, user_id, manual
        )

async def reset_user(pool: asyncpg.Pool, guild_id: int, user_id: int):
    async with pool.acquire() as con:
        await con.execute(
            "UPDATE profanity_strikes SET points=0, level=0, manual_mute=FALSE WHERE guild_id=$1 AND user_id=$2",
            guild_id, user_id
        )

async def send_log(guild: discord.Guild, channel_id: int, embed: discord.Embed):
    if not channel_id:
        return
    ch = guild.get_channel(channel_id)
    if ch:
        try:
            await ch.send(embed=embed)
        except Exception:
            pass

async def ensure_muted_role(guild: discord.Guild) -> discord.Role:
    name = "Muted"
    for r in guild.roles:
        if r.name == name:
            return r
    # létrehozzuk
    muted = await guild.create_role(name=name, reason="Profanity L3 – feloldásig némítás")
    # végigmegyünk a csatornákon és tiltjuk az írást/beszédet
    perms_text = discord.PermissionOverwrite(send_messages=False, add_reactions=False, create_public_threads=False, create_private_threads=False)
    perms_voice = discord.PermissionOverwrite(connect=False, speak=False, stream=False)
    for ch in guild.channels:
        try:
            if isinstance(ch, discord.TextChannel) or isinstance(ch, discord.Thread):
                await ch.set_permissions(muted, overwrite=perms_text)
            elif isinstance(ch, discord.VoiceChannel) or isinstance(ch, discord.StageChannel):
                await ch.set_permissions(muted, overwrite=perms_voice)
        except Exception:
            continue
    return muted

class ProfanityGuard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: Optional[asyncpg.Pool] = None
        self._webhook_cache: Dict[int, discord.Webhook] = {}

    async def cog_load(self) -> None:
        if DATABASE_URL:
            self.pool = await ensure_pool()

    # ===== Helpers =====

    def is_staff(self, member: discord.Member) -> bool:
        if member.guild.owner_id == member.id:  # szerver tulaj
            return True
        if OWNER_ID and member.id == OWNER_ID:
            return True
        role_ids = {r.id for r in member.roles}
        if STAFF_ROLE_ID and STAFF_ROLE_ID in role_ids:
            return True
        for x in STAFF_EXTRA_ROLE_IDS:
            if x in role_ids:
                return True
        return False

    async def _get_or_create_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        if not USE_WEBHOOK_MIMIC:
            return None
        wh = self._webhook_cache.get(channel.id)
        if wh:
            return wh
        try:
            hooks = await channel.webhooks()
            for h in hooks:
                if h.name == "ISERO_MIMIC":
                    self._webhook_cache[channel.id] = h
                    return h
            wh = await channel.create_webhook(name="ISERO_MIMIC", reason="Profanity mimic")
            self._webhook_cache[channel.id] = wh
            return wh
        except Exception:
            return None

    async def _repost_masked(self, message: discord.Message, masked: str):
        """Eredeti törlése, maszkolt újraküldése webhookkal (ha lehet)."""
        # attachment-ek átvitele
        files = []
        try:
            for a in message.attachments:
                files.append(await a.to_file())
        except Exception:
            files = []

        wh = None
        if isinstance(message.channel, discord.TextChannel):
            wh = await self._get_or_create_webhook(message.channel)

        try:
            await message.delete()
        except Exception:
            # ha nem tudjuk törölni, legalább reagáljunk
            await message.channel.send(masked, allowed_mentions=allowed_mentions_none())
            return

        if wh:
            await wh.send(
                content=masked,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url if message.author.display_avatar else discord.Embed.Empty,
                files=files,
                allowed_mentions=allowed_mentions_none(),
            )
        else:
            await message.channel.send(masked, files=files, allowed_mentions=allowed_mentions_none())

    # ===== Event =====

    @commands.Cog.listener("on_message")
    async def guard(self, message: discord.Message):
        # alap szűrés
        if not message.guild or not message.content:
            return
        if message.author.bot:
            # bot üzenetet is csillagozunk? A kérés szerint Iseró is – de bot üzenetet ritkán illik átírni.
            # Hogy biztonságos legyen, a botoknál csak mérünk, nem törlünk/posztolunk újra.
            return

        # tartalom maszkolása
        masked, hits = mask_content(message.content)
        if hits == 0 and not any(PROF_RE.search(a.filename) for a in message.attachments):
            return  # nincs teendő

        # Mindenkinél csillagozás (téged és a botot is) -> üzenet törlés + maszkolt újraposzt
        if masked != message.content or hits > 0:
            await self._repost_masked(message, masked)

        # Büntetés csak NEM staff felhasználónál
        if self.is_staff(message.author):
            return

        # pontszámítás: csak a FREE feletti kerül pontozásba
        extra = max(0, hits - PROFANITY_FREE_PER_MSG)
        if extra == 0 or not self.pool:
            return

        points, level, _ = await add_points_and_get_level(self.pool, message.guild.id, message.author.id, extra)

        # Akciók
        emb = discord.Embed(
            title="Profanity",
            description=f"{message.author.mention} +{extra} pont (összesen: **{points}**). Szint: **L{level}**",
            color=discord.Color.orange(),
        )
        emb.timestamp = discord.utils.utcnow()
        emb.add_field(name="Üzenet csatorna", value=message.channel.mention, inline=True)
        await send_log(message.guild, CHANNEL_GENERAL_LOGS or CHANNEL_MOD_LOGS, emb)

        if level == 1:
            # figyelmeztetés
            try:
                await message.channel.send(
                    f"{message.author.mention} Figyu. A trágár szavakat csillagozzuk, "
                    f"de a túlzásért pont jár. Most: **{points}**. L1 megvan.",
                    allowed_mentions=allowed_mentions_none()
                )
            except Exception:
                pass

        elif level == 2:
            # Timeout (kommunikáció tiltása) 40 perc
            try:
                until = datetime.now(timezone.utc) + timedelta(minutes=PROF_TIMEOUT_L2_MIN)
                await message.author.timeout(until, reason="Profanity L2")
            except Exception:
                pass

            e2 = discord.Embed(
                title="Profanity L2",
                description=f"{message.author} {PROF_TIMEOUT_L2_MIN} perces timeoutra került.",
                color=discord.Color.red()
            )
            await send_log(message.guild, CHANNEL_MOD_LOGS or CHANNEL_GENERAL_LOGS, e2)

        elif level >= 3:
            # Feloldásig némítás
            if PROF_TIMEOUT_L3_MIN > 0:
                try:
                    until = datetime.now(timezone.utc) + timedelta(minutes=PROF_TIMEOUT_L3_MIN)
                    await message.author.timeout(until, reason="Profanity L3")
                except Exception:
                    pass
            else:
                try:
                    muted = await ensure_muted_role(message.guild)
                    await message.author.add_roles(muted, reason="Profanity L3 – feloldásig némítás")
                    if self.pool:
                        await set_manual_mute(self.pool, message.guild.id, message.author.id, True)
                except Exception:
                    pass

            e3 = discord.Embed(
                title="Profanity L3",
                description=f"{message.author} feloldásig némítva.",
                color=discord.Color.dark_red()
            )
            await send_log(message.guild, CHANNEL_MOD_LOGS or CHANNEL_GENERAL_LOGS, e3)

    # ===== Slash parancsok (admin/staff) =====

    profanity = app_commands.Group(name="profanity", description="Profanity guard admin")

    @profanity.command(name="status", description="Egy tag pontjai/szintje")
    @app_commands.describe(user="Tag")
    async def status(self, interaction: discord.Interaction, user: discord.Member):
        if not self.pool:
            await interaction.response.send_message("Nincs adatbázis beállítva.", ephemeral=True)
            return
        row = await get_row(self.pool, interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"{user.mention}: pontok **{row['points']}**, szint **L{row['level']}**, manuális némítás: **{bool(row['manual_mute'])}**",
            ephemeral=True
        )

    @profanity.command(name="reset", description="Pontok és szint nullázása + némítás feloldása")
    @app_commands.describe(user="Tag")
    async def reset_cmd(self, interaction: discord.Interaction, user: discord.Member):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("Nincs jogod.", ephemeral=True)
            return
        if self.pool:
            await reset_user(self.pool, interaction.guild.id, user.id)
        # timeout & role levétele
        try:
            await user.timeout(None, reason="Profanity reset")
        except Exception:
            pass
        try:
            muted = discord.utils.get(interaction.guild.roles, name="Muted")
            if muted and muted in user.roles:
                await user.remove_roles(muted, reason="Profanity reset")
        except Exception:
            pass

        await interaction.response.send_message(f"{user.mention} lenullázva és feloldva.", ephemeral=True)

    @profanity.command(name="preview", description="Maszkolás előnézet (staff)")
    @app_commands.describe(text="Szöveg")
    async def preview(self, interaction: discord.Interaction, text: str):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("Nincs jogod.", ephemeral=True)
            return
        masked, hits = mask_content(text)
        await interaction.response.send_message(
            f"Maszkolt ({hits} találat):\n```\n{masked}\n```", ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
