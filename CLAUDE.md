# CLAUDE.md

## Project Overview

Agent 数据空间平台 - A data management and AI collaboration platform with RAG-based chat, knowledge graphs, file management, and digital asset trading.

## Context Constraints

- **回答问题使用中文** - When answering questions or providing explanations, always respond in Chinese.

## L0-L5 记忆架构

- L0: 组织策略 (`.claude/policies/org-policy.md`)
- L1: 项目章程 (`CLAUDE.md`)
- L2: 领域规则 (`backend/app/agents/rules/*.md`)
- L3: 会话工作记忆 (Redis)
- L4: 情节与流程记忆 (PostgreSQL)
- L5: 语义与长期记忆 (PostgreSQL + pgvector + Neo4j)

**约定**: `session_id` 是一等公民，所有聊天请求必须通过 `session_id` 驱动服务端记忆，前端不再通过 `history` 参数传入对话历史。

## Development Commands

```bash
# Backend
conda activate agent
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Celery
celery -A app.celery_worker.celery_app worker --loglevel=info --queues=celery,ingest,high_priority

# Frontend
cd frontend
npm install
npm run dev
```

## Architecture

```
backend/app/
├── main.py                 # FastAPI app factory
├── api/v1/router.py        # API endpoints
├── core/                   # Config, security, middleware
├── db/models.py            # SQLAlchemy models
├── repositories/           # Data access
├── services/               # Business logic
│   └── memory/             # L3-L5 memory services
├── agents/                 # Agent system
│   ├── core/main_agent.py  # Main orchestrator
│   ├── subagents/          # QA, Trade, Review, etc.
│   └── rules/              # L2 domain rules
├── ai/                     # Embedding, ingest pipeline
└── tasks/                  # Celery tasks

frontend/src/
├── api/client.ts          # HTTP + SSE client
├── store/                  # Zustand stores
├── layout/                 # Workbench layout
├── views/                  # Explorer, Assets, Graph
└── worktabs/               # Chat, Markdown, Asset, Graph
```

## Key Technologies

- PostgreSQL + pgvector, MinIO, Redis, Neo4j
- Celery, LangChain/LangGraph, DeepSeek API
- React + Vite + Zustand

## Service Layer Pattern

Services inherit from `SpaceAwareService` (`services/base.py`) for space permission checking and LLM client access.

## Authentication

JWT Bearer tokens. Frontend stores token in localStorage via Zustand persist.
