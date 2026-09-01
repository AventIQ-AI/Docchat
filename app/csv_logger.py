"""
app/csv_logger.py
=================
Thread-safe CSV activity logging module for the Ollama Persistent Folder RAG system.
Logs events in exact format: datetime, module_name, action, status, details.
"""

from __future__ import annotations

import csv
import datetime
import logging
from pathlib import Path
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Directory and File path
LOGS_DIR = Path("logs")
LOGS_FILE = LOGS_DIR / "app_activity.csv"

_CSV_LOCK = threading.Lock()
_CSV_HEADERS = ["datetime", "module_name", "action", "status", "details"]


def _ensure_csv_initialized() -> None:
    """Ensure logs directory and CSV file with headers exist."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if not LOGS_FILE.exists():
            with _CSV_LOCK:
                with open(LOGS_FILE, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(_CSV_HEADERS)
    except Exception as exc:
        logger.error(f"Failed to initialize CSV log file: {exc}")


def log_csv(module_name: str, action: str, status: str, details: str = "") -> None:
    """
    Log an action entry into logs/app_activity.csv.
    Format: datetime, module_name, action, status, details
    """
    _ensure_csv_initialized()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [now_str, module_name, action, status, str(details)]

    try:
        with _CSV_LOCK:
            with open(LOGS_FILE, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row)
    except Exception as exc:
        logger.error(f"Failed to write entry to CSV log: {exc}")


def get_recent_csv_logs(limit: int = 100) -> list[dict[str, str]]:
    """Return the recent N CSV log records as dictionaries."""
    _ensure_csv_initialized()
    records: list[dict[str, str]] = []

    try:
        with _CSV_LOCK:
            if LOGS_FILE.exists():
                with open(LOGS_FILE, mode="r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    records = list(reader)
    except Exception as exc:
        logger.error(f"Failed to read CSV log file: {exc}")

    # Return newest entries first
    records.reverse()
    return records[:limit]
