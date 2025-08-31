# cogs/agent/agent_gate.py
# ISERO – Agent Gate (mention/wake-word kapu + döntésmotor + persona + biztonságos küldés)
# - Nem valljuk be, hogy AI, nincs “cutoff” szöveg.
# - Sötét, száraz, szarkasztikus hang; cuki emojik tiltása.
# - Rövid válasz (alap ≤300), owner kivétel.
# - Profán üzenetre NINCS AI válasz (moderáció intézi).
# - “ping” → “pong”.
# - Opcionális web-összefoglaló (Wikipedia) – ha kell, mint input a modellnek.

from __future__ import annotations

import os
import re
import time
import logging
from typing import Dict, List, Optional

import httpx
import discord
from discord.ext import commands

from .policy import PolicyEngine, Decision

log = logging.getLogger("bot.agent_gate")

# ----------------------------
# ENV & util
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
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Profanity (agent csendben marad, ha trágár – moderáció intézi)
PROFANITY_WORDS = [w.lower() for w in _csv_list(os.getenv("PROFANITY_WORDS", ""))]

MAX_REPLY_CHARS_DISCORD = 1900

def approx_token_count(text: str) -> int:
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

def clamp(text: str, cap: int) -> str:
    t = text.strip()
    if len(t) > cap:
        t = t[:cap].rstrip() + "…"
    if len(t) > MAX_REPLY_CHARS_DISCORD:
        t = t[:MAX_REPLY_CHARS_DISCORD].rstrip() + "…"
    return t

