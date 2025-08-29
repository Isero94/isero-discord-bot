from bot.config import PRECHAT_MSG_CHAR_LIMIT, OPENAI_API_KEY, OPENAI_MODEL
import asyncio

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None  # lib fallback

_client = None
if OPENAI_API_KEY and AsyncOpenAI is not None:
    _client = AsyncOpenAI(api_key=OPENAI_API_KEY)

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
    Short ISERO reply with hard clamp. Uses OpenAI if key is set, else safe fallback.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return "Rendben. Milyen témájú munka és mikorra kell?"

    # OpenAI path
    if _client:
        try:
            sys_msg = _SYSTEM_TMPL.format(limit=max_chars)
            if system:
                sys_msg += " " + system
            resp = await _client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=160,  # rövid válasz
            )
            out = (resp.choices[0].message.content or "").strip()
            if len(out) > max_chars:
                out = out[:max_chars]
            return out or "Oké. Mi a stílus és a határidő?"
        except Exception:
            # visszaesés fallbackre
            pass

    # Fallback – soha ne echozzunk, adjunk céltudatos kérdést
    fallback = (
        "Értettem. Add meg kérlek: kívánt stílus, méret/képarány, "
        "színek/
