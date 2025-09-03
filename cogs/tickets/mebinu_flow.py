from __future__ import annotations

import time
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
    cog.mebinu_sessions[ch.id] = session
    q = session.next_question()
    await interaction.response.send_message(
        f"{interaction.user.mention} {q} [{session.step+1}/{len(QUESTIONS)}]",
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )
    return True
# endregion ISERO PATCH MEBINU_DIALOG_V1
