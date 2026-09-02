"""
app/api.py
==========
FastAPI REST API application for the Ollama Persistent Folder RAG chatbot.
Exposes endpoints for querying, uploading documents, listing documents,
deleting documents, folder scanning, and system health checks.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.csv_logger import log_csv, get_recent_csv_logs, LOGS_FILE

from app.config import Config, load_config
from app.db import check_postgres, get_knowledge_stats, init_schema
from app.ingestion import (
    IngestionResult,
    IngestionStatus,
    ingest_uploaded_file,
    run_ingestion,
)
from app.ollama_client import check_ollama, verify_models, list_installed_models, pull_model
from app.rag import RAGResult, answer_question
from app.repository import delete_document_by_id, list_indexed_documents

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Ollama Folder RAG API",
    description="Local & Cloud-deployable REST API for RAG chatbot backed by Ollama and PostgreSQL pgvector.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Global config cache
_cfg: Optional[Config] = None


def get_cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


# Add CORS middleware at app level
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    cfg = get_cfg()
    # Initialize schema idempotently on startup
    try:
        init_schema(cfg)
        logger.info("Database schema initialized successfully.")
    except Exception as exc:
        logger.error("Failed to initialize database schema on API startup: %s", exc)


def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    cfg: Config = Depends(get_cfg),
) -> None:
    """Optional API key authentication dependency if API_KEY is set in .env."""
    if cfg.api_key and x_api_key != cfg.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text content")


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question text")
    history: list[ChatMessage] = Field(
        default_factory=list, description="Conversation history"
    )
    top_k: Optional[int] = Field(
        default=None, description="Optional override for top_k document retrieval"
    )
    doc_ids: Optional[list[int]] = Field(
        default=None, description="Optional document IDs list for per-session isolation"
    )
    model: Optional[str] = Field(
        default=None, description="Optional LLM model override for generation"
    )


class ModelPullRequest(BaseModel):
    model: str = Field(..., min_length=1, description="Model tag name to pull, e.g., llama3.2:1b")


class SourceChunkResponse(BaseModel):
    chunk_id: int
    file_name: str
    source_path: str
    page_number: Optional[int]
    similarity: float
    text: str


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunkResponse]


class DocumentSummaryResponse(BaseModel):
    id: int
    file_name: str
    source_path: str
    sha256: str
    chunk_count: int
    ingested_at: str


class IngestionItemResponse(BaseModel):
    file_name: str
    source_path: str
    status: str
    chunk_count: int
    error: Optional[str] = ""


class IngestionSummaryResponse(BaseModel):
    results: list[IngestionItemResponse]
    stats: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    postgres: str
    pgvector: str
    ollama: str
    chat_model: str
    embed_model: str
    knowledge_base: dict[str, int]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
def health_check(cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    """Check connection status for PostgreSQL, pgvector, and Ollama."""
    pg_status = "Disconnected"
    vector_status = "Disabled"
    try:
        res = check_postgres(cfg)
        pg_status = res.get("postgres", "Connected")
        vector_status = res.get("pgvector", "Enabled")
    except Exception as exc:
        pg_status = f"Error: {exc}"

    ollama_status = "Disconnected"
    try:
        check_ollama(cfg)
        verify_models(cfg)
        ollama_status = "Connected"
    except Exception as exc:
        ollama_status = f"Error: {exc}"

    stats = {"documents": 0, "chunks": 0}
    try:
        stats = get_knowledge_stats(cfg)
    except Exception:
        pass

    overall = (
        "healthy"
        if ("Connected" in pg_status and "Connected" in ollama_status)
        else "unhealthy"
    )

    return {
        "status": overall,
        "postgres": pg_status,
        "pgvector": vector_status,
        "ollama": ollama_status,
        "chat_model": cfg.ollama_chat_model,
        "embed_model": cfg.ollama_embed_model,
        "knowledge_base": stats,
    }


@app.post(
    "/api/query",
    response_model=QueryResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["RAG"],
)
def query_rag(req: QueryRequest, cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    """Ask a question to the RAG chatbot using retrieved context."""
    # Convert Pydantic history models to dict format for RAG pipeline
    history_dicts = [{"role": msg.role, "content": msg.content} for msg in req.history]

    # Optionally override top_k for this request
    effective_cfg = cfg
    if req.top_k is not None and req.top_k > 0:
        # Create a modified config copy
        effective_cfg = Config(
            ollama_base_url=cfg.ollama_base_url,
            ollama_chat_model=cfg.ollama_chat_model,
            ollama_embed_model=cfg.ollama_embed_model,
            ollama_timeout_seconds=cfg.ollama_timeout_seconds,
            postgres_host=cfg.postgres_host,
            postgres_port=cfg.postgres_port,
            postgres_db=cfg.postgres_db,
            postgres_user=cfg.postgres_user,
            postgres_password=cfg.postgres_password,
            documents_folder=cfg.documents_folder,
            top_k=req.top_k,
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.chunk_overlap,
            embed_batch_size=cfg.embed_batch_size,
            max_history_messages=cfg.max_history_messages,
            api_host=cfg.api_host,
            api_port=cfg.api_port,
            cors_origins=cfg.cors_origins,
            api_key=cfg.api_key,
        )

    try:
        result: RAGResult = answer_question(
            question=req.question,
            history=history_dicts,
            cfg=effective_cfg,
            doc_ids=req.doc_ids,
            model=req.model,
        )
        log_csv("RAG_API", "QUERY", "SUCCESS", f"question: {req.question[:40]}..., model: {req.model or cfg.ollama_chat_model}")
    except RuntimeError as exc:
        log_csv("RAG_API", "QUERY", "FAILED", f"error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RAG query failed: {exc}",
        )

    sources_response = [
        SourceChunkResponse(
            chunk_id=c.id,
            file_name=c.file_name,
            source_path=c.source_path,
            page_number=c.page_number,
            similarity=round(c.similarity, 4),
            text=c.text,
        )
        for c in result.sources
    ]

    return {
        "question": req.question,
        "answer": result.answer,
        "sources": sources_response,
    }


@app.get(
    "/api/documents",
    response_model=list[DocumentSummaryResponse],
    dependencies=[Depends(verify_api_key)],
    tags=["Documents"],
)
def list_documents(cfg: Config = Depends(get_cfg)) -> list[dict[str, Any]]:
    """List all indexed documents in the knowledge base."""
    docs = list_indexed_documents(cfg)
    return [
        {
            "id": d.id,
            "file_name": d.file_name,
            "source_path": d.source_path,
            "sha256": d.sha256,
            "chunk_count": d.chunk_count,
            "ingested_at": (
                d.ingested_at.isoformat() if d.ingested_at else ""
            ),
        }
        for d in docs
    ]


@app.post(
    "/api/documents/upload",
    response_model=IngestionSummaryResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Documents"],
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    cfg: Config = Depends(get_cfg),
) -> dict[str, Any]:
    """Upload one or more files (.pdf, .docx, .txt, .md) to be parsed, chunked, and indexed."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided."
        )

    results: list[IngestionItemResponse] = []
    for file in files:
        content = await file.read()
        res = ingest_uploaded_file(file.filename, content, cfg)
        results.append(
            IngestionItemResponse(
                file_name=res.file_name,
                source_path=res.source_path,
                status=res.status.name,
                chunk_count=res.chunk_count,
                error=res.error or "",
            )
        )
        log_csv("INGESTION", "FILE_UPLOAD", res.status.name, f"file: {res.file_name}, chunks: {res.chunk_count}")

    stats = get_knowledge_stats(cfg)
    return {"results": results, "stats": stats}


