import os

# Ha Render/ENV-ben adod meg, onnan olvassa ki – ezek csak DEFAULT-ok fejlesztéshez.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0") or 0)
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0") or 0)

TICKET_USER_MAX_MSG = int(os.getenv("TICKET_USER_MAX_MSG", "5"))
TICKET_MSG_CHAR_LIMIT = int(os.getenv("TICKET_MSG_CHAR_LIMIT", "800"))
TICKET_IDLE_SECONDS = int(os.getenv("TICKET_IDLE_SECONDS", "600"))

ALLOW_STAFF_FREESPEECH = os.getenv("ALLOW_STAFF_FREESPEECH", "true").lower() in ("1","true","yes","y","on")
WAKE_WORDS = [w.strip() for w in os.getenv("WAKE_WORDS", "isero,x").split(",") if w.strip()]
