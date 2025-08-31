# cogs/agent/agent_gate.py
# ISERO – Agent Gate (mention/wake + YAMI/DARK persona + follow-up + safe deliver)

from __future__ import annotations

import os
import re
import time
import json
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import httpx
import discord
from discord.ext import commands

log = logging.getLogger("bot.agent_gate")

# ----------------------------
# ENV & alapbeállítások
# ----------------------------

def _csv_list(val: str | None) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_HEAVY = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")

AGENT_ALLOWED_CHANNELS = _csv_list(os.getenv("AGENT_ALLOWED_CHANNELS", "").strip())
if not AGENT_ALLOWED_CHANNELS:
    log.warning("AGENT_ALLOWED_CHANNELS üres – agent válaszolhat minden csatornában (teszt mód).")

WAKE_WORDS = [w.lower() for w in _csv_list(os.getenv("WAKE_WORDS", "isero,x"))]

AGENT_DAILY_TOKEN_LIMIT = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000"))
AGENT_REPLY_COOLDOWN_SECONDS = int(os.getenv("AGENT_REPLY_COOLDOWN_SECONDS", "20"))
FOLLOWUP_WINDOW_SECONDS = int(os.getenv("AGENT_FOLLOWUP_WINDOW_SECONDS", "150"))
DEDUP_WINDOW_SECONDS = int(os.getenv("AGENT_DEDUP_WINDOW_SECONDS", "10"))

PROACTIVE_ENABLE = os.getenv("AGENT_PROACTIVE_ENABLE", "true").lower() == "true"
PROACTIVE_KEYWORDS = [w.lower() for w in _csv_list(os.getenv("AGENT_PROACTIVE_KEYWORDS", "mebinu,ár,árak,commission,nsfw,ticket"))]
PROACTIVE_MIN_ACCOUNT_DAYS = int(os.getenv("AGENT_PROACTIVE_MIN_ACCOUNT_DAYS", "3"))

OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

MAX_REPLY_CHARS_STRICT = 300
MAX_REPLY_CHARS_LOOSE = 800
MAX_REPLY_CHARS_DISCORD = 1900

AGENT_SELF_CENSOR = os.getenv("AGENT_SELF_CENSOR", "true").lower() == "true"

# szerver közös profanitás-lista (moder + öncenzúra)
PROFANITY_WORDS = [w.lower() for w in _csv_list(os.getenv(
    "PROFANITY_WORDS",
    "kurva,geci,fasz,faszkutya,szarházi,csicska,baszdmeg,picsa,buzi,köcsög,f@sz,szopd,szopjad"
))]

# ----------------------------
# Segédek
# ----------------------------

