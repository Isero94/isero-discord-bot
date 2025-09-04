import json
import logging
from typing import Iterable, List
from pathlib import Path

logger = logging.getLogger(__name__)

def _read_lines(p: Path) -> List[str]:
    try:
        if not p.exists():
            return []
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        return []

def load_db(db_path: str, packs: Iterable[str]) -> List[str]:
    """Betölti a miniDB JSON-t + opcionális pack fájlokat (txt), majd egyesít."""
    words: List[str] = []
    try:
        p = Path(db_path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for lang in ("hu", "en"):
                section = (data or {}).get(lang, {})
                words += (section.get("stems", []) or []) + (section.get("phrases", []) or [])
            logger.info("ISERO/ProfanityDB: loaded %d words from %s", len(words), db_path)
        else:
            logger.info("ISERO/ProfanityDB: %s not found → using packs only", db_path)
    except Exception as e:
        logger.warning("ISERO/ProfanityDB: failed to load %s (%s)", db_path, e)
    for raw in (packs or []):
        p = Path(raw.strip())
        add = _read_lines(p)
        if add:
            words += add
            logger.info("ISERO/ProfanityDB: loaded %d words from pack %s", len(add), p)
    out, seen = [], set()
    for w in words:
        lw = (w or "").strip().lower()
        if not lw or lw in seen:
            continue
        seen.add(lw)
        out.append(lw)
    logger.info("ISERO/ProfanityDB: merged total %d base entries", len(out))
    return out
