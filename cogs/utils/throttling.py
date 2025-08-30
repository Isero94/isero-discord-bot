# cogs/utils/throttling.py
import time
from typing import Dict

class Throttle:
    def __init__(self):
        self._last: Dict[str, float] = {}

    def remaining(self, key: str, cooldown_sec: int) -> int:
        now = time.time()
        t = self._last.get(key, 0.0)
        left = int(cooldown_sec - (now - t))
        return left if left > 0 else 0

    def allow(self, key: str, cooldown_sec: int) -> bool:
        left = self.remaining(key, cooldown_sec)
        if left > 0:
            return False
        self._last[key] = time.time()
        return True
