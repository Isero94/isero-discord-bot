# cogs/agent/agent_gate.py
# ISERO – Agent Gate (wake/mention kapu + modellhívás + biztonságos küldés)
# - Dark-sarcasm persona (max)
# - Változó válaszhossz (80–320) komplexitás alapján
# - Low-intent üzikre némaság (nem-owner)
# - Owner kivétel: mention nélkül is, nincs cooldown/limit
# - 50035 reply-fallback
# - Profanity -> agent hallgat (moderáció dolgozik)

from __future__ import annotations

import os
import re
import time
import logging
from typing import Dict, Optional, List, Tuple

import httpx
import discord
from discord.ext import commands

log = logging.getLogger("bot.agent_gate")

# ----------------------------
# ENV / konfiguráció
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

OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

# napi token keret + user cooldown (másnak)
AGENT_DAILY_TOKEN_LIMIT = int(os.getenv("AGENT_DAILY_TOKEN_LIMIT", "20000"))
AGENT_REPLY_COOLDOWN_SECONDS = int(os.getenv("AGENT_REPLY_COOLDOWN_SECONDS", "20"))

# válaszhossz határok (karakter)
LEN_SHORT_MIN = int(os.getenv("AGENT_LEN_SHORT_MIN", "80"))
LEN_SHORT_MAX = int(os.getenv("AGENT_LEN_SHORT_MAX", "140"))
LEN_MED_MIN   = int(os.getenv("AGENT_LEN_MED_MIN", "160"))
LEN_MED_MAX   = int(os.getenv("AGENT_LEN_MED_MAX", "240"))
LEN_LONG_MIN  = int(os.getenv("AGENT_LEN_LONG_MIN", "260"))
LEN_LONG_MAX  = int(os.getenv("AGENT_LEN_LONG_MAX", "320"))
LEN_HARD_CAP  = 1900  # Discord safety

# Profanity – agent NE válaszoljon, ezt a moderációs cog intézi
PROFANITY_WORDS = [w.lower() for w in _csv_list(os.getenv("PROFANITY_WORDS", ""))]

# ----------------------------
# Segédek
# ----------------------------

def approx_token_count(text: str) -> int:
    # 4 char ~= 1 token
    return max(1, len(text) // 4)

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

def clamp(text: str, max_len: int) -> str:
    t = text.strip()
    if len(t) > max_len:
        t = t[:max_len].rstrip() + "…"
    if len(t) > LEN_HARD_CAP:
        t = t[:LEN_HARD_CAP].rstrip() + "…"
    return t

def is_low_intent(raw: str) -> bool:
    """
    „Mi a helyzet?”, „oké?”, „hmm”, 1-3 szavas smalltalk -> ne válaszoljon (nem-owner).
    Kérdőjel, kulcsszavak, parancsok kilövik.
    """
    low = (raw or "").lower().strip()
    if not low:
        return True
    # ha kérdés van benne, az már intent
    if "?" in low:
        return False
    # kulcsszavak, amik kérésre utalnak
    key = ("segíts", "help", "hogyan", "miért", "csináld", "csinálj", "állítsd", "állíts", "parancs", "kód", "ticket")
    if any(k in low for k in key):
        return False
    # 3 szónál kevesebb és nincs igazi tartalom
    words = [w for w in re.split(r"\s+", low) if w]
    if len(words) <= 3:
        return True
    # semmitmondó sablonok
    if re.fullmatch(r"(mi a helyzet|mizu|hali|szia|csó|na|ok|oké|okey|jó).*", low):
        return True
    return False

def measure_complexity(raw: str) -> Tuple[str, int]:
    """
    Visszaadja a („short”|„med”|„long”, target_max_len) párost.
    Egyszerű heurisztika: szóhossz + kérdőjelek + kulcsszavak száma.
    """
    text = (raw or "").strip()
    words = [w for w in re.split(r"\s+", text) if w]
    n = len(words)
    q = text.count("?")
    keys = ("hogyan", "miért", "lépés", "részletes", "hiba", "error", "kód", "parancs", "deploy", "render", "discord")
    kscore = sum(1 for k in keys if k in text.lower())

    score = (n / 12.0) + (2 * q) + (1.5 * kscore)

    if score < 1.5:
        return "short", LEN_SHORT_MAX
    elif score < 3.5:
        return "med", LEN_MED_MAX
    else:
        return "long", LEN_LONG_MAX

def system_persona(target_max_len: int, owner: bool) -> str:
    """
    Max-dark szarkazmus, de funkcionális.
    """
    base = (
        "Te ISERO vagy. Magyarul válaszolj. Stílus: hideg, sötét, szarkasztikus, "
        "profi, félelmet keltő – de mindig hasznos és pontos. Nincs cuki hangvétel, "
        "nincs túlmagyarázás. Használhatsz ritkán minimalista emojit (😏, ⚠️, 🛠️), "
        "de ne vidd túlzásba. Ne pletykázz titkokról, ne ígérj lehetetlen dolgokat. "
        f"Legyen tömör: maximum ~{target_max_len} karakter per üzenet. "
        "Ha a kérés homályos, tegyél fel EGY rövid pontosító kérdést. "
        "Ha a felhasználó provokál, csípős szarkazmussal válaszolj, de ne sértegess "
        "és ne lépd át a moderáció határát. "
    )
    if owner:
        base += (
            "A tulajdonos beszél: neki elsőbbséget élvező, célratörő, technikai válaszokat adj. "
            "Elfogadható a kissé hosszabb (de továbbra is tömör) válasz."
        )
    else:
        base += "Random usernek rövidebb, pengeéles válaszokat adj."
    return base

async def call_openai(messages: list[dict], model: str, timeout_s: float = 30.0) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY hiányzik az ENV-ből")
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 500}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return (data["choices"][0]["message"]["content"] or "").strip()

