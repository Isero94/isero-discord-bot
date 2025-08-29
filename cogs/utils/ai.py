# cogs/utils/ai.py
from bot.config import PRECHAT_MSG_CHAR_LIMIT, OPENAI_API_KEY, OPENAI_MODEL
from loguru import logger

try:
    from openai import AsyncOpenAI
except Exception:  # lib nincs installálva → fallback
    AsyncOpenAI = None

_client = None
if OPENAI_API_KEY and AsyncOpenAI is not None:
    try:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        logger.info("AI: OpenAI kliens inicializálva (model={})", OPENAI_MODEL or "default")
    except Exception as e:
        logger.warning("AI: OpenAI kliens inicializálás nem sikerült: {}", e)
        _client = None
else:
    logger.info("AI: Fallback mód (nincs kulcs vagy könyvtár).")

_SYSTEM_TMPL = (
    "You are ISERO, a concise assistant for collecting commission details. "
    "Rules: 1) Max reply {limit} characters. 2) Be friendly, professional. "
    "3) Ask at most ONE short clarifying question if needed. "
    "4) Do NOT echo the user's message. 5) No emoji, no markdown blocks. "
    "6) Keep it safe and SFW unless explicitly NSFW is selected. "
    "7) Prefer the user's language if detectable; otherwise reply in English."
)

async def short_reply(prompt: str, system: str = "", max_chars: int = PRECHAT_MSG_CHAR_LIMIT) -> str:
    """
    Rövid ISERO válasz (kemény karakter-korlát). Van OpenAI → használjuk, különben kulturált fallback.
    """
    content = (prompt or "").strip()
    if not content:
        return "Rendben. Milyen témájú munka és mikorra kell?"[:max_chars]

    # --- OpenAI ág ---
    if _client:
        try:
            sys_msg = _SYSTEM_TMPL.format(limit=max_chars)
            if system:
                sys_msg += " " + system
            resp = await _client.chat.completions.create(
                model=OPENAI_MODEL or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": content},
                ],
                temperature=0.6,
                max_tokens=160,  # rövid válaszokat kérünk
            )
            out = (resp.choices[0].message.content or "").strip()
            if len(out) > max_chars:
                out = out[:max_chars]
            return out or "Oké. Mi a stílus és a határidő?"[:max_chars]
        except Exception as e:
            logger.warning("AI: OpenAI hívás hiba, fallbackre esünk: {}", e)

    # --- Fallback ág (soha nem echo-zunk) ---
    fallback = (
        "Értettem. Írd meg kérlek: stílus, méret vagy képarány, főbb színek és karakter(ek), "
        "határidő és költségkeret."
    )
    return fallback[:max_chars]
