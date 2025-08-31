# cogs/utils/wake.py
# Ébresztési segéd: előtag + CORE kulcsszó, diakritika-normalizálással, max N előtag engedve.
from __future__ import annotations

import os
import re
import unicodedata
from typing import List, Tuple, Set

# --- ENV olvasók ---

def _csv(val: str | None) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]

# CORE nevek (ritkán változnak) – ha nincs ENV: "isero, issero"
WAKE_CORE: List[str] = _csv(os.getenv("WAKE_CORE")) or ["isero", "issero"]

# HU/EN előtagok – ha nincs ENV: készlet alább
DEFAULT_PREFIXES_HU = [
    "hé","hej","szia","hello","helló","na","figyi","hallod","kérlek","légyszi","lécci",
    "pls","oké","csá","uram","mester","tesó","haver","bro","bocsi","bocs"
]
DEFAULT_PREFIXES_EN = [
    "hey","hi","hello","yo","ok","okay","please","pls","dude","man","sir","boss","bro","excuse me","sorry"
]
WAKE_PREFIXES_HU: List[str] = _csv(os.getenv("WAKE_PREFIXES_HU")) or DEFAULT_PREFIXES_HU
WAKE_PREFIXES_EN: List[str] = _csv(os.getenv("WAKE_PREFIXES_EN")) or DEFAULT_PREFIXES_EN

# max hány előtag állhat közvetlenül a CORE előtt (0, 1 vagy 2 javasolt)
try:
    WAKE_MAX_PREFIX_TOKENS: int = int(os.getenv("WAKE_MAX_PREFIX_TOKENS", "2"))
except Exception:
    WAKE_MAX_PREFIX_TOKENS = 2

# --- normalizálás ---

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)     # minden nem betű/szám/whitespace -> space
_WS_RE    = re.compile(r"\s+")

def _strip_accents(s: str) -> str:
    # NFD + Mn szűrés → "hé" -> "he"
    nf = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nf if unicodedata.category(ch) != "Mn")

def normalize(s: str) -> str:
    s = s.lower()
    s = _strip_accents(s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s

def tokenize(s: str) -> List[str]:
    s = normalize(s)
    return [t for t in s.split(" ") if t]

# --- ébresztés logika ---

# Fuzzy CORE: engedi a "issero", "iseroo", "isseroo" stb. apró elütéseket/nyújtásokat
_CORE_PATTERN = re.compile(r"^i+ss?e+ro+$")

def _is_core(tok: str, cores: Set[str]) -> bool:
    # Ha pontos CORE (pl. "isero"), vagy fuzzy egyezés:
    return tok in cores or bool(_CORE_PATTERN.fullmatch(tok))

def has_mention(raw: str, bot_id: int) -> bool:
    return f"<@{bot_id}>" in raw or f"<@!{bot_id}>" in raw

def should_wake(raw: str, bot_id: int) -> bool:
    if has_mention(raw, bot_id):
        return True

    cores: Set[str] = set(tokenize(" ".join(WAKE_CORE)))
    prefixes: Set[str] = set(tokenize(" ".join(WAKE_PREFIXES_HU + WAKE_PREFIXES_EN)))
    toks = tokenize(raw)
    if not toks:
        return False

    for i, t in enumerate(toks):
        if _is_core(t, cores):
            # legfeljebb N közvetlen előtte álló token engedett, és mind prefix legyen
            start = max(0, i - WAKE_MAX_PREFIX_TOKENS)
            before = toks[start:i]
            # üres before -> ok; ha nem üres, minden elem prefix?
            if all(b in prefixes for b in before):
                return True
    return False

def strip_wake(raw: str, bot_id: int) -> str:
    """Eltávolítja a mentiont és a felismerhető előtag+CORE blokkot; visszaadja a többi szöveget."""
    # mentionok leszedése nyersen
    raw2 = raw.replace(f"<@{bot_id}>", " ").replace(f"<@!{bot_id}>", " ")
    toks = tokenize(raw2)
    if not toks:
        return raw2.strip()

    cores: Set[str] = set(tokenize(" ".join(WAKE_CORE)))
    prefixes: Set[str] = set(tokenize(" ".join(WAKE_PREFIXES_HU + WAKE_PREFIXES_EN)))

    i_core = None
    for i, t in enumerate(toks):
        if _is_core(t, cores):
            i_core = i
            break

    if i_core is None:
        # nincs CORE: marad a mention nélküli szöveg
        return normalize(raw2)

    start = max(0, i_core - WAKE_MAX_PREFIX_TOKENS)
    # visszafelé csak prefixeket törlünk
    j = i_core
    k = i_core
    while j > start and toks[j - 1] in prefixes:
        j -= 1
    # törlendő szelet: [j, k] (prefixek + core)
    keep = toks[:j] + toks[k + 1:]
    return " ".join(keep).strip()