# ----------------------------
# Könyvelés
# ----------------------------

class Budget:
    def __init__(self):
        self.day = time.strftime("%Y-%m-%d")
        self.spent = 0

    def reset_if_needed(self):
        today = time.strftime("%Y-%m-%d")
        if today != self.day:
            self.day = today
            self.spent = 0

    def book(self, tokens: int) -> bool:
        self.reset_if_needed()
        if self.spent + tokens > AGENT_DAILY_TOKEN_LIMIT:
            return False
        self.spent += tokens
        return True

# ----------------------------
# Cog
# ----------------------------

class AgentGate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns: Dict[int, float] = {}
        self._budget = Budget()

    # ---- belső utilok ----

    def _allowed_channel(self, channel: discord.abc.GuildChannel | discord.Thread) -> bool:
        if not AGENT_ALLOWED_CHANNELS:
            return True
        try:
            return str(channel.id) in AGENT_ALLOWED_CHANNELS
        except Exception:
            return False

    def _is_wake(self, message: discord.Message) -> bool:
        # Ownernek mention nélkül is „wake”
        if OWNER_ID and message.author.id == OWNER_ID:
            return True
        # Bot mention?
        if self.bot.user and self.bot.user.mentioned_in(message):
            return True
        # Wake word?
        content = (message.content or "").lower()
        for w in WAKE_WORDS:
            if re.search(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", content):
                return True
        return False

    def _cooldown_ok(self, user_id: int) -> bool:
        # Owner: sosem throttled
        if OWNER_ID and user_id == OWNER_ID:
            return True
        last = self._cooldowns.get(user_id, 0.0)
        now = time.time()
        if now - last >= AGENT_REPLY_COOLDOWN_SECONDS:
            self._cooldowns[user_id] = now
            return True
        return False

    async def _safe_send(self, message: discord.Message, text: str):
        ref = message.to_reference(fail_if_not_exists=False)
        try:
            await message.channel.send(
                content=text,
                reference=ref,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            log.warning("Reply reference bukott (code=%s) – fallback sima send.", getattr(e, "code", None))
            await message.channel.send(text, allowed_mentions=discord.AllowedMentions.none())

    # ---- esemény ----

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # botok / DM off
        if message.author.bot or not getattr(message, "guild", None):
            return
        if not self._allowed_channel(message.channel):
            return

        raw = (message.content or "").strip()
        low = raw.lower()

        # Agent ne reagáljon profán üzenetre (moderation intézi)
        if contains_profane(low):
            log.info("Profanity észlelve (agent csendben marad).")
            return

        # Ping -> azonnali
        if re.search(r"\bping(el|elsz|elek|etek|etni)?\b", low):
            await self._safe_send(message, "pong")
            return

        # Wake gate
        if not self._is_wake(message):
            return

        # Low-intent némítás (nem-owner)
        if (not (OWNER_ID and message.author.id == OWNER_ID)) and is_low_intent(raw):
            # néma marad
            return

        # Cooldown (nem-owner)
        if not self._cooldown_ok(message.author.id):
            return

        # Token keret (nem-owner)
        est = approx_token_count(raw) + 150
        if not (OWNER_ID and message.author.id == OWNER_ID):
            if not self._budget.book(est):
                await self._safe_send(message, "A napi AI-keret most elfogyott. Próbáld később. ⚠️")
                return

        # Dinamikus válaszhossz
        band, target_max = measure_complexity(raw)
        is_owner = (OWNER_ID and message.author.id == OWNER_ID)

        sys = system_persona(target_max_len=target_max, owner=is_owner)

        # bot-mention / wake szavak levágása a user_promptból
        cleaned = low
        for w in WAKE_WORDS:
            cleaned = re.sub(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", " ", cleaned)
        if self.bot.user:
            mention = f"<@{self.bot.user.id}>"
            cleaned = cleaned.replace(mention, " ")
        user_prompt = re.sub(r"\s+", " ", cleaned).strip() or raw

        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": user_prompt},
        ]

        # Ownernek heavy modell, másnak light
        model = OPENAI_MODEL_HEAVY if is_owner else OPENAI_MODEL

        try:
            reply = await call_openai(messages, model=model)
        except httpx.HTTPError as e:
            log.exception("OpenAI hiba: %s", e)
            await self._safe_send(message, "Most akadozom az AI-nál. Próbáljuk kicsit később. 🛠️")
            return
        except Exception as e:
            log.exception("Váratlan AI hiba: %s", e)
            await self._safe_send(message, "Váratlan hiba történt. Jelentem a staffnak. ⚠️")
            return

        # Biztonságos küldés (levágás a target_max-re)
        await self._safe_send(message, clamp(reply, target_max))
        

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
