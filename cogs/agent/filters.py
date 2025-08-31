import re

# Alap magyar/angol lista – bővíthető. Mindent kisbetűsítünk ellenőrzés előtt.
BAD_WORDS = {
    "bazdmeg", "b*zdmeg", "fasz", "faszom", "segg", "picsa", "kurva", "kúrva",
    "fuck", "fucking", "shit", "asshole", "bitch", "dick", "cunt"
}

PATTERNS = [
    re.compile(r"\b" + re.escape(w) + r"\b", re.I) for w in BAD_WORDS
]

def count_profanity(text: str) -> int:
    if not text:
        return 0
    s = text.lower()
    n = 0
    for rx in PATTERNS:
        n += len(rx.findall(s))
    return n

def censor_outgoing(text: str) -> str:
    if not text:
        return text
    out = text
    for rx in PATTERNS:
        out = rx.sub(lambda m: m.group(0)[0] + "*" * max(1, len(m.group(0)) - 2) + m.group(0)[-1], out)
    return out
