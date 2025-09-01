from __future__ import annotations
import os
import re
from typing import List, Optional

def _csv(val: str | None) -> List[str]:
    if not val:
        return []
    # engedjük az idézőjelek/extra whitespace és dupla vessző hibáit is
    raw = val.strip().strip('"').strip("'")
    parts = [p.strip().strip('"').strip("'") for p in raw.split(",")]
    return [p for p in parts if p]

def _int(val: str | None, default: int) -> int:
    try:
        return int((val or "").strip() or default)
    except Exception:
        return default

WAKE_CORE = _csv(os.getenv("WAKE_CORE", "isero,issero"))
WAKE_PREFIXES_HU = _csv(os.getenv("WAKE_PREFIXES_HU", "hé,hej,szia,helló,hello,na,figyi,hallod,kérlek,légyszi,lécci,pls,oké,csá,uram,mester,tesó,haver,bro,bocsi,bocs"))
WAKE_PREFIXES_EN = _csv(os.getenv("WAKE_PREFIXES_EN", "hey,hi,hello,yo,ok,okay,please,pls,dude,man,sir,boss,bro,excuse me,sorry"))
WAKE_MAX_PREFIX_TOKENS = _int(os.getenv("WAKE_MAX_PREFIX_TOKENS"), 2)

def _build_regex(core_words: List[str], pref_hu: List[str], pref_en: List[str], max_tokens: int) -> re.Pattern:
    # Szóhatáras alternációk, mindent re.escape-eljünk
    core_alt = "|".join(re.escape(w) for w in core_words if w)
    pref_alt = "|".join(re.escape(w) for w in (pref_hu + pref_en) if w)

    # prefix-szekvencia: legfeljebb N darab „prefix + tetszőleges elválasztó”
    # – NEM használunk egymásba ágyazott kvantorokat, elkerülve a „multiple repeat”-et
    if pref_alt:
        prefix_seq = rf"(?:\b(?:{pref_alt})\b[\s,.:;!?-]*){{0,{max_tokens}}}"
    else:
        prefix_seq = ""

    # fő minta: sor/üzenet elején vagy whitespace után: [prefixek]{0,N} + mag
    # a core lehet mention vagy plain szó
    core_pat = rf"(?:@?(?:{core_alt}))\b"
    pat = rf"(?i)(?:^|\s){prefix_seq}{core_pat}"
    return re.compile(pat)

# A mintát modul importkor felépítjük – kivételt nem dobunk ENV hibákra
try:
    _WAKE_RE = _build_regex(WAKE_CORE, WAKE_PREFIXES_HU, WAKE_PREFIXES_EN, WAKE_MAX_PREFIX_TOKENS)
except Exception:
    # nagyon defenzív fallback
    _WAKE_RE = re.compile(r"(?i)(?:^|\s)@?(?:isero|issero)\b")

class WakeMatcher:
    def has_wake(self, text: str, bot_mention: Optional[str] = None) -> bool:
        if not text:
            return False
        if bot_mention and bot_mention in text:
            return True
        return _WAKE_RE.search(text) is not None

    def strip(self, text: str, bot_mention: Optional[str] = None) -> str:
        if not text:
            return ""
        t = text
        if bot_mention and bot_mention in t:
            t = t.replace(bot_mention, "")
        # csak az elejéről csapjuk le a prefix+core részt
        t = re.sub(_WAKE_RE, "", t, count=1)
        # felesleges whitespace-ek
        return re.sub(r"\s+", " ", t).strip()
