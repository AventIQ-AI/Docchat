"""
app/rag.py
==========
Retrieval-Augmented Generation pipeline:

  User question
    → embed question
    → pgvector cosine similarity search
    → Top-K chunks
    → build grounded context
    → qwen3:4b via Ollama
    → grounded answer + source citations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import Config
from app.csv_logger import log_csv
from app.ollama_client import chat, embed_single
from app.repository import ChunkRecord, vector_search

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert document-grounded assistant.
You must answer questions strictly using the provided document context excerpts.

CRITICAL MANDATORY CITATION RULES:
1. Do not invent facts or use outside knowledge.
2. For EVERY claim, fact, number, URL, or detail in your answer, you MUST insert inline citation tags like [S1], [S2], [S3] matching the exact source chunk used. For example: "The SAP contract processing URL is https://example.com [S1]."
3. If the context does not contain the answer, respond exactly:
   "I could not find this information in the indexed documents."
4. Be concise, direct, and clear.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RAGResult:
    answer: str
    sources: list[ChunkRecord]


# ─────────────────────────────────────────────────────────────────────────────
# Context builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_context_block(sources: list[ChunkRecord]) -> str:
    """Format retrieved chunks as a numbered knowledge context block."""
    lines: list[str] = ["KNOWLEDGE CONTEXT", ""]
    for idx, chunk in enumerate(sources, start=1):
        lines.append(f"[S{idx}]")
        lines.append(f"File: {chunk.file_name}")
        if chunk.page_number is not None:
            lines.append(f"Page: {chunk.page_number}")
        lines.append(f"Content:\n{chunk.text.strip()}")
        lines.append("")  # blank separator
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Conversation history management
# ─────────────────────────────────────────────────────────────────────────────

def trim_history(
    history: list[dict[str, str]],
    max_messages: int,
) -> list[dict[str, str]]:
    """
    Keep only the most recent *max_messages* entries from conversation history.

    Ensures we always keep pairs (user + assistant) to avoid orphaned turns.
    """
    if len(history) <= max_messages:
        return history
    # Always trim to an even count to preserve user/assistant pairs
    trimmed = history[-max_messages:]
    return trimmed


# ─────────────────────────────────────────────────────────────────────────────
# Main RAG function
# ─────────────────────────────────────────────────────────────────────────────

def answer_question(
    question: str,
    history: list[dict[str, str]],
    cfg: Config,
    doc_ids: Optional[list[int]] = None,
    model: Optional[str] = None,
) -> RAGResult:
    """
    Full RAG pipeline with optional session-isolated doc_ids filtering and dynamic model selection:

    1. Embed the user question.
    2. pgvector similarity search → Top-K chunks (filtered by doc_ids if provided).
    3. Build grounded context string.
    4. Send [system, ...history, context+question] to selected LLM.
    5. Return answer + source chunk list.
    """
    # Step 1 – embed the question
    try:
        question_embedding = embed_single(question, cfg)
    except RuntimeError as exc:
        raise RuntimeError(f"Failed to embed question: {exc}") from exc

    # If doc_ids is an empty list, fallback to searching all indexed documents
    search_doc_ids = doc_ids if (doc_ids and len(doc_ids) > 0) else None

    # Step 2 – vector search with smart Top-K expansion for broad/listing queries
    is_broad_query = any(w in question.lower() for w in ["all", "how many", "total", "list", "every", "count", "invoice", "part", "summary"])
    effective_top_k = max(cfg.top_k, 15) if is_broad_query else cfg.top_k

    sources: list[ChunkRecord] = vector_search(
        question_embedding, effective_top_k, cfg, doc_ids=search_doc_ids
    )

    # Step 3 – build context
    if not sources:
        # No indexed documents yet
        return RAGResult(
            answer="I could not find this information in the indexed documents.",
            sources=[],
        )

    context_block = _build_context_block(sources)

    # Step 4 – assemble messages
    # System prompt + trimmed history + current question (with context injected)
    trimmed_history = trim_history(history, cfg.max_history_messages)

    user_message = f"{context_block}\n\nQUESTION:\n{question}"

    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_message})

    target_model = model.strip() if model and model.strip() else cfg.ollama_chat_model

    # Step 5 – generate answer using specified model
    try:
        answer = chat(messages, cfg, temperature=0.2, model=target_model)
        log_csv("RAG_PIPELINE", "GENERATE_ANSWER", "SUCCESS", f"model: {target_model}, sources: {len(sources)}")
    except RuntimeError as exc:
        log_csv("RAG_PIPELINE", "GENERATE_ANSWER", "WARNING_OOM_FALLBACK", f"model {target_model} failed: {exc}. Retrying with lightweight qwen2.5:1.5b")
        # Automatic memory fallback to qwen2.5:1.5b if heavy model crashes
        if target_model != "qwen2.5:1.5b":
            try:
                fallback_answer = chat(messages, cfg, temperature=0.2, model="qwen2.5:1.5b")
                final_answer = f"*(Note: Switched to qwen2.5:1.5b due to RAM constraints on '{target_model}')*\n\n{fallback_answer}"
                log_csv("RAG_PIPELINE", "GENERATE_ANSWER", "SUCCESS_FALLBACK", "model: qwen2.5:1.5b")
                return RAGResult(answer=final_answer, sources=sources)
            except RuntimeError:
                pass
        raise RuntimeError(f"Failed to generate answer: {exc}") from exc

    return RAGResult(answer=answer, sources=sources)
