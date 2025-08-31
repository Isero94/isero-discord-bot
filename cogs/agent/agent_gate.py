import os
import re
import math
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from openai import OpenAI

from .moderation import AutoMod
from .filters import censor_outgoing

INTENTS = discord.Intents.default()
INTENTS.message_content = True  # a background workerednél ez már engedélyezett

def _parse_id_list(env_value: str | None) -> set[int]:
    if not env_value:
        return set()
    ids = set()
    for part in env_value.split(","):
        s = part.strip()
        if not s:
            continue
        try:
            ids.add(int(s))
        except ValueError:
            pass
    return ids

def _yes(env_value: str | None) -> bool:
    return str(env_value).lower() in {"1","true","yes","y","on"}

class AgentGate(commands.Cog):
    """Szabad beszélgetés + automod + emberi-nyelvű parancs-közvetítés."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # --- ENV / CONFIG ---
        self.owner_id = int(os.getenv("OWNER_ID", "0"))
        self.allowed_channels = _parse_id_list(os.getenv("AGENT_ALLOWED_CHANNELS"))
        self.nsfw_channels = _parse_id_list(os.getenv("NSFW_CHANNELS"))
        self.staff_role_id = int(os.getenv("STAFF_ROLE_ID", "0"))
        self.staff_extra_roles = _parse_id_list(os.getenv("STAFF_EXTRA_ROLE_IDS"))
        self.modlog_channel_id = int(os.getenv("CHANNEL_MOD_LOGS", "0"))

        self.openai_model_light = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_model_heavy = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")
        self.daily_token_limit = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000"))
        self.command_use_limit = int(os.getenv("COMMAND_USE_LIMIT", "3"))

        self.client = OpenAI()  # api kulcs env-ből

        # napi token számláló (egyszerű, memóriás)
        self._day = datetime.now(timezone.utc).date()
        self._used_tokens = 0

        # AutoMod (pontok, timeoutok, logolás)
        early = _parse_id_list(os.getenv("EARLY_USER_IDS"))
        self.automod = AutoMod(
            bot=bot,
            modlog_channel_id=self.modlog_channel_id,
            owner_id=self.owner_id,
            staff_role_id=self.staff_role_id,
            staff_extra_roles=self.staff_extra_roles,
            nsfw_channels=self.nsfw_channels,
            early_users=early,
        )

        self._mention_re = None  # később készítjük, amikor a bot kész

        self.bot.loop.create_task(self._post_ready())

    async def _post_ready(self):
        await self.bot.wait_until_ready()
        me = self.bot.user
        if me:
            # mention vagy névalapú megszólítás
            patt = r"^(?:<@!?%s>|%s|isero)\b" % (me.id, re.escape(me.name.lower()))
            self._mention_re = re.compile(patt, re.I)
        guild_id = os.getenv("GUILD_ID")
        limit_info = f"Limit/24h={self.daily_token_limit} tokens"
        model_info = f"Model={self.openai_model_light}"
        print(f"[AgentGate] ready. {model_info}, {limit_info}")

    # ------------- Segédfüggvények -------------

    def _in_allowed_channel(self, channel: discord.abc.GuildChannel) -> bool:
        if not self.allowed_channels:
            return True  # üres = mindenhol figyel
        return channel.id in self.allowed_channels

    def _addressed(self, message: discord.Message) -> bool:
        """Igaz, ha a botot megszólították."""
        if message.author.id == self.owner_id:
            return True  # neked mindig válaszol
        if self._mention_re and self._mention_re.search(message.content.strip()):
            return True
        return False

    def _choose_model(self, text: str, is_staff: bool) -> str:
        # egyszerű “heavy” detektálás: hossz, kódrészlet, staff
        has_code = "```" in text or re.search(r"\b(class|def|SELECT|INSERT|function)\b", text, re.I)
        longish = len(text) > 800
        if is_staff or has_code or longish:
            return self.openai_model_heavy
        return self.openai_model_light

    def _est_tokens(self, text: str) -> int:
        # nagyon durva becslés: ~4 char / token
        return max(1, math.ceil(len(text) / 4))

    def _rollover_tokens(self):
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._used_tokens = 0

    # ------------- Eseménykezelő -------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if not self._in_allowed_channel(message.channel):
            return

        # Moderáció fut minden üzenetre (válasz nélkül is)
        await self.automod.process_message(message)

        # Ha nem címezték a botot és nem te írtad, nincs beszélgetős válasz
        if not self._addressed(message):
            return

        # Ha napi tokenkeret kifutott, udvarias jelzés
        self._rollover_tokens()
        if self._used_tokens >= self.daily_token_limit:
            await message.reply("Ma elértem a napi keretemet, holnap folytassuk. 🙏")
            return

        # Üzenet kitisztítása (ha mentionnel kezdődik)
        content = message.content.strip()
        if self._mention_re:
            content = self._mention_re.sub("", content, count=1).strip()

        # staff-e (szabadabb/heavy)
        is_staff = False
        if isinstance(message.author, discord.Member):
            roles = {r.id for r in message.author.roles}
            if self.staff_role_id in roles or roles.intersection(self.staff_extra_roles):
                is_staff = True

        model = self._choose_model(content, is_staff=is_staff)

        # rendszer prompt – személyiség + működési elvek
        system = (
            "Te vagy ISERO, a szerver asszisztense. Légy segítőkész, kedves és rövid.\n"
            "Tartsd tiszteletben a közösségi normákat; kerüld a trágár szavakat, még idézéskor is cenzúrázd őket.\n"
            "Ha a felhasználó a szerver működéséről vagy szabályokról kérdez, foglald össze tömören."
        )

        # OpenAI hívás
        try:
            resp = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                temperature=0.6,
            )
            text = resp.choices[0].message.content or ""
            usage_in = resp.usage.prompt_tokens or 0
            usage_out = resp.usage.completion_tokens or 0
            used = int(usage_in) + int(usage_out)
            if used <= 0:
                # fallback becslés
                used = self._est_tokens(content) + self._est_tokens(text)
            self._used_tokens += used

            # öncenzúra a kimeneten
            text = censor_outgoing(text)

            # hosszú üzenet tördelése
            chunks = []
            while text:
                chunks.append(text[:1800])
                text = text[1800:]

            first = True
            for ch in chunks:
                if first:
                    await message.reply(ch, suppress_embeds=True)
                    first = False
                else:
                    await message.channel.send(ch, reference=message.to_reference(), suppress_embeds=True)

        except Exception as e:
            await message.reply("Hopp, valami elszállt a felhőkben. Szólj egy staffnak! 🙈")
            raise

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
