import os
import asyncio
import logging
import typing as T

import discord
from discord.ext import commands
from openai import AsyncOpenAI

log = logging.getLogger("isero.agent")

# ---- env helpers ------------------------------------------------------------
def _env_list(name: str, sep: str = ",") -> list[str]:
    raw = os.getenv(name, "") or ""
    return [x.strip() for x in raw.split(sep) if x.strip()]

def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None and str(v).strip() != "" else default

def _is_ticket_channel(ch: discord.abc.GuildChannel | None) -> bool:
    if isinstance(ch, discord.TextChannel):
        topic = ch.topic or ""
        return "owner:" in topic  # a tickets cog ilyen markert tesz
    return False

# ---- reply-want detector ----------------------------------------------------
def _wants_agent_reply(message: discord.Message, me: discord.Member | discord.ClientUser,
                       wake_words: list[str]) -> bool:
    """Döntsük el, hogy az ügynök válaszoljon-e erre az üzenetre."""
    # explicit mention
    try:
        if isinstance(me, (discord.Member, discord.ClientUser)) and me.mentioned_in(message):
            return True
    except Exception:
        # nagyon konzervatívan: ha valamiért a fenti bedőlne, nézzük a mentions listát
        if isinstance(me, (discord.Member, discord.ClientUser)):
            if any(getattr(u, "id", 0) == getattr(me, "id", -1) for u in message.mentions):
                return True

    # wake words (elején)
    content = (message.content or "").strip().lower()
    for w in wake_words:
        w = w.lower()
        if not w:
            continue
        if content.startswith(w + " ") or content == w or content.startswith(w + ",") or content.startswith(w + ":"):
            return True

    # jegycsatornában válaszolunk akkor is, ha nincs trigger (kényelmi ok)
    if _is_ticket_channel(message.channel):
        return True

    return False

# ---- persona ----------------------------------------------------------------
SYSTEM_PERSONA = (
    "You are ISERO, a helpful Discord assistant for the ISERO server. "
    "Speak concisely, be friendly, and keep context to the current channel. "
    "If a request involves moderation or private info, act carefully and ask clarifying questions. "
    "Answer in the language of the user. If the message is short like 'hello', greet and ask how to help."
)

# ---- the Cog ----------------------------------------------------------------
class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        api_key = _env_str("OPENAI_API_KEY")
        self.model = _env_str("OPENAI_MODEL", "gpt-4o-mini")
        self.daily_token_limit = int(_env_str("AGENT_DAILY_TOKENS", "20000") or "20000")
        self.wake_words = _env_list("WAKE_WORDS") or ["isero", "ai"]

        # OpenAI kliens (async)
        self.ai = AsyncOpenAI(api_key=api_key) if api_key else None

        # nagyon egyszerű throttling (per process)
        self._last_reply_per_user: dict[int, float] = {}

        log.info("[AgentGate] ready. Model=%s, Limit/24h=%s tokens", self.model, self.daily_token_limit)

    # --- kis helper, hogy a bot beszélhet-e itt ------------------------------
    def _can_talk_here(self, ch: discord.abc.GuildChannel) -> bool:
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            return False
        perms = ch.permissions_for(ch.guild.me)  # type: ignore
        return perms.send_messages and perms.read_messages

    # --- fő üzenetfigyelő ----------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # alap szűrők
        if message.author.bot:
            return
        if not message.guild:
            return
        if not self.ai:
            return
        me = message.guild.me  # discord.Member

        # csak akkor, ha beszélhetünk, és tényleg akar tőlünk választ
        if not self._can_talk_here(message.channel):  # type: ignore
            return
        if not _wants_agent_reply(message, me, self.wake_words):  # <-- itt volt a hiba korábban
            return

        # nagyon light flood-védelem felhasználóra
        now = asyncio.get_event_loop().time()
        last = self._last_reply_per_user.get(message.author.id, 0.0)
        if (now - last) < 2.0:  # 2 mp
            return
        self._last_reply_per_user[message.author.id] = now

        try:
            await self._answer(message)
        except Exception as e:
            log.exception("Agent reply failed: %s", e)

    # --- válaszgenerálás -----------------------------------------------------
    async def _answer(self, message: discord.Message):
        content = message.content or ""
        user_name = getattr(message.author, "display_name", message.author.name)

        msgs = [
            {"role": "system", "content": SYSTEM_PERSONA},
            {"role": "user", "content": f"{user_name}: {content}".strip()},
        ]

        # kis aktivitás jelzés
        async with message.channel.typing():  # type: ignore
            resp = await self.ai.chat.completions.create(
                model=self.model,
                messages=msgs,
                temperature=0.6,
            )
        reply = (resp.choices[0].message.content or "").strip()

        if reply:
            await message.reply(reply, mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
