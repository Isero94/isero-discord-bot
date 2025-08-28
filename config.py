import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0")) or None

STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0")) or None
TICKET_HUB_CHANNEL_ID = int(os.getenv("TICKET_HUB_CHANNEL_ID", "0")) or None

DB_PATH = os.getenv("DB_PATH", "data/isero.db")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY_1", ""))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_SMART = os.getenv("OPENAI_MODEL_SMART", "gpt-4o")
SMART_THRESHOLD = float(os.getenv("SMART_THRESHOLD", "0.8"))

LANG_HINT_EVERY = int(os.getenv("LANG_HINT_EVERY", "5"))
TICKET_USER_MAX_MSG = int(os.getenv("TICKET_USER_MAX_MSG", "10"))
TICKET_MSG_CHAR_LIMIT = int(os.getenv("TICKET_MSG_CHAR_LIMIT", "300"))
TICKET_IDLE_SECONDS = int(os.getenv("TICKET_IDLE_SECONDS", "600"))
