"""
app/parsers.py
==============
Document text extraction for PDF, DOCX, TXT, and Markdown.

Each parser returns a list of ParsedBlock namedtuples:
  - text        : extracted text string
  - page_number : 1-based page number (None for formats without pages)

One corrupted document raises ParserError; caller decides whether to skip.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ParsedBlock(NamedTuple):
    text: str
    page_number: int | None  # None when source format has no page concept


class ParserError(Exception):
    """Raised when a document cannot be parsed."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_whitespace(text: str) -> str:
    """Collapse runs of whitespace / blank lines into single newlines."""
    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse horizontal whitespace inside lines
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

def parse_pdf(path: Path) -> list[ParsedBlock]:
    """Extract text page-by-page from a PDF using pypdf."""
    try:
        import pypdf  # type: ignore[import]
    except ImportError:
        raise ParserError("pypdf is not installed.  Run: pip install pypdf")

    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as exc:
        raise ParserError(f"Cannot open PDF '{path.name}': {exc}") from exc

    if len(reader.pages) == 0:
        raise ParserError(f"PDF '{path.name}' has no pages.")

    blocks: list[ParsedBlock] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
            text = _normalise_whitespace(raw)
            if text:
                blocks.append(ParsedBlock(text=text, page_number=page_num))
        except Exception as exc:
            logger.warning(
                "Could not extract page %d from '%s': %s", page_num, path.name, exc
            )

    if not blocks:
        raise ParserError(f"PDF '{path.name}' yielded no extractable text.")

    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# DOCX
# ─────────────────────────────────────────────────────────────────────────────

def parse_docx(path: Path) -> list[ParsedBlock]:
    """Extract paragraph text from a DOCX file using python-docx."""
    try:
        import docx as python_docx  # type: ignore[import]
    except ImportError:
        raise ParserError("python-docx is not installed.  Run: pip install python-docx")

    try:
        doc = python_docx.Document(str(path))
    except Exception as exc:
        raise ParserError(f"Cannot open DOCX '{path.name}': {exc}") from exc

    paragraphs: list[str] = []
    for para in doc.paragraphs:
        text = _normalise_whitespace(para.text)
        if text:
            paragraphs.append(text)

    if not paragraphs:
        raise ParserError(f"DOCX '{path.name}' yielded no extractable text.")

    # Combine all paragraphs into a single block (page numbers not available)
    full_text = "\n\n".join(paragraphs)
    return [ParsedBlock(text=full_text, page_number=None)]


# ─────────────────────────────────────────────────────────────────────────────
# TXT / Markdown
# ─────────────────────────────────────────────────────────────────────────────

def parse_text(path: Path) -> list[ParsedBlock]:
    """Read a plain-text or Markdown file as UTF-8."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError as exc:
        raise ParserError(f"Permission denied reading '{path.name}': {exc}") from exc
    except OSError as exc:
        raise ParserError(f"Cannot read '{path.name}': {exc}") from exc

    text = _normalise_whitespace(raw)
    if not text:
        raise ParserError(f"'{path.name}' is empty.")

    return [ParsedBlock(text=text, page_number=None)]


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def parse_document(path: Path) -> list[ParsedBlock]:
    """
    Dispatch to the correct parser based on file extension.

    Raises ParserError for unsupported extensions or parse failures.
    """
    ext = path.suffix.lower()

    if ext == ".pdf":
        return parse_pdf(path)
    elif ext == ".docx":
        return parse_docx(path)
    elif ext in (".txt", ".md"):
        return parse_text(path)
    else:
        raise ParserError(
            f"Unsupported file type '{ext}' for '{path.name}'."
        )
