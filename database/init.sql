-- database/init.sql
-- Idempotent schema initialization for ollama-folder-rag
-- Run this manually OR let app/db.py execute it at startup.

-- Enable pgvector extension (requires pgvector to be installed in PostgreSQL)
CREATE EXTENSION IF NOT EXISTS vector;

-- ----------------------------------------------------------------
-- TABLE: documents
-- Stores metadata + SHA-256 hash for every ingested file.
-- source_path is unique to prevent duplicates.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents
(
    id             BIGSERIAL     PRIMARY KEY,
    source_path    TEXT          NOT NULL UNIQUE,
    file_name      TEXT          NOT NULL,
    file_extension TEXT,
    sha256         TEXT          NOT NULL,
    file_size      BIGINT,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    ingested_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------
-- TABLE: chunks
-- Stores individual text chunks plus their pgvector embeddings.
-- document_id → documents.id with CASCADE DELETE so that
-- re-indexing a document can cleanly remove stale chunks.
-- embedding column uses unconstrained VECTOR so the dimension is
-- discovered at runtime from the actual model output.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks
(
    id            BIGSERIAL   PRIMARY KEY,
    document_id   BIGINT      NOT NULL
                      REFERENCES documents(id)
                      ON DELETE CASCADE,
    chunk_index   INTEGER     NOT NULL,
    page_number   INTEGER,
    text          TEXT        NOT NULL,
    embedding     VECTOR(1024) NOT NULL,
    metadata      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(document_id, chunk_index)
);

-- Ensure embedding column has explicit dimension 1024 if table existed previously unconstrained
DO $$
BEGIN
    ALTER TABLE chunks ALTER COLUMN embedding TYPE VECTOR(1024);
EXCEPTION
    WHEN OTHERS THEN NULL;
END $$;

-- ----------------------------------------------------------------
-- INDEX: cosine similarity search via pgvector ivfflat
-- Created AFTER initial data load for best performance.
-- Using hnsw which works well even on small datasets.
-- ----------------------------------------------------------------
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks
    USING hnsw (embedding vector_cosine_ops);
