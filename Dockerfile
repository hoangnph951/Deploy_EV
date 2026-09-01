# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .

# Install dependencies into a temporary shared prefix
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- Stage 2: Production ----
FROM python:3.11-slim

WORKDIR /app

# Copy Python packages and executables to /usr/local
COPY --from=builder /install /usr/local

# Security: run as non-root user
RUN useradd -m appuser

# Copy application code
COPY . .

# Create writable data directory
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://localhost:{os.getenv('PORT', '8000')}/health\")" || exit 1

# Cloud Run injects PORT. The local default stays at 8000 for docker compose.
CMD ["sh", "-c", "exec uvicorn src.apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
