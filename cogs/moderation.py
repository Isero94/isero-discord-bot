import re, time, asyncio
from discord.ext import commands
from .profiles import Profiles
import discord

BAD_WORDS = [
    "fuck","shit","bitch","asshole","bastard","cunt","dick","pussy","faggot","moron","retard",
    "kurva","geci","fasz","picsa","segg","buzi","köcsög","szar","hülye"
]
BAD_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in BAD_WORDS) + r")\b", re.IGNORECASE)

MUTE_ROLE_NAME = "Muted"

async def ensure_mute_role(guild):
    role = next((r for r in guild.roles if r.name == MUTE_ROLE_NAME), None)
    if role: return role
    try:
        role = await guild.create_role(name=MUTE_ROLE_NAME, reason="Auto moderation mute role")
        for ch in guild.channels:
            try:
                await ch.set_permissions(role, send_messages=False, add_reactions=False, speak=False)
            except Exception:
                pass
        return role
    except Exception as e:
        print(f"[moderation] cannot create mute role: {e}")
        return None

async def temp_mute(member, seconds: int, reason: str):
    role = await ensure_mute_role(member.guild)
    if not role: return
    try:
        await member.add_roles(role, reason=reason)
    except Exception as e:
        print(f"[moderation] add role failed: {e}")
        return
    async def unmute_later():
        await asyncio.sleep(seconds)
        try:
            await member.remove_roles(role, reason="Timeout over")
        except Exception:
            pass
    member.guild._state.loop.create_task(unmute_later())

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        content = message.content or ""
        prof = await Profiles.get_profile(message.guild.id, message.author.id)

        # NOTE: No language nagging. Hungarian and English are both fine,
        # and we won't DM people about language usage.

        # Swear word logic with a tolerance of 2 per message
        bads = len(BAD_RE.findall(content))
        excess = max(0, bads - 2)
        stage = prof.get("stage") or 0
        total = prof.get("swear_excess") or 0

        action = None
        if excess > 0:
            if stage == 0:
                total += excess
                if total >= 5:
                    stage = 1
                    action = ("mute", 40*60, "Stage 1: 40 min timeout (excess >= 5)")
            elif stage == 1:
                total += excess
                if total >= 3:
                    stage = 2
                    action = ("mute", 8*60*60, "Stage 2: 8 hours timeout (excess >= 3)")
            elif stage == 2:
                total += excess
                if total >= 1:
                    stage = 3
                    action = ("perma", None, "Stage 3: Permanent mute")
        
        await Profiles.update_profile(message.guild.id, message.author.id, stage=stage, swear_excess=total, last_msg_ts=time.time())

        if action:
            kind, seconds, reason = action
            if kind == "mute":
                await temp_mute(message.author, seconds, reason)
                try:
                    await message.reply(f"🔇 {reason}")
                except Exception:
                    pass
            else:
                role = await ensure_mute_role(message.guild)
                if role:
                    try:
                        await message.author.add_roles(role, reason=reason)
                        await message.reply(f"🔒 {reason}")
                    except Exception as e:
                        print(f"[moderation] perma mute failed: {e}")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
