"""
app/db.py
=========
PostgreSQL connection management, pgvector registration,
schema initialization, and health checking.

Uses psycopg 3 (the `psycopg` package, not `psycopg2`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

import psycopg
from pgvector.psycopg import register_vector

from app.config import Config

logger = logging.getLogger(__name__)

_SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "init.sql"


# ─────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_connection(cfg: Config) -> psycopg.Connection:
    """Open and return a new psycopg3 connection with pgvector registered."""
    conn = psycopg.connect(cfg.postgres_dsn, autocommit=False)
    register_vector(conn)
    return conn


def get_autocommit_connection(cfg: Config) -> psycopg.Connection:
    """Open a connection in autocommit mode (used during schema init)."""
    conn = psycopg.connect(cfg.postgres_dsn, autocommit=True)
    register_vector(conn)
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

def check_postgres(cfg: Config) -> dict[str, str]:
    """
    Verify PostgreSQL is reachable and pgvector extension is available.

    Returns a status dict.
    Raises RuntimeError with a clear message on failure.
    """
    try:
        conn = get_autocommit_connection(cfg)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot connect to PostgreSQL at {cfg.postgres_host}:{cfg.postgres_port}.\n"
            f"  Database : {cfg.postgres_db}\n"
            f"  User     : {cfg.postgres_user}\n"
            f"  Error    : {exc}\n\n"
            "Ensure PostgreSQL is running and credentials in .env are correct."
        ) from exc

    try:
        with conn.cursor() as cur:
            # Basic connectivity
            cur.execute("SELECT version();")
            pg_version: str = cur.fetchone()[0]  # type: ignore[index]

            # pgvector check
            cur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    "pgvector extension is NOT installed in the database.\n"
                    "Run inside psql (connected to the target DB):\n\n"
                    "  CREATE EXTENSION IF NOT EXISTS vector;\n\n"
                    "Then restart the application."
                )
            vector_version: str = row[0]
    finally:
        conn.close()

    return {
        "postgres": "Connected",
        "pg_version": pg_version.split(",")[0],
        "pgvector": f"Enabled (v{vector_version})",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Schema initialisation
# ─────────────────────────────────────────────────────────────────────────────

def init_schema(cfg: Config) -> None:
    """
    Execute database/init.sql idempotently.

    Uses IF NOT EXISTS throughout so re-running never drops existing data.
    """
    if not _SCHEMA_FILE.exists():
        raise FileNotFoundError(
            f"Schema file not found: {_SCHEMA_FILE}\n"
            "Ensure database/init.sql exists in the project root."
        )

    sql = _SCHEMA_FILE.read_text(encoding="utf-8")

    try:
        conn = get_autocommit_connection(cfg)
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.close()
        logger.debug("Database schema initialised successfully.")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to initialise database schema: {exc}\n"
            "Check that the database user has CREATE TABLE / CREATE EXTENSION privileges."
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge statistics
# ─────────────────────────────────────────────────────────────────────────────

def get_knowledge_stats(cfg: Config) -> dict[str, int]:
    """Return document and chunk counts from the knowledge base."""
    conn = get_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents;")
            doc_count: int = cur.fetchone()[0]  # type: ignore[index]
            cur.execute("SELECT COUNT(*) FROM chunks;")
            chunk_count: int = cur.fetchone()[0]  # type: ignore[index]
        conn.commit()
    finally:
        conn.close()
    return {"documents": doc_count, "chunks": chunk_count}
