"""
app/ingestion.py
================
Orchestrates the full document ingestion pipeline:

  File → SHA-256 → New/Unchanged/Updated decision
       → Parse → Chunk → Batch Embed → Store

Key design points:
- SHA-256 is calculated from raw bytes for binary-exact change detection.
- Updated documents: old chunks are deleted inside a transaction before new
  chunks are inserted, so a failed update never leaves a corrupt state.
- One bad document does not abort the rest of the folder scan.
- Batch embedding respects EMBED_BATCH_SIZE to avoid overloading Ollama.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

import psycopg

from app.chunking import TextChunk, chunk_document
from app.config import Config
from app.db import get_connection
from app.ollama_client import embed_texts
from app.parsers import ParsedBlock, ParserError, parse_document
from app.repository import (
    delete_chunks_for_document,
    get_document_by_path,
    insert_chunks,
    insert_document,
    update_document_metadata,
)
from app.scanner import scan_folder

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Status types
# ─────────────────────────────────────────────────────────────────────────────

class IngestionStatus(Enum):
    NEW = auto()
    UNCHANGED = auto()
    UPDATED = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class IngestionResult:
    file_name: str
    source_path: str
    status: IngestionStatus
    chunk_count: int = 0
    error: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# SHA-256 helper
# ─────────────────────────────────────────────────────────────────────────────

def calculate_sha256(path: Path) -> str:
    """Read *path* in binary and return its SHA-256 hex digest."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError as exc:
        raise OSError(f"Cannot read '{path}' for SHA-256: {exc}") from exc
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Embedding helpers
# ─────────────────────────────────────────────────────────────────────────────

def _embed_chunks_in_batches(
    chunks: list[TextChunk],
    cfg: Config,
) -> list[list[float]]:
    """
    Generate embeddings for all chunks in batches of EMBED_BATCH_SIZE.

    Returns a flat list of embedding vectors in the same order as *chunks*.
    """
    all_embeddings: list[list[float]] = []
    batch_size = cfg.embed_batch_size

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.text for c in batch]
        embeddings = embed_texts(texts, cfg)
        all_embeddings.extend(embeddings)

    return all_embeddings


# ─────────────────────────────────────────────────────────────────────────────
# Core ingestion helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_chunk_data(
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    source_path: str,
    file_name: str,
) -> list[dict[str, Any]]:
    """Zip chunks with their embeddings and build insert-ready dicts."""
    result = []
    for chunk, embedding in zip(chunks, embeddings):
        result.append(
            {
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "text": chunk.text,
                "embedding": embedding,
                "metadata": {
                    "source_path": source_path,
                    "file_name": file_name,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                },
            }
        )
    return result


def _ingest_new_document(
    path: Path,
    sha256: str,
    cfg: Config,
) -> IngestionResult:
    """Parse, chunk, embed, and store a brand-new document."""
    source_path = str(path)
    file_name = path.name
    file_extension = path.suffix.lower()
    file_size = path.stat().st_size

    try:
        blocks: list[ParsedBlock] = parse_document(path)
    except ParserError as exc:
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error=str(exc),
        )

    chunks = chunk_document(blocks, cfg.chunk_size, cfg.chunk_overlap)
    if not chunks:
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error="Document produced no chunks after parsing.",
        )

    try:
        embeddings = _embed_chunks_in_batches(chunks, cfg)
    except RuntimeError as exc:
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error=f"Embedding failed: {exc}",
        )

    chunk_data = _build_chunk_data(chunks, embeddings, source_path, file_name)

    conn = get_connection(cfg)
    try:
        doc_id = insert_document(
            source_path=source_path,
            file_name=file_name,
            file_extension=file_extension,
            sha256=sha256,
            file_size=file_size,
            cfg=cfg,
            conn=conn,
        )
        insert_chunks(doc_id, chunk_data, conn)
        conn.commit()

        if getattr(cfg, "vector_db_type", "postgres") == "chroma":
            try:
                from app.chroma_repository import add_chunks_chroma
                add_chunks_chroma(doc_id, file_name, source_path, chunks, embeddings, cfg)
            except Exception as chroma_exc:
                logger.warning("ChromaDB storage warning for '%s': %s", file_name, chroma_exc)
    except Exception as exc:
        conn.rollback()
        logger.error("DB error storing new document '%s': %s", file_name, exc)
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error=f"Database error: {exc}",
        )
    finally:
        conn.close()

    return IngestionResult(
        file_name=file_name,
        source_path=source_path,
        status=IngestionStatus.NEW,
        chunk_count=len(chunks),
    )


