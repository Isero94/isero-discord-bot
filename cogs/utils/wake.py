# utils/wake.py
from __future__ import annotations

import os
import re
import unicodedata
from typing import List

__all__ = ["WakeMatcher"]

def _csv(val: str | None) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]

def _fold(s: str) -> str:
    # kisbetű + ékezetelt → ékezet nélküli
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    # egyszerű zajok kiszedése
    s = re.sub(r"[^\w\s!?.,:;@<>/\\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

class WakeMatcher:
    """Kétlépcsős wake:
    - mention (<@id>) vagy <@!id> azonnal ébreszt
    - legfeljebb N prefix + core kulcsszó (isero/issero)
    """
    def __init__(self, cores: List[str], prefixes: List[str], max_prefix_tokens: int, legacy_words: List[str]):
        self.cores = [c.strip().lower() for c in cores if c.strip()]
        if not self.cores:
            self.cores = ["isero", "issero"]
        self.prefixes = [p.strip().lower() for p in prefixes if p.strip()]
        self.max_prefix_tokens = max(0, int(max_prefix_tokens))
        self.legacy = [w.strip().lower() for w in legacy_words if w.strip()]

        # regex i+ss?e+ro+ engedi az apró gépelési elütéseket (issero/iseroo)
        core_pat = r"(?:%s|i+ss?e*ro+)" % "|".join(map(re.escape, self.cores))
        if self.prefixes and self.max_prefix_tokens > 0:
            pref_group = r"(?:\b(?:%s)\b[\s,;:.—-]{0,2}){0,%d}" % ("|".join(map(re.escape, self.prefixes)), self.max_prefix_tokens)
            self.regex = re.compile(rf"(?i)(^|[\s,;:.—-]){pref_group}\b{core_pat}\b[!?.,]*")
        else:
            self.regex = re.compile(rf"(?i)(^|[\s,;:.—-])\b{core_pat}\b[!?.,]*")

    @classmethod
    def from_env(cls) -> "WakeMatcher":
        cores = _csv(os.getenv("WAKE_CORE", ""))  # pl.: "isero,issero"
        pref_hu = _csv(os.getenv("WAKE_PREFIXES_HU", ""))
        pref_en = _csv(os.getenv("WAKE_PREFIXES_EN", ""))
        legacy = _csv(os.getenv("WAKE_WORDS", ""))  # visszafelé kompatibilitás
        maxn = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2"))
        return cls(cores=cores, prefixes=pref_hu + pref_en, max_prefix_tokens=maxn, legacy_words=legacy)

    def is_wake(self, text: str, *, bot_id: int | None = None) -> bool:
        if bot_id:
            if f"<@{bot_id}>" in text or f"<@!{bot_id}>" in text:
                return True
        folded = _fold(text)
        if self.regex.search(folded):
            return True
        # fallback a régi WAKE_WORDS listára (szigorúbb, de megmarad)
        for w in self.legacy:
            if not w:
                continue
            if re.search(rf"(^|\s){re.escape(w.lower())}(\s|[!?.,:]|$)", folded):
                return True
        return False

    def strip_wake_prefixes(self, text: str, *, bot_id: int | None = None) -> str:
        """Eltávolítja a felfogott prefix+core részt a prompt elejéről – a többi marad."""
        t = text
        if bot_id:
            t = t.replace(f"<@{bot_id}>", " ").replace(f"<@!{bot_id}>", " ")
        # csak az elejéről vágunk
        m = self.regex.search(_fold(t))
        if m and m.start() <= 2:
            # durva kivágás: a nem-foldolt sztringből vágni bonyolult; egyszerűsítünk
            # – az első 1-2 szó + végjelek gyakran a wake rész.
            t = re.sub(r"^\s*[\w\-!?.:,;]{1,40}(\s+[\w\-!?.:,;]{1,20}){0,2}\s*", " ", t)
        return re.sub(r"\s+", " ", t).strip()
