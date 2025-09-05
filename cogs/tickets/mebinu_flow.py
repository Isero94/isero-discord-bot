from __future__ import annotations

import time
import os
import re
import logging
from dataclasses import dataclass, field
from typing import List
import discord
import datetime as dt
from discord.ext import commands
from ..utils.prompt import compose_mebinu_prompt
from ..utils.sales import calc_total, env_prices
from .general_flow import _is_nsfw_env

MAX_TURNS = 10

log = logging.getLogger("ISERO.Mebinu")

# region ISERO PATCH legacy-flags
def _envb(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")

_SUPPRESS_ALWAYS = _envb("MEBINU_SUPPRESS_LEGACY_ALWAYS", "true")
_LEGACY_VISIBLE = _envb("MEBINU_LEGACY_HINT_VISIBLE", "false")
_LEGACY_ENABLED = (_LEGACY_VISIBLE and not _SUPPRESS_ALWAYS)
_SWEEP_EVERY_MSG = _envb("MEBINU_SWEEP_EVERY_MSG", "true")
# endregion

QUESTIONS = [
    "Melyik termék vagy variáns érdekel?",
    "Milyen stílus/színvilág tetszik? (adj példát)",
    "Mi a határidő? (nap/dátum)",
    "Mekkora a keret? (HUF/EUR)",
    "Van 1–4 referencia képed? (írj: igen/nem)",
]

# region ISERO PATCH signal-regex
_RE_QTY = re.compile(r"(?:\b|#)(\d{1,2})\s*(?:db|darab|pcs?)?\b", re.IGNORECASE)
_RE_BUDGET = re.compile(r"(\d{1,5})(?:\s?[-–]?\s?(?:usd|eur|huf|ft|\$|€))", re.IGNORECASE)
_RE_STYLE = re.compile(r"\b(piros|vörös|kék|zöld|lila|rózsaszín|fekete|fehér|arany|ezüst|pastel|pastell|angel|démon|dark|cute|kawaii)\b", re.IGNORECASE)


def extract_signals(text: str):
    qty = None
    m = _RE_QTY.search(text)
    if m:
        try:
            n = int(m.group(1))
            if 1 <= n <= 99:
                qty = n
        except Exception:
            pass
    budget = None
    m = _RE_BUDGET.search(text)
    if m:
        try:
            budget = int(m.group(1))
        except Exception:
            pass
    styles = [sm.group(1).lower() for sm in _RE_STYLE.finditer(text)]
    style = ", ".join(dict.fromkeys(styles)) if styles else None
    return qty, budget, style
# endregion

# region ISERO PATCH legacy-purge
LEGACY_KEYS = (
    "Melyik termék vagy téma?", "Mennyiség, ritkaság, színvilág?", "Határidő", "Keret (HUF/EUR)?",
    "Van 1-4 referencia képed?",
    "Which product/variant", "quantity", "deadline", "budget", "reference image",
)

async def _purge_legacy_block(channel: discord.TextChannel):
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        async for m in channel.history(limit=30):
            if not m.author.bot:
                continue
            txt = m.content or ""
            if any(k in txt for k in LEGACY_KEYS):
                try:
                    await m.delete()
                    log.info("Legacy prompt removed msg_id=%s in #%s", m.id, channel.id)
                except Exception:
                    pass
    except Exception:
        pass
# endregion


def _agent_active(bot, channel_id: int) -> bool:
    ag = bot.get_cog("AgentGate") if bot else None
    try:
        return bool(ag and getattr(ag, "is_active", lambda _id: False)(channel_id))
    except Exception:
        return False


async def _sweep_legacy(channel: discord.TextChannel):
    await _purge_legacy_block(channel)


async def strip_legacy_bot_message(bot, message: discord.Message):
    """Remove legacy prompt blocks sent by bots if agent is active or legacy disabled."""
    if not message.author.bot:
        return
    ch = message.channel
    if not isinstance(ch, discord.TextChannel):
        return
    if _SUPPRESS_ALWAYS or _agent_active(bot, ch.id):
        txt = message.content or ""
        if any(k in txt for k in LEGACY_KEYS):
            try:
                await message.delete()
                log.info("Legacy prompt auto-removed msg_id=%s in #%s", message.id, ch.id)
            except Exception:
                pass


@dataclass
class MebinuSession:
    created: float = field(default_factory=time.time)
    step: int = 0
    answers: List[str] = field(default_factory=list)

    def next_question(self) -> str | None:
        if self.step >= len(QUESTIONS) or self.step >= MAX_TURNS:
            return None
        return QUESTIONS[self.step]

    def record(self, text: str) -> None:
        if self.step < len(QUESTIONS):
            self.answers.append(text[:300])
            self.step += 1

    # region ISERO PATCH MEBINU_PREFILL
    COLOR_WORDS = {
        "piros",
        "fekete",
        "kék",
        "zöld",
        "sárga",
        "lila",
        "fehér",
        "barna",
        "szürke",
        "arany",
        "ezüst",
    }

    def prefill(self, text: str) -> None:
        low = text.lower()
        colors = [c for c in self.COLOR_WORDS if c in low]
        if colors:
            # terméktípus implicit Mebinu
            self.answers.append("Mebinu")
            self.answers.append(" ".join(colors)[:300])
            self.step = 2
    # endregion ISERO PATCH MEBINU_PREFILL

    def remaining(self) -> int:
        return max(0, len(QUESTIONS) - self.step)

    def summary(self) -> str:
        parts = []
        for q, a in zip(QUESTIONS, self.answers):
            parts.append(f"{q} {a}")
        return "\n".join(parts)[:800]


# region ISERO PATCH MEBINU_DIALOG_V1
async def start_flow(cog, interaction) -> bool:
    """Start guided Mebinu flow; return True if started."""
    ch = interaction.channel
    # region ISERO PATCH agent-first
    if hasattr(cog, "ensure_ticket_perms"):
        await cog.ensure_ticket_perms(ch, interaction.user)
    if hasattr(cog, "post_welcome_and_sla"):
        await cog.post_welcome_and_sla(ch, "mebinu", interaction.user)
    if _is_nsfw_env(ch) or os.getenv("NSFW_AGENT_ENABLED", "true").lower() == "false":
        try:
            await ch.send(os.getenv("NSFW_SAFE_MODE_TEXT", "NSFW safe-mode: írd le a kérésed és csatolj referenciát."))
        except Exception:
            pass
        return True

    use_agent = os.getenv("MEBINU_USE_AGENT", "true").lower() == "true"
    show_legacy = _LEGACY_VISIBLE
    suppress_always = _SUPPRESS_ALWAYS
    if use_agent:
        agent = cog.bot.get_cog("AgentGate") if cog.bot else None
        if agent:
            if getattr(agent, "sessions", {}).get(ch.id):
                await _sweep_legacy(ch)
                if show_legacy and not suppress_always:
                    await interaction.response.send_message("ISERO már aktív ebben a ticketben. 😊 Folytassuk a részletekkel!")
                return True
            kb = getattr(cog, "kb", {}) or {}
            sys = compose_mebinu_prompt(cog.bot, ch, interaction.user, kb)
            try:
                await agent.start_session(
                    channel=ch,
                    system_prompt=sys,
                    prefer_heavy=True,
                    ttl_seconds=int(os.getenv("AGENT_DEDUP_TTL_SECONDS", "120") or "120"),
                )
                await _sweep_legacy(ch)
                await interaction.response.send_message(
                    "Oké, nézzük meg együtt! 😊 Röviden: milyen hangulatú/ruhájú Mebinut szeretnél elsőnek?"
                )
                try:
                    cog.mebinu_agent_openers
                except AttributeError:
                    cog.mebinu_agent_openers = {}
                cog.mebinu_agent_openers[ch.id] = interaction.user.id
                return True
            except Exception:
                await interaction.response.send_message(
                    "Bekapcsoltam. Írd le egy mondatban, mit szeretnél, és kérdezek lépésenként. ✍️"
                )
                return True
    if not show_legacy or suppress_always:
        await _sweep_legacy(ch)
        await interaction.response.send_message("Írd le röviden az elképzelést, és végigkérdezlek lépésenként. 😉")
        return True
    session = MebinuSession()
    async for m in ch.history(limit=1, before=interaction.created_at):
        if m.author.id == interaction.user.id:
            session.prefill(m.content)
            break
    cog.mebinu_sessions[ch.id] = session
    q = session.next_question()
    await interaction.response.send_message(
        f"{interaction.user.mention} {q} [{session.step+1}/{len(QUESTIONS)}]",
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )
    # endregion ISERO PATCH agent-first
    return True
# endregion ISERO PATCH MEBINU_DIALOG_V1

# region ISERO PATCH mebinu-offer-cmd
@commands.hybrid_command(name="offer", description="Gyors ajánlat Mebinura (db × ár, kedvezménnyel).")
async def offer(ctx: commands.Context, qty: int | None = None):
    if not isinstance(ctx.channel, discord.TextChannel):
        return await ctx.reply("Csak csatornában használható.")
    if qty is None:
        qty = 1
        if os.getenv("PLAYER_CARD_ENABLED", "false").lower() == "true":
            pcog = ctx.bot.get_cog("PlayerDB")
            if pcog and hasattr(pcog, "get_snapshot"):
                try:
                    snap = pcog.get_snapshot(ctx.author.id) or {}
                    qty = int(snap.get("last_qty") or qty)
                except Exception:
                    pass
    unit, bulk_min, off_each = env_prices()
    sub, disc, total = calc_total(unit, qty, bulk_min, off_each)
    txt = (f"Ajánlat: **{qty}× ${unit:.0f}** = ${sub:.2f}" +
           (f" • Kedvezmény: −${disc:.2f}" if disc > 0 else "") +
           f" → **Végösszeg: ${total:.2f}**  ( {bulk_min}+ darabnál −${off_each:.0f}/db )")
    try:
        await ctx.reply(txt)
    except Exception:
        await ctx.send(txt)
# endregion ISERO PATCH mebinu-offer-cmd

# region ISERO PATCH mebinu-checkout
@commands.hybrid_command(name="checkoutmebinu", description="Mebinu rendelés lezárása és logolása.")
async def checkoutmebinu(ctx: commands.Context, qty: int | None = None):
    if not isinstance(ctx.channel, discord.TextChannel):
        return await ctx.reply("Csak csatornában használható.")
    opener = ctx.author
    if qty is None:
        qty = 1
        if os.getenv("PLAYER_CARD_ENABLED", "false").lower() == "true":
            pcog = ctx.bot.get_cog("PlayerDB")
            if pcog and hasattr(pcog, "get_snapshot"):
                try:
                    snap = pcog.get_snapshot(opener.id) or {}
                    qty = int(snap.get("last_qty") or qty)
                except Exception:
                    pass
    unit, bulk_min, off_each = env_prices()
    sub, disc, total = calc_total(unit, qty, bulk_min, off_each)
    items = f"{qty} × Mebinu @ ${unit:.2f}  =  ${sub:.2f}"
    if disc > 0:
        items += f"\nKedvezmény (≥{bulk_min}): −${disc:.2f}"
    due = dt.datetime.utcnow() + dt.timedelta(days=int(os.getenv("TICKET_DEFAULT_SLA_DAYS","3") or "3"))
    tickets = ctx.bot.get_cog("Tickets")
    if not tickets:
        return await ctx.reply("Ticket rendszer nem elérhető.")
    emb = tickets.build_order_embed(kind="mebinu", opener=opener, items_text=items, total_usd=total, due_utc=due)
    await tickets.post_order_log(channel=ctx.channel, embed=emb)
    try:
        await ctx.reply("Rendelés rögzítve és továbbítva a stábnak. ✅")
    except Exception:
        pass
# endregion ISERO PATCH mebinu-checkout

# region ISERO PATCH mebinu-summary
@commands.hybrid_command(name="summarymebinu", description="Rövid összefoglaló a csatorna beszélgetése alapján (qty/budget/style + ár).")
async def summarymebinu(ctx: commands.Context):
    if not isinstance(ctx.channel, discord.TextChannel):
        return await ctx.reply("Csak csatornában használható.")
    opener = ctx.author
    pcog = ctx.bot.get_cog("PlayerDB")
    snap = {}
    if pcog and os.getenv("PLAYER_CARD_ENABLED", "false").lower() == "true":
        try:
            snap = pcog.get_snapshot(opener.id) or {}
        except Exception:
            snap = {}
    qty = int(snap.get("last_qty") or 1)
    style = snap.get("last_style") or "—"
    budget = snap.get("last_budget")
    unit, bulk_min, off_each = env_prices()
    sub, disc, total = calc_total(unit, qty, bulk_min, off_each)
    styles_seen = set()
    try:
        async for m in ctx.channel.history(limit=30):
            t = (m.content or "").lower()
            for kw in ("piros","vörös","fekete","zöld","lila","rózsaszín","pastel","kawaii","angel","démon","dark","cute","neon"):
                if kw in t:
                    styles_seen.add(kw)
    except Exception:
        pass
    if style == "—" and styles_seen:
        style = ", ".join(sorted(styles_seen))[:120]
    due = dt.datetime.utcnow() + dt.timedelta(days=int(os.getenv("TICKET_DEFAULT_SLA_DAYS","3") or "3"))
    e = discord.Embed(
        title="Mebinu — Összefoglaló",
        description=f"Rendelő: {opener.mention}",
        color=discord.Color.purple(),
    )
    e.add_field(name="Mennyiség", value=str(qty), inline=True)
    e.add_field(name="Stílus/szín", value=style, inline=True)
    e.add_field(name="Keret", value=(f"${budget}" if budget else "—"), inline=True)
    items = f"{qty} × Mebinu @ ${unit:.2f}  =  ${sub:.2f}"
    if disc > 0:
        items += f"\nKedvezmény (≥{bulk_min}): −${disc:.2f}"
    e.add_field(name="Árösszegzés", value=f"{items}\n**Végösszeg: ${total:.2f}**", inline=False)
    e.add_field(name="Céldátum (≈ puha határidő)", value=due.strftime("%Y-%m-%d %H:%M UTC"), inline=False)
    e.set_footer(text="ISERO • Brief Summary")
    msg = await ctx.reply(embed=e)
    if os.getenv("ORDER_SUMMARY_PIN", "true").lower() == "true":
        try:
            await msg.pin()
        except Exception:
            pass
# endregion ISERO PATCH mebinu-summary
