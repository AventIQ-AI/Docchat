"""
app/scanner.py
==============
Recursively scans DOCUMENTS_FOLDER for supported file types.
Unsupported files are silently skipped.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported extensions (lower-case, with leading dot)
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".txt", ".md"})


def scan_folder(folder: Path) -> list[Path]:
    """
    Recursively walk *folder* and return a sorted list of supported file paths.

    Rules:
    - Non-existent folder → returns empty list with a warning (not an error).
    - Files with unsupported extensions are ignored silently.
    - Hidden files / system files are included if their extension matches.
    - Permission errors on individual entries are logged and skipped.
    """
    if not folder.exists():
        logger.warning(
            "Document folder does not exist: %s\n"
            "Create the folder and add documents to index them.",
            folder,
        )
        return []

    if not folder.is_dir():
        logger.warning("DOCUMENTS_FOLDER path is not a directory: %s", folder)
        return []

    found: list[Path] = []

    try:
        for entry in folder.rglob("*"):
            try:
                if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                    found.append(entry.resolve())
            except PermissionError as exc:
                logger.warning("Permission denied, skipping: %s — %s", entry, exc)
            except OSError as exc:
                logger.warning("OS error scanning entry %s — %s", entry, exc)
    except PermissionError as exc:
        logger.error("Permission denied reading folder %s — %s", folder, exc)
    except OSError as exc:
        logger.error("OS error scanning folder %s — %s", folder, exc)

    found.sort()
    logger.debug("Folder scan found %d supported file(s) in %s.", len(found), folder)
    return found