def _ingest_updated_document(
    path: Path,
    doc_id: int,
    sha256: str,
    cfg: Config,
) -> IngestionResult:
    """Re-parse, re-chunk, re-embed, and replace all chunks for an updated document."""
    source_path = str(path)
    file_name = path.name
    file_size = path.stat().st_size

    try:
        blocks = parse_document(path)
    except ParserError as exc:
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error=str(exc),
        )

    chunks = chunk_document(blocks, cfg.chunk_size, cfg.chunk_overlap)
    if not chunks:
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error="Document produced no chunks after parsing.",
        )

    try:
        embeddings = _embed_chunks_in_batches(chunks, cfg)
    except RuntimeError as exc:
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error=f"Embedding failed: {exc}",
        )

    chunk_data = _build_chunk_data(chunks, embeddings, source_path, file_name)

    # Atomic replacement: update metadata → delete old → insert new
    conn = get_connection(cfg)
    try:
        update_document_metadata(doc_id, sha256, file_size, conn)
        delete_chunks_for_document(doc_id, conn)
        insert_chunks(doc_id, chunk_data, conn)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("DB error updating document '%s': %s", file_name, exc)
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.FAILED,
            error=f"Database error (rolled back): {exc}",
        )
    finally:
        conn.close()

    return IngestionResult(
        file_name=file_name,
        source_path=source_path,
        status=IngestionStatus.UPDATED,
        chunk_count=len(chunks),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_ingestion(cfg: Config) -> list[IngestionResult]:
    """
    Scan the documents folder and ingest new/changed files.

    Returns a list of IngestionResult for every file examined.
    Errors in individual files are captured and do not abort processing.
    """
    folder = cfg.documents_folder
    paths = scan_folder(folder)

    if not paths:
        return []

    results: list[IngestionResult] = []

    for path in paths:
        file_name = path.name
        source_path = str(path)

        # Compute hash
        try:
            sha256 = calculate_sha256(path)
        except OSError as exc:
            results.append(
                IngestionResult(
                    file_name=file_name,
                    source_path=source_path,
                    status=IngestionStatus.FAILED,
                    error=str(exc),
                )
            )
            continue

        # Check existing record
        record = get_document_by_path(source_path, cfg)

        if record is None:
            # Brand-new document
            result = _ingest_new_document(path, sha256, cfg)
        elif record.sha256 == sha256:
            # Unchanged
            result = IngestionResult(
                file_name=file_name,
                source_path=source_path,
                status=IngestionStatus.UNCHANGED,
            )
        else:
            # Modified
            result = _ingest_updated_document(path, record.id, sha256, cfg)

        results.append(result)

    return results


def ingest_uploaded_file(file_name: str, content_bytes: bytes, cfg: Config) -> IngestionResult:
    """
    Save uploaded file bytes to documents_folder and run the ingestion pipeline.
    Overwrites existing file if present and re-indexes if hash changed.
    """
    folder = cfg.documents_folder
    folder.mkdir(parents=True, exist_ok=True)
    target_path = folder / file_name

    try:
        target_path.write_bytes(content_bytes)
    except OSError as exc:
        return IngestionResult(
            file_name=file_name,
            source_path=str(target_path),
            status=IngestionStatus.FAILED,
            error=f"Could not save file to disk: {exc}",
        )

    sha256 = hashlib.sha256(content_bytes).hexdigest()
    source_path = str(target_path)
    record = get_document_by_path(source_path, cfg)

    if record is None:
        return _ingest_new_document(target_path, sha256, cfg)
    elif record.sha256 == sha256:
        stats = get_knowledge_stats(cfg)
        return IngestionResult(
            file_name=file_name,
            source_path=source_path,
            status=IngestionStatus.UNCHANGED,
            chunk_count=stats.get("chunks", 0),
        )
    else:
        return _ingest_updated_document(target_path, record.id, sha256, cfg)
