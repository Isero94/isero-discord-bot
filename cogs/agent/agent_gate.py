# cogs/agent/agent_gate.py
from __future__ import annotations

import os, re, time, json, logging, unicodedata, hashlib
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import httpx
import discord
from discord.ext import commands

from utils.wake import WakeMatcher  # <— ÚJ: kétlépcsős wake

log = logging.getLogger("bot.agent_gate")

# ===== ENV =====

def _csv_list(val: str | None) -> List[str]:
    if not val: return []
    return [x.strip() for x in val.split(",") if x.strip()]

OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_KEY")
OPENAI_MODEL         = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_HEAVY   = os.getenv("OPENAI_MODEL_HEAVY", "gpt-4o")

OWNER_ID             = int(os.getenv("OWNER_ID", "0") or "0")
AGENT_DAILY_TOKEN_LIMIT        = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000"))
AGENT_REPLY_COOLDOWN_SECONDS   = int(os.getenv("AGENT_REPLY_COOLDOWN_SECONDS", "20"))

AGENT_SESSION_WINDOW_SECONDS   = int(os.getenv("AGENT_SESSION_WINDOW_SECONDS", "120"))
AGENT_SESSION_MIN_CHARS        = int(os.getenv("AGENT_SESSION_MIN_CHARS", "4"))
AGENT_DEDUP_TTL_SECONDS        = int(os.getenv("AGENT_DEDUP_TTL_SECONDS", "5"))

AGENT_ALLOWED_CHANNELS         = _csv_list(os.getenv("AGENT_ALLOWED_CHANNELS", ""))

# tickets
TICKETS_CATEGORY_ID            = int(os.getenv("TICKETS_CATEGORY_ID", "0") or "0")
TICKET_HUB_CHANNEL_ID          = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0") or "0")
# kompatibilitás a korábbi kulccsal
if not TICKET_HUB_CHANNEL_ID:
    TICKET_HUB_CHANNEL_ID = int(os.getenv("CHANNEL_TICKET_HUB", "0") or "0")

# wake (kétlépcsős)
WAKE_CORE         = _csv_list(os.getenv("WAKE_CORE", "isero,issero"))
WAKE_PREFIXES_HU  = _csv_list(os.getenv("WAKE_PREFIXES_HU", "hé,hej,szia,hello,helló,na,figyi,hallod,kérlek,légyszi,lécci,pls,oké,csá,uram,mester,tesó,haver,bro,bocsi,bocs"))
WAKE_PREFIXES_EN  = _csv_list(os.getenv("WAKE_PREFIXES_EN", "hey,hi,hello,yo,ok,okay,please,pls,dude,man,sir,boss,bro,excuse me,sorry"))
WAKE_MAX_PREFIX   = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2"))

# profanitás (moderátor cog kezeli csillagozást; itt NEM tiltunk)
PROFANITY_WORDS   = [w.lower() for w in _csv_list(os.getenv("PROFANITY_WORDS", ""))]

MAX_REPLY_CHARS_STRICT   = 300
MAX_REPLY_CHARS_LOOSE    = 800
MAX_REPLY_CHARS_DISCORD  = 1900

# ===== Segédek =====

def approx_token_count(text: str) -> int:
    return max(1, len(text)//4)

def clamp_len(text: str, hard_cap: int = MAX_REPLY_CHARS_DISCORD) -> str:
    t = text.strip()
    return t[:hard_cap].rstrip()+"…" if len(t)>hard_cap else t

def _channel_mention(guild: Optional[discord.Guild], ch_id: int, fallback_name: str) -> str:
    if guild and ch_id:
        ch = guild.get_channel(ch_id)
        if isinstance(ch, discord.abc.GuildChannel):
            return ch.mention
    if guild:
        ch = discord.utils.get(guild.text_channels, name=fallback_name)
        if ch: return ch.mention
    return f"#{fallback_name}"

@dataclass
class Budget:
    day_key: str
    spent: int = 0

# ===== OpenAI =====

async def call_openai_chat(messages: list[dict], model: str, timeout_s: float = 30.0) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 600}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

