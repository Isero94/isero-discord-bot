import os
import re
import time
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List

import discord
from discord.ext import commands

import httpx  # gyors, egyszerű /v1/chat/completions hívásra

# ---- Konfig env (egyszerű, helyi beolvasás) -------------------------------
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_HEAVY = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")

AGENT_DAILY_TOKEN_LIMIT = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000"))

# üres = minden csatorna engedélyezett
_allowed_raw = os.getenv("AGENT_ALLOWED_CHANNELS", "").strip()
AGENT_ALLOWED_CHANNELS: Optional[List[int]] = None
if _allowed_raw:
    AGENT_ALLOWED_CHANNELS = [int(x.strip()) for x in _allowed_raw.split(",") if x.strip().isdigit()]

# opcionális log csatornák (itt NEM válaszolunk, csak naplózunk)
CHANNEL_GENERAL_LOGS = int(os.getenv("CHANNEL_GENERAL_LOGS", "0") or 0)
CHANNEL_MOD_LOGS = int(os.getenv("CHANNEL_MOD_LOGS", "0") or 0)

# rövid, pörgős, nem sablonos, kis humor/szarkazmus (spec)
SYSTEM_STYLE_HU = (
    "Te egy magyar nyelvű, röviden és lényegre törően válaszoló chat-asszisztens vagy. "
    "Ne légy bőbeszédű. Ne használd a sablonos lezárásokat ('ha van még kérdésed...'). "
    "Lehet kis humorod és szarkazmusod, de maradj kedves. "
    "Titkokat/privát infót ne adj ki. Káromkodást finoman kipontozol. "
)

# szándékos, nagyon kicsi profanitás-szűrés a saját kimenetre
_BAD_WORDS = [
    "kurva", "kurvára", "picsa", "picsába", "fasz", "fasza", "baszd", "baszki", "fuck", "shit"
]
_bad_re = re.compile(r"(?i)\b(" + "|".join(re.escape(w) for w in _BAD_WORDS) + r")\b")

def censor(text: str) -> str:
    def rep(m: re.Match) -> str:
        w = m.group(0)
        return w[0] + "•" * max(1, len(w) - 1)
    return _bad_re.sub(rep, text)


def estimate_tokens(text: str) -> int:
    # durva becslés: 1 token ~ 4 karakter
    return max(1, len(text) // 4)

def choose_model(message_text: str, mode_override: Optional[str]) -> str:
    if mode_override in {"mini", "heavy"}:
        return OPENAI_MODEL_HEAVY if mode_override == "heavy" else OPENAI_MODEL_DEFAULT
    # auto: hossz + kulcsszavak alapján
    longish = len(message_text) >= 600
    complex_kw = re.search(r"\b(plan|spec|design|részletesen|összetett|architektúra)\b", message_text, re.I)
    return OPENAI_MODEL_HEAVY if (longish or complex_kw) else OPENAI_MODEL_DEFAULT


class AgentGate(commands.Cog):
    """A fő kapu: mikor és hogyan válaszoljon az agent."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._http = httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"})
        self._base_url = "https://api.openai.com/v1/chat/completions"

        # napi token-limit követés
        self.tokens_used = 0
        self.day_start = datetime.now(timezone.utc).date()

        # /agent model kapcsoló (auto/mini/heavy)
        self.model_mode = "auto"  # 'auto' | 'mini' | 'heavy'

        # trigger: mention vagy név (isero/iseró)
        self.name_triggers = ("isero", "iseró", "isero a")

        # állapot-jelzés a logban
        limit = f"{AGENT_DAILY_TOKEN_LIMIT} tokens"
        model = OPENAI_MODEL_DEFAULT
        self.bot.logger.info(f"[AgentGate] ready. Model={model}, Limit/24h={limit}")

    # ----- segédek ----------------------------------------------------------
    def _reset_tokens_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day_start:
            self.day_start = today
            self.tokens_used = 0

    def _allowed_here(self, channel_id: int) -> bool:
        if channel_id in {CHANNEL_GENERAL_LOGS, CHANNEL_MOD_LOGS}:
            return False  # log csatornákon ne beszélgessen
        if AGENT_ALLOWED_CHANNELS is None:
            return True  # üres = mindenhol
        return channel_id in AGENT_ALLOWED_CHANNELS

    def _is_addressed(self, message: discord.Message) -> bool:
        if message.mention_everyone:
            return False
        # mention a botra
        if self.bot.user and self.bot.user.mentioned_in(message):
            return True
        # név szerinti megszólítás
        low = (message.content or "").lower()
        return any(tr in low for tr in self.name_triggers)

    async def _openai_chat(self, model: str, user_text: str) -> Tuple[str, int]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_STYLE_HU},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.6,
            "max_tokens": 500,
        }
        r = await self._http.post(self._base_url, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        # becsült tokenhasználat (input + output)
        used = estimate_tokens(user_text) + estimate_tokens(text)
        return text, used

    # ----- event hook -------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        # Ownernek mindig válaszolunk, csatornától függetlenül
        owner_msg = (message.author.id == OWNER_ID)

        if not owner_msg:
            # csak engedélyezett csatornákon dolgozunk
            if not self._allowed_here(message.channel.id):
                return
            # csak megszólításra vagy reply-ban (ha neki válaszolnak)
            is_reply_to_bot = (
                isinstance(message.reference, discord.MessageReference)
                and message.reference.resolved
                and getattr(message.reference.resolved.author, "id", None) == self.bot.user.id
            )
            if not (self._is_addressed(message) or is_reply_to_bot):
                return

        # napi limit ellenőrzés
        self._reset_tokens_if_new_day()
        if self.tokens_used >= AGENT_DAILY_TOKEN_LIMIT:
            if owner_msg:
                await message.channel.send("Elfogyott a napi tokenkeret. Szólj, ha emeljem. 😅")
            return

        # modell kiválasztás
        model = choose_model(message.content or "", self.model_mode)

        try:
            reply_text, used = await self._openai_chat(model, message.content)
        except Exception as e:
            self.bot.logger.exception("AgentGate: OpenAI hiba", exc_info=e)
            return

        self.tokens_used += used

        # öncenzúra a saját kimenetre
        reply_text = censor(reply_text)

        # ha névvel szólítottak, illik levenni a név-ismétlést
        reply_text = re.sub(r"(?i)\b(isero|iseró)\b[:,]?\s*", "", reply_text).strip()

        # válasz
        try:
            await message.channel.send(reply_text, reference=message)
        except discord.Forbidden:
            pass  # nincs írás jog, hagyjuk

    # ----- admin API, a másik cog hívja ------------------------------------
    def set_model_mode(self, mode: str):
        self.model_mode = mode

    def get_status(self) -> str:
        self._reset_tokens_if_new_day()
        return f"mode={self.model_mode}, tokens_used={self.tokens_used}/{AGENT_DAILY_TOKEN_LIMIT}, model_default={OPENAI_MODEL_DEFAULT}, model_heavy={OPENAI_MODEL_HEAVY}"


async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
