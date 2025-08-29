from bot.config import PRECHAT_MSG_CHAR_LIMIT, OPENAI_API_KEY, OPENAI_MODEL
import asyncio

# Minimal OpenAI client stub; replace with real call if OPENAI_API_KEY set.
async def short_reply(prompt: str, system: str = "", max_chars: int = PRECHAT_MSG_CHAR_LIMIT) -> str:
    # In a real implementation, you'd call OpenAI here.
    # For safety + offline default: echo + clamp.
    text = prompt.strip().replace("\n", " ")
    if len(text) > max_chars:
        text = text[:max_chars]
    await asyncio.sleep(0)  # keep it awaitable
    return text