@app.delete(
    "/api/documents/{doc_id}",
    dependencies=[Depends(verify_api_key)],
    tags=["Documents"],
)
def delete_document(doc_id: int, cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    """Delete an indexed document and its vector chunks from the database by ID."""
    success = delete_document_by_id(doc_id, cfg)
    if not success:
        log_csv("REPOSITORY", "DELETE_DOCUMENT", "FAILED", f"doc_id: {doc_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {doc_id} not found.",
        )
    log_csv("REPOSITORY", "DELETE_DOCUMENT", "SUCCESS", f"doc_id: {doc_id} deleted")
    stats = get_knowledge_stats(cfg)
    return {
        "message": f"Document ID {doc_id} successfully deleted.",
        "stats": stats,
    }


@app.post(
    "/api/scan",
    response_model=IngestionSummaryResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Documents"],
)
def trigger_scan(cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    """Rescan the server's documents directory for new or updated files."""
    raw_results = run_ingestion(cfg)
    item_results = [
        IngestionItemResponse(
            file_name=r.file_name,
            source_path=r.source_path,
            status=r.status.name,
            chunk_count=r.chunk_count,
            error=r.error,
        )
        for r in raw_results
    ]
    log_csv("INGESTION", "FOLDER_SCAN", "COMPLETED", f"files_processed: {len(raw_results)}")
    stats = get_knowledge_stats(cfg)
    return {"results": item_results, "stats": stats}


@app.get(
    "/api/models",
    tags=["Models"],
)
def get_installed_models(cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    """List locally installed Ollama models."""
    models = list_installed_models(cfg)
    return {"models": models}


@app.post(
    "/api/models/pull",
    tags=["Models"],
)
def pull_model_endpoint(req: ModelPullRequest, cfg: Config = Depends(get_cfg)) -> dict[str, Any]:
    """Pull/download an Ollama model asynchronously."""
    log_csv("OLLAMA", "PULL_MODEL_START", "IN_PROGRESS", f"model: {req.model}")
    success = pull_model(req.model, cfg)
    if not success:
        log_csv("OLLAMA", "PULL_MODEL", "FAILED", f"model: {req.model}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pull model '{req.model}'. Make sure Ollama has internet access.",
        )
    log_csv("OLLAMA", "PULL_MODEL", "SUCCESS", f"model: {req.model}")
    return {"message": f"Model '{req.model}' pulled successfully.", "model": req.model}


@app.get(
    "/api/logs",
    tags=["System"],
)
def get_activity_logs(limit: int = 100) -> dict[str, Any]:
    """Retrieve recent CSV application activity logs."""
    logs = get_recent_csv_logs(limit=limit)
    return {"count": len(logs), "logs": logs}


@app.get(
    "/api/logs/csv",
    tags=["System"],
)
def download_activity_csv_file() -> FileResponse:
    """Download the raw app_activity.csv file directly."""
    if not LOGS_FILE.exists():
        log_csv("SYSTEM", "INITIALIZE_LOGS", "CREATED", "logs/app_activity.csv created")
    return FileResponse(
        path=LOGS_FILE,
        filename="app_activity.csv",
        media_type="text/csv",
    )
