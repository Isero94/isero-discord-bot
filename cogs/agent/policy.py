# cogs/agent/policy.py
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

# ---- Heurisztikákhoz regexek ----
_RE_BOT_PROBE = re.compile(
    r"\b(ai|bot|chatgpt|gpt|mesterséges|korlát|limit|cutoff|meddig tud|tudásod|mik a képességeid)\b",
    re.I,
)
_RE_PING = re.compile(r"\bping(el|elsz|elek|etek|etni)?\b", re.I)
_RE_PROMO_INTENT = re.compile(
    r"\b(mebinu|commission|komiss|ár|mennyi|vásárol(n|ni)|vennék|megrendel(és|ni))\b", re.I
)
_RE_QUESTION = re.compile(r"[?]")

# Cuki/infantilis emojik tiltólista – ezeket SOHA
CUTE_EMOJI = {"🥺", "😊", "😁", "😇", "🥰", "😍", "😘", "😜", "🤗", "✨", "💖", "💕", "💓", "🌸", "✨"}

# Engedett, ritkán használt neutrális emojik (ha nagyon muszáj)
ALLOWED_EMOJI = {"🙂", "😐", "😑", "🗡️"}

@dataclass
class Decision:
    allow: bool
    ask_clarify: bool = False
    use_heavy: bool = False
    max_chars: int = 300
    tone_dial: int = 1  # -2 .. +2 (negatív = higgadtabb; pozitív = csípősebb)
    marketing_nudge: bool = False
    say_pong: bool = False
    persona_deflect: Optional[str] = None  # ha AI/limit kérdés: fix in-character válasz


class PolicyEngine:
    def __init__(self,
                 owner_id: int,
                 reply_cooldown_s: int = 20,
                 engaged_window_s: int = 30):
        self.owner_id = owner_id
        self.reply_cooldown_s = reply_cooldown_s
        self.engaged_window_s = engaged_window_s
        self._last_user_reply: dict[int, float] = {}
        self._last_channel_reply: dict[int, float] = {}

    # ---- anti-spam / ablakok ----
    def _cooldown_ok(self, user_id: int) -> bool:
        t = time.time()
        last = self._last_user_reply.get(user_id, 0.0)
        if t - last >= self.reply_cooldown_s:
            self._last_user_reply[user_id] = t
            return True
        return False

    def _channel_window_ok(self, channel_id: int) -> bool:
        t = time.time()
        last = self._last_channel_reply.get(channel_id, 0.0)
        if t - last >= self.engaged_window_s:
            self._last_channel_reply[channel_id] = t
            return True
        return False

    # ---- fő döntés ----
    def decide(self,
               *,
               author_id: int,
               channel_id: int,
               is_owner: bool,
               is_allowed_channel: bool,
               is_profane: bool,
               content: str,
               user_style_dial: int | None = None,
               promo_score: int = 0,
               engagement_score: int = 0) -> Decision:

        low = content.lower().strip()

        # Profánra az agent NEM reagál
        if is_profane:
            return Decision(allow=False)

        # Csatorna whitelist
        if not is_allowed_channel:
            return Decision(allow=False)

        # PING rövid válasz
        if _RE_PING.search(low):
            return Decision(allow=True, say_pong=True, max_chars=10)

        # Owner: mindig engedjük, heavy modell is mehet, hosszabb válasz is mehet
        if is_owner:
            # ha direkt AI/limit témára nyom, akkor is persona-deflect
            persona = self._persona_deflect_if_needed(low)
            return Decision(
                allow=True,
                use_heavy=True,
                max_chars=900,
                tone_dial=self._merge_tone(user_style_dial, 2),
                marketing_nudge=_RE_PROMO_INTENT.search(low) is not None,
                persona_deflect=persona,
            )

        # Anti-spam ablakok (user és channel)
        if not self._cooldown_ok(author_id):
            return Decision(allow=False)
        if not self._channel_window_ok(channel_id):
            return Decision(allow=False)

        # AI/limit/probe → soha nem valljuk be, persona-fix
        persona = self._persona_deflect_if_needed(low)
        if persona:
            return Decision(
                allow=True,
                max_chars=220,
                tone_dial=self._merge_tone(user_style_dial, 1),
                persona_deflect=persona,
            )

        # Ha nincs kérdőjel és nincs konkrét kérés, nagy eséllyel ignor
        if not _RE_QUESTION.search(low) and not _RE_PROMO_INTENT.search(low):
            # rövid, csípős elütés néha hasznosabb az ignornál – itt most ignor
            return Decision(allow=False)

        # Promo szándék
        if _RE_PROMO_INTENT.search(low) or promo_score >= 2:
            return Decision(
                allow=True,
                max_chars=260,
                marketing_nudge=True,
                tone_dial=self._merge_tone(user_style_dial, 2),
            )

        # Normál kérdés
        # Engagement alapján hosszhatár
        cap = 280 if engagement_score < 2 else 360
        return Decision(
            allow=True,
            ask_clarify=len(low) < 8,  # “mi van?” típusú rövidke
            max_chars=cap,
            tone_dial=self._merge_tone(user_style_dial, 1),
        )

    # ---- persona védelem ----
    def _persona_deflect_if_needed(self, low: str) -> Optional[str]:
        if _RE_BOT_PROBE.search(low):
            # Nem valljuk be, nem beszélünk cutoffról, nincs “én csak AI…”
            return (
                "Nem érdekes, mi vagyok. A lényeg, hogy működöm. "
                "Kérdezz konkrétan, és kapsz választ. Ha nem, annak is oka van."
            )
        return None

    @staticmethod
    def _merge_tone(user_dial: Optional[int], base: int) -> int:
        if user_dial is None:
            return base
        x = max(-2, min(2, user_dial + base))
        return x

    # ---- segéd: emoji szűrés ----
    @staticmethod
    def scrub_emojis(text: str) -> str:
        # cuki emojik kuka; engedett maradhat ritkán
        out = []
        for ch in text:
            if ch in CUTE_EMOJI:
                continue
            out.append(ch)
        return "".join(out)
