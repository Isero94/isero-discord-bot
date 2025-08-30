# cogs/agent/playerdb.py
import os
import asyncio
import logging
from typing import Any, Optional

import asyncpg

log = logging.getLogger("isero.playerdb")

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS users (
    user_id      BIGINT      PRIMARY KEY,
    username     TEXT        NOT NULL,
    first_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level        INT         NOT NULL DEFAULT 0,
    rank         TEXT,
    flags        INT         NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id      BIGINT      PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    short_prompt TEXT,
    style_dial   INT         NOT NULL DEFAULT 0,        -- -2..+2 pl.
    tags         TEXT[]      NOT NULL DEFAULT '{}',
    notes_staff  TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    engagement  INT         NOT NULL DEFAULT 0,
    mood        INT         NOT NULL DEFAULT 0,
    promo       INT         NOT NULL DEFAULT 0,
    total       INT         NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS scores_user_ts_idx ON scores(user_id, ts DESC);

CREATE TABLE IF NOT EXISTS ai_usage (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id BIGINT,
    model   TEXT        NOT NULL,
    tokens  INT         NOT NULL DEFAULT 0,
    cost    NUMERIC     NOT NULL DEFAULT 0
);
"""

class PlayerDB:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        async with self._pool.acquire() as con:
            await con.execute(SCHEMA_SQL)
        log.info("PlayerDB connected and schema ensured.")

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ---------------- users / profiles ----------------

    async def upsert_user(self, user_id: int, username: str):
        assert self._pool
        q = """
        INSERT INTO users (user_id, username)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE
          SET username = EXCLUDED.username,
              last_seen = NOW();
        """
        async with self._pool.acquire() as con:
            await con.execute(q, user_id, username)

    async def get_profile(self, user_id: int) -> dict[str, Any]:
        assert self._pool
        q = """
        SELECT u.user_id, u.username, u.level, u.rank, u.flags,
               p.short_prompt, p.style_dial, p.tags, p.notes_staff
          FROM users u
          LEFT JOIN profiles p ON p.user_id = u.user_id
         WHERE u.user_id = $1
        """
        async with self._pool.acquire() as con:
            row = await con.fetchrow(q, user_id)
        if not row:
            return {}
        d = dict(row)
        # Postgres array -> python list
        if d.get("tags") is None:
            d["tags"] = []
        return d

    async def set_profile(
        self,
        user_id: int,
        short_prompt: Optional[str] = None,
        style_dial: Optional[int] = None,
        tags: Optional[list[str]] = None,
        notes_staff: Optional[str] = None,
    ):
        assert self._pool
        # ensure user row
        async with self._pool.acquire() as con:
            async with con.transaction():
                await con.execute(
                    """
                    INSERT INTO users (user_id, username)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    user_id, f"user:{user_id}"
                )
                exists = await con.fetchval(
                    "SELECT 1 FROM profiles WHERE user_id=$1", user_id
                )
                if not exists:
                    await con.execute(
                        "INSERT INTO profiles (user_id) VALUES ($1)", user_id
                    )
                # dynamic update
                sets = []
                vals = []
                if short_prompt is not None:
                    sets.append("short_prompt=$%d" % (len(vals)+1))
                    vals.append(short_prompt)
                if style_dial is not None:
                    sets.append("style_dial=$%d" % (len(vals)+1))
                    vals.append(style_dial)
                if tags is not None:
                    sets.append("tags=$%d" % (len(vals)+1))
                    vals.append(tags)
                if notes_staff is not None:
                    sets.append("notes_staff=$%d" % (len(vals)+1))
                    vals.append(notes_staff)
                if sets:
                    q = "UPDATE profiles SET " + ", ".join(sets) + " WHERE user_id=$%d" % (len(vals)+1)
                    vals.append(user_id)
                    await con.execute(q, *vals)

    # ---------------- scores / usage ----------------

    async def add_score(self, user_id: int, engagement: int, mood: int, promo: int, total: int):
        assert self._pool
        q = "INSERT INTO scores(user_id, engagement, mood, promo, total) VALUES ($1,$2,$3,$4,$5)"
        async with self._pool.acquire() as con:
            await con.execute(q, user_id, engagement, mood, promo, total)

    async def usage_last_24h(self, user_id: int) -> int:
        """Return tokens used by user in last 24h."""
        assert self._pool
        q = "SELECT COALESCE(SUM(tokens),0) FROM ai_usage WHERE user_id=$1 AND ts > NOW() - INTERVAL '24 hours'"
        async with self._pool.acquire() as con:
            v = await con.fetchval(q, user_id)
        return int(v or 0)

    async def log_ai_usage(self, user_id: Optional[int], model: str, tokens: int, cost: float = 0.0):
        assert self._pool
        q = "INSERT INTO ai_usage(user_id, model, tokens, cost) VALUES ($1,$2,$3,$4)"
        async with self._pool.acquire() as con:
            await con.execute(q, user_id, model, tokens, cost)
