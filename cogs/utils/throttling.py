# cogs/utils/throttling.py
from __future__ import annotations
import hashlib
import time
from typing import Dict, Tuple

class Deduper:
    """Per-channel dedup + cooldown. Nem enged duplát és túl sűrű választ."""
    def __init__(self, cooldown_sec: int = 20, ttl_sec: int = 5):
        self.cooldown = cooldown_sec
        self.ttl = ttl_sec
        # channel_id -> (last_hash, last_time)
        self._state: Dict[int, Tuple[str, float]] = {}

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def allow(self, channel_id: int, text: str) -> bool:
        now = time.time()
        h = self._hash(text)
        last = self._state.get(channel_id)
        if last:
            last_h, last_t = last
            if h == last_h and (now - last_t) < self.ttl:
                return False
            if (now - last_t) < self.cooldown:
                return False
        self._state[channel_id] = (h, now)
        return True
