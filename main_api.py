"""
main_api.py
===========
Web API entry point for launching the FastAPI server with Uvicorn.

Usage:
  python main_api.py
"""

from __future__ import annotations

import logging
import sys
import uvicorn

from app.config import load_config
from app.db import check_postgres, init_schema
from app.ollama_client import check_ollama, verify_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("rag_api")


def main() -> None:
    try:
        cfg = load_config()
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Starting Ollama Persistent Folder RAG REST API")
    logger.info("=" * 60)

    # Validate database connection
    try:
        pg_status = check_postgres(cfg)
        logger.info("PostgreSQL: %s | pgvector: %s", pg_status["postgres"], pg_status["pgvector"])
        init_schema(cfg)
    except Exception as exc:
        logger.warning("PostgreSQL warning during startup: %s", exc)

    # Validate Ollama connection
    try:
        check_ollama(cfg)
        verify_models(cfg)
        logger.info("Ollama: Connected (%s)", cfg.ollama_base_url)
        logger.info("Chat Model: %s | Embed Model: %s", cfg.ollama_chat_model, cfg.ollama_embed_model)
    except Exception as exc:
        logger.warning("Ollama warning during startup: %s", exc)

    logger.info("Serving API at http://%s:%d", cfg.api_host, cfg.api_port)
    logger.info("Swagger docs at http://%s:%d/docs", cfg.api_host, cfg.api_port)

    uvicorn.run(
        "app.api:app",
        host=cfg.api_host,
        port=cfg.api_port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
