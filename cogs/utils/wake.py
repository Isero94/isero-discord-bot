# cogs/utils/wake.py
from __future__ import annotations

import os
import re
import unicodedata
from typing import Iterable


def _fold(s: str) -> str:
    """Kisbetű + ékezetlevétel (hé -> he), felesleges whitespace összehúzva."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _split_csv(env_name: str, default: str = "") -> list[str]:
    raw = os.getenv(env_name, default) or default
    return [x.strip() for x in raw.split(",") if x.strip()]


class WakeMatcher:
    """
    Kétlépcsős ébresztő:
      1) Mentions (<@id>) mindig ébresztenek
      2) Prefix(ek) [HU/EN] + core ('isero', 'issero') max N előtaggal
    """

    def __init__(self) -> None:
        self.core = {c.lower() for c in _split_csv("WAKE_CORE", "isero,issero")}
        self.prefixes = {_fold(p) for p in (
            _split_csv("WAKE_PREFIXES_HU", "")
            + _split_csv("WAKE_PREFIXES_EN", "")
        )}
        self.max_pref = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2") or "2")

        # engedékeny "isero/issero/iseroo" mag
        self._core_regex = r"(?:i+ss?e+ro+)"
        # előtagok (accent-foldolt) beégetése a regexbe
        pref_alt = "|".join(map(re.escape, sorted(self.prefixes)))
        if pref_alt:
            pref_block = rf"(?:\b({pref_alt})\b[\s,;:.—-]{{0,2}}){{0,{self.max_pref}}}"
        else:
            pref_block = r""

        self._re = re.compile(
            rf"(?i)(?:^|[\s,;:.—-]){pref_block}\b{self._core_regex}\b[!?.,:;—-]*"
        )

        # normalizáló a core eltávolításához (wake-szó kipucolása a promptból)
        self._re_strip_core = re.compile(rf"(?i)\b{self._core_regex}\b[!?.,:;—-]*")

    # ---------- API ----------

    def is_wake(self, text: str, *, bot_id: int | None = None) -> bool:
        """Visszaadja, hogy a szöveg ébreszt-e (mention vagy prefix+core)."""
        if not text:
            return False
        # Mention gyors út:
        if bot_id and (f"<@{bot_id}>" in text or f"<@!{bot_id}>" in text):
            return True
        # Accent-foldolt vizsgálat
        return bool(self._re.search(_fold(text)))

    def strip_wake(self, text: str, *, bot_id: int | None = None) -> str:
        """Eltávolítja a mentiont és a wake-magot a szövegből."""
        if not text:
            return text
        t = text
        if bot_id:
            t = t.replace(f"<@{bot_id}>", " ").replace(f"<@!{bot_id}>", " ")
        # core eltávolítás (accent-foldolt mintára keresünk, de az eredetiből vágunk)
        # egyszerű csere a leggyakoribb alakokra…
        t = re.sub(self._re_strip_core, " ", t)
        # whitespace takarítás
        t = re.sub(r"\s+", " ", t).strip()
        return t
