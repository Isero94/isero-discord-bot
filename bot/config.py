"""Runtime configuration via environment variables.


from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    ENV_SCHEMA_VERSION: int = 1

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MODEL_HEAVY: str = Field(default="gpt-4o")
    PRECHAT_MSG_CHAR_LIMIT: int = Field(default=300)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=20000)


        if v <= 0 or v > 2_000_000:
            raise ValueError("AGENT_DAILY_TOKEN_LIMIT out of range")
        return v


# Instantiate once for app-wide use
settings = Settings()


OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_MODEL = settings.OPENAI_MODEL
PRECHAT_MSG_CHAR_LIMIT = settings.PRECHAT_MSG_CHAR_LIMIT

__all__ = [
    "Settings",
    "settings",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "PRECHAT_MSG_CHAR_LIMIT",
]
