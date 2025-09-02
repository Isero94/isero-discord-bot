# cogs/utils/text.py
from __future__ import annotations
import re
from typing import List, Optional

from bot.config import settings


def shorten(s: str, limit: Optional[int] = None) -> str:
    """Condense whitespace and cut to ``limit`` characters with ellipsis."""
    limit = limit or settings.MAX_MSG_CHARS
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


def truncate_by_chars(s: str, limit: int) -> str:
    """Cut string to ``limit`` characters, appending ellipsis if truncated."""
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


def no_repeat(s: str) -> str:
    """Collapse long character runs and duplicate words."""
    s = re.sub(r"(.)\1{4,}", r"\1\1\1", s)
    s = re.sub(r"(\b.+?\b)(?:\s+\1\b){1,}", r"\1", s, flags=re.IGNORECASE)
    return s.strip()


def chunk_message(text: str, limit: Optional[int] = None) -> List[str]:
    """Split ``text`` into <=limit character pieces with (n/m) prefixes.

    Each chunk fits within ``limit`` including the ``(n/m)`` marker when
    multiple chunks are returned.
    """
    limit = limit or settings.MAX_MSG_CHARS
    if len(text) <= limit:
        return [text]
    raw_chunks = [text[i : i + limit] for i in range(0, len(text), limit)]
    total = len(raw_chunks)
    out: List[str] = []
    for idx, chunk in enumerate(raw_chunks, start=1):
        if total > 1:
            prefix = f"({idx}/{total}) "
        else:
            prefix = ""
        allowed = limit - len(prefix)
        out.append(prefix + chunk[:allowed])
    return out
