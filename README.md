# Agent Data Space Platform

A data management and AI collaboration platform with RAG-based chat, knowledge graphs, file management, and digital asset trading.

## Architecture

| Component | Stack |
|---|---|
| **Backend API** | FastAPI + SQLAlchemy (async) + PostgreSQL (pgvector) |
| **Task Queue** | Celery + Redis |
| **Object Storage** | MinIO (S3-compatible) |
| **Knowledge Graph** | Neo4j |
| **LLM Integration** | DeepSeek / Qwen via LangChain LCEL |
| **Frontend** | React 18 + TypeScript + Vite + Zustand |

## Quick Start (Docker Compose)

```bash
# 1. Clone the repository
git clone https://github.com/Happy-Coding-G/Agent.git
cd Agent

# 2. Create your environment file
cp backend/.env.example backend/app/.env
# Edit backend/app/.env and fill in your API keys and secrets

# 3. Start all services
docker compose up -d

# 4. Access the application
#    Frontend:  http://localhost
#    API:       http://localhost:8000/docs
#    MinIO:     http://localhost:9001
#    Neo4j:     http://localhost:7474
```

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 15+ (with pgvector extension)
- Redis 7+
- Neo4j 5+
- MinIO

### Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example app/.env
# Edit app/.env with your settings

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Celery Worker

```bash
cd backend
celery -A app.celery_worker.celery_app worker \
    --loglevel=info \
    --queues=celery,ingest,high_priority
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # Development server at http://localhost:5173
npm run build      # Production build
```

## API Documentation

When the backend is running, interactive API docs are available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application factory
│   │   ├── api/v1/              # API endpoints
│   │   ├── core/                # Config, security, middleware
│   │   ├── db/                  # SQLAlchemy models, sessions
│   │   ├── services/            # Business logic layer
│   │   ├── agents/              # AI agent system
│   │   ├── ai/                  # Embedding, ingest pipeline
│   │   ├── repositories/        # Data access layer
│   │   ├── schemas/             # Pydantic request/response models
│   │   └── tasks/               # Celery async tasks
│   ├── alembic/                 # Database migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Root component with routing
│   │   ├── api/                 # HTTP client
│   │   ├── store/               # Zustand state stores
│   │   ├── layout/              # VS Code-style workbench
│   │   ├── views/               # Main views
│   │   └── worktabs/            # Tab components
│   ├── package.json
│   └── Dockerfile
├── tests/                       # Test suite
├── docker-compose.yml
└── README.md
```

## Environment Variables

See [`backend/.env.example`](backend/.env.example) for a complete list of configurable environment variables.

> **Security Note**: Never commit `.env` files containing real credentials. The project's `.gitignore` is configured to exclude them.

## Testing

```bash
# Run all tests
cd backend
pytest

# Run with coverage
pytest --cov=app --cov-report=html
```

## License

This project is for educational and research purposes.
