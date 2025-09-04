# region ISERO PATCH hu-tolerant-patterns
try:
    import regex as re  # supports Unicode properties like \P{L}
except Exception:  # pragma: no cover
    import re
from typing import Iterable, List, Tuple

__all__ = [
    "build_patterns",
    "find_matches",
    "mask_spans",
    "tolerant_phrase_regex",
    "tolerant_stem_regex",
    "build_patterns_with_sepmax",
]

SUBS = {
    "a": "[aáä@4]",
    "e": "[eé3]",
    "i": "[ií1!|l]",
    "o": "[oóöő0]",
    "u": "[uúüű]",
    "y": "[yýɏ]",
    "s": "[s$5]",
    "z": "[z2]",
    "g": "[g69]",
    "b": "[b8]",
    "c": "(?:c|ch)",
}
SEP_SYMBOLS = r"[.\-_|:/\\~–—,;!?+'\"()*\[\]{}<>]"
HU_WORD_BOUNDARY = r"\b"

def _char(c: str) -> str:
    return SUBS.get(c, re.escape(c))

def _sep(max_n: int) -> str:
    n = max(0, min(int(max_n or 0), 8))
    # Allow any non-letter sequence (emoji, punctuation, spaces) up to n chars
    return rf"(?:\P{{L}}){{0,{n}}}"

def _token_pat(token: str, sepmax: int, repeatmax: int) -> str:
    SEP = _sep(sepmax)
    rmax = max(1, min(int(repeatmax or 1), 16))
    def _rep(ch: str) -> str:
        base = _char(ch)
        return f"(?:{base}{{1,{rmax}}})"
    return SEP.join(_rep(c) for c in token)

def tolerant_phrase_regex(phrase: str, sepmax: int = 4, repeatmax: int = 1) -> re.Pattern:
    tokens = [t for t in re.split(r"\s+", phrase.strip().lower()) if t]
    if not tokens:
        tokens = [phrase.strip().lower()]
    SEP = _sep(sepmax)
    parts = [f"(?:{_token_pat(t, sepmax, repeatmax)})" for t in tokens]
    pat = rf"{HU_WORD_BOUNDARY}{SEP.join(parts)}{HU_WORD_BOUNDARY}"
    return re.compile(pat, re.IGNORECASE | re.UNICODE)

def tolerant_stem_regex(stem: str, allow_compounds: bool = True, sepmax: int = 4, repeatmax: int = 1) -> re.Pattern:
    s = stem.strip().lower() or stem.lower()
    base = _token_pat(s, sepmax, repeatmax)
    suffix = ""
    if allow_compounds:
        suffix_map = {
            "fasz": r"(?:fej(?:ű|u)?|feju|fejű|fej|szop(?:ó|o|od|d|ja|jál|ni)?|om|omat|odra|od|ok|os|osabb)?",
            "geci": r"(?:s|k|ség|ss?ég|vel|veles)?",
            "kurva": r"(?:ny|z|zás|zva|nagy)?",
            "szar": r"(?:os|rá|ra|ral|ba|ból|rá|osabb)?",
            "buzi": r"(?:s|k|ka|val|ság)?",
            "pina": r"(?:s|val|ba|ból)?",
            "picsa": r"(?:fej|fejű|s|ba|val)?",
            "segg": r"(?:fej|fejű|lyuk|nyal(?:ó|o|ni|t)?|be|es)?",
            "kúr": r"(?:ja|jál|tad|ták|ás|ni)?",
            "csicska": r"(?:fej|fejű|s)?",
        }
        suffix = suffix_map.get(s, r"(?:[a-záéíóöőúüű]{0,3})?")
    pat = rf"{HU_WORD_BOUNDARY}(?:{base}){suffix}{HU_WORD_BOUNDARY}"
    return re.compile(pat, re.IGNORECASE | re.UNICODE)

def build_patterns_with_sepmax(words: Iterable[str], sepmax: int = 4, repeatmax: int = 1) -> List[re.Pattern]:
    seen = set()
    pats: List[re.Pattern] = []
    for w in (words or []):
        w = (w or "").strip().lower()
        if not w or w in seen:
            continue
        seen.add(w)
        if " " in w:
            pats.append(tolerant_phrase_regex(w, sepmax, repeatmax))
        else:
            pats.append(tolerant_stem_regex(w, sepmax=sepmax, repeatmax=repeatmax))
    for base in ("bazd meg", "seggfej"):
        if base not in seen:
            pats.append(tolerant_phrase_regex(base, sepmax, repeatmax))
    return pats

def build_patterns(words: Iterable[str]) -> List[re.Pattern]:
    return build_patterns_with_sepmax(words, sepmax=4, repeatmax=1)

def find_matches(patterns: List[re.Pattern], text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for p in patterns:
        for m in p.finditer(text):
            spans.append((m.start(), m.end()))
    if not spans:
        return []
    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged

def mask_spans(text: str, spans: List[Tuple[int, int]], mask_char: str = "*") -> str:
    if not spans:
        return text
    out = []
    last = 0
    for s, e in spans:
        if s > last:
            out.append(text[last:s])
        out.append(mask_char * max(0, e - s))
        last = e
    if last < len(text):
        out.append(text[last:])
    return "".join(out)
# endregion ISERO PATCH hu-tolerant-patterns
