"""
app/chroma_repository.py
=========================
ChromaDB Vector Database implementation.
Provides persistent vector storage, metadata filtering, and similarity search.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import chromadb
from chromadb.config import Settings

from app.chunking import TextChunk
from app.config import Config
from app.repository import ChunkRecord

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "docchat_chunks"
_chroma_client: Optional[chromadb.PersistentClient] = None


def get_chroma_client(cfg: Config) -> chromadb.PersistentClient:
    """Return a persistent ChromaDB client instance."""
    global _chroma_client
    if _chroma_client is None:
        cfg.chroma_db_path.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(cfg.chroma_db_path.resolve()),
            settings=Settings(anonymized_telemetry=False)
        )
    return _chroma_client


def get_chroma_collection(cfg: Config) -> Any:
    """Get or create the ChromaDB collection for Docchat chunks."""
    client = get_chroma_client(cfg)
    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    if collection.count() == 0:
        sync_postgres_chunks_to_chroma(collection, cfg)
    return collection


def sync_postgres_chunks_to_chroma(collection: Any, cfg: Config) -> None:
    """Sync existing text chunks & vector embeddings from PostgreSQL to ChromaDB."""
    try:
        from app.db import get_connection
        conn = get_connection(cfg)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.document_id, c.chunk_index, c.page_number, c.text, c.embedding, d.file_name, d.source_path
                FROM chunks c
                JOIN documents d ON d.id = c.document_id;
            """)
            rows = cur.fetchall()
        conn.close()

        if not rows:
            return

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        embeds: list[list[float]] = []

        for row in rows:
            cid, doc_id, chunk_idx, page_num, text, emb, file_name, source_path = row
            ids.append(f"doc_{doc_id}_chunk_{chunk_idx}")
            documents.append(text)
            # Convert embedding to float list safely from pgvector / numpy / string
            if hasattr(emb, "to_list"):
                embeds.append(emb.to_list())
            elif hasattr(emb, "tolist"):
                embeds.append(emb.tolist())
            elif hasattr(emb, "to_numpy"):
                embeds.append(emb.to_numpy().tolist())
            elif isinstance(emb, str):
                cleaned = emb.strip("[]() ").split(",")
                embeds.append([float(x) for x in cleaned if x.strip()])
            else:
                embeds.append([float(x) for x in list(emb)])

            metadatas.append({
                "document_id": doc_id,
                "chunk_index": chunk_idx,
                "page_number": page_num or 1,
                "file_name": file_name,
                "source_path": source_path,
            })

        collection.upsert(
            ids=ids,
            embeddings=embeds,
            documents=documents,
            metadatas=metadatas
        )
        logger.info(f"Synced {len(rows)} existing chunks from PostgreSQL to ChromaDB")
    except Exception as exc:
        logger.warning(f"Could not sync PostgreSQL chunks to ChromaDB: {exc}")


def add_chunks_chroma(
    doc_id: int,
    file_name: str,
    source_path: str,
    chunks: list[PreparedChunk],
    embeddings: list[list[float]],
    cfg: Config,
) -> None:
    """Store text chunks and embeddings into ChromaDB."""
    if not chunks:
        return

    collection = get_chroma_collection(cfg)

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    embeds: list[list[float]] = []

    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"doc_{doc_id}_chunk_{chunk.chunk_index}"
        ids.append(chunk_id)
        documents.append(chunk.text)
        embeds.append(emb)

        meta = {
            "document_id": doc_id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number or 1,
            "file_name": file_name,
            "source_path": source_path,
        }
        metadatas.append(meta)

    collection.upsert(
        ids=ids,
        embeddings=embeds,
        documents=documents,
        metadatas=metadatas
    )
    logger.info(f"Inserted {len(chunks)} chunks into ChromaDB for document_id={doc_id}")


def vector_search_chroma(
    query_embedding: list[float],
    top_k: int,
    cfg: Config,
    doc_ids: Optional[list[int]] = None,
) -> list[ChunkRecord]:
    """
    Perform cosine similarity vector search in ChromaDB.
    Supports session-isolated document ID filtering via doc_ids.
    """
    collection = get_chroma_collection(cfg)

    where_filter: Optional[dict[str, Any]] = None
    if doc_ids is not None:
        if not doc_ids:
            return []
        if len(doc_ids) == 1:
            where_filter = {"document_id": doc_ids[0]}
        else:
            where_filter = {"document_id": {"$in": doc_ids}}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, max(1, collection.count())),
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    chunk_records: list[ChunkRecord] = []
    if not results or not results.get("ids") or not results["ids"][0]:
        return chunk_records

    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for chunk_id, text, meta, dist in zip(ids, docs, metas, distances):
        # Convert cosine distance to similarity score (1 - distance)
        similarity = max(0.0, min(1.0, 1.0 - float(dist)))

        rec = ChunkRecord(
            id=hash(chunk_id) & 0x7FFFFFFF,
            document_id=int(meta.get("document_id", 0)),
            chunk_index=int(meta.get("chunk_index", 0)),
            page_number=int(meta.get("page_number", 1)),
            text=text,
            metadata=meta,
            file_name=str(meta.get("file_name", "Document")),
            source_path=str(meta.get("source_path", "")),
            similarity=similarity,
        )
        chunk_records.append(rec)

    # Sort descending by similarity
    chunk_records.sort(key=lambda r: r.similarity, reverse=True)
    return chunk_records[:top_k]


def delete_document_chroma(doc_id: int, cfg: Config) -> None:
    """Delete all chunks belonging to doc_id from ChromaDB."""
    try:
        collection = get_chroma_collection(cfg)
        collection.delete(where={"document_id": doc_id})
        logger.info(f"Deleted chunks for document_id={doc_id} from ChromaDB")
    except Exception as exc:
        logger.warning(f"Failed to delete document {doc_id} from ChromaDB: {exc}")
