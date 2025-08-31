# storage/playercard.py
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import asyncpg
from .store import get_pool

@dataclass
class PlayerCard:
    user_id: int
    prompt_snippet: str | None = None
    persona_tags: list[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=lambda: {
        "activity": 0, "helpfulness": 0, "marketing": 0, "toxicity": 0, "trust": 0
    })
    mood: float = 0.0
    marketing_score: int = 0           # 0..100
    profanity: Dict[str, int] = field(default_factory=lambda: {"points": 0, "stage": 0})
    tokens_today: int = 0

class PlayerCardStore:
    @staticmethod
    async def ensure_player(user_id: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                "INSERT INTO players(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", user_id
            )
            await con.execute(
                "INSERT INTO player_cards(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", user_id
            )

    @staticmethod
    async def get_card(user_id: int) -> PlayerCard:
        pool = await get_pool()
        await PlayerCardStore.ensure_player(user_id)
        async with pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM player_cards WHERE user_id=$1", user_id)
        return PlayerCard(
            user_id=row["user_id"],
            prompt_snippet=row["prompt_snippet"],
            persona_tags=row["persona_tags"] or [],
            scores=dict(row["scores"]),
            mood=row["mood"] or 0.0,
            marketing_score=row["marketing_score"] or 0,
            profanity=dict(row["profanity"]),
            tokens_today=row["tokens_today"] or 0,
        )

    @staticmethod
    async def set_prompt(user_id: int, snippet: str | None) -> None:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                "UPDATE player_cards SET prompt_snippet=$2 WHERE user_id=$1",
                user_id, snippet
            )

    @staticmethod
    async def add_signal(user_id: int, kind: str, value: float | None, meta: Dict[str, Any] | None = None) -> None:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                "INSERT INTO signals(user_id, kind, value, meta) VALUES($1,$2,$3,$4)",
                user_id, kind, value, json.dumps(meta or {})
            )

    @staticmethod
    async def bump_marketing(user_id: int, points: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                """
                UPDATE player_cards
                SET marketing_score = LEAST(100, GREATEST(0, marketing_score + $2)),
                    scores = jsonb_set(scores, '{marketing}', to_jsonb(((scores->>'marketing')::float + $3)), true),
                    last_seen_at = NOW()
                WHERE user_id=$1
                """,
                user_id, points, float(points)
            )

    @staticmethod
    async def update_mood(user_id: int, obs: float) -> None:
        # gördülő átlag: új = (régi*0.8 + obs*0.2)
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                """
                UPDATE player_cards
                SET mood = (COALESCE(mood,0)*0.8 + $2*0.2),
                    last_seen_at = NOW()
                WHERE user_id=$1
                """,
                user_id, obs
            )

    @staticmethod
    async def add_profanity_points(user_id: int, points: int, stage_delta: int = 0) -> None:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                """
                UPDATE player_cards
                SET profanity = jsonb_set(
                      jsonb_set(profanity, '{points}', to_jsonb(((profanity->>'points')::int + $2)), true),
                      '{stage}', to_jsonb(((profanity->>'stage')::int + $3)), true
                    ),
                    scores = jsonb_set(scores, '{toxicity}', to_jsonb(((scores->>'toxicity')::float + $2)), true),
                    last_seen_at = NOW()
                WHERE user_id=$1
                """,
                user_id, int(points), int(stage_delta)
            )

    @staticmethod
    async def add_tokens(user_id: int, tokens: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as con:
            await con.execute(
                "UPDATE player_cards SET tokens_today=tokens_today+$2 WHERE user_id=$1", user_id, tokens
            )
