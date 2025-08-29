from pathlib import Path
import json, time
from typing import Optional, Dict, Any

class JSONStore:
    def __init__(self, base="data"):
        self.base = Path(base)
        (self.base / "players").mkdir(parents=True, exist_ok=True)
        (self.base / "commissions").mkdir(parents=True, exist_ok=True)

    def get_player(self, user_id: int) -> Optional[Dict[str, Any]]:
        p = self.base / "players" / f"{user_id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save_player(self, user_id: int, data: Dict[str, Any]):
        p = self.base / "players" / f"{user_id}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_commission(self, data: Dict[str, Any]):
        ts = int(time.time() * 1000)
        p = self.base / "commissions" / f"{ts}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
