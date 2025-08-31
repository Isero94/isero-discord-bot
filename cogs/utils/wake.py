# cogs/utils/wake.py
from __future__ import annotations

import os
import re
import unicodedata
from typing import List

def _csv_list(val: str | None) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]

def _norm(text: str) -> str:
    # kisbetű + ékezetelt betűk kiegyenesítése (hé -> he, helló -> hello)
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    # zajjelek lazán: vesszők, pontok stb. szóközzé
    t = re.sub(r"[\s,;:._\-–—]+", " ", t).strip()
    return t

class WakeMatcher:
    """
    2-rétegű ébresztés:
      - CORE: pl. "isero", "issero" (+ opcionális !?.)
      - max N előtag engedve (hu+en), pl. "hej", "oke", "pls", "excuse me", stb.
    Mentions (<@id>) mindig ébresztenek.
    """

    def __init__(self):
        self.core = [w for w in _csv_list(os.getenv("WAKE_CORE", ""))] or ["isero", "issero"]
        self.pref_hu = _csv_list(os.getenv("WAKE_PREFIXES_HU", ""))
        self.pref_en = _csv_list(os.getenv("WAKE_PREFIXES_EN", ""))
        self.max_pref = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2") or "2")

        # lazán engedjük a “issero/isero/iseero” nyújtásokat
        core_pattern = r"(?:%s)" % "|".join([r"i+ss?e+ro+" for _ in self.core])
        pre_list = [p for p in (self.pref_hu + self.pref_en) if p]
        if pre_list:
            pre_alt = "|".join(re.escape(_norm(p)) for p in pre_list)
            pre_block = rf"(?:\b(?:{pre_alt})\b\s{{0,2}}){{0,{self.max_pref}}}"
        else:
            pre_block = r""

        self._rx = re.compile(
            rf"(?i)(?:^|[\s,;:.—-]){pre_block}\b{core_pattern}\b[!?.,]*"
        )

    def has_wake(self, content: str, *, bot_mention: str | None = None) -> bool:
        if not content:
            return False
        if bot_mention and bot_mention in content:
            return True
        norm = _norm(content)
        return bool(self._rx.search(norm))

    def strip(self, content: str, *, bot_mention: str | None = None) -> str:
        if not content:
            return ""
        t = content
        if bot_mention:
            t = t.replace(bot_mention, " ")
        # a normalizált alapján keressük meg a match szegmenst, majd a “nyersben” nagyjából kivágjuk
        norm = _norm(t)
        m = self._rx.search(norm)
        if not m:
            return re.sub(r"\s+", " ", t).strip()
        # durva kivágás: a match-hez tartozó szavakat a nyersből is eltüntetjük
        span_text = m.group(0)
        # egyszerű stratégia: a “nyers szövegben” is cseréljük a normált rész szavait
        for token in span_text.split():
            if len(token) >= 2:
                t = re.sub(re.escape(token), " ", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip()
        return t
