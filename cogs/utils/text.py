# utils/text.py
import re
from typing import Tuple

_WORD_RE = re.compile(r"\w+", re.UNICODE)

def star_profanity(text: str, profane: set[str], free_words: int = 2) -> Tuple[str, int]:
    """Visszaad: (csillagozott_szöveg, csúnya_szavak_száma)."""
    count = 0
    def repl(m: re.Match) -> str:
        nonlocal count
        w = m.group(0)
        lw = w.lower()
        if lw in profane:
            count += 1
            if count > free_words:
                return w[0] + "*"*(max(0, len(w)-2)) + (w[-1] if len(w) > 1 else "")
        return w
    return _WORD_RE.sub(repl, text), count