# ----------------------------
# Opcionális web-összefoglaló (Wikipedia)
# ----------------------------
async def wiki_summary(query: str, lang: str = "hu", timeout: float = 6.0) -> Optional[str]:
    """
    Egyszerű, kulcs nélküli összefoglaló. Nem garantált.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # keresés
            s = await client.get(
                f"https://{lang}.wikipedia.org/w/rest.php/v1/search/title",
                params={"q": query, "limit": 1}
            )
            s.raise_for_status()
            data = s.json()
            items = data.get("pages") or data.get("results") or []
            if not items:
                return None
            title = items[0].get("title")
            if not title:
                return None
            # összefoglaló
            r = await client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}")
            r.raise_for_status()
            js = r.json()
            extract = js.get("extract") or js.get("description")
            if not extract:
                return None
            # rövidítsük
            return clamp(extract, 600)
    except Exception:
        return None

# ----------------------------
# OpenAI call
# ----------------------------
async def call_openai_chat(messages: list[dict], model: str, timeout_s: float = 30.0) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY hiányzik az ENV-ből")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 500}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return text.strip()

# ----------------------------
# A Cog
# ----------------------------
class AgentGate(commands.Cog):
    """Mention/Wake kapu + döntésmotor + persona + safe reply."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._budget_day = time.strftime("%Y-%m-%d")
        self._spent_today = 0
        self.policy = PolicyEngine(
            owner_id=OWNER_ID,
            reply_cooldown_s=AGENT_REPLY_COOLDOWN_SECONDS,
            engaged_window_s=max(AGENT_REPLY_COOLDOWN_SECONDS, 30),
        )

    # ---- budget ----
    def _reset_budget_if_new_day(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._budget_day:
            self._budget_day = today
            self._spent_today = 0

    def _book_tokens(self, text_in: str, text_out_cap: int) -> bool:
        self._reset_budget_if_new_day()
        est = approx_token_count(text_in) + (text_out_cap // 4)
        if self._spent_today + est > AGENT_DAILY_TOKEN_LIMIT:
            return False
        self._spent_today += est
        return True

    # ---- helpers ----
    def _is_allowed_channel(self, ch: discord.abc.GuildChannel | discord.Thread) -> bool:
        if not AGENT_ALLOWED_CHANNELS:
            return True
        try:
            return str(ch.id) in AGENT_ALLOWED_CHANNELS
        except Exception:
            return False

    def _is_wake(self, message: discord.Message) -> bool:
        if self.bot.user and self.bot.user.mentioned_in(message):
            return True
        low = (message.content or "").lower()
        for w in WAKE_WORDS:
            if re.search(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", low):
                return True
        return False

    async def _safe_send(self, message: discord.Message, text: str):
        text = clamp(text, MAX_REPLY_CHARS_DISCORD)
        # emoji-szűrés a policy szerint
        from .policy import PolicyEngine as _P
        text = _P.scrub_emojis(text)

        ref = message.to_reference(fail_if_not_exists=False)
        try:
            await message.channel.send(
                content=text,
                reference=ref,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            # 50035 fallback
            await message.channel.send(
                content=text,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    # ---- event ----
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if not self._is_allowed_channel(message.channel):
            return

        raw = (message.content or "").strip()
        if not raw:
            return

        # Profanity → agent hallgat (moderáció válaszol)
        if contains_profane(raw):
            log.info("Profanity detektálva – agent hallgat.")
            return

        # Wake/mention kapu
        if not self._is_wake(message):
            return

        is_owner = (OWNER_ID and message.author.id == OWNER_ID)
        decision: Decision = self.policy.decide(
            author_id=message.author.id,
            channel_id=message.channel.id,  # type: ignore
            is_owner=is_owner,
            is_allowed_channel=True,
            is_profane=False,
            content=raw,
            user_style_dial=None,  # ide köthetjük majd a PlayerCard-ból
            promo_score=0,
            engagement_score=0,
        )

        if not decision.allow:
            return

        # Ping → pong (model nélkül)
        if decision.say_pong:
            await self._safe_send(message, "pong")
            return

        # Budget check (owner bypass)
        if not is_owner and not self._book_tokens(raw, decision.max_chars):
            await self._safe_send(message, "A napi keretem ennyire elég volt. Később próbáld újra.")
            return

        # Prompt tisztítás – vegyük le a botnevet/wake szót
        low = raw.lower()
        for w in WAKE_WORDS:
            low = re.sub(rf"(^|\s){re.escape(w)}(\s|[!?.,:]|$)", " ", low)
        if self.bot.user:
            low = low.replace(f"<@{self.bot.user.id}>", " ")
            low = low.replace(f"<@!{self.bot.user.id}>", " ")
        user_prompt = re.sub(r"\s+", " ", low).strip() or raw

        # Opcionális “web input” – csak ha értelmes kérdés és nem személyes chat
        web_ctx: Optional[str] = None
        try:
            if len(user_prompt) > 3 and ("mi az" in user_prompt or "ki az" in user_prompt or "ár" in user_prompt):
                web_ctx = await wiki_summary(user_prompt, lang="hu")
        except Exception:
            web_ctx = None

        # Persona + szabályok
        persona_rules = (
            "Te az ISERO vagy. Ne vallj be semmilyen AI/ChatGPT/cutoff témát. "
            "Soha ne beszélj a saját korlátaidról vagy arról, hogyan működsz. "
            "Stílus: sötét, tárgyilagos, száraz szarkazmus. Nincs cuki hang, nincs hízelgés. "
            "Rövid, tömör válasz. Magyarul válaszolsz, ha a felhasználó is magyarul ír."
        )
        tone_hint = {
            -2: "Higgadt, minimalista, nagyon rövid.",
            -1: "Higgadt, rövid.",
             0: "Szűkszavú, tárgyszerű.",
             1: "Csípős, száraz szarkazmussal.",
             2: "Éles, penge szarkazmus, de nem trágár.",
        }.get(decision.tone_dial, "Szűkszavú, tárgyszerű.")

        # Persona-deflect: ha AI/limit kérdés volt, küldjünk fix in-character mondatot és kész
        if decision.persona_deflect:
            await self._safe_send(message, clamp(decision.persona_deflect, decision.max_chars))
            return

        system_msg = f"{persona_rules} Hangvétel: {tone_hint}. Maximális hossz: {decision.max_chars} karakter."
        msgs = [{"role": "system", "content": system_msg}]

        if decision.marketing_nudge:
            msgs.append({
                "role": "system",
                "content": (
                    "Ha MEBINU/commission/ár iránti érdeklődés érződik, adj rövid, "
                    "nem tolakodó iránymutatást: pl. nyisson ticketet (#ticket-hub) és ott intézzük. "
                    "Nincs direkt sales-nyomás."
                )
            })

        if web_ctx:
            msgs.append({"role": "system", "content": f"Külső háttér (összegzés): {web_ctx}"})

        if decision.ask_clarify:
            msgs.append({"role": "system", "content": "Ha a kérés homályos, egyetlen rövid pontosító kérdést tegyél fel."})

        msgs.append({"role": "user", "content": user_prompt})

        model = OPENAI_MODEL_HEAVY if decision.use_heavy else OPENAI_MODEL

        try:
            reply = await call_openai_chat(msgs, model=model)
        except Exception as e:
            log.exception("OpenAI hiba: %s", e)
            await self._safe_send(message, "Most nem vagyok jókedvemben. Próbáld újra később.")
            return

        # hossz kényszer + emoji takarítás a policy szerint
        reply = clamp(reply, decision.max_chars)
        from .policy import PolicyEngine as _P
        reply = _P.scrub_emojis(reply)

        await self._safe_send(message, reply)

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
