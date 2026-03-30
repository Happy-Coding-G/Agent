# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Agent 数据空间平台 - A data management and AI collaboration platform with RAG-based chat, knowledge graphs, file management, and digital asset trading.

## Context Constraints

- **回答问题使用中文** - When answering questions or providing explanations, always respond in Chinese.

## Development Commands

### Virtual Environment

**重要**: 所有后端 Python 操作必须使用 `agent` conda 环境。

```bash
# 激活 agent 环境 (Windows)
conda activate agent

# 验证环境
python --version  # 应该是 3.11.x
pip show fastapi  # 确认包已安装
```

### Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Celery Worker (async tasks)

```bash
cd backend
celery -A app.celery_worker.celery_app worker --loglevel=info --queues=celery,ingest,high_priority
```

### Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev        # development
npm run build      # production build
```

### Environment

Backend reads from `.env` file in `backend/` directory. See `app/core/config.py` for all configurable environment variables (database, MinIO, Redis, Neo4j, LLM API keys).

## Architecture

### Backend Structure

```
backend/app/
├── main.py                 # FastAPI app factory (create_app)
├── api/v1/router.py        # All API endpoints registered here
├── core/                   # Config, security, caching, middleware
├── db/models.py            # SQLAlchemy models (PostgreSQL + pgvector)
├── repositories/           # Data access layer
├── services/               # Business logic (auth_service, chat_service, etc.)
├── ai/                     # AI modules: embedding_client, ingest_pipeline (LCEL)
└── tasks/                  # Celery async tasks
```

### API Routes (`/api/v1/`)

- `health` - Health checks
- `auth` - Registration, login, JWT tokens
- `spaces` - Space management
- `files` - File upload/download (MinIO presigned URLs)
- `markdown` - Markdown document CRUD
- `graph` - Knowledge graph (Neo4j)
- `chat` - RAG chat with SSE streaming
- `assets` - Digital asset management
- `trade` - Marketplace and wallet
- `tasks` - Celery task status

### Frontend Structure

```
frontend/src/
├── App.tsx                 # Root component with routing
├── api/client.ts          # HTTP client with SSE streaming support
├── store/                  # Zustand stores (auth, workbench)
├── layout/                 # VS Code-style workbench layout
├── views/                  # Main views (Explorer, Assets, Graph)
└── worktabs/               # Tab components (Chat, Markdown, Asset, Graph)
```

### Key Technologies

- **Database**: PostgreSQL with pgvector extension (vector embeddings)
- **Object Storage**: MinIO (S3-compatible)
- **Cache**: Redis with TTLCache
- **Async Tasks**: Celery with Redis broker
- **Knowledge Graph**: Neo4j
- **LLM Integration**: DeepSeek API + Qwen Embedding via LangChain LCEL
- **Frontend State**: Zustand with localStorage persistence

### Service Layer Pattern

Services inherit from `SpaceAwareService` (in `services/base.py`) which provides:
- Space permission checking
- Space-level caching
- Common LLM client access via `get_llm_client()`

### Document Ingest Pipeline (LCEL)

`app/ai/ingest_pipeline.py` implements the document processing flow:
1. File download (MinIO/URL)
2. Text extraction (PDF/DOCX/TXT/Markdown)
3. Markdown conversion
4. Chunking (MarkdownHeader + RecursiveCharacter)
5. Embedding generation + vector storage
6. Knowledge graph construction (Neo4j)

### Authentication

JWT-based with Bearer tokens. All API requests (except `/healthz`) require:
```
Authorization: Bearer <token>
```

Frontend stores token in localStorage via Zustand persist middleware.
