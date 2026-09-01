"""
main.py
=======
Entry point for the Local Ollama Persistent Folder RAG application.

Startup sequence:
  1. Load .env / validate config
  2. Validate document directory
  3. Connect to PostgreSQL + verify pgvector
  4. Initialise DB schema (idempotent)
  5. Connect to Ollama + verify models
  6. Run test embedding → detect dimension
  7. Scan folder + ingest new/changed documents
  8. Print knowledge statistics
  9. Interactive CLI

CLI commands:
  /scan    – rescan and ingest
  /docs    – list indexed documents
  /status  – show system status
  /exit    – quit
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

# ─── Logging setup (before any imports that log) ────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Application imports ─────────────────────────────────────────────────────
from app.config import Config, load_config
from app.db import check_postgres, get_knowledge_stats, init_schema
from app.ingestion import IngestionResult, IngestionStatus, run_ingestion
from app.ollama_client import check_ollama, embed_single, verify_models
from app.rag import RAGResult, answer_question, trim_history
from app.repository import list_indexed_documents


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

DIVIDER = "=" * 60


def _print(text: str = "") -> None:
    print(text, flush=True)


def _section(title: str) -> None:
    _print(f"\n{DIVIDER}")
    _print(title)
    _print(DIVIDER)


def _print_ingestion_results(results: list[IngestionResult]) -> None:
    if not results:
        return
    for r in results:
        if r.status == IngestionStatus.NEW:
            label = "[NEW]      "
        elif r.status == IngestionStatus.UNCHANGED:
            label = "[UNCHANGED]"
        elif r.status == IngestionStatus.UPDATED:
            label = "[UPDATED]  "
        elif r.status == IngestionStatus.FAILED:
            label = "[FAILED]   "
        else:
            label = "[SKIPPED]  "

        line = f"  {label} {r.file_name}"
        if r.status == IngestionStatus.FAILED:
            line += f"\n             ↳ {r.error}"
        elif r.status in (IngestionStatus.NEW, IngestionStatus.UPDATED):
            line += f"  ({r.chunk_count} chunks)"
        _print(line)


def _print_stats(stats: dict[str, int]) -> None:
    _print(f"\nKnowledge Base:")
    _print(f"  Documents : {stats['documents']}")
    _print(f"  Chunks    : {stats['chunks']}")


def _print_sources(sources: list) -> None:
    if not sources:
        return
    _print("\nRetrieved Sources:")
    for idx, chunk in enumerate(sources, start=1):
        _print(f"\n  [S{idx}]")
        _print(f"  File      : {chunk.file_name}")
        if chunk.page_number is not None:
            _print(f"  Page      : {chunk.page_number}")
        _print(f"  Similarity: {chunk.similarity:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# Startup validation
# ─────────────────────────────────────────────────────────────────────────────

def startup(cfg: Config) -> None:
    """Run all startup checks and print the banner."""
    _section("Local Ollama Persistent Folder RAG")

    # ── 1. Document directory ────────────────────────────────────────────────
    folder = cfg.documents_folder
    if not folder.exists():
        _print(f"\n⚠  Document folder does not exist: {folder}")
        _print("   It will be created automatically.")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _print(f"   Could not create folder: {exc}")

    # ── 2. PostgreSQL ─────────────────────────────────────────────────────────
    try:
        pg_status = check_postgres(cfg)
        _print(f"\nPostgreSQL  : {pg_status['postgres']}")
        _print(f"pgvector    : {pg_status['pgvector']}")
    except RuntimeError as exc:
        _print(f"\n✗ PostgreSQL error:\n  {exc}")
        sys.exit(1)

    # ── 3. Schema ─────────────────────────────────────────────────────────────
    try:
        init_schema(cfg)
    except (RuntimeError, FileNotFoundError) as exc:
        _print(f"\n✗ Schema initialisation failed:\n  {exc}")
        sys.exit(1)

    # ── 4. Ollama ─────────────────────────────────────────────────────────────
    try:
        check_ollama(cfg)
        _print(f"\nOllama      : Connected  ({cfg.ollama_base_url})")
    except RuntimeError as exc:
        _print(f"\n✗ Ollama error:\n  {exc}")
        sys.exit(1)

    # ── 5. Model verification ─────────────────────────────────────────────────
    try:
        verify_models(cfg)
        _print(f"Chat Model  : {cfg.ollama_chat_model}")
        _print(f"Embed Model : {cfg.ollama_embed_model}")
    except RuntimeError as exc:
        _print(f"\n✗ {exc}")
        sys.exit(1)

    # ── 6. Test embedding ─────────────────────────────────────────────────────
    try:
        test_vec = embed_single("startup dimension check", cfg)
        _print(f"Embed Dim   : {len(test_vec)}")
    except RuntimeError as exc:
        _print(f"\n✗ Embedding test failed:\n  {exc}")
        sys.exit(1)

    # ── 7. Document folder ───────────────────────────────────────────────────
    _print(f"\nDocument Folder: {folder.resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
# Scan and ingest
# ─────────────────────────────────────────────────────────────────────────────

def do_scan(cfg: Config) -> dict[str, int]:
    """Scan + ingest, print results, and return updated stats."""
    _print("\nScanning documents...")
    results = run_ingestion(cfg)

    if results:
        _print_ingestion_results(results)
    else:
        stats = get_knowledge_stats(cfg)
        _print("\n  No new documents found in folder.")
        if stats["documents"] > 0:
            _print("  Using previously indexed knowledge.")
        _print_stats(stats)
        return stats

    stats = get_knowledge_stats(cfg)
    _print_stats(stats)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# CLI command handlers
# ─────────────────────────────────────────────────────────────────────────────

def cmd_scan(cfg: Config) -> None:
    do_scan(cfg)


def cmd_docs(cfg: Config) -> None:
    docs = list_indexed_documents(cfg)
    if not docs:
        _print("\nNo documents indexed yet.")
        return
    _print("\nIndexed Documents:")
    for i, doc in enumerate(docs, start=1):
        ts = doc.ingested_at.strftime("%Y-%m-%d %H:%M") if doc.ingested_at else "—"
        _print(f"\n  {i}. {doc.file_name}")
        _print(f"     Chunks  : {doc.chunk_count}")
        _print(f"     Indexed : {ts}")
        _print(f"     Path    : {doc.source_path}")


def cmd_status(cfg: Config) -> None:
    _print("\nSystem Status")
    _print("─" * 40)

    # Ollama
    try:
        check_ollama(cfg)
        _print(f"  Ollama      : Connected")
    except RuntimeError:
        _print("  Ollama      : ✗ Not reachable")

    # PostgreSQL
    try:
        pg = check_postgres(cfg)
        _print(f"  PostgreSQL  : {pg['postgres']}")
        _print(f"  pgvector    : {pg['pgvector']}")
    except RuntimeError:
        _print("  PostgreSQL  : ✗ Not reachable")

    _print(f"  Chat Model  : {cfg.ollama_chat_model}")
    _print(f"  Embed Model : {cfg.ollama_embed_model}")
    _print(f"  Folder      : {cfg.documents_folder.resolve()}")

    stats = get_knowledge_stats(cfg)
    _print(f"  Documents   : {stats['documents']}")
    _print(f"  Chunks      : {stats['chunks']}")


# ─────────────────────────────────────────────────────────────────────────────
# Interactive CLI
# ─────────────────────────────────────────────────────────────────────────────

def run_cli(cfg: Config) -> None:
    """Main interactive question-answer loop."""
    conversation_history: list[dict[str, str]] = []

    _print(f"\n{'─' * 60}")
    _print("Ready.  Type your question or a command:")
    _print("  /scan   – rescan document folder")
    _print("  /docs   – list indexed documents")
    _print("  /status – show system status")
    _print("  /exit   – quit")
    _print(f"{'─' * 60}")

    while True:
        try:
            _print("")
            raw = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            _print("\nExiting.")
            break

        if not raw:
            continue

        # ── Commands ──────────────────────────────────────────────────────────
        if raw.lower() == "/exit":
            _print("Goodbye.")
            break

        if raw.lower() == "/scan":
            do_scan(cfg)
            continue

        if raw.lower() == "/docs":
            cmd_docs(cfg)
            continue

        if raw.lower() == "/status":
            cmd_status(cfg)
            continue

        # ── Question flow ─────────────────────────────────────────────────────

        # Rescan before every question (picks up new files without restart)
        results = run_ingestion(cfg)
        new_or_updated = [
            r for r in results
            if r.status in (IngestionStatus.NEW, IngestionStatus.UPDATED)
        ]
        if new_or_updated:
            _print("")
            _print_ingestion_results(new_or_updated)

        _print("\n⏳ Thinking...")

        try:
            rag_result: RAGResult = answer_question(raw, conversation_history, cfg)
        except RuntimeError as exc:
            _print(f"\n✗ Error: {exc}")
            continue

        _print(f"\nAssistant:\n{rag_result.answer}")
        _print_sources(rag_result.sources)

        # Update conversation history
        conversation_history.append({"role": "user", "content": raw})
        conversation_history.append(
            {"role": "assistant", "content": rag_result.answer}
        )
        conversation_history = trim_history(
            conversation_history, cfg.max_history_messages
        )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Load & validate configuration
    try:
        cfg = load_config()
    except EnvironmentError as exc:
        print(f"\n✗ Configuration error:\n  {exc}")
        sys.exit(1)

    # Run startup checks + banner
    startup(cfg)

    # Initial folder scan + ingestion
    do_scan(cfg)

    # Print ready prompt
    _print(f"\n{'=' * 60}")

    # Start interactive loop
    run_cli(cfg)


if __name__ == "__main__":
    main()
