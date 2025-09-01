# cogs/utils/wake.py
from __future__ import annotations
import os
import re
import unicodedata
from typing import Iterable, Optional

WAKE_CORE = [w.strip() for w in os.getenv("WAKE_CORE", "isero,issero").split(",") if w.strip()]
WAKE_PREFIXES_HU = [w.strip() for w in os.getenv("WAKE_PREFIXES_HU", "").split(",") if w.strip()]
WAKE_PREFIXES_EN = [w.strip() for w in os.getenv("WAKE_PREFIXES_EN", "").split(",") if w.strip()]
WAKE_MAX_PREFIX_TOKENS = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2"))

_WORD_SEP = r"[\s,;:.\-—–!?…]+"


def _fold(s: str) -> str:
    # kisbetű + ékezetlevétel + dupla szóköz gyalulás
    s = s.lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_regex(core: Iterable[str], prefixes_hu: Iterable[str], prefixes_en: Iterable[str], max_pref: int) -> re.Pattern:
    safe = lambda ws: "|".join(re.escape(_fold(w)) for w in ws if w)
    core_pat = r"(?:%s)" % safe(core)
    pref_pat = r"(?:%s)" % safe([*_fold(",".join(prefixes_hu)).split(","), *_fold(",".join(prefixes_en)).split(",")])
    if not pref_pat:
        # csak core
        pat = rf"(?i)(?:^|{_WORD_SEP}){core_pat}(?:{_WORD_SEP}|$)"
    else:
        pat = rf"(?i)(?:^|{_WORD_SEP})(?:\b{pref_pat}\b{_WORD_SEP}{{0,2}}){{0,{max_pref}}}\b{core_pat}\b(?:{_WORD_SEP}|$)"
    return re.compile(pat)


_WAKE_RE = _build_regex(WAKE_CORE, WAKE_PREFIXES_HU, WAKE_PREFIXES_EN, WAKE_MAX_PREFIX_TOKENS)


class WakeMatcher:
    """Kétszintű wake: opcionális előtagok + core név. Mentions élveznek elsőbbséget."""

    def __init__(self, bot_user_id: Optional[int] = None):
        self.bot_user_id = bot_user_id

    def is_wake(self, content: str, mentions_bot: bool) -> bool:
        if mentions_bot:
            return True
        return bool(_WAKE_RE.search(_fold(content)))
