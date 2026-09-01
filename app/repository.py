"""
app/repository.py
=================
All PostgreSQL query functions:
  - Document metadata CRUD
  - Chunk storage
  - Vector similarity search (via pgvector)
  - Indexed document listing

All queries use parameterised SQL to prevent injection.
Transactions for multi-step writes (update + delete old + insert new).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.config import Config
from app.db import get_connection

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DocumentRecord:
    id: int
    source_path: str
    file_name: str
    file_extension: Optional[str]
    sha256: str
    file_size: Optional[int]
    ingested_at: datetime


@dataclass
class ChunkRecord:
    id: int
    document_id: int
    chunk_index: int
    page_number: Optional[int]
    text: str
    metadata: dict[str, Any]
    file_name: str
    source_path: str
    similarity: float


# ─────────────────────────────────────────────────────────────────────────────
# Document CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_document_by_path(source_path: str, cfg: Config) -> Optional[DocumentRecord]:
    """Return the stored document record for *source_path*, or None."""
    conn = get_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_path, file_name, file_extension,
                       sha256, file_size, ingested_at
                FROM documents
                WHERE source_path = %s;
                """,
                (source_path,),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if row is None:
        return None

    return DocumentRecord(
        id=row[0],
        source_path=row[1],
        file_name=row[2],
        file_extension=row[3],
        sha256=row[4],
        file_size=row[5],
        ingested_at=row[6],
    )


def insert_document(
    source_path: str,
    file_name: str,
    file_extension: str,
    sha256: str,
    file_size: int,
    cfg: Config,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    """
    Insert a new document record and return its generated id.

    If *conn* is provided the caller owns the transaction; otherwise a
    short-lived connection is used.
    """
    sql = """
        INSERT INTO documents
            (source_path, file_name, file_extension, sha256, file_size)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
    """
    params = (source_path, file_name, file_extension, sha256, file_size)

    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]  # type: ignore[index]

    own_conn = get_connection(cfg)
    try:
        with own_conn.cursor() as cur:
            cur.execute(sql, params)
            doc_id: int = cur.fetchone()[0]  # type: ignore[index]
        own_conn.commit()
    except Exception:
        own_conn.rollback()
        raise
    finally:
        own_conn.close()
    return doc_id


def update_document_metadata(
    doc_id: int,
    sha256: str,
    file_size: int,
    conn: psycopg.Connection,
) -> None:
    """Update sha256, file_size, updated_at, and ingested_at for a document."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET sha256      = %s,
                file_size   = %s,
                updated_at  = NOW(),
                ingested_at = NOW()
            WHERE id = %s;
            """,
            (sha256, file_size, doc_id),
        )


def delete_chunks_for_document(doc_id: int, conn: psycopg.Connection) -> None:
    """Delete all chunks belonging to *doc_id* (used before re-indexing)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s;", (doc_id,))


# ─────────────────────────────────────────────────────────────────────────────
# Chunk storage
# ─────────────────────────────────────────────────────────────────────────────

def insert_chunks(
    document_id: int,
    chunks_data: list[dict[str, Any]],
    conn: psycopg.Connection,
) -> None:
    """
    Bulk-insert chunk rows into the chunks table.

    Each element of *chunks_data* must contain:
      chunk_index, page_number, text, embedding (list[float]), metadata (dict)
    """
    sql = """
        INSERT INTO chunks
            (document_id, chunk_index, page_number, text, embedding, metadata)
        VALUES (%s, %s, %s, %s, %s::vector, %s)
        ON CONFLICT (document_id, chunk_index) DO NOTHING;
    """
    with conn.cursor() as cur:
        for item in chunks_data:
            embedding_list = item["embedding"]
            # Convert to numpy array for pgvector compatibility
            embedding_np = np.array(embedding_list, dtype=np.float32)
            cur.execute(
                sql,
                (
                    document_id,
                    item["chunk_index"],
                    item.get("page_number"),
                    item["text"],
                    embedding_np,
                    json.dumps(item.get("metadata", {})),
                ),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Vector similarity search
# ─────────────────────────────────────────────────────────────────────────────

def vector_search(
    query_embedding: list[float],
    top_k: int,
    cfg: Config,
    doc_ids: Optional[list[int]] = None,
) -> list[ChunkRecord]:
    """
    Perform cosine similarity search in PostgreSQL via pgvector.
    Supports optional document ID filtering (doc_ids) for session-isolated RAG.
    """
    emb_np = np.array(query_embedding, dtype=np.float32)
    where_clause = ""
    params: list[Any] = [emb_np]

    if doc_ids is not None:
        if not doc_ids:
            # Empty doc_ids list means no documents uploaded for this session yet
            return []
        where_clause = "WHERE d.id = ANY(%s::int[])"
        params.append(doc_ids)

    params.extend([emb_np, top_k])

    sql = f"""
        SELECT
            c.id,
            c.document_id,
            c.chunk_index,
            c.page_number,
            c.text,
            c.metadata,
            d.file_name,
            d.source_path,
            1 - (c.embedding <=> %s::vector) AS similarity
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where_clause}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s;
    """

    conn = get_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    results: list[ChunkRecord] = []
    for row in rows:
        results.append(
            ChunkRecord(
                id=row[0],
                document_id=row[1],
                chunk_index=row[2],
                page_number=row[3],
                text=row[4],
                metadata=row[5] if isinstance(row[5], dict) else {},
                file_name=row[6],
                source_path=row[7],
                similarity=float(row[8]),
            )
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Listing
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IndexedDocSummary:
    id: int
    file_name: str
    source_path: str
    sha256: str
    chunk_count: int
    ingested_at: datetime


def list_indexed_documents(cfg: Config) -> list[IndexedDocSummary]:
    """Return all indexed documents with their chunk counts."""
    sql = """
        SELECT
            d.id,
            d.file_name,
            d.source_path,
            d.sha256,
            COUNT(c.id) AS chunk_count,
            d.ingested_at
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        GROUP BY d.id
        ORDER BY d.ingested_at;
    """
    conn = get_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    return [
        IndexedDocSummary(
            id=row[0],
            file_name=row[1],
            source_path=row[2],
            sha256=row[3],
            chunk_count=row[4],
            ingested_at=row[5],
        )
        for row in rows
    ]


def delete_document_by_id(doc_id: int, cfg: Config) -> bool:
    """Delete a document by ID (cascade deletes associated chunks). Returns True if found and deleted."""
    conn = get_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s RETURNING id;", (doc_id,))
            deleted = cur.fetchone()
        conn.commit()
        return deleted is not None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
