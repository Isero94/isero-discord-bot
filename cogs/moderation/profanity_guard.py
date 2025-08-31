# cogs/moderation/profanity_guard.py
from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Tuple, Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

# --- Káromkodás listák (bővíthető) ---
# Mindig kisbetűvel tároljuk, és case-insensitive keresést végzünk.
HU_BADWORDS = [
    "kurva", "kurvanyád", "kurvaanyád", "kúrva", "geci", "g*ci", "fasz", "f@sz",
    "picsa", "picsába", "picsafüst", "buzi", "buzik", "szar", "szarrá", "segg",
    "segghülye", "hülye", "anyád", "bazd", "bazmeg", "baszd", "baszod", "baszott",
    "csicska", "kretén", "idióta", "kibasz", "kibaszott", "faszfej", "pina", "p*na",
    "faszom", "anyádé", "k*va", "k*rva",
]

EN_BADWORDS = [
    "fuck", "fucking", "fuckin", "f*ck", "shit", "bullshit", "bitch", "asshole",
    "ass", "dick", "cunt", "motherfucker", "mf", "wtf", "stfu",
]

BADWORDS = sorted(set(HU_BADWORDS + EN_BADWORDS), key=len, reverse=True)

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _mask_word(w: str) -> str:
    """Csillagoz: első és utolsó karakter megmarad, közepe csillag.
    1-2 hossz esetén teljes csillagozás.
    """
    if len(w) <= 2:
        return "*" * len(w)
    return w[0] + "*" * (len(w) - 2) + w[-1]


def _censor_text(text: str) -> Tuple[str, int, List[str]]:
    """Visszaad: (cenzúrázott_szöveg, talált_káromkodás_db, talált_szavak)"""
    lowered = text.lower()
    found: List[str] = []
    out = text

    # token szintű csere: csak teljes szóegyezésre (word boundary)
    for bad in BADWORDS:
        # word boundary + case-insensitive
        pattern = re.compile(rf"\b{re.escape(bad)}\b", flags=re.IGNORECASE)
        if pattern.search(out):
            found.append(bad)
            def repl(m: re.Match) -> str:
                original = m.group(0)
                return _mask_word(original)
            out = pattern.sub(repl, out)

    return out, len(found), found


def _is_exempt(member: Optional[discord.Member]) -> bool:
    """Tulaj / Bot mentes a pontoktól, de csillagozás náluk is megy."""
    if member is None:
        return False
    if member.bot:
        return True
    if config.OWNER_ID and member.id == config.OWNER_ID:
        return True
    return False


