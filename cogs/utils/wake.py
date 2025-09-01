# cogs/utils/wake.py
from __future__ import annotations
import os
import re
from typing import List, Optional

def _csv(s: str | None) -> List[str]:
    if not s:
        return []
    # levágjuk az idézőjeleket/whitespace-t, üreseket kidobjuk
    raw = s.strip().strip('"\'')

    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]

WAKE_CORE = _csv(os.getenv("WAKE_CORE") or "isero")
WAKE_PREFIXES_HU = _csv(os.getenv("WAKE_PREFIXES_HU") or "")
WAKE_PREFIXES_EN = _csv(os.getenv("WAKE_PREFIXES_EN") or "")
WAKE_MAX_PREFIX_TOKENS = int(os.getenv("WAKE_MAX_PREFIX_TOKENS") or "2")

def _build_regex(core: List[str],
                 pref_hu: List[str],
                 pref_en: List[str],
                 max_tokens: int) -> re.Pattern:
    # védőszűrés
    core = [c for c in core if c]
    pref_hu = [p for p in pref_hu if p]
    pref_en = [p for p in pref_en if p]
    if not core:
        core = ["isero"]

    core_alt = "|".join(re.escape(c) for c in core)
    # prefixek szóközökkel lehetnek (pl. "excuse me") → engedjük
    pref_all = pref_hu + pref_en
    if pref_all:
        pref_alt = "|".join(re.escape(p) for p in pref_all)
        # max_tokens darab PREFIX + whitespace ismételhető, de üres alternatíva nincs
        prefix_block = rf"(?:\s*(?:{pref_alt})\s+){{0,{max(0, max_tokens)}}}"
    else:
        prefix_block = ""

    # mention minták
    mention = r"(?:<@!?\d+>)"

    # a 'core' megengedett írásjelek határolásával
    body = rf"(?:{prefix_block}(?:{core_alt}|{mention}))"
    pat = rf"(?i)(?:^|\s){body}(?:\s|[!?.,:;]|$)"

    return re.compile(pat)

_WAKE_RE = _build_regex(WAKE_CORE, WAKE_PREFIXES_HU, WAKE_PREFIXES_EN, WAKE_MAX_PREFIX_TOKENS)

class WakeMatcher:
    def has_wake(self, text: str, bot_mention: Optional[str] = None) -> bool:
        if bot_mention and bot_mention in text:
            return True
        return bool(_WAKE_RE.search(text))

    def strip(self, text: str, bot_mention: Optional[str] = None) -> str:
        t = text
        if bot_mention:
            t = t.replace(bot_mention, "")
        # kivágjuk az elejéről az esetleges prefix+core részt
        m = _WAKE_RE.search(t)
        if not m:
            return t.strip()
        start, end = m.span()
        # ha a wake az elején van, levágjuk addig
        if start <= 1:
            return t[end:].strip()
        # különben csak a mentiont távolítjuk – marad a szöveg
        return t.replace(m.group(0), "").strip()
