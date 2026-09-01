"""
app/config.py
=============
Loads and validates all environment variables.
Raises clear errors when required values are missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (one level up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _require(name: str) -> str:
    """Return env var or raise with a helpful message."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set.\n"
            f"Copy .env.example to .env and fill in the values."
        )
    return value


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise EnvironmentError(
            f"Environment variable '{name}' must be an integer, got: {raw!r}"
        )


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise EnvironmentError(
            f"Environment variable '{name}' must be a float, got: {raw!r}"
        )


@dataclass(frozen=True)
class Config:
    # ── Ollama ──────────────────────────────────────────────────────────────
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embed_model: str
    ollama_timeout_seconds: float

    # ── PostgreSQL ──────────────────────────────────────────────────────────
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # ── Document folder ─────────────────────────────────────────────────────
    documents_folder: Path

    # ── RAG knobs ───────────────────────────────────────────────────────────
    top_k: int
    chunk_size: int
    chunk_overlap: int
    embed_batch_size: int
    max_history_messages: int

    # ── REST API ────────────────────────────────────────────────────────────
    api_host: str
    api_port: int
    cors_origins: list[str]
    api_key: str

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} "
            f"port={self.postgres_port} "
            f"dbname={self.postgres_db} "
            f"user={self.postgres_user} "
            f"password={self.postgres_password}"
        )


def load_config() -> Config:
    """Parse, validate and return the application configuration."""

    # Documents folder may be an absolute Windows path like D:\Knowledge
    raw_folder = os.getenv("DOCUMENTS_FOLDER", "./documents")
    documents_folder = Path(raw_folder).expanduser()

    raw_cors = os.getenv("CORS_ORIGINS", "*")
    cors_origins = [origin.strip() for origin in raw_cors.split(",") if origin.strip()]

    return Config(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_chat_model=os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:1.5b"),
        ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b"),
        ollama_timeout_seconds=_get_float("OLLAMA_TIMEOUT_SECONDS", 300.0),
        postgres_host=os.getenv("POSTGRES_HOST", "localhost"),
        postgres_port=_get_int("POSTGRES_PORT", 5432),
        postgres_db=os.getenv("POSTGRES_DB", "ollama_rag"),
        postgres_user=os.getenv("POSTGRES_USER", "rag_user"),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "rag_password"),
        documents_folder=documents_folder,
        top_k=_get_int("TOP_K", 5),
        chunk_size=_get_int("CHUNK_SIZE", 1200),
        chunk_overlap=_get_int("CHUNK_OVERLAP", 200),
        embed_batch_size=_get_int("EMBED_BATCH_SIZE", 16),
        max_history_messages=_get_int("MAX_HISTORY_MESSAGES", 6),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=_get_int("API_PORT", 8000),
        cors_origins=cors_origins,
        api_key=os.getenv("API_KEY", ""),
    )