class ProfanityGuard(commands.Cog):
    """Globális csillagozás + pontozás.

    - minden csatornán csillagoz (nincs kivétel),
    - tulaj + bot: NINCS pont, de csillagozás van,
    - többiek: 2 "ingyen" szó / üzenet; a fölötte levő mennyiség pontozódik.
    - webhookkal újraküldjük a cenzúrázott üzenetet (eredetit töröljük),
      ha a botnak van Manage Messages + Manage Webhooks joga.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.points: Dict[int, int] = {}  # user_id -> pont
        self.webhooks: Dict[int, discord.Webhook] = {}  # channel_id -> webhook cache

        # küszöbök a configból
        self.free_words = config.PROFANITY_FREE_WORDS
        self.stage1 = config.PROFANITY_STAGE1_POINTS      # pl. 5
        self.stage2 = config.PROFANITY_STAGE2_POINTS      # pl. 10
        self.stage3 = config.PROFANITY_STAGE3_POINTS      # pl. 20

        # log csatornák (opcionális, ha be vannak állítva)
        self.mod_logs_id = _int_or_none(getattr(config, "CHANNEL_MOD_LOGS", None))
        self.gen_logs_id = _int_or_none(getattr(config, "CHANNEL_GENERAL_LOGS", None))

    # ---------------------- belső segéd ----------------------

    async def _get_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Előszedi / létrehozza a csatorna webhookját a cenzúrázott újraküldéshez."""
        if channel.id in self.webhooks:
            return self.webhooks[channel.id]

        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            return None

        # megpróbálunk már meglévő, tőlünk létrehozott webhookot találni
        try:
            hooks = await channel.webhooks()
            for h in hooks:
                if h.user and h.user.id == self.bot.user.id:
                    self.webhooks[channel.id] = h
                    return h
            # ha nincs, csinálunk egyet
            hook = await channel.create_webhook(name="ISERO Guard")
            self.webhooks[channel.id] = hook
            return hook
        except Exception:
            return None

    async def _log(self, guild: discord.Guild, text: str) -> None:
        for cid in [self.mod_logs_id, self.gen_logs_id]:
            if cid:
                ch = guild.get_channel(cid)
                if isinstance(ch, discord.TextChannel):
                    try:
                        await ch.send(text)
                    except Exception:
                        pass

    def _add_points(self, user_id: int, added: int) -> int:
        cur = self.points.get(user_id, 0)
        cur += added
        self.points[user_id] = cur
        return cur

    # ---------------------- eventek ----------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # saját webhook üzeneteinket nem dolgozzuk fel
        if message.webhook_id is not None:
            return

        if not message.guild:
            return  # csak szerveren

        if message.author == self.bot.user:
            return  # a bot saját üzeneteihez nem nyúlunk (az agent már „tiszta” tartalmat küld)

        # cenzúrázás
        censored, hits, words = _censor_text(message.content)

        if hits == 0:
            return  # nincs teendő

        # csatorna + jogosultságok
        channel = message.channel
        if not isinstance(channel, discord.TextChannel):
            return

        # próbáljuk webhookkal újraküldeni
        # ha nincs jogunk, fallback: csak válaszban megmutatjuk a csillagozott másolatot
        used_webhook = False
        webhook = await self._get_webhook(channel)

        try:
            if channel.permissions_for(channel.guild.me).manage_messages and webhook:
                try:
                    await message.delete()
                except Exception:
                    pass

                username = message.author.display_name
                avatar = message.author.display_avatar
                await webhook.send(
                    content=censored,
                    username=username,
                    avatar_url=avatar.url if avatar else discord.Embed.Empty
                )
                used_webhook = True
            else:
                # fallback – nem ideális, de legalább azonnal látszik a csillagozott változat
                await channel.send(
                    f"**Cenzúrázott változat** ({message.author.mention}):\n{censored}"
                )
        except Exception:
            # ha bármi gond, akkor se dőljünk el
            pass

        # pontozás
        if not _is_exempt(message.author):
            over = max(0, hits - max(0, self.free_words))
            if over > 0:
                total = self._add_points(message.author.id, over)
                # szarkasztikus, száraz figyelmeztetés – nem „erkölcsi lecke”
                try:
                    await message.author.send(
                        f"**+{over} pont.** Jelenleg: **{total}**.\n"
                        f"Az első {self.free_words} még „ingyen”, utána számolunk. "
                        f"Vágd rövidebbre a szókimondást, különben a modok unalmasak lesznek."
                    )
                except Exception:
                    pass

                # küszöbök kezelése (log + opcionálisan timeout – itt csak logolunk)
                if total >= self.stage3:
                    await self._log(message.guild,
                        f"🚫 **Stage3**: {message.author} összesen {total} pont. "
                        f"Kézi feloldás javasolt. Utolsó szavak: {', '.join(set(words))}")
                elif total >= self.stage2:
                    await self._log(message.guild,
                        f"⚠️ **Stage2**: {message.author} {total} pontnál tart. "
                        f"Utolsó szavak: {', '.join(set(words))}")
                elif total >= self.stage1:
                    await self._log(message.guild,
                        f"ℹ️ **Stage1**: {message.author} {total} pontnál tart. "
                        f"Utolsó szavak: {', '.join(set(words))}")

    # ---------------------- slash parancsok ----------------------

    group = app_commands.Group(name="profanity", description="Profanity guard parancsok")

    @group.command(name="score", description="Pontszám lekérdezése")
    @app_commands.describe(member="Akinek a pontját kéred (üresen: te)")
    async def score(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        member = member or interaction.user
        total = self.points.get(member.id, 0)
        await interaction.response.send_message(
            f"{member.mention} jelenlegi pontja: **{total}**", ephemeral=True
        )

    @group.command(name="reset", description="Pontszám nullázása (admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reset(self, interaction: discord.Interaction, member: discord.Member):
        self.points.pop(member.id, None)
        await interaction.response.send_message(
            f"{member.mention} pontjai törölve.", ephemeral=True
        )

    @score.error
    @reset.error
    async def on_appcmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            await interaction.response.send_message(f"Hiba: {error}", ephemeral=True)
        except Exception:
            pass


def _int_or_none(x) -> Optional[int]:
    try:
        return int(x) if x is not None else None
    except Exception:
        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfanityGuard(bot))
    try:
        if config.GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=config.GUILD_ID))
        else:
            await bot.tree.sync()
    except Exception:
        pass