# ===== Persona / guard =====

YAMI_PERSONA = (
"Te ISERO vagy – sötét, YAMI-dark operátor, hideg nyugalommal és száraz, metsző szarkazmussal. "
"Nem magyarázkodsz a működésedről. Nincs személyeskedő vagy kirekesztő támadás; maradj csípős, "
"de profi. Rövid, feszes mondatok. Ha az ügy üzlet: lényegre törő triage (költségkeret, határidő, referencia)."
)

AI_LEAK_PATTERNS = [
    r"\b(nyelvi modell|gpt|openai|képzésem|cutoff|nem.*tudok.*internet)\b",
]
FORBIDDEN_PATTERNS = [
    r"\b(api.?key|token|jelszó)\b",
]

def sanitize(text: str) -> str:
    t = text
    for pat in AI_LEAK_PATTERNS + FORBIDDEN_PATTERNS:
        t = re.sub(pat, "—", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return clamp_len(t)

def decide_length_bounds(user_prompt: str, promo_focus: bool) -> Tuple[int,int]:
    long_triggers = ["ár", "mebinu", "commission", "részlet", "opció", "jegy", "ticket", "technika", "debug"]
    return (MAX_REPLY_CHARS_LOOSE, MAX_REPLY_CHARS_DISCORD) if (promo_focus or any(w in user_prompt.lower() for w in long_triggers) or len(user_prompt)>200) else (MAX_REPLY_CHARS_STRICT, MAX_REPLY_CHARS_DISCORD)

# ===== Cog =====

class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._budget = Budget(day_key=self._today())
        self._user_cooldown: Dict[int, float] = {}
        self._last_sent: Dict[int, Tuple[str, float]] = {}  # channel_id -> (hash, ts)
        self._session: Dict[Tuple[int,int], float] = {}     # (channel_id, user_id) -> last_ts
        self._wake = WakeMatcher(WAKE_CORE, WAKE_PREFIXES_HU + WAKE_PREFIXES_EN, WAKE_MAX_PREFIX)

    # ---- util
    def _today(self) -> str: return time.strftime("%Y-%m-%d")
    def _reset_budget(self):
        if self._budget.day_key != self._today():
            self._budget = Budget(day_key=self._today())

    def _book_tokens(self, n:int) -> bool:
        self._reset_budget()
        if self._budget.spent + n > AGENT_DAILY_TOKEN_LIMIT: return False
        self._budget.spent += n; return True

    def _in_allowed_channel(self, ch: discord.abc.GuildChannel | discord.Thread) -> bool:
        return True if not AGENT_ALLOWED_CHANNELS else (str(getattr(ch,"id",None)) in AGENT_ALLOWED_CHANNELS)

    def _is_ticket_channel(self, ch: discord.abc.GuildChannel | discord.Thread) -> bool:
        try:
            cat_id = getattr(ch, "category_id", None)
            name = (getattr(ch, "name", "") or "").lower()
            return (TICKETS_CATEGORY_ID and cat_id == TICKETS_CATEGORY_ID) or ("mebinu" in name or "ticket" in name)
        except Exception:
            return False

    def _cooldown_ok(self, user_id: int) -> bool:
        last = self._user_cooldown.get(user_id, 0)
        if time.time()-last >= AGENT_REPLY_COOLDOWN_SECONDS:
            self._user_cooldown[user_id] = time.time(); return True
        return False

    def _session_alive(self, ch_id:int, user_id:int) -> bool:
        key = (ch_id, user_id)
        ts = self._session.get(key, 0)
        alive = (time.time()-ts) <= AGENT_SESSION_WINDOW_SECONDS
        if alive: self._session[key] = time.time()
        return alive

    def _touch_session(self, ch_id:int, user_id:int):
        self._session[(ch_id, user_id)] = time.time()

    def _dedup(self, ch_id:int, text:str) -> bool:
        h = hashlib.sha1(text.encode("utf8")).hexdigest()
        last = self._last_sent.get(ch_id)
        now = time.time()
        if last and last[0]==h and (now-last[1])<=AGENT_DEDUP_TTL_SECONDS:
            return True
        self._last_sent[ch_id] = (h, now)
        return False

    async def _safe_send(self, message: discord.Message, text:str):
        text = clamp_len(text)
        if self._dedup(message.channel.id, text): 
            return
        try:
            await message.channel.send(
                content=text,
                reference=message.to_reference(fail_if_not_exists=False),
                allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            await message.channel.send(content=text, allowed_mentions=discord.AllowedMentions.none())

    # ---- event
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot: return
        if self.bot.user and message.author.id == self.bot.user.id: return
        if not self._in_allowed_channel(message.channel): return

        content_raw = (message.content or "").strip()
        content_low = content_raw.lower()

        # session + wake
        in_ticket = self._is_ticket_channel(message.channel)
        mentioned = self.bot.user and self.bot.user.mentioned_in(message)
        woke = self._wake.is_wake(content_raw) or mentioned

        # ticket csatornában NEM kell wake, ha van aktív session, vagy elég hosszú a szöveg
        if in_ticket and not woke:
            if len(content_low) >= AGENT_SESSION_MIN_CHARS:
                woke = True

        # publik csatornában: wake VAGY aktív session
        if not woke and self._session_alive(message.channel.id, message.author.id):
            woke = True

        if not woke:
            return

        # owner kivétel – cooldown nélküli
        if message.author.id != OWNER_ID and not self._cooldown_ok(message.author.id):
            return

        # “ping” gyors válasz
        if re.search(r"\bping(el|elek|etek|etni)?\b", content_low):
            await self._safe_send(message, "pong"); self._touch_session(message.channel.id, message.author.id); return

        # prompt előkészítés
        user_prompt = re.sub(rf"<@!?{self.bot.user.id}>", " ", content_raw).strip() if self.bot.user else content_raw
        est_tokens = approx_token_count(user_prompt) + 180
        if not self._book_tokens(est_tokens):
            await self._safe_send(message, "A napi keret elfogyott. Próbáld később."); return

        # persona + ticket triage
        ticket_mention = _channel_mention(message.guild, TICKET_HUB_CHANNEL_ID, "ticket-hub")
        promo_focus = any(k in user_prompt.lower() for k in ["mebinu","ár","árak","commission","nsfw","vásárl","ticket"])
        soft_cap, _ = decide_length_bounds(user_prompt, promo_focus)

        sys = YAMI_PERSONA
        if in_ticket:
            sys += (
                "\nJelenleg TICKET csatornában vagy. Nincs small talk. "
                "Kezdj triage-gal: kérj három adatot: költségkeret (USD), határidő, rövid leírás + referencia (max 4 kép). "
                "Adj lépéses javaslatot és foglald össze a következő teendőt. "
                "Ha az üzenet csak ‘helló’ típusú, kérdezz rá udvariasan a fenti háromra."
            )
        else:
            # publikus: rövid terelés
            sys += (
                "\nPublikus csatorna. Ha ‘mebinu/ár’ téma: 1–2 mondatos összefoglaló + irány a ticket: "
                f"{ticket_mention}."
            )

        rules = f"Maximális hossz: {soft_cap} karakter. Ne magyarázd a működésed. Kerüld a szóismétlést és az azonos üzeneteket."

        messages = [
            {"role":"system","content":sys},
            {"role":"system","content":rules},
            {"role":"user","content":user_prompt},
        ]

        model = OPENAI_MODEL_HEAVY if (message.author.id==OWNER_ID and mentioned) else OPENAI_MODEL

        try:
            reply = await call_openai_chat(messages, model=model)
        except Exception as e:
            log.exception("AI hiba: %s", e)
            await self._safe_send(message, "Most akadozom. Próbáljuk kicsit később.")
            return

        reply = sanitize(reply)
        if len(reply) > soft_cap:
            reply = reply[:soft_cap].rstrip()+"…"

        await self._safe_send(message, reply)
        self._touch_session(message.channel.id, message.author.id)

# ---- setup
async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
