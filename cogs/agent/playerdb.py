from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict, Any

# region ISERO PATCH ticket_session imports
from dataclasses import dataclass, field
import datetime
# endregion ISERO PATCH ticket_session imports

import asyncpg

log = logging.getLogger("isero.playerdb")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
  user_id     BIGINT PRIMARY KEY,
  display     TEXT,
  role        TEXT CHECK (role IN ('owner','staff','user')) DEFAULT 'user',
  trust       SMALLINT DEFAULT 0,
  locale      TEXT DEFAULT 'en',
  style       TEXT DEFAULT 'pro_sarcastic_concise',
  allow_admin BOOLEAN DEFAULT FALSE,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT REFERENCES players(user_id),
  channel_id BIGINT,
  sentiment  REAL,
  intent     TEXT,
  score      SMALLINT,
  ts         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS briefs (
  id               BIGSERIAL PRIMARY KEY,
  user_id          BIGINT REFERENCES players(user_id),
  ticket_channel_id BIGINT,
  type             TEXT,
  goal             TEXT,
  deadline         TEXT,
  refs_count       SMALLINT DEFAULT 0,
  status           TEXT DEFAULT 'open',
  created_at       TIMESTAMPTZ DEFAULT now(),
  updated_at       TIMESTAMPTZ DEFAULT now()
);
"""

class PlayerDB:
    def __init__(self, dsn: str, owner_id: int | None = None):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._owner_id = owner_id
        # region ISERO PATCH in-memory-fallback
        self._mem: Dict[int, Dict[str, Any]] = {}
        # endregion

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        async with self._pool.acquire() as con:
            await con.execute(SCHEMA_SQL)
            if self._owner_id:
                await con.execute(
                    """
                    INSERT INTO players(user_id, role, trust, allow_admin, locale, style)
                    VALUES($1,'owner',3,TRUE,'hu','pro_sarcastic_concise')
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    self._owner_id,
                )
        log.info("PlayerDB ready")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_player(self, user_id: int) -> Optional[asyncpg.Record]:
        assert self._pool
        async with self._pool.acquire() as con:
            return await con.fetchrow("SELECT * FROM players WHERE user_id=$1", user_id)

    async def set_pref(self, user_id: int, locale: Optional[str], style: Optional[str]) -> None:
        assert self._pool
        async with self._pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO players(user_id, locale, style)
                VALUES($1, COALESCE($2,'en'), COALESCE($3,'pro_sarcastic_concise'))
                ON CONFLICT (user_id) DO UPDATE SET
                    locale = COALESCE($2, players.locale),
                    style  = COALESCE($3, players.style),
                    updated_at = now()
                """,
                user_id, locale, style
            )

    async def log_signal(self, user_id: int, channel_id: int, sentiment: float, intent: str, score: int) -> None:
        assert self._pool
        async with self._pool.acquire() as con:
            await con.execute(
                "INSERT INTO signals(user_id, channel_id, sentiment, intent, score) VALUES($1,$2,$3,$4,$5)",
                user_id, channel_id, sentiment, intent, score
            )

    async def get_scores(self, user_id: int) -> Tuple[float, float]:
        """Return (mood_score, marketing_score)."""
        assert self._pool
        async with self._pool.acquire() as con:
            mood = await con.fetchval(
                "SELECT COALESCE(AVG(sentiment),0) FROM signals WHERE user_id=$1", user_id
            )
            marketing = await con.fetchval(
                "SELECT COALESCE(AVG(score),0) FROM signals WHERE user_id=$1 AND intent='buy'",
                user_id,
            )
        return float(mood or 0.0), float(marketing or 0.0)

    async def allow_admin(self, user_id: int) -> bool:
        assert self._pool
        async with self._pool.acquire() as con:
            v = await con.fetchval(
                "SELECT allow_admin FROM players WHERE user_id=$1", user_id
            )
        return bool(v)

    # region ISERO PATCH player-snapshot-api
    def get_snapshot(self, user_id: int) -> Dict[str, Any]:
        """Gyors olvasás a sales/agent komponenseknek (blocking)."""
        try:
            return dict(self._mem.get(user_id) or {})
        except Exception:
            return {}

    async def set_fields(self, user_id: int, **fields: Any) -> None:
        """Memóriába ír, opcionálisan DB-be is."""
        base = self._mem.get(user_id) or {}
        base.update(fields)
        self._mem[user_id] = base
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as con:
                await con.execute(
                    "INSERT INTO players(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING",
                    user_id,
                )
        except Exception:
            pass
    # endregion

# region ISERO PATCH ticket_session

@dataclass
class TicketSession:
    channel_id: int
    owner_id: int
    type: str
    stage: int = 1
    answers: dict[str, str] = field(default_factory=dict)
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    last_turn_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)

_ticket_sessions: dict[int, TicketSession] = {}


def get_ticket_session(channel_id: int) -> TicketSession | None:
    return _ticket_sessions.get(channel_id)


def upsert_ticket_session(session: TicketSession) -> None:
    session.last_turn_at = datetime.datetime.utcnow()
    _ticket_sessions[session.channel_id] = session


def clear_ticket_session(channel_id: int) -> None:
    _ticket_sessions.pop(channel_id, None)

# endregion ISERO PATCH ticket_session
