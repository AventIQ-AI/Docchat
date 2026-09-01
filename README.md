# Local Ollama Persistent Folder RAG & Chatbot

A privacy-preserving, enterprise-grade Retrieval-Augmented Generation (RAG) system with a **ChatGPT-style React UI** and **FastAPI REST backend**.  
No cloud AI, no external APIs — everything runs locally on your machine.

```
[ Attached Document / File ]
           │
           ▼
 [ React UI Frontend ] ── (POST /api/documents/upload) ──► [ FastAPI Backend ]
                                                                   │
 ┌─────────────────────────────────────────────────────────────────┴────────────────────────────────┐
 │ 1. Parse File (.pdf, .docx, .txt, .md)                                                           │
 │ 2. Split into Overlapping Chunks (1200 chars)                                                    │
 │ 3. Generate Vector Embeddings ── (Ollama API: qwen3-embedding:0.6b, 1024 dims)                   │
 │ 4. Store in PostgreSQL + pgvector (documents & chunks tables with HNSW vector index)             │
 └─────────────────────────────────────────────────────────────────┬────────────────────────────────┘
                                                                   │
 [ User Question ] ── (POST /api/query) ───────────────────────────┤
                                                                   ▼
                                                [ Vector Search (pgvector) ]
                                                • Cosine similarity search (1 - embedding <=> query)
                                                • Filtered strictly by session doc_ids
                                                • Top-K chunk retrieval
                                                                   │
                                                                   ▼
                                                [ LLM Generation (Ollama) ]
                                                • Prompt = System + History + Context + Question
                                                • Model = qwen2.5:1.5b (1.1 GB RAM efficient)
                                                • Returns grounded answer + [S1], [S2] citations
```

---

## 📑 Contents

- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [Module & Code Architecture](#module--code-architecture)
  - [Backend Architecture (`app/`)](#1-backend-architecture-app)
  - [Database Layer (`database/`)](#2-database-layer-database)
  - [Frontend Architecture (`frontend/`)](#3-frontend-architecture-frontend)
  - [Deployment & Containers](#4-deployment--containers)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
- [Quickstart Guide](#quickstart-guide)
  - [Option A: Running with Docker Compose (Recommended)](#option-a-running-with-docker-compose-recommended)
  - [Option B: Running Locally (Python + React Dev Server)](#option-b-running-locally-python--react-dev-server)
- [Troubleshooting](#troubleshooting)

---

## 💡 Project Overview

This application allows you to ask questions about your documents (PDFs, Word documents, Markdown, Text files) using a locally running LLM.

- **Privacy-Preserving**: No data leaves your network or local environment.
- **RAG Architecture**: Documents are parsed, chunked, embedded, and stored in PostgreSQL using pgvector. At query time, the relevant chunks are retrieved and provided as context to the local LLM (`qwen2.5:1.5b`).
- **Grounded Citations**: The LLM cites exact sources (`[S1]`, `[S2]`) corresponding to retrieved document snippets.

---

## ✨ Key Features

- **ChatGPT-Style React Interface**: Dark & Light mode toggle, auto-expanding textarea, avatar bubbles, markdown rendering, and empty prompt suggestions.
- **Inline Chat Document Attachments**: Attach documents using the 📎 paperclip button directly in the chat bar.
- **Per-Session Document Isolation**: Document knowledge is strictly scoped to the chat session it was uploaded to, avoiding cross-chat knowledge leakage.
- **Persistent Multi-Session History**: Multiple chat threads saved automatically in `localStorage`.
- **Interactive Citation Inspection Drawer**: Click any `[S1]` or `[S2]` citation pill to open a slide-over panel displaying the exact text snippet, file path, page number, and similarity score.
- **RAM-Optimized Model Default**: Defaults to `qwen2.5:1.5b` (1.1 GB RAM requirement), making it fast and lightweight for laptops with 8 GB RAM.

---

## 📁 Module & Code Architecture

### 1. Backend Architecture (`app/`)

| File / Module | Description |
| :--- | :--- |
| [`app/config.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/config.py) | Configuration loader using Python `@dataclass`. Reads `.env` settings for Ollama endpoints, PostgreSQL credentials, top_k, and default model fallbacks (`qwen2.5:1.5b`). |
| [`app/db.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/db.py) | Database connection helper and schema initializer. Executes `database/init.sql` on startup. |
| [`app/repository.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/repository.py) | Data Access Layer (CRUD). Performs batch inserts and vector similarity search (`vector_search`) with `WHERE d.id = ANY(%s::int[])` for session isolation. |
| [`app/ollama_client.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/ollama_client.py) | HTTP client interacting with Ollama REST API (`/api/embed` and `/api/chat`). |
| [`app/parser.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/parser.py) | Document text extractor supporting `.pdf` (via `pypdf`), `.docx` (via `python-docx`), `.txt`, and `.md` files. |
| [`app/chunker.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/chunker.py) | Segments long document text into overlapping chunks (`chunk_size=1200`, `chunk_overlap=200`). |
| [`app/ingestion.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/ingestion.py) | Ingestion pipeline coordinator. Computes SHA-256 hashes to prevent redundant processing and handles direct HTTP file uploads. |
| [`app/rag.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/rag.py) | RAG pipeline: embeds question -> queries pgvector -> builds context block -> invokes Ollama chat LLM -> returns answer + citations. |
| [`app/api.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/app/api.py) | FastAPI REST service defining endpoints for health, querying, file upload, document management, and directory scanning. |
| [`main_api.py`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/main_api.py) | Uvicorn server entry point (`http://0.0.0.0:8000`). |

---

### 2. Database Layer (`database/`)

- [`database/init.sql`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/database/init.sql): SQL script creating the `documents` and `chunks` tables with `VECTOR(1024)` column and HNSW vector index (`vector_cosine_ops`).

---

### 3. Frontend Architecture (`frontend/`)

| File / Component | Description |
| :--- | :--- |
| [`frontend/src/App.jsx`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/frontend/src/App.jsx) | Main React state manager connecting UI state to FastAPI endpoints. Handles multi-session history, theme switching, and per-session `doc_ids` query parameters. |
| [`frontend/src/components/Sidebar.jsx`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/frontend/src/components/Sidebar.jsx) | Sidebar component containing Recent Chats switcher, Session Knowledge manager, Theme toggle, and system health status. |
| [`frontend/src/components/ChatInput.jsx`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/frontend/src/components/ChatInput.jsx) | Auto-expanding prompt bar with 📎 paperclip file attachment button, preview chips, and Top-K retrieval slider. |
| [`frontend/src/components/ChatMessage.jsx`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/frontend/src/components/ChatMessage.jsx) | Chat bubble renderer formatting markdown, file attachment badges (`📎 Attached: file.pdf`), and interactive citation pills (`[S1]`, `[S2]`). |
| [`frontend/src/components/SourcesDrawer.jsx`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/frontend/src/components/SourcesDrawer.jsx) | Slide-over drawer displaying retrieved source snippet, file name, page number, and similarity score. |
| [`frontend/src/index.css`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/frontend/src/index.css) | Complete design system supporting ChatGPT Dark Mode (`#17181c`, `#20222a`) and Soft Light Mode (`#f8fafc`, `#ffffff`, `#0f172a`). |

---

### 4. Deployment & Containers

- [`docker-compose.yml`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/docker-compose.yml): Orchestrates PostgreSQL + pgvector, Ollama LLM, model auto-puller, and FastAPI API.
- [`Dockerfile`](file:///c:/Users/ShubhamKumar/OneDrive%20-%20Mittal%20Software%20Labs%20Limited/Documents/AI/ragchatbot/ollama-folder-rag/Dockerfile): Multi-stage Dockerfile for FastAPI backend container.

---

## 🗄️ Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Document Metadata Table
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    file_hash VARCHAR(64) NOT NULL,
    chunk_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Text Chunks & Embeddings Table
CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    page_number INT DEFAULT 1,
    text TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding VECTOR(1024) NOT NULL
);

-- HNSW Cosine Distance Index
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON chunks USING hnsw (embedding vector_cosine_ops);
```

---

## 🚀 API Endpoints

Interactive Swagger UI is available at **`http://localhost:8000/docs`**.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Check health status of DB, pgvector, Ollama, and models. |
| `POST` | `/api/query` | RAG QA endpoint. Accepts `question`, `history`, `top_k`, and `doc_ids`. |
| `POST` | `/api/documents/upload` | Multipart upload for `.pdf`, `.docx`, `.txt`, `.md`. |
| `GET` | `/api/documents` | List indexed documents with chunk counts. |
| `DELETE` | `/api/documents/{doc_id}` | Cascade delete a document and its chunks. |
| `POST` | `/api/scan` | Trigger directory rescan. |

---

## ⚡ Quickstart Guide

### Option A: Running with Docker Compose (Recommended)

```powershell
docker compose up -d --build
```
This automatically starts:
1. PostgreSQL with pgvector on port `5432`
2. Ollama LLM server on port `11434`
3. Ollama model auto-puller (`qwen2.5:1.5b` & `qwen3-embedding:0.6b`)
4. FastAPI REST API on port `8000`

Next, launch the React UI:
```powershell
cd frontend
npm run dev
```
Open **`http://localhost:3000`** in your browser!

---

### Option B: Running Locally (Python + Local Ollama)

1. **Activate Virtual Environment & Install Dependencies**:
   ```powershell
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Pull Ollama Models**:
   ```powershell
   ollama pull qwen2.5:1.5b
   ollama pull qwen3-embedding:0.6b
   ```

3. **Start FastAPI Backend**:
   ```powershell
   python main_api.py
   ```

4. **Start React Frontend**:
   ```powershell
   cd frontend
   npm run dev
   ```
   Open **`http://localhost:3000`**!

---

## ❓ Troubleshooting

- **Ollama 500 (`llama-server process has terminated: signal: killed`)**:
  This happens if your system runs out of free RAM loading heavy 4B+ parameter models. The project defaults to **`qwen2.5:1.5b`**, which requires only **1.1 GB RAM**.
- **pgvector `column does not have dimensions`**:
  pgvector v0.8+ requires explicit dimension declarations (`VECTOR(1024)`) in `init.sql`.
