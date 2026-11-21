import os
from dataclasses import dataclass, field

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    api_keys: list[str] = field(default_factory=list)
    database_url: str = "sqlite:///./app.db"
    allowed_origins: list[str] = field(default_factory=list)
    enable_failure_simulation: bool = False
    model: str = "gemini/gemini-3.5-flash-lite"
    request_timeout: int = 30


def get_settings() -> Settings:
    """Read env on every call so tests can change it."""
    return Settings(
        api_keys=_split(os.getenv("LLM_API_KEYS", "")),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
        allowed_origins=_split(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")),
        enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true",
        model=os.getenv("LLM_MODEL", "gemini/gemini-3.5-flash-lite"),
        request_timeout=int(os.getenv("LLM_TIMEOUT", "30")),
    )
