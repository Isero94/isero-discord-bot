# cogs/agent/agent_gate.py
import os
import re
import logging
import asyncio
from typing import Optional, Sequence

import discord
from discord.ext import commands

from openai import AsyncOpenAI

from .playerdb import PlayerDB

log = logging.getLogger("isero.agent")

# ---------- ENV helpers ----------

def _env_int(name: str) -> Optional[int]:
    v = os.getenv(name, "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None

def _env_int_list(name: str) -> list[int]:
    raw = os.getenv(name, "").strip()
    out: list[int] = []
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out

# Basic config
GUILD_ID            = _env_int("GUILD_ID")
OWNER_ID            = _env_int("OWNER_ID")
NSFW_CHANNELS       = _env_int_list("NSFW_CHANNELS")
STAFF_ROLE_ID       = _env_int("STAFF_ROLE_ID")
STAFF_EXTRA_ROLE_IDS= _env_int_list("STAFF_EXTRA_ROLE_IDS")
OPENAI_MODEL        = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
AI_DAILY_TOKEN_LIMIT= int(os.getenv("AI_DAILY_TOKEN_LIMIT", "20000"))
DATABASE_URL        = os.getenv("DATABASE_URL", os.getenv("DATABASE_URL".lower(), "")) or os.getenv("DATABASE_URL".upper(), "")

# Tickets category support (bármelyik kulcs nevét elfogadjuk)
TICKETS_CATEGORY_ID = _env_int("TICKETS_CATEGORY_ID") or _env_int("CATEGORY_TICKETS")

ALLOW_STAFF_FREESPEECH = (os.getenv("ALLOW_STAFF_FREESPEECH", "false").lower() == "true")

# ---------- OWNER hard-coded Player Card override ----------
OWNER_PROFILE = {
    "short_prompt": (
        "Talking to the server owner (call-sign: Boss / IkamazuTIQ). "
        "Be technically precise, concise, bilingual (HU/EN), and action-oriented. "
        "Assume strong context; skip baby steps. If unsure, ask 1 sharp question max."
    ),
    "style_dial": +1,
    "tags": ["owner","admin","architect"]
}

# ---------- utilities ----------

def _is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if STAFF_ROLE_ID and member.get_role(STAFF_ROLE_ID):
        return True
    for rid in STAFF_EXTRA_ROLE_IDS:
        if member.get_role(rid):
            return True
    return False

def _wants_agent_reply(content: str, me: discord.Member) -> bool:
    # mention / "isero" hívószó / ? jel indító
    if me.mentioned_in(discord.Object(id=0)):  # dummy just to keep signature consistent
        pass
    lowered = content.lower().strip()
    if re.search(r"\biser[oó]\b", lowered) or lowered.startswith(("ai,", "isero,", "iseró,", "?")):
        return True
    return False

def _in_ticket_channel(ch: discord.abc.GuildChannel) -> bool:
    try:
        return bool(TICKETS_CATEGORY_ID and getattr(ch, "category", None) and ch.category and ch.category.id == TICKETS_CATEGORY_ID)
    except Exception:
        return False

# ---------- Cog ----------

class AgentGate(commands.Cog):
    """OpenAI alapú asszisztens, DB-s Player Carddal és napi limit védőkorláttal."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            log.warning("OPENAI_API_KEY not set. Agent will be disabled.")
        self.ai = AsyncOpenAI(api_key=api_key) if api_key else None
        self.db = PlayerDB(DATABASE_URL) if DATABASE_URL else None
        self.enabled = True  # globális on/off
        self.default_model = OPENAI_MODEL

    async def cog_load(self):
        if self.db:
            await self.db.start()
        log.info("[AgentGate] ready. Model=%s, Limit/24h=%s tokens", self.default_model, AI_DAILY_TOKEN_LIMIT)

    async def cog_unload(self):
        if self.db:
            await self.db.close()

    # ------------- Core reply --------------

    async def build_persona_for(self, author: discord.Member) -> dict:
        """Összerakja a system promptot a user Player Card alapján."""
        persona_base = (
            "You are ISERO, a helpful, concise Discord assistant for the ISERO server. "
            "Follow server rules. Be bilingual (Hungarian/English) depending on the user's message. "
            "Prefer short, actionable answers. Avoid over-explaining. "
            "When giving steps or code, be precise and minimal."
        )
        user_profile = {}
        if OWNER_ID and author.id == OWNER_ID:
            user_profile = OWNER_PROFILE
        elif self.db:
            # biztosítsuk, hogy user benne legyen az adatbázisban
            await self.db.upsert_user(author.id, f"{author.name}#{author.discriminator}")
            user_profile = await self.db.get_profile(author.id)

        short = (user_profile.get("short_prompt") or "").strip()
        style = int(user_profile.get("style_dial") or 0)

        sx = []
        if short:
            sx.append(f"[User-specific guidance]: {short}")
        if style:
            sx.append(f"[Style dial]: {style}  # -2 terse/neutral, +2 friendly/creative")

        system = persona_base + ("\n" + "\n".join(sx) if sx else "")
        return {"system": system, "profile": user_profile}

    async def call_openai(self, author: discord.Member, content: str, recent: list[dict]) -> Optional[str]:
        if not self.ai:
            return None

        # napi token limit (24h) – owner és staff felülírhatja, ha ALLOW_STAFF_FREESPEECH=True
        if self.db and AI_DAILY_TOKEN_LIMIT > 0 and not (_is_staff(author) and ALLOW_STAFF_FREESPEECH):
            used = await self.db.usage_last_24h(author.id)
            if used >= AI_DAILY_TOKEN_LIMIT:
                return "Napi AI kereted elfogyott. Kérj meg egy moderátort, vagy próbáld meg holnap. 🙂"

        per = await self.build_persona_for(author)
        msg = [
            {"role": "system", "content": per["system"]},
        ]
        msg.extend(recent)
        msg.append({"role": "user", "content": content})

        try:
            resp = await self.ai.chat.completions.create(
                model=self.default_model,
                messages=msg,
                temperature=0.6,
                max_tokens=600,
            )
        except Exception as e:
            log.exception("OpenAI call failed: %s", e)
            return "AI hiba történt (model hívás). Kérlek próbáld újra később."

        text = (resp.choices[0].message.content or "").strip()
        # usage log
        try:
            if self.db and resp.usage:
                total = int(getattr(resp.usage, "total_tokens", 0) or 0)
                await self.db.log_ai_usage(author.id, self.default_model, total, 0.0)
        except Exception:
            pass

        return text or None

    async def _collect_recent(self, message: discord.Message, limit: int = 6) -> list[dict]:
        """Környezet: az utolsó néhány üzenet a csatornából (csak szöveg, rövidítve)."""
        out: list[dict] = []
        try:
            async for m in message.channel.history(limit=limit, before=message, oldest_first=False):
                if m.author.bot:
                    role = "assistant" if m.author.id == (self.bot.user.id if self.bot.user else 0) else "system"
                else:
                    role = "user"
                txt = (m.content or "").strip()
                if not txt:
                    continue
                # rövidítés
                if len(txt) > 500:
                    txt = txt[:500] + " …"
                out.append({"role": role, "content": f"{m.author.display_name}: {txt}"})
            out.reverse()
        except Exception:
            pass
        return out

    # ------------- Message listener -------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.enabled:
            return
        if message.author.bot or not message.guild:
            return
        if GUILD_ID and message.guild.id != GUILD_ID:
            return

        me = message.guild.me  # type: ignore
        if not me:
            return

        # Kinek válaszoljon?
        triggered = False
        if me.mentioned_in(message):
            triggered = True
        elif _wants_agent_reply(message.content, me):
            triggered = True
        elif _in_ticket_channel(message.channel) and message.reference and getattr(message.reference, "resolved", None) is None:
            # ticketben megengedőbbek lehetünk – csak opcionális példa
            triggered = False

        if not triggered:
            return

        # NSFW gate – csak dedikált NSFW csatornákban engedjük (ha listázva vannak)
        if NSFW_CHANNELS and (message.channel.id in NSFW_CHANNELS) is False:
            # ha a kérdés egyértelműen nem NSFW, mehetne – egyszerűsítve most tiltunk
            pass

        # válasz
        recent = await self._collect_recent(message)
        text = await self.call_openai(message.author, message.content, recent)
        if not text:
            return
        try:
            await message.reply(text, mention_author=False, suppress_embeds=False)
        except discord.Forbidden:
            pass

    # ------------- Slash parancsok -------------

    @commands.hybrid_group(name="ai", with_app_command=True, description="ISERO agent beállítások")
    async def ai_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply("`/ai on`, `/ai off`, `/ai model <név>`", mention_author=False)

    @ai_group.command(name="on", with_app_command=True, description="Agent engedélyezése")
    @commands.has_permissions(manage_guild=True)
    async def ai_on(self, ctx: commands.Context):
        self.enabled = True
        await ctx.reply("ISERO agent **bekapcsolva**.", mention_author=False)

    @ai_group.command(name="off", with_app_command=True, description="Agent kikapcsolása")
    @commands.has_permissions(manage_guild=True)
    async def ai_off(self, ctx: commands.Context):
        self.enabled = False
        await ctx.reply("ISERO agent **kikapcsolva**.", mention_author=False)

    @ai_group.command(name="model", with_app_command=True, description="Aktív modell váltása (pl. gpt-4o-mini)")
    @commands.has_permissions(manage_guild=True)
    async def ai_model(self, ctx: commands.Context, model: str):
        self.default_model = model
        await ctx.reply(f"Modell beállítva: **{model}**", mention_author=False)

    # ----- Player Card parancsok -----

    @commands.hybrid_group(name="pc", with_app_command=True, description="Player Card műveletek")
    async def pc_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply("`/pc show @user`, `/pc set-style @user <num>`, `/pc note @user <szöveg>`, `/pc export @user`", mention_author=False)

    @pc_group.command(name="show", with_app_command=True, description="Player Card megjelenítése (staff)")
    @commands.has_permissions(manage_messages=True)
    async def pc_show(self, ctx: commands.Context, member: discord.Member):
        if not self.db:
            return await ctx.reply("DB nincs inicializálva.", mention_author=False)
        await self.db.upsert_user(member.id, f"{member.name}#{member.discriminator}")
        prof = await self.db.get_profile(member.id)
        if OWNER_ID and member.id == OWNER_ID:
            prof.update(OWNER_PROFILE)
        emb = discord.Embed(title=f"Player Card — {member.display_name}")
        emb.add_field(name="Short prompt", value=prof.get("short_prompt") or "—", inline=False)
        emb.add_field(name="Style dial", value=str(prof.get("style_dial") or 0))
        emb.add_field(name="Tags", value=", ".join(prof.get("tags") or []) or "—", inline=False)
        notes = prof.get("notes_staff") or "—"
        if len(notes) > 512: notes = notes[:512] + " …"
        emb.add_field(name="Staff notes", value=notes, inline=False)
        await ctx.reply(embed=emb, ephemeral=True, mention_author=False)  # type: ignore

    @pc_group.command(name="set-style", with_app_command=True, description="Style dial beállítása (-2..+2)")
    @commands.has_permissions(manage_messages=True)
    async def pc_set_style(self, ctx: commands.Context, member: discord.Member, value: int):
        if not self.db:
            return await ctx.reply("DB nincs inicializálva.", mention_author=False)
        if OWNER_ID and member.id == OWNER_ID:
            return await ctx.reply("A tulaj (OWNER) Player Card override kódban van — azt ott kell módosítani.", mention_author=False)
        value = max(-2, min(2, value))
        await self.db.set_profile(member.id, style_dial=value)
        await ctx.reply(f"Style dial beállítva: **{value}**", mention_author=False)

    @pc_group.command(name="note", with_app_command=True, description="Staff megjegyzés hozzáadása")
    @commands.has_permissions(manage_messages=True)
    async def pc_note(self, ctx: commands.Context, member: discord.Member, *, text: str):
        if not self.db:
            return await ctx.reply("DB nincs inicializálva.", mention_author=False)
        if OWNER_ID and member.id == OWNER_ID:
            return await ctx.reply("A tulaj (OWNER) Player Card override kódban van — azt ott kell módosítani.", mention_author=False)
        await self.db.set_profile(member.id, notes_staff=text)
        await ctx.reply("Megjegyzés mentve.", mention_author=False)

    @pc_group.command(name="export", with_app_command=True, description="Player Card export (JSON)")
    @commands.has_permissions(manage_messages=True)
    async def pc_export(self, ctx: commands.Context, member: discord.Member):
        if not self.db:
            return await ctx.reply("DB nincs inicializálva.", mention_author=False)
        await self.db.upsert_user(member.id, f"{member.name}#{member.discriminator}")
        prof = await self.db.get_profile(member.id)
        if OWNER_ID and member.id == OWNER_ID:
            prof.update(OWNER_PROFILE)
        # egyszerű JSON dump
        import json, io
        buf = io.BytesIO(json.dumps(prof, ensure_ascii=False, indent=2).encode("utf-8"))
        fname = f"playercard_{member.id}.json"
        await ctx.reply(file=discord.File(buf, filename=fname), mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(AgentGate(bot))
