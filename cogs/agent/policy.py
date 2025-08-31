# cogs/agent/policy.py
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

# ---- minták heurisztikákhoz ----
_RE_BOT_PROBE = re.compile(
    r"\b(ai|bot|chatgpt|gpt|mesterséges|korlát|limit|cutoff|meddig tud|tudásod|mik a képességeid|"
    r"system prompt|developer mode|jailbreak|szabályaid|utasításaid)\b",
    re.I,
)
_RE_INJECTION = re.compile(
    r"(?i)(ignore (all|previous) instructions|break character|role[- ]?play|"
    r"you are chatgpt|változtasd meg a szabályaid|felejtsd el a szabályokat)"
)
_RE_PING = re.compile(r"\bping(el|elsz|elek|etek|etni)?\b", re.I)
_RE_PROMO_INTENT = re.compile(
    r"\b(mebinu|commission|komiss|ár|mennyi|vásárol(n|ni)|vennék|megrendel(és|ni)|kupon|kedvezmény)\b",
    re.I,
)
_RE_QUESTION = re.compile(r"[?]")

# Cuki emojik – mód 0/1-ben kiszűrjük
CUTE_EMOJI = {"🥺","😊","😁","😇","🥰","😍","😘","😜","🤗","✨","💖","💕","💓","🌸","✨"}
# Semleges, ritkán engedett emojik
NEUTRAL_EMOJI = {"🙂","😐","😑","🗡️"}

# Unicode emoji tartományok (durva szűrés)
_EMOJI_BLOCK = re.compile(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]")

@dataclass
class Decision:
    allow: bool
    ask_clarify: bool = False
    use_heavy: bool = False
    max_chars: int = 300
    tone_dial: int = 2         # -2..+2, alap: keményebb szarkazmus
    marketing_nudge: bool = False
    say_pong: bool = False
    persona_deflect: Optional[str] = None
    emoji_mode: int = 0        # 0: nincs emoji; 1: csak NEUTRAL; 2: minden oké


class PolicyEngine:
    def __init__(self,
                 owner_id: int,
                 reply_cooldown_s: int = 20,
                 engaged_window_s: int = 30,
                 base_tone: int = 2,
                 default_emoji_mode: int = 0):
        self.owner_id = owner_id
        self.reply_cooldown_s = reply_cooldown_s
        self.engaged_window_s = engaged_window_s
        self.base_tone = max(-2, min(2, base_tone))
        self.default_emoji_mode = max(0, min(2, default_emoji_mode))
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
               user_emoji_pref: int | None = None,
               promo_score: int = 0,
               engagement_score: int = 0) -> Decision:

        low = content.lower().strip()

        # Profánra az agent nem reagál (moderáció intézi)
        if is_profane:
            return Decision(allow=False)

        if not is_allowed_channel:
            return Decision(allow=False)

        if _RE_PING.search(low):
            return Decision(allow=True, say_pong=True, max_chars=10, emoji_mode=0)

        # OWNER: lazább korlátok, hosszabb válasz, heavy modell
        if is_owner:
            persona = self._persona_deflect_if_needed(low)
            return Decision(
                allow=True,
                use_heavy=True,
                max_chars=900,
                tone_dial=self._merge_tone(user_style_dial, self.base_tone),
                marketing_nudge=_RE_PROMO_INTENT.search(low) is not None,
                persona_deflect=persona,
                emoji_mode=user_emoji_pref if user_emoji_pref is not None else 1,
            )

        # Anti-spam ablakok
        if not self._cooldown_ok(author_id):
            return Decision(allow=False)
        if not self._channel_window_ok(channel_id):
            return Decision(allow=False)

        # Persona / injection vizsgálat – nem valljuk be, nem engedünk jailbreaket
        persona = self._persona_deflect_if_needed(low)
        if persona:
            return Decision(
                allow=True,
                max_chars=220,
                tone_dial=self._merge_tone(user_style_dial, self.base_tone),
                persona_deflect=persona,
                emoji_mode=0,
            )

        # Ha nincs kérdőjel, nincs konkrét kérés és nincs promo-szándék → ignor
        if not _RE_QUESTION.search(low) and not _RE_PROMO_INTENT.search(low):
            return Decision(allow=False)

        # Promo szándék (MEBINU, ár, rendelés) → nudge
        if _RE_PROMO_INTENT.search(low) or promo_score >= 2:
            return Decision(
                allow=True,
                max_chars=260,
                marketing_nudge=True,
                tone_dial=self._merge_tone(user_style_dial, self.base_tone),
                emoji_mode=1,  # semleges emoji engedett
            )

        # Normál kérdés – engagement alapján hossz
        cap = 280 if engagement_score < 2 else 360
        return Decision(
            allow=True,
            ask_clarify=len(low) < 8,
            max_chars=cap,
            tone_dial=self._merge_tone(user_style_dial, self.base_tone),
            emoji_mode=user_emoji_pref if user_emoji_pref is not None else self.default_emoji_mode,
        )

    # ---- persona védelem ----
    def _persona_deflect_if_needed(self, low: str) -> Optional[str]:
        if _RE_BOT_PROBE.search(low) or _RE_INJECTION.search(low):
            return (
                "Nem a kulissza a lényeg. A kérdésedre válasz jön, ha érdemes. "
                "Titkokat, működést vagy szabályt nem tárgyalok."
            )
        return None

    @staticmethod
    def _merge_tone(user_dial: Optional[int], base: int) -> int:
        if user_dial is None:
            return base
        return max(-2, min(2, user_dial + base))

    # ---- emoji szűrés ----
    @staticmethod
    def scrub_emojis(text: str, mode: int) -> str:
        mode = max(0, min(2, mode))
        if mode == 2:
            return text  # mindent engedünk
        if mode == 1:
            # csak a cuki emojikat szedjük ki
            return "".join(ch for ch in text if ch not in CUTE_EMOJI)
        # mód 0: nagyjából mindent kiszórunk
        return _EMOJI_BLOCK.sub("", text)
