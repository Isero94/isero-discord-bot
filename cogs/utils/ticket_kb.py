import logging
from pathlib import Path
from typing import Dict
import yaml

logger = logging.getLogger(__name__)

def load_ticket_kb(root_dir: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    names = {
        'mebinu': 'kb_mebinu.yml',
        'commission': 'kb_commission.yml',
        'general': 'kb_general.yml',
        'nsfw': 'kb_nsfw.yml',
    }
    base = Path(root_dir)
    for key, fname in names.items():
        p = base / fname
        if not p.exists():
            logger.warning('ISERO/TicketKB: missing %s', p)
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
            out[key] = data
            logger.info('ISERO/TicketKB: loaded %s (%s)', key, p)
        except Exception as e:
            logger.error('ISERO/TicketKB: failed %s (%s)', p, e)
    return out
