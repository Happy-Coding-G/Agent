# ---- Builder stage (Python deps) --------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----------------------------------------------------------
FROM python:3.11-slim

# OS-level deps (pg_isready for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

EXPOSE 8000

# Default command — override in docker-compose for celery worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
