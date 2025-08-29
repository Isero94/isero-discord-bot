import asyncpg
import asyncio
from discord.ext import commands
from config import DATABASE_URL

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profiles (
  guild_id BIGINT,
  user_id BIGINT,
  stage INT DEFAULT 0,
  swear_excess INT DEFAULT 0,
  last_msg_ts DOUBLE PRECISION,
  non_en_hu_count INT DEFAULT 0,
  PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS tickets (
  guild_id BIGINT,
  channel_id BIGINT PRIMARY KEY,
  user_id BIGINT,
  opened_ts DOUBLE PRECISION,
  last_user_msg_ts DOUBLE PRECISION,
  user_msg_count INT DEFAULT 0,
  status TEXT DEFAULT 'open',
  category TEXT,
  agent_turns INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage_stats (
  key TEXT PRIMARY KEY,
  value DOUBLE PRECISION
);
"""

class Profiles(commands.Cog):
    pool = None
    def __init__(self, bot):
        self.bot = bot
        asyncio.create_task(self._init_db())

    def cog_unload(self):
        if self.pool:
            asyncio.create_task(self.pool.close())

    async def _init_db(self):
        if not DATABASE_URL:
            print("[profiles] DATABASE_URL is not set. Database features will be unavailable.")
            return
        # Render Postgres usually needs SSL
        Profiles.pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
        async with Profiles.pool.acquire() as conn:
            await conn.execute(SCHEMA)
        print("[profiles] PostgreSQL DB ready ✅")

    @staticmethod
    async def get_profile(guild_id: int, user_id: int):
        if not Profiles.pool: return {}
        async with Profiles.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE guild_id=$1 AND user_id=$2",
                guild_id, user_id
            )
            if row:
                return dict(row)
            await conn.execute(
                "INSERT INTO user_profiles (guild_id, user_id) VALUES ($1,$2)",
                guild_id, user_id
            )
            return await Profiles.get_profile(guild_id, user_id)

    @staticmethod
    async def update_profile(guild_id: int, user_id: int, **kv):
        if not Profiles.pool or not kv: return
        cols = ", ".join([f"{k}=${i+3}" for i, k in enumerate(kv.keys())])
        vals = [guild_id, user_id] + list(kv.values())
        async with Profiles.pool.acquire() as conn:
            await conn.execute(f"UPDATE user_profiles SET {cols} WHERE guild_id=$1 AND user_id=$2", *vals)

async def setup(bot):
    await bot.add_cog(Profiles(bot))
