# ── Multi-stage Dockerfile for FastAPI RAG Web Service ─────────────────────────
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies needed for compiling python packages if any
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Final runtime image ────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application files
COPY app/ ./app/
COPY database/ ./database/
COPY documents/ ./documents/
COPY main_api.py .
COPY .env.example .env

# Expose FastAPI port
EXPOSE 8000

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
ENV API_PORT=8000

# Run FastAPI web server
CMD ["python", "main_api.py"]
