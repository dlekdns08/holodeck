from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
CACHE_DIR = DATA_DIR / "cache"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    director_model: str = "claude-opus-4-7"

    video_provider: Literal["mock", "veo", "sora", "runway"] = "mock"
    google_api_key: str = ""
    openai_api_key: str = ""
    runway_api_key: str = ""

    clip_seconds: int = 5
    clip_resolution: str = "720p"

    # Speculative pre-generation: after each turn, ask the Director for K likely
    # next user inputs and render them in the background so a matching real input
    # plays instantly. Off by default — real providers cost real money.
    speculative_pregen_enabled: bool = False
    speculative_pregen_k: int = 2

    database_url: str = f"sqlite:///{DATA_DIR / 'holodeck.db'}"


settings = Settings()

SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
