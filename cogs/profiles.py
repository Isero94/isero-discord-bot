import os
import asyncio
import aiosqlite
from discord.ext import commands

# ---- DB path: env -> fallback ----
DB_PATH = os.getenv("DB_PATH", "data/isero.db")
DB_DIR = os.path.dirname(DB_PATH) or "."

# biztos, hogy a könyvtár létezik
os.makedirs(DB_DIR, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profiles (
  guild_id INTEGER,
  user_id INTEGER,
  stage INTEGER DEFAULT 0,
  swear_hits INTEGER DEFAULT 0,
  timeouts INTEGER DEFAULT 0,
  perma_flag INTEGER DEFAULT 0,
  intent_score REAL DEFAULT 0,
  mood_score REAL DEFAULT 50,
  msg_total INTEGER DEFAULT 0,
  msg_since_lang INTEGER DEFAULT 0,
  last_msg_ts REAL,
  PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS tickets (
  guild_id INTEGER,
  channel_id INTEGER PRIMARY KEY,
  user_id INTEGER,
  opened_ts REAL,
  last_user_msg_ts REAL,
  user_msg_count INTEGER DEFAULT 0,
  status TEXT DEFAULT "open",
  category TEXT
);
CREATE TABLE IF NOT EXISTS usage_stats (
  key TEXT PRIMARY KEY,
  value REAL
);
CREATE TABLE IF NOT EXISTS assistant_threads (
  guild_id INTEGER,
  user_id INTEGER,
  thread_id TEXT,
  last_dm_ts REAL,
  PRIMARY KEY (guild_id, user_id)
);
"""

class Profiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _init_db(self):
        # Jelöld a logban, hogy mit használ
        print(f"[profiles] Using DB_PATH = {DB_PATH}")
        # Kapcsolódás + alap PRAGMA-k
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.executescript(SCHEMA)
            await db.commit()
        print("[profiles] DB ready ✅")

    @staticmethod
    async def get_profile(guild_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            cur = await db.execute(
                """
                SELECT guild_id, user_id, stage, swear_hits, timeouts, perma_flag,
                       intent_score, mood_score, msg_total, msg_since_lang, last_msg_ts
                FROM user_profiles
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            if row:
                keys = [
                    "guild_id","user_id","stage","swear_hits","timeouts","perma_flag",
                    "intent_score","mood_score","msg_total","msg_since_lang","last_msg_ts"
                ]
                return dict(zip(keys, row))

            # ha nincs, beszúrjuk az alap rekordot
            await db.execute(
                "INSERT INTO user_profiles (guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await db.commit()

        # rekurzívan visszaolvassuk, hogy map-et adjunk vissza
        return await Profiles.get_profile(guild_id, user_id)

    @staticmethod
    async def update_profile(guild_id: int, user_id: int, **kv):
        if not kv:
            return
        cols = ",".join([f"{k}=?" for k in kv.keys()])
        vals = list(kv.values()) + [guild_id, user_id]
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await db.execute(
                f"UPDATE user_profiles SET {cols} WHERE guild_id=? AND user_id=?",
                vals,
            )
            await db.commit()

async def setup(bot):
    cog = Profiles(bot)
    await bot.add_cog(cog)
    # külön taskként indítjuk az initet, hogy ne blokkoljon
    asyncio.create_task(cog._init_db())
