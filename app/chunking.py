"""
app/chunking.py
===============
Overlapping text chunking with intelligent split-point selection.

Splitting priority (per chunk boundary):
  1. Paragraph boundary  (\n\n)
  2. Sentence boundary   (. ! ?)
  3. Whitespace          ( )
  4. Hard cut            (last resort)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.parsers import ParsedBlock

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    chunk_index: int
    text: str
    page_number: Optional[int]
    char_start: int  # character offset in the document's full text
    char_end: int


# ─────────────────────────────────────────────────────────────────────────────
# Core splitting logic
# ─────────────────────────────────────────────────────────────────────────────

def _find_split_point(text: str, target: int) -> int:
    """
    Find the best split position near `target` in `text`.

    Searches backwards from target for a good boundary.
    Returns a character index into `text`.
    """
    if target >= len(text):
        return len(text)

    # Window to search backwards (up to 20% of chunk size)
    search_window = max(target // 5, 50)
    search_start = max(0, target - search_window)
    segment = text[search_start:target]

    # 1. Paragraph boundary (\n\n)
    pos = segment.rfind("\n\n")
    if pos != -1:
        return search_start + pos + 2  # after the double newline

    # 2. Single newline
    pos = segment.rfind("\n")
    if pos != -1:
        return search_start + pos + 1

    # 3. Sentence boundary (. ! ? followed by space or end)
    match = None
    for m in re.finditer(r"[.!?]\s+", segment):
        match = m
    if match:
        return search_start + match.end()

    # 4. Whitespace
    pos = segment.rfind(" ")
    if pos != -1:
        return search_start + pos + 1

    # 5. Hard cut
    return target


def chunk_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    page_number: Optional[int],
    start_chunk_index: int = 0,
) -> list[TextChunk]:
    """
    Split *text* into overlapping chunks of approximately *chunk_size* characters.

    Returns a list of TextChunk objects.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})."
        )

    chunks: list[TextChunk] = []
    text_len = len(text)
    start = 0
    chunk_idx = start_chunk_index

    while start < text_len:
        end_target = start + chunk_size
        end = _find_split_point(text, end_target)

        # Guard: if split_point didn't advance (very long word), hard-cut
        if end <= start:
            end = start + chunk_size

        # Clamp to text length
        end = min(end, text_len)

        chunk_text_content = text[start:end].strip()
        if chunk_text_content:
            chunks.append(
                TextChunk(
                    chunk_index=chunk_idx,
                    text=chunk_text_content,
                    page_number=page_number,
                    char_start=start,
                    char_end=end,
                )
            )
            chunk_idx += 1

        if end >= text_len:
            break

        # Advance with overlap
        next_start = end - chunk_overlap
        # Ensure we always make forward progress
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# High-level: chunk a list of ParsedBlocks
# ─────────────────────────────────────────────────────────────────────────────

def chunk_document(
    blocks: list[ParsedBlock],
    chunk_size: int,
    chunk_overlap: int,
) -> list[TextChunk]:
    """
    Accept parsed blocks from a document and produce a flat list of TextChunks.

    Each block's page_number is propagated to its chunks.
    Chunk indices are globally sequential across all blocks in the document.
    """
    all_chunks: list[TextChunk] = []
    global_chunk_idx = 0

    for block in blocks:
        if not block.text.strip():
            continue
        new_chunks = chunk_text(
            text=block.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            page_number=block.page_number,
            start_chunk_index=global_chunk_idx,
        )
        all_chunks.extend(new_chunks)
        global_chunk_idx += len(new_chunks)

    logger.debug("Produced %d chunks from %d block(s).", len(all_chunks), len(blocks))
    return all_chunks
