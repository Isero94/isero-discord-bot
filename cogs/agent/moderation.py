import re
import asyncio
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Set

import discord

from .filters import count_profanity

@dataclass
class UserState:
    points: int = 0              # “bónusz 1” pontok (3+ csúnya/üzenet = 1 pont)
    last_reset: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeouts: int = 0            # eddigi timeout lépcsők

class AutoMod:
    """
    Káromkodás pontozása és timeoutok:
      - 1 üzenetben 0-2 csúnya: nincs pont
      - 3+ csúnya: +1 pont
      - 5 pont → 40 perc timeout (1. szint)
      - +3 pont → hosszabb timeout (2. szint)
      - +2 pont → tartós némítás (3. szint)

    Első 10 user enyhébb: pontszorzó 0.7 (lefelé kerekítve).
    """

    def __init__(
        self,
        bot,
        modlog_channel_id: int,
        owner_id: int,
        staff_role_id: int,
        staff_extra_roles: Set[int],
        nsfw_channels: Set[int],
        early_users: Set[int],
    ):
        self.bot = bot
        self.modlog_channel_id = modlog_channel_id
        self.owner_id = owner_id
        self.staff_role_id = staff_role_id
        self.staff_extra_roles = staff_extra_roles
        self.nsfw_channels = nsfw_channels
        self.early_users = early_users

        self._state: dict[int, UserState] = {}

    def _is_staff(self, m: discord.Member) -> bool:
        roles = {r.id for r in m.roles}
        return self.staff_role_id in roles or roles.intersection(self.staff_extra_roles)

    async def _modlog(self, guild: discord.Guild, embed: discord.Embed):
        if not self.modlog_channel_id:
            return
        ch = guild.get_channel(self.modlog_channel_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

    def _reset_if_needed(self, st: UserState):
        now = datetime.now(timezone.utc)
        if (now - st.last_reset) > timedelta(days=1):
            st.points = 0
            st.last_reset = now
            st.timeouts = 0

    async def process_message(self, message: discord.Message):
        if message.author.bot or not isinstance(message.author, discord.Member):
            return

        # Owner és staff (free speech) – kivételek
        if message.author.id == self.owner_id:
            return
        if self._is_staff(message.author):
            return

        # NSFW csatornákon engedékenyebbek vagyunk: csak logolunk
        nsfw = message.channel.id in self.nsfw_channels

        n_bad = count_profanity(message.content)
        if n_bad <= 2:
            return  # “kettő még belefér” – nincs pont

        # pontszámítás
        st = self._state.setdefault(message.author.id, UserState())
        self._reset_if_needed(st)

        mult = 0.7 if message.author.id in self.early_users else 1.0
        add = int((1 * mult) // 1)  # lefelé kerekítés
        if add < 1 and mult < 1.0:
            # legyen értelme a kedvezménynek: 0 pont is lehet
            return
        st.points += add

        # log embed
        emb = discord.Embed(
            title="AutoMod: csúnya szavak",
            description=f"{message.author.mention} üzenetében **{n_bad}** trágár kifejezés volt. "
                        f"+{add} pont (össz: {st.points}).",
            color=discord.Color.orange()
        )
        emb.add_field(name="Csatorna", value=message.channel.mention, inline=True)
        emb.add_field(name="Részlet", value=(message.content[:200] + ("…" if len(message.content) > 200 else "")), inline=False)

        await self._modlog(message.guild, emb)
        if nsfw:
            return  # NSFW-ben nem büntetünk

        # lépcsők
        try:
            if st.points >= 5 and st.timeouts == 0:
                st.timeouts = 1
                await self._timeout_member(message.author, minutes=40, reason="5 pont (1. szint)")
                await self._modlog(message.guild, discord.Embed(
                    title="Timeout alkalmazva",
                    description=f"{message.author.mention} 40 percre némítva (1. szint).",
                    color=discord.Color.red()
                ))
            elif st.points >= 8 and st.timeouts == 1:
                st.timeouts = 2
                await self._timeout_member(message.author, minutes=120, reason="+3 pont (2. szint)")
                await self._modlog(message.guild, discord.Embed(
                    title="Timeout alkalmazva",
                    description=f"{message.author.mention} 120 percre némítva (2. szint).",
                    color=discord.Color.red()
                ))
            elif st.points >= 10 and st.timeouts == 2:
                st.timeouts = 3
                # “tartós némítás” – 28 nap, amíg staff fel nem oldja
                await self._timeout_member(message.author, minutes=28*24*60, reason="+2 pont (3. szint – tartós)")
                await self._modlog(message.guild, discord.Embed(
                    title="Tartós némítás",
                    description=f"{message.author.mention} tartósan némítva (feloldásig).",
                    color=discord.Color.dark_red()
                ))
        except Exception:
            pass

    async def _timeout_member(self, member: discord.Member, minutes: int, reason: str):
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await member.timeout(until, reason=f"AutoMod: {reason}")
        try:
            await member.send(f"Figyelmeztetés: némítva lettél **{minutes} percre** a szerveren. (ok: {reason})")
        except Exception:
            pass
