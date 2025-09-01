# cogs/utils/text.py
from __future__ import annotations
import re

MAX_REPLY_CHARS = 300  # kemény sapka; ENV-re is tehető, ha akarod

def shorten(s: str, limit: int = MAX_REPLY_CHARS) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"

def no_repeat(s: str) -> str:
    # nagyon egyszerű ismétlésvágó
    s = re.sub(r"(.)\1{4,}", r"\1\1\1", s)  # hosszan ismétlődő karakterek
    s = re.sub(r"(\b.+?\b)(?:\s+\1\b){1,}", r"\1", s, flags=re.IGNORECASE)  # azonos szóduplázás
    return s.strip()
