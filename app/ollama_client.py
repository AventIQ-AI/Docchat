"""
app/ollama_client.py
====================
All Ollama HTTP interactions:
  - Health check (GET /api/tags)
  - Model verification
  - Embedding generation (POST /api/embed)
  - Chat / text generation (POST /api/chat)

Uses httpx for HTTP.  All timeouts are configurable via Config.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _client(cfg: Config) -> httpx.Client:
    return httpx.Client(
        base_url=cfg.ollama_base_url,
        timeout=cfg.ollama_timeout_seconds,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Health check & model verification
# ─────────────────────────────────────────────────────────────────────────────

def check_ollama(cfg: Config) -> list[str]:
    """
    Ping Ollama and return a list of locally installed model names.

    Raises RuntimeError when Ollama is not reachable.
    """
    try:
        with _client(cfg) as client:
            resp = client.get("/api/tags")
            resp.raise_for_status()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {cfg.ollama_base_url}.\n"
            "Make sure Ollama is running:  ollama serve"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text}"
        ) from exc

    data: dict[str, Any] = resp.json()
    return [m["name"] for m in data.get("models", [])]


def list_installed_models(cfg: Config) -> list[str]:
    """Return a list of locally installed Ollama model names/tags."""
    try:
        return check_ollama(cfg)
    except Exception as exc:
        logger.warning(f"Could not list Ollama models: {exc}")
        return []


def pull_model(model_name: str, cfg: Config) -> bool:
    """Pull an Ollama model via POST /api/pull."""
    try:
        with _client(cfg) as client:
            resp = client.post("/api/pull", json={"name": model_name, "stream": False}, timeout=600.0)
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.error(f"Failed to pull model '{model_name}': {exc}")
        return False


def verify_models(cfg: Config) -> None:
    """
    Ensure both the chat and embedding models are installed locally.

    Raises RuntimeError listing exactly which models are missing and
    the 'ollama pull' commands needed to install them.
    """
    installed = check_ollama(cfg)
    # Normalise: strip ":latest" variants for comparison
    installed_normalised = {m.split(":")[0] + ":" + m.split(":")[1] if ":" in m else m + ":latest"
                            for m in installed}

    missing: list[str] = []
    for required in (cfg.ollama_chat_model, cfg.ollama_embed_model):
        # Accept exact match or base-name match
        if required not in installed and required not in installed_normalised:
            # Try base-name check
            base = required.split(":")[0]
            if not any(m.split(":")[0] == base for m in installed):
                missing.append(required)

    if missing:
        pull_cmds = "\n".join(f"  ollama pull {m}" for m in missing)
        raise RuntimeError(
            "Required Ollama models are not installed.\n\n"
            "Run:\n" + pull_cmds
        )


# ─────────────────────────────────────────────────────────────────────────────
# Embeddings
# ─────────────────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], cfg: Config) -> list[list[float]]:
    """
    Generate embeddings for a batch of texts using the configured embed model.

    Uses POST /api/embed which accepts an array under the "input" key.
    Validates that the returned count matches the input count.

    Raises RuntimeError on any HTTP or shape mismatch error.
    """
    if not texts:
        return []

    payload: dict[str, Any] = {
        "model": cfg.ollama_embed_model,
        "input": texts,
    }

    try:
        with _client(cfg) as client:
            resp = client.post("/api/embed", json=payload)
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama embedding request timed out after {cfg.ollama_timeout_seconds}s.\n"
            "Increase OLLAMA_TIMEOUT_SECONDS or reduce EMBED_BATCH_SIZE."
        )
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Ollama embed API error {exc.response.status_code}: {exc.response.text}"
        ) from exc

    data: dict[str, Any] = resp.json()
    embeddings: list[list[float]] = data.get("embeddings", [])

    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: sent {len(texts)} texts, "
            f"received {len(embeddings)} embeddings."
        )

    return embeddings


def embed_single(text: str, cfg: Config) -> list[float]:
    """Convenience wrapper to embed a single string."""
    return embed_texts([text], cfg)[0]


# ─────────────────────────────────────────────────────────────────────────────
# Chat / generation
# ─────────────────────────────────────────────────────────────────────────────

def chat(
    messages: list[dict[str, str]],
    cfg: Config,
    temperature: float = 0.2,
    model: Optional[str] = None,
) -> str:
    """
    Send a multi-turn messages list to Ollama and return the assistant reply.
    Supports dynamic model override via parameter.
    """
    target_model = model.strip() if model and model.strip() else cfg.ollama_chat_model

    payload: dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "stream": False,
        "think": False,          # Disable Qwen3 thinking output
        "options": {
            "temperature": temperature,
        },
    }

    try:
        with _client(cfg) as client:
            resp = client.post("/api/chat", json=payload)
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama chat request timed out after {cfg.ollama_timeout_seconds}s.\n"
            "Increase OLLAMA_TIMEOUT_SECONDS or try a shorter question."
        )
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Ollama chat API error {exc.response.status_code}: {exc.response.text}"
        ) from exc

    data: dict[str, Any] = resp.json()
    content: str = data.get("message", {}).get("content", "")
    return content.strip()
