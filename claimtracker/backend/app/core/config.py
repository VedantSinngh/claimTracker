"""
app/core/config.py
──────────────────
Central configuration loaded from environment variables via pydantic-settings.
Never import os.environ directly elsewhere in the app — use `get_settings()`.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Database ───────────────────────────────────────────────────
    DATABASE_URL: str

    # ── Groq ───────────────────────────────────────────────────────
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama3-70b-8192"

    # ── Embeddings / FAISS ─────────────────────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    FAISS_INDEX_DIR: Path = Path("./faiss_index")
    RAG_TOP_K: int = 5
    CONFIDENCE_THRESHOLD: float = 0.70

    # ── OCR ────────────────────────────────────────────────────────
    TESSERACT_CMD: str = "/usr/bin/tesseract"

    # ── Uploads ────────────────────────────────────────────────────
    UPLOAD_DIR: Path = Path("./uploads")
    MAX_UPLOAD_SIZE_MB: int = 20

    # ── n8n ────────────────────────────────────────────────────────
    N8N_WEBHOOK_URL: str = "http://n8n:5678/webhook/claim-decided"

    # ── CORS ───────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: str) -> str:
        return v  # kept as string; split in main.py

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton — safe to call from any module."""
    return Settings()  # type: ignore[call-arg]
