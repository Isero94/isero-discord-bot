from dataclasses import dataclass

@dataclass
class PlayerCard:
    user_id: int
    lang: str | None = None
    score: int = 0
    reputation: int = 0
