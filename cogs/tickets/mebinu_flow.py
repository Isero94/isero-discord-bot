from __future__ import annotations

import time
import os
from dataclasses import dataclass, field
from typing import List
import discord

MAX_TURNS = 10

QUESTIONS = [
    "Melyik termék vagy variáns érdekel?",
    "Milyen stílus/színvilág tetszik? (adj példát)",
    "Mi a határidő? (nap/dátum)",
    "Mekkora a keret? (HUF/EUR)",
    "Van 1–4 referencia képed? (írj: igen/nem)",
]


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
    session = MebinuSession()
    async for m in ch.history(limit=1, before=interaction.created_at):
        if m.author.id == interaction.user.id:
            session.prefill(m.content)
            break
    # region ISERO PATCH mebinu-welcome-agent
    cog.mebinu_sessions[ch.id] = session
    if hasattr(cog, "post_welcome_and_sla"):
        await cog.post_welcome_and_sla(ch, "mebinu", interaction.user)

    kb = (getattr(cog, "kb", {}) or {}).get("mebinu", {})
    sys = kb.get("system_prompt", "")
    questions = "\n".join(f"- {q}" for q in kb.get("questions", []))
    sales_boot = f"{sys}\n\nStart by asking:\n{questions}\n"
    agent = cog.bot.get_cog("AgentGate") if cog.bot else None
    allowed = set(str(x).strip() for x in (os.getenv("AGENT_ALLOWED_CHANNELS", "") or "").split(",") if x.strip())
    if agent and (not allowed or str(ch.id) in allowed):
        try:
            await agent.start_session(channel=ch, system_prompt=sales_boot, prefer_heavy=True, ttl_seconds=int(os.getenv("AGENT_DEDUP_TTL_SECONDS", "120") or "120"))
        except Exception:
            pass

    q = session.next_question()
    await interaction.response.send_message(
        f"{interaction.user.mention} {q} [{session.step+1}/{len(QUESTIONS)}]",
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )
    # endregion ISERO PATCH mebinu-welcome-agent
    return True
# endregion ISERO PATCH MEBINU_DIALOG_V1
