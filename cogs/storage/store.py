# storage/store.py
from __future__ import annotations
import os
import asyncpg
import logging

log = logging.getLogger("isero.playerdb")

_POOL: asyncpg.Pool | None = None

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS players (
  user_id BIGINT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  first10 BOOLEAN NOT NULL DEFAULT FALSE,
  rank INT NOT NULL DEFAULT 0,
  level INT NOT NULL DEFAULT 0,
  lang_pref TEXT,
  flags JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS player_cards (
  user_id BIGINT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
  prompt_snippet TEXT,
  persona_tags TEXT[] DEFAULT '{}',
  scores JSONB NOT NULL DEFAULT '{"activity":0,"helpfulness":0,"marketing":0,"toxicity":0,"trust":0}'::jsonb,
  mood DOUBLE PRECISION DEFAULT 0,
  marketing_score INT NOT NULL DEFAULT 0,
  profanity JSONB NOT NULL DEFAULT '{"points":0,"stage":0}'::jsonb,
  tokens_today INT NOT NULL DEFAULT 0,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS signals (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  kind TEXT NOT NULL,
  value DOUBLE PRECISION,
  meta JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

async def get_pool() -> asyncpg.Pool:
    global _POOL
    if _POOL:
        return _POOL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL hiányzik az ENV-ből")
    _POOL = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=5)
    async with _POOL.acquire() as con:
        await con.execute(SCHEMA)
    log.info("isero.playerdb: schema ensured.")
    return _POOL
