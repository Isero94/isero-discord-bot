# utils/wake.py
from __future__ import annotations
import re, unicodedata
from typing import List

def _fold(s: str) -> str:
    # kisbetű + ékezetlehántás + extra szóközök rendezése
    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
    s = re.sub(r"[“”„”]", '"', s)
    s = re.sub(r"[’`´]", "'", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

class WakeMatcher:
    def __init__(self, core: List[str], prefixes: List[str], max_prefix: int = 2):
        self.core = [ _fold(x) for x in core if x ]
        self.pref = [ re.escape(_fold(x)) for x in prefixes if x ]
        pref_group = "|".join(self.pref) if self.pref else ""
        core_group = "|".join([r"i+ss?e+ro+" if c.startswith("isero") else re.escape(c) for c in self.core]) or "isero"
        if pref_group:
            self.rx = re.compile(
                rf"(?i)(?:^|[\s,;:.—-])(?:\b(?:{pref_group})\b[\s,;:.—-]{{0,2}}){{0,{max_prefix}}}\b({core_group})\b[!?.,]*"
            )
        else:
            self.rx = re.compile(rf"(?i)\b({core_group})\b[!?.,]*")

    def is_wake(self, text: str) -> bool:
        return bool(self.rx.search(_fold(text or "")))
