import os, asyncio, aiosqlite
from discord.ext import commands
from config import DB_PATH

DB_DIR = os.path.dirname(DB_PATH) or "."
os.makedirs(DB_DIR, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profiles (
  guild_id INTEGER,
  user_id INTEGER,
  stage INTEGER DEFAULT 0,
  swear_excess INTEGER DEFAULT 0,
  last_msg_ts REAL,
  non_en_hu_count INTEGER DEFAULT 0,
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
  category TEXT,
  agent_turns INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage_stats (
  key TEXT PRIMARY KEY,
  value REAL
);
"""

class Profiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        asyncio.create_task(self._init_db())

    async def _init_db(self):
        print(f"[profiles] Using DB_PATH = {DB_PATH}")
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.executescript(SCHEMA)
            await db.commit()
        print("[profiles] DB ready ✅")

    @staticmethod
    async def get_profile(guild_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            cur = await db.execute(
                "SELECT guild_id, user_id, stage, swear_excess, last_msg_ts, non_en_hu_count "
                "FROM user_profiles WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            if row:
                keys = ["guild_id","user_id","stage","swear_excess","last_msg_ts","non_en_hu_count"]
                return dict(zip(keys, row))
            await db.execute("INSERT INTO user_profiles (guild_id, user_id) VALUES (?,?)",(guild_id, user_id))
            await db.commit()
        return await Profiles.get_profile(guild_id, user_id)

    @staticmethod
    async def update_profile(guild_id: int, user_id: int, **kv):
        if not kv: return
        cols = ",".join([f"{k}=?" for k in kv.keys()])
        vals = list(kv.values()) + [guild_id, user_id]
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            await db.execute(f"UPDATE user_profiles SET {cols} WHERE guild_id=? AND user_id=?", vals)
            await db.commit()

async def setup(bot):
    await bot.add_cog(Profiles(bot))
