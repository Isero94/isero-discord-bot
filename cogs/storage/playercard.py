# storage/playercard.py
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import asyncpg
from pydantic import BaseModel, Field

from config import DATABASE_URL, OWNER_ID

# ---------- Pydantic modellek ----------

class PlayerCard(BaseModel):
    user_id: int
    first10: bool = False
    rank: int = 0
    level: int = 0
    lang_pref: str = "auto"

    prompt_snippet: str = ""
    persona_tags: List[str] = Field(default_factory=list)

    scores: Dict[str, float] = Field(default_factory=lambda: {
        "activity": 0.0, "helpfulness": 0.0, "marketing": 0.0, "toxicity": 0.0, "trust": 0.0
    })
    mood: float = 0.0
    marketing_score: int = 0
    profanity: Dict[str, Any] = Field(default_factory=lambda: {"points": 0, "stage": 0, "last_reset_at": None})

    tokens_today: int = 0
    last_seen_at: Optional[datetime] = None
    flags: Dict[str, Any] = Field(default_factory=dict)

# ---------- Tároló réteg (singleton pool) ----------

class PlayerCardStore:
    _pool: Optional[asyncpg.pool.Pool] = None
    _lock = asyncio.Lock()

    @classmethod
    async def pool(cls) -> asyncpg.pool.Pool:
        async with cls._lock:
            if cls._pool is None:
                cls._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
                await cls._ensure_schema()
        return cls._pool

    @classmethod
    async def _ensure_schema(cls) -> None:
        pool = cls._pool
        assert pool is not None
        async with pool.acquire() as con:
            await con.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                first10 BOOL NOT NULL DEFAULT FALSE,
                rank INT NOT NULL DEFAULT 0,
                level INT NOT NULL DEFAULT 0,
                lang_pref TEXT NOT NULL DEFAULT 'auto'
            );
            CREATE TABLE IF NOT EXISTS player_cards (
                user_id BIGINT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
                prompt_snippet TEXT NOT NULL DEFAULT '',
                persona_tags TEXT[] NOT NULL DEFAULT '{}',
                scores JSONB NOT NULL DEFAULT '{}'::jsonb,
                mood DOUBLE PRECISION NOT NULL DEFAULT 0,
                marketing_score INT NOT NULL DEFAULT 0,
                profanity JSONB NOT NULL DEFAULT '{}'::jsonb,
                tokens_today INT NOT NULL DEFAULT 0,
                last_seen_at TIMESTAMPTZ,
                flags JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            CREATE TABLE IF NOT EXISTS signals (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                kind TEXT NOT NULL,
                value DOUBLE PRECISION,
                meta JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)
            # seed owner if needed
            if OWNER_ID:
                row = await con.fetchrow("SELECT user_id FROM players WHERE user_id=$1", OWNER_ID)
                if not row:
                    # owner seed
                    await con.execute("""
                        INSERT INTO players(user_id, first10, rank, level, lang_pref)
                        VALUES ($1, TRUE, 999, 99, 'hu')
                    """, OWNER_ID)
                    await con.execute("""
                        INSERT INTO player_cards(user_id, prompt_snippet, persona_tags, scores, flags)
                        VALUES ($1,
                           $2,
                           $3,
                           $4::jsonb,
                           $5::jsonb
                        )
                    """,
                    OWNER_ID,
                    "Owner/creator. Talk directly, be efficient, assume context. Can ask for diagnostics & budget.",
                    ["owner","admin","poweruser"],
                    json.dumps({"activity":1000,"helpfulness":1000,"marketing":100,"toxicity":0,"trust":1000}),
                    json.dumps({"owner": True})
                    )

    # -------- CRUD --------

    @classmethod
    async def get_card(cls, user_id: int) -> PlayerCard:
        pool = await cls.pool()
        async with pool.acquire() as con:
            row = await con.fetchrow("""
                SELECT p.user_id, p.first10, p.rank, p.level, p.lang_pref,
                       c.prompt_snippet, c.persona_tags, c.scores, c.mood, c.marketing_score,
                       c.profanity, c.tokens_today, c.last_seen_at, c.flags
                FROM players p
                LEFT JOIN player_cards c ON c.user_id = p.user_id
                WHERE p.user_id=$1
            """, user_id)
            if not row:
                # create default
                await con.execute("INSERT INTO players(user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
                await con.execute("INSERT INTO player_cards(user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
                row = await con.fetchrow("""
                    SELECT p.user_id, p.first10, p.rank, p.level, p.lang_pref,
                           c.prompt_snippet, c.persona_tags, c.scores, c.mood, c.marketing_score,
                           c.profanity, c.tokens_today, c.last_seen_at, c.flags
                    FROM players p
                    LEFT JOIN player_cards c ON c.user_id = p.user_id
                    WHERE p.user_id=$1
                """, user_id)
            data = dict(row)
            data["persona_tags"] = list(data["persona_tags"] or [])
            data["scores"] = dict(data["scores"] or {})
            data["profanity"] = dict(data["profanity"] or {})
            data["flags"] = dict(data["flags"] or {})
            return PlayerCard(**data)

    @classmethod
    async def upsert_card(cls, card: PlayerCard) -> None:
        pool = await cls.pool()
        async with pool.acquire() as con:
            await con.execute("INSERT INTO players(user_id, first10, rank, level, lang_pref) VALUES ($1,$2,$3,$4,$5) "
                              "ON CONFLICT (user_id) DO UPDATE SET first10=EXCLUDED.first10, rank=EXCLUDED.rank, "
                              "level=EXCLUDED.level, lang_pref=EXCLUDED.lang_pref",
                              card.user_id, card.first10, card.rank, card.level, card.lang_pref)
            await con.execute("""
                INSERT INTO player_cards(user_id, prompt_snippet, persona_tags, scores, mood, marketing_score, profanity, tokens_today, last_seen_at, flags)
                VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7::jsonb,$8,$9,$10::jsonb)
                ON CONFLICT (user_id) DO UPDATE SET
                  prompt_snippet=EXCLUDED.prompt_snippet,
                  persona_tags=EXCLUDED.persona_tags,
                  scores=EXCLUDED.scores,
                  mood=EXCLUDED.mood,
                  marketing_score=EXCLUDED.marketing_score,
                  profanity=EXCLUDED.profanity,
                  tokens_today=EXCLUDED.tokens_today,
                  last_seen_at=EXCLUDED.last_seen_at,
                  flags=EXCLUDED.flags
            """,
            card.user_id, card.prompt_snippet, card.persona_tags, json.dumps(card.scores), card.mood,
            card.marketing_score, json.dumps(card.profanity), card.tokens_today, card.last_seen_at, json.dumps(card.flags))

    @classmethod
    async def bump_tokens(cls, user_id: int, tokens: int) -> int:
        pool = await cls.pool()
        async with pool.acquire() as con:
            val = await con.fetchval("""
            UPDATE player_cards SET tokens_today = COALESCE(tokens_today,0)+$2, last_seen_at=now() WHERE user_id=$1
            RETURNING tokens_today
            """, user_id, tokens)
            if val is None:
                await con.execute("INSERT INTO player_cards(user_id, tokens_today) VALUES ($1,$2) ON CONFLICT DO NOTHING", user_id, tokens)
                val = tokens
        return int(val)

    @classmethod
    async def add_signal(cls, user_id: int, kind: str, value: float = 0.0, meta: Optional[Dict[str, Any]] = None) -> None:
        pool = await cls.pool()
        async with pool.acquire() as con:
            await con.execute("INSERT INTO signals(user_id, kind, value, meta) VALUES($1,$2,$3,$4::jsonb)",
                              user_id, kind, value, json.dumps(meta or {}))
