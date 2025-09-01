# cogs/utils/wake.py
# Biztonságos, ENV-ből paraméterezhető wake matcher ISERO-hoz.
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

def _split_csv(val: str | None) -> List[str]:
    if not val:
        return []
    parts = [p.strip() for p in val.split(",")]
    # üres, duplikált és túl rövid tokenek kidobása
    clean = []
    seen = set()
    for p in parts:
        if not p:
            continue
        if p.lower() in seen:
            continue
        seen.add(p.lower())
        clean.append(p)
    return clean

def _mk_alt(tokens: Iterable[str]) -> Optional[str]:
    toks = [t for t in (re.escape(x.strip()) for x in tokens) if t]
    if not toks:
        return None
    # hossz szerint rendezés, hogy a hosszabb variáns előbb illeszkedjen
    toks = sorted(set(toks), key=len, reverse=True)
    return r"(?:%s)" % "|".join(toks)

@dataclass
class WakeConfig:
    core_names: List[str]
    prefixes_hu: List[str]
    prefixes_en: List[str]
    max_prefix_tokens: int

    @classmethod
    def from_env(cls) -> "WakeConfig":
        core = _split_csv(os.getenv("WAKE_CORE") or "isero,issero")
        pf_hu = _split_csv(os.getenv("WAKE_PREFIXES_HU") or "hé,szia,hello,helló,na,figyi,kérlek,pls")
        pf_en = _split_csv(os.getenv("WAKE_PREFIXES_EN") or "hey,hi,hello,please,pls")
        try:
            mpt = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2"))
        except Exception:
            mpt = 2
        # biztonsági korlát
        mpt = max(0, min(mpt, 4))
        return cls(core, pf_hu, pf_en, mpt)

class WakeMatcher:
    """
    Egyszerű, de strapabíró „ébresztő”:
      - Mentions: <@id> → azonnal wake
      - Core név (pl. isero, issero) bárhol a szövegben → wake
      - Prefix(ek) a sor elején (0..N) + core később → wake
    A strip() kiveszi az elejéről a mentiont/prefixet/core-t és visszaadja a hasznos promptot.
    """
    def __init__(self, cfg: Optional[WakeConfig] = None):
        self.cfg = cfg or WakeConfig.from_env()
        self._core_alt = _mk_alt(self.cfg.core_names)

        # prefix alt – hu+en együtt
        pf_all = self.cfg.prefixes_hu + self.cfg.prefixes_en
        self._pf_alt = _mk_alt(pf_all)

        # prefix-block regex az elejéről, 0..max darab szó
        if self._pf_alt:
            self._pref_re = re.compile(
                rf"^(?:\s*{self._pf_alt}\s+)" rf"{{0,{self.cfg.max_prefix_tokens}}}",
                flags=re.IGNORECASE
            )
        else:
            self._pref_re = None

        # core a sor elején (miután prefixet levettük)
        if self._core_alt:
            self._core_head_re = re.compile(
                rf"^\s*{self._core_alt}\s*[:,\-–—]*\s*",
                flags=re.IGNORECASE
            )
        else:
            self._core_head_re = None

    # ---- API ----
    def has_wake(self, text: str, *, bot_mention: Optional[str] = None) -> bool:
        if not text:
            return False
        if bot_mention and bot_mention in text:
            return True
        low = text.lower()

        # core bárhol
        if self._core_alt and re.search(self._core_alt, low, flags=re.IGNORECASE):
            return True

        # prefixek a sor elején + később core
        if self._pref_re and self._core_alt:
            tail = self._pref_re.sub("", text, count=1)
            if re.search(self._core_alt, tail, flags=re.IGNORECASE):
                return True

        return False

    def strip(self, text: str, *, bot_mention: Optional[str] = None) -> str:
        if not text:
            return ""
        t = text

        # mention kivágása bárhonnan
        if bot_mention and bot_mention in t:
            t = t.replace(bot_mention, " ")

        # elejéről prefix blokk
        if self._pref_re:
            t = self._pref_re.sub("", t, count=1)

        # elejéről core
        if self._core_head_re:
            t = self._core_head_re.sub("", t, count=1)

        # maradék felesleges kezdő írásjelek
        t = re.sub(r"^[\s:,\-–—]+", "", t)
        return t.strip()