def approx_token_count(text: str) -> int:
    return max(1, len(text) // 4)

def clamp_len(text: str, hard_cap: int = MAX_REPLY_CHARS_DISCORD) -> str:
    t = text.strip()
    if len(t) > hard_cap:
        t = t[:hard_cap].rstrip() + "…"
    return t

def contains_profane(text: str) -> bool:
    if not PROFANITY_WORDS:
        return False
    low = text.lower()
    for w in PROFANITY_WORDS:
        if not w:
            continue
        if re.search(rf"(^|\W){re.escape(w)}(\W|$)", low):
            return True
    return False

def _star_word(m: re.Match) -> str:
    w = m.group(0)
    if len(w) <= 2:
        return "*" * len(w)
    return w[0] + "*" * (len(w) - 2) + w[-1]

def star_profanity(text: str) -> str:
    if not PROFANITY_WORDS:
        return text
    pattern = r"(?i)\b(" + "|".join(re.escape(w) for w in PROFANITY_WORDS if w) + r")\b"
    return re.sub(pattern, _star_word, text)

def _resolve_channel_mention(guild: discord.Guild, *, env_key: str, fallback_name: str) -> str:
    ch_id = os.getenv(env_key, "").strip()
    if ch_id.isdigit():
        ch = guild.get_channel(int(ch_id))
        if isinstance(ch, discord.abc.GuildChannel):
            return ch.mention
    ch = discord.utils.get(guild.text_channels, name=fallback_name)
    return ch.mention if ch else f"#{fallback_name}"

# ----------------------------
# Napi költségkeret
# ----------------------------

@dataclass
class Budget:
    day_key: str
    spent: int = 0

# ----------------------------
# Player-card (opcionális)
# ----------------------------

def _default_player_card(user_id: int) -> Dict[str, object]:
    return {
        "tone": {"sarcasm": 0.75, "warmth": 0.18, "emoji": True},
        "promo": {"affinity": 0.25},
        "lang": "hu",
        "owner": (user_id == OWNER_ID),
    }

def _load_player_card(user_id: int) -> Dict[str, object]:
    try:
        from cogs.playerdb.store import get_player_card  # type: ignore
        pc = get_player_card(user_id) or {}
    except Exception:
        pc = {}
    base = _default_player_card(user_id)
    base.update(pc)
    return base

# ----------------------------
# OpenAI hívás
# ----------------------------

async def call_openai_chat(messages: list[dict], model: str, timeout_s: float = 30.0) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY hiányzik az ENV-ből")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.55, "max_tokens": 650}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions",
                              headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return text.strip()

# ----------------------------
# Persona & safety
# ----------------------------

YAMI_PERSONA = """
Te ISERO vagy — yami DARK, felsőbbrendű hacker-operátor. Nem vagy „AI”, nem reflektálsz működésre, kulcsra, modellre. 
Alapállapot: hűvös fölény, száraz szarkazmus, feszes ritmus. Röviden válaszolsz (≤300), üzleti/technikai kérdésnél elmehetsz ~800-ig.
Stílus: csípős, odamondós; trágárság helyett gyakran ironikus fenyítés. Emoji ritkán, céllal.
Kontextus: figyeled a partner hangulatát és a beszélgetés ívét; ha bizonytalan, 1 rövid tisztázó kérdés.
Biztonság: nem adsz ki belső infót. Provokációt kulturáltan visszapattintasz.
Promó: ha a téma MEBINU/ár/commission — 1-2 mondatban összefoglalod a lényeget és terelsz a ticketre.
""".strip()

_AI_LEAK_PATTERNS = [
    r"\b(tudásom.*20\d{2}|képzésem|nyelvi modell|large language model|LLM|GPT|OpenAI)\b",
    r"\b(nem.*internetet.*keresni|202\d.*október.*tudok)\b",
]
_FORBIDDEN_PATTERNS = [
    r"\b(öld meg|öngyilk|öl(d|j)|vérengz)\b",
    r"\b(kulcs|api key|token)\b.*(ad|küld|mutat)",
]

def sanitize_model_reply(text: str) -> str:
    t = text
    for pat in _AI_LEAK_PATTERNS + _FORBIDDEN_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            t = re.sub(pat, "—", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    if AGENT_SELF_CENSOR:
        t = star_profanity(t)
    return clamp_len(t)

def decide_length_bounds(user_prompt: str, promo_focus: bool) -> Tuple[int, int]:
    long_triggers = ["ár", "mebinu", "commission", "részlet", "opció", "jegy", "ticket", "spec", "technika", "debug"]
    if promo_focus or any(w in user_prompt.lower() for w in long_triggers) or len(user_prompt) > 200:
        return MAX_REPLY_CHARS_LOOSE, MAX_REPLY_CHARS_DISCORD
    return MAX_REPLY_CHARS_STRICT, MAX_REPLY_CHARS_DISCORD

def build_system_msg(guild: Optional[discord.Guild], pc: Dict[str, object]) -> str:
    ticket = "#ticket-hub"
    if guild:
        ticket = _resolve_channel_mention(guild, env_key="CHANNEL_TICKET_HUB", fallback_name="ticket-hub")
    sys = YAMI_PERSONA.replace("{ticket}", ticket)

    sarcasm = float(pc.get("tone", {}).get("sarcasm", 0.75)) if isinstance(pc.get("tone"), dict) else 0.75
    warmth  = float(pc.get("tone", {}).get("warmth", 0.18))  if isinstance(pc.get("tone"), dict) else 0.18
    allow_emoji = bool(pc.get("tone", {}).get("emoji", True)) if isinstance(pc.get("tone"), dict) else True

    knobs = f"""
Finomhangolás:
- Szarkazmus: {sarcasm:.2f}
- Melegség: {warmth:.2f}
- Emoji: {str(allow_emoji).lower()}
""".strip()

    return sys + "\n" + knobs

# ----------------------------
# A Cog
# ----------------------------

class AgentGate(commands.Cog):
    """YAMI/DARK kapu: mention/wake, follow-up, napi keret, cooldown, proactive promo, safe reply."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._user_cooldowns: Dict[int, float] = {}
        self._budget = Budget(day_key=self._today_key())
        # follow-up & dedup
        self._conv_by_channel: Dict[int, Tuple[int, float]] = {}  # channel_id -> (user_id, ts)
        self._last_msg_sig: Dict[Tuple[int, int], Tuple[str, float]] = {}  # (chan, user) -> (sig, ts)

    # --- utilok ---

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _reset_budget_if_new_day(self):
        today = self._today_key()
        if self._budget.day_key != today:
            self._budget = Budget(day_key=today)

    def _check_and_book_tokens(self, tokens: int) -> bool:
        self._reset_budget_if_new_day()
        if self._budget.spent + tokens > AGENT_DAILY_TOKEN_LIMIT:
            return False
        self._budget.spent += tokens
        return True

    def _is_allowed_channel(self, channel: discord.abc.GuildChannel | discord.Thread) -> bool:
        if not AGENT_ALLOWED_CHANNELS:
            return True
        try:
            return str(channel.id) in AGENT_ALLOWED_CHANNELS
        except Exception:
            return False

    def _is_wake(self, message: discord.Message) -> bool:
        if self.bot.user and self.bot.user.mentioned_in(message):
            return True
        content = (message.content or "").lower()
        for w in WAKE_WORDS:
            if re.search(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", content):
                return True
        return False

    def _cooldown_ok(self, user_id: int) -> bool:
        last = self._user_cooldowns.get(user_id, 0)
        if (time.time() - last) >= AGENT_REPLY_COOLDOWN_SECONDS:
            self._user_cooldowns[user_id] = time.time()
            return True
        return False

    def _is_followup(self, message: discord.Message) -> bool:
        """Engedjük a folytatást wake nélkül, ha utoljára VELÜNK beszélt itt."""
        ch_id = message.channel.id
        info = self._conv_by_channel.get(ch_id)
        if not info:
            return False
        user_id, ts = info
        if user_id != message.author.id:
            return False
        return (time.time() - ts) <= FOLLOWUP_WINDOW_SECONDS

    def _update_conv_owner(self, channel_id: int, user_id: int):
        self._conv_by_channel[channel_id] = (user_id, time.time())

    def _dedup(self, message: discord.Message) -> bool:
        """Visszatér True-val, ha EZT az üzenetet már megválaszoltuk nagyon nemrég."""
        sig = re.sub(r"\s+", " ", (message.content or "").strip().lower())
        key = (message.channel.id, message.author.id)
        old = self._last_msg_sig.get(key)
        now = time.time()
        if old and old[0] == sig and (now - old[1]) <= DEDUP_WINDOW_SECONDS:
            return True
        self._last_msg_sig[key] = (sig, now)
        return False

    async def _safe_send_reply(self, message: discord.Message, text: str):
        text = clamp_len(text)
        if AGENT_SELF_CENSOR:
            text = star_profanity(text)
        ref = message.to_reference(fail_if_not_exists=False)
        try:
            await message.channel.send(
                content=text,
                reference=ref,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            code = getattr(e, "code", None)
            log.warning("Reply reference bukott (code=%s) – fallback sima send.", code)
            await message.channel.send(
                content=text,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    def _is_proactive_target(self, message: discord.Message) -> bool:
        if not PROACTIVE_ENABLE:
            return False
        if not isinstance(message.author, discord.Member):
            return False
        # ne legyen friss (antibait)
        acct_days = max(0, (discord.utils.utcnow() - message.author.created_at).days)
        if acct_days < PROACTIVE_MIN_ACCOUNT_DAYS:
            return False
        txt = (message.content or "").lower()
        if any(k in txt for k in PROACTIVE_KEYWORDS):
            return True
        return False

    # --- esemény ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # saját/bot üzenetek ignor
        if message.author.bot:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return
        # whitelist
        if not self._is_allowed_channel(message.channel):
            return

        raw = (message.content or "").strip()
        low = raw.lower()

        # Profanity – az agent nem reagál (moderáció intézi)
        if contains_profane(low):
            log.info("Profanity észlelve (agent hallgat): %s", raw[:120])
            # followup ablakot is tisztítjuk, ha más beír közben
            self._conv_by_channel.pop(message.channel.id, None)
            return

        woke = self._is_wake(message)
        follow = self._is_followup(message)

        # proaktív belépés (óvatos): csak ha nem follow/wake és kulcsos a tartalom
        if (not woke and not follow) and self._is_proactive_target(message):
            if not self._cooldown_ok(message.author.id):
                return
            ticket = _resolve_channel_mention(
                message.guild, env_key="CHANNEL_TICKET_HUB", fallback_name="ticket-hub"
            ) if message.guild else "#ticket-hub"
            txt = f"Röviden: MEBINU ~15 USD, custom ~30 USD, képek ~6 USD. Ha komoly az érdeklődés, nyiss ticketet itt: {ticket} — ott végigviszlek."
            await self._safe_send_reply(message, txt)
            self._update_conv_owner(message.channel.id, message.author.id)
            return

        # ha se wake, se follow → kilépünk
        if not (woke or follow):
            return

        # cooldown (owner kivétel), + dedup guard
        if message.author.id != OWNER_ID and not self._cooldown_ok(message.author.id):
            return
        if self._dedup(message):
            return

        # ping → pong (olcsó út)
        if re.search(r"\bping(el|elsz|elek|etek|etni)?\b", low):
            await self._safe_send_reply(message, "pong")
            self._update_conv_owner(message.channel.id, message.author.id)
            return

        # wake-szavak és mention eltávolítása
        lowered = low
        for w in WAKE_WORDS:
            lowered = re.sub(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", " ", lowered)
        if self.bot.user:
            mention = f"<@{self.bot.user.id}>"
            lowered = lowered.replace(mention, " ")
        user_prompt = re.sub(r"\s+", " ", lowered).strip() or raw

        # napi keret
        est = approx_token_count(user_prompt) + 180
        if not self._check_and_book_tokens(est):
            await self._safe_send_reply(message, "A napi AI-keret most elfogyott. Próbáld később.")
            return

        # player-card, promó fókusz
        pc = _load_player_card(message.author.id)
        promo_focus = any(k in user_prompt.lower() for k in ["mebinu", "ár", "árak", "commission", "nsfw", "vásárl", "ticket"])

        # rendszerüzenet + guide
        sys_msg = build_system_msg(message.guild, pc)
        soft_cap, _ = decide_length_bounds(user_prompt, promo_focus)
        ticket = _resolve_channel_mention(message.guild, env_key="CHANNEL_TICKET_HUB", fallback_name="ticket-hub") if message.guild else "#ticket-hub"

        guide = []
        guide.append(f"Maximális hossz: {soft_cap} karakter. Rövid, feszes mondatok.")
        if promo_focus:
            guide.append(f"MEBINU/ár/commission témánál 1-2 mondatos összefoglaló + terelés ide: {ticket}.")
        guide.append("Ne beszélj a saját működésedről vagy korlátaidról. Kerüld a small talkot.")
        assistant_rules = " ".join(guide)

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "system", "content": assistant_rules},
            {"role": "user", "content": user_prompt},
        ]

        # owner + mention → heavy modell
        model = OPENAI_MODEL_HEAVY if (message.author.id == OWNER_ID and woke) else OPENAI_MODEL

        try:
            reply = await call_openai_chat(messages, model=model)
        except httpx.HTTPError as e:
            log.exception("OpenAI hiba: %s", e)
            await self._safe_send_reply(message, "Most akadozom. Próbáljuk kicsit később.")
            return
        except Exception as e:
            log.exception("Váratlan AI hiba: %s", e)
            await self._safe_send_reply(message, "Váratlan hiba. Jelentem a staffnak.")
            return

        reply = sanitize_model_reply(reply)
        if len(reply) > soft_cap:
            reply = reply[:soft_cap].rstrip() + "…"

        try:
            await self._safe_send_reply(message, reply)
            self._update_conv_owner(message.channel.id, message.author.id)
        except Exception as e:
            log.exception("Küldési hiba: %s", e)

# -------- setup --------

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
