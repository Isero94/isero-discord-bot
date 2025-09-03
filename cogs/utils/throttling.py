# cogs/utils/throttling.py
from __future__ import annotations
import hashlib
import time
from typing import Dict, Tuple
import time

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


_redir_state: Dict[str, float] = {}

# ISERO PATCH: simple point tracker with TTL
_points: Dict[str, Tuple[int, float]] = {}


class PerUserChannelTTL:
    def __init__(self, ttl: int = 30):
        self.ttl = ttl
        self._last: Dict[Tuple[int, int], float] = {}

    def allow(self, user_id: int, channel_id: int) -> bool:
        now = time.time()
        key = (user_id, channel_id)
        last = self._last.get(key, 0.0)
        if now - last < self.ttl:
            return False
        self._last[key] = now
        return True


def should_redirect(key: str, ttl: int = 120) -> bool:
    """Return True if redirect should be sent for ``key`` (else dedup)."""
    now = time.time()
    last = _redir_state.get(key, 0.0)
    if now - last < ttl:
        return False
    _redir_state[key] = now
    return True


def add_points(key: str, amount: int, ttl: int = 180) -> int:
    """Add ``amount`` points to ``key`` and return new total (with TTL)."""
    now = time.time()
    total, expires = _points.get(key, (0, 0.0))
    if now > expires:
        total = 0
    total += int(amount)
    _points[key] = (total, now + ttl)
    return total


def bump_score(scope, inc: int, ttl_seconds: int) -> int:
    key = ":".join(str(x) for x in scope)
    return add_points(key, inc, ttl_seconds)


def get_score(scope) -> int:
    key = ":".join(str(x) for x in scope)
    total, expires = _points.get(key, (0, 0.0))
    if time.time() > expires:
        return 0
    return total
