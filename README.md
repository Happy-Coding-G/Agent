# Agent 数据空间平台

<p align="center">
  <strong>Agent-First 数据管理与 AI 协作平台</strong><br>
  自然语言即接口 · RAG 智能问答 · 知识图谱 · 数字资产交易
</p>

<p align="center">
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi" alt="FastAPI"></a>
  <a href="https://react.dev"><img src="https://img.shields.io/badge/React-18-61DAFB?logo=react" alt="React"></a>
  <a href="https://www.postgresql.org"><img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql" alt="PostgreSQL"></a>
  <a href="https://neo4j.com"><img src="https://img.shields.io/badge/Neo4j-5-008CC1?logo=neo4j" alt="Neo4j"></a>
  <a href="https://langchain.com"><img src="https://img.shields.io/badge/LangGraph-0.0.35-1C3C3C?logo=langchain" alt="LangGraph"></a>
  <a href="https://docs.celeryq.dev"><img src="https://img.shields.io/badge/Celery-5.3-37814A?logo=celery" alt="Celery"></a>
</p>

---

## 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [本地开发](#本地开发)
- [环境变量](#环境变量)
- [项目结构](#项目结构)
- [Agent 系统](#agent-系统)
- [API 文档](#api-文档)
- [测试](#测试)
- [部署](#部署)
- [安全建议](#安全建议)

---

## 项目简介

Agent 数据空间平台是一个以 **Agent-First** 为核心理念的数据管理与 AI 协作平台。系统通过最小化的公开 API 表面，将绝大多数业务能力下沉为 Agent 可调用的工具（Tool）、技能（Skill）和子代理（SubAgent），人类主要通过自然语言聊天与系统交互。

平台支持 RAG 智能问答、知识图谱可视化、多版本文件管理、数字资产交易、文档审查、数据血缘追踪等能力，适用于企业知识管理、数据资产运营、智能客服等场景。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **Agent-First 架构** | 统一聊天入口驱动所有业务，自然语言即接口 |
| **三层 RAG 检索** | 向量检索（pgvector）→ 图谱检索（Neo4j）→ 远程重排，生成可溯源回答 |
| **知识图谱** | 文档摄入后自动构建 Neo4j 知识图谱，支持实体/关系可视化 |
| **文件管理** | 多版本文件上传、目录树、MinIO 对象存储、扩展名白名单 |
| **数字资产交易** | 资产上架、购买、定价、结算、钱包管理 |
| **文档审查** | LLM 多维度质量 / 合规 / 完整性审查 |
| **资产整理聚类** | 基于 Embedding 的自动资产分类与聚类 |
| **数据血缘追踪** | 统一血缘与定价服务（AssetLineagePricingService） |
| **三层记忆架构** | L1 工作记忆（Redis）/ L2 中期记忆（PostgreSQL）/ L3 长期记忆（pgvector） |
| **Token 用量统计** | 按功能类型、模型、时间维度统计 LLM 调用成本 |
| **流式响应** | SSE 流式输出 Agent 回复 |
| **Markdown 驱动工作流** | Skills 和 SubAgents 通过 `SKILL.md` 文档定义，无需修改代码即可扩展 |

---

## 技术架构

### 系统架构图

```
+----------------------------+        +----------------------------+
|        Frontend            |        |        Backend             |
|  React 18 + Vite + MUI v5 |<------>|  FastAPI + LangGraph       |
|  Zustand + React Router v7 | HTTP   |  PostgreSQL + pgvector     |
|  Recharts + react-markdown | SSE    |  Neo4j + Redis + MinIO     |
+----------------------------+        |  Celery + DeepSeek API     |
                                      +----------------------------+
                                                  |
                    +-----------------------------+-----------------------------+
                    |                                                           |
            +-------v-------+   +---------v---------+   +----------v----------+
            |  MainAgent    |   |   SubAgents       |   |    Tools / Skills   |
            |  (LangGraph   |   |  qa_research      |   |  file_search        |
            |   ReAct)      |   |  trade_workflow   |   |  vector_search      |
            +---------------+   |  review_workflow  |   |  graph_search       |
                                |  dynamic_workflow |   |  rerank             |
                                |  asset_organize   |   |  review_document    |
                                +-------------------+   |  trade_execute      |
                                                        |  memory_manage      |
                                                        |  ...                |
                                                        +---------------------+
```

### 技术栈

**后端**

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI 0.109 |
| ORM | SQLAlchemy 2.0 (Async) |
| 数据库 | PostgreSQL 16 + pgvector |
| 迁移 | Alembic |
| 对象存储 | MinIO |
| 缓存 | Redis + TTLCache |
| 异步任务 | Celery + Redis Broker |
| 知识图谱 | Neo4j 5 |
| LLM | DeepSeek API |
| Embedding | Qwen Embedding (可选本地部署) |
| Agent 编排 | LangGraph + LangChain LCEL |
| 认证 | JWT Bearer Token |

**前端**

| 组件 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建工具 | Vite |
| UI 组件 | Material-UI (MUI) v5 |
| 状态管理 | Zustand |
| 路由 | React Router v7 |
| 图表 | Recharts |
| Markdown | react-markdown + remark-gfm |

---

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 克隆仓库
git clone git@github.com:Happy-Coding-G/Agent.git
cd Agent

# 2. 配置基础设施环境变量
cp .env.compose.example .env.compose
# 编辑 .env.compose，设置强密码

# 3. 配置后端环境变量
cp backend/.env.example backend/app/.env
# 编辑 backend/app/.env，填入 DEEPSEEK_API_KEY 等真实值

# 4. 启动所有服务
docker compose --env-file .env.compose up -d

# 5. 执行数据库迁移
docker compose exec backend alembic upgrade head

# 6. 访问
# 前端: http://localhost
# 后端 API: http://localhost:8000
# API 文档: http://localhost:8000/docs
# MinIO 控制台: http://localhost:9001
```

### 方式二：本地开发

#### 前置依赖

- Python 3.11+
- Node.js 20+
- PostgreSQL 16 + pgvector
- Redis 7
- Neo4j 5
- MinIO

#### 启动基础设施

```bash
# 仅启动基础设施服务（不启动应用）
docker compose --env-file .env.compose up -d postgres redis minio neo4j
```

#### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example app/.env
# 编辑 app/.env

# 数据库迁移
alembic upgrade head

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Celery Worker

```bash
cd backend
source venv/bin/activate

celery -A app.celery_worker.celery_app worker \
  --loglevel=info \
  --queues=celery,ingest,high_priority
```

#### 前端

```bash
cd frontend

npm install
npm run dev

# 访问 http://localhost:5173
```

---

## 环境变量

### 后端环境变量 (`backend/app/.env`)

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql://user:pass@localhost:5432/dbname` |
| `DB_SSLMODE` | SSL 模式（生产环境设为 `require`） | `disable` |
| `MINIO_ENDPOINT` | MinIO 服务地址 | `127.0.0.1:9000` |
| `MINIO_ACCESS_KEY` | MinIO 访问密钥 | `minioadmin` |
| `MINIO_SECRET_KEY` | MinIO  secret 密钥 | `minioadmin` |
| `MINIO_SECURE` | 是否使用 HTTPS | `False` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-...` |
| `DEEPSEEK_BASE_URL` | DeepSeek API 基础 URL | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 默认模型 | `deepseek-chat` |
| `REMOTE_EMBEDDING_ENABLED` | 启用远程 Embedding 服务 | `False` |
| `REMOTE_EMBEDDING_BASE_URL` | 本地 Embedding 服务地址 | `http://localhost:27701` |
| `REMOTE_RERANK_ENABLED` | 启用远程重排服务 | `False` |
| `REMOTE_RERANK_BASE_URL` | 本地重排服务地址 | `http://localhost:29639` |
| `NEO4J_URI` | Neo4j Bolt 地址 | `bolt://127.0.0.1:7687` |
| `NEO4J_USER` | Neo4j 用户名 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 密码 | `...` |
| `REDIS_URL` | Redis 连接 URL | `redis://localhost:6379/0` |
| `SECRET_KEY` | JWT 签名密钥（请生成强密钥） | `...` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 过期时间（分钟） | `30` |
| `CORS_ALLOWED_ORIGINS` | 允许的 CORS 来源 | `http://localhost:5173` |

> **安全提示**：`SECRET_KEY` 请使用 `python -c "import secrets; print(secrets.token_urlsafe(64))"` 生成，切勿使用默认值部署到生产环境。

---

## 项目结构

```
Agent/
├── docker-compose.yml           # Docker Compose 编排（基础设施 + 应用）
├── .env.compose.example         # Compose 环境变量模板
├── backend/
│   ├── Dockerfile               # 后端容器镜像
│   ├── requirements.txt         # Python 依赖
│   ├── alembic/                 # 数据库迁移脚本
│   ├── app/
│   │   ├── main.py              # FastAPI 应用工厂
│   │   ├── celery_worker.py     # Celery 应用定义
│   │   ├── api/v1/              # API 路由与端点
│   │   ├── core/                # 配置、安全、中间件、异常处理
│   │   ├── db/                  # SQLAlchemy 模型与会话
│   │   ├── repositories/        # 数据访问层
│   │   ├── services/            # 业务逻辑层
│   │   │   ├── base.py          # SpaceAwareService 基类
│   │   │   ├── memory/          # L1-L3 记忆服务
│   │   │   ├── trade/           # 交易、定价服务
│   │   │   └── skills/          # Skill 后端实现
│   │   ├── ai/                  # Embedding、摄入 Pipeline、文本分块
│   │   ├── agents/              # Agent 系统核心
│   │   │   ├── core/            # MainAgent、状态、Prompts
│   │   │   ├── tools/           # 12+ 原子工具
│   │   │   ├── skills/          # SKILL.md 技能定义与加载器
│   │   │   └── subagents/       # SubAgent 文档（Markdown 驱动）
│   │   ├── schemas/             # Pydantic DTO
│   │   └── tasks/               # Celery 异步任务
│   ├── tests/                   # 测试套件
│   └── docs/                    # 架构文档、数据库模型文档
└── frontend/
    ├── Dockerfile               # 前端容器镜像（Nginx 静态资源）
    ├── package.json
    └── src/
        ├── api/client.ts        # HTTP + SSE 客户端
        ├── store/               # Zustand 状态管理
        ├── layout/              # Workbench 布局
        ├── views/               # 页面视图
        └── worktabs/            # 工作区标签页
```

---

## Agent 系统

### MainAgent（主控智能体）

MainAgent 是系统的编排中心，基于 LangGraph ReAct 状态机实现四层能力路由：

```
用户请求 → 意图识别 → 能力路由
                              |
              +---------------+---------------+---------------+
              |               |               |               |
           direct          tool           skill         subagent
         (直接回答)      (原子操作)      (分析能力)      (复杂工作流)
```

- **direct**：纯闲聊、问候、轻量建议
- **tool**：一步完成的原子操作（如 `file_search`、`vector_search`）
- **skill**：可复用的分析能力（如 `market_overview`、`audit_report`）
- **subagent**：跨多个阶段、需要自主决策的复杂任务

### SubAgents（子智能体）

| SubAgent | 功能 | 模型 | 最大轮数 |
|----------|------|------|----------|
| `qa_research` | RAG 三层检索问答（向量→图谱→重排→生成） | deepseek-chat | 15 |
| `trade_workflow` | 交易目标标准化、机制选择、执行 | deepseek-chat | 12 |
| `review_workflow` | 文档质量/合规/完整性多维度审查 | deepseek-chat | 10 |
| `asset_organize_workflow` | 资产特征提取、聚类、报告生成 | deepseek-chat | 10 |
| `dynamic_workflow` | 复杂任务动态拆分与阶段规划 | deepseek-chat | 10 |

### Tools（原子工具）

| 工具 | 能力 |
|------|------|
| `vector_search` / `graph_search` / `rerank` | 三层检索（可独立调用） |
| `qa_generate_answer` | 基于上下文生成可溯源回答 |
| `file_search` / `file_read` | 文件搜索与内容读取 |
| `file_manage` | 目录树、文件操作 |
| `space_manage` | 空间 CRUD、切换 |
| `asset_manage` | 资产列表、获取、生成 |
| `create_listing` | 创建交易挂单 |
| `trade_normalize_goal` / `trade_select_mechanism` / `trade_execute` | 交易工具链 |
| `review_document` / `check_document_*` / `judge_review` | 审查工具链 |
| `memory_manage` | 会话/消息/偏好/长期记忆管理 |
| `user_config_manage` | LLM 配置、交易偏好 |
| `graph_manage` | 知识图谱节点/边操作 |
| `token_usage_query` | Token 用量统计 |

---

## API 文档

启动后端后，自动生成的 API 文档可通过以下地址访问：

- **Swagger UI**：`http://localhost:8000/docs`
- **ReDoc**：`http://localhost:8000/redoc`

### 主要 API 模块

| 模块 | 端点前缀 | 说明 |
|------|----------|------|
| 认证 | `/api/v1/auth` | 注册、登录、JWT 刷新 |
| 用户 | `/api/v1/users` | 用户信息、偏好配置 |
| 空间 | `/api/v1/spaces` | 空间 CRUD、成员管理 |
| 文件 | `/api/v1/files` | 文件上传、下载、目录树 |
| 文档 | `/api/v1/documents` | 文档摄入、检索、问答 |
| 资产 | `/api/v1/assets` | 数据资产、聚类 |
| 交易 | `/api/v1/trade` | 挂单、订单、钱包 |
| 知识图谱 | `/api/v1/graph` | 图谱查询、可视化 |
| 血缘 | `/api/v1/lineage` | 数据血缘追踪 |
| 聊天 | `/api/v1/chat` | SSE 流式聊天 |
| Agent | `/api/v1/agent` | Agent 任务管理 |
| 记忆 | `/api/v1/memory` | 会话与长期记忆 |

---

## 测试

### 运行测试

```bash
cd backend

# 安装测试依赖（已包含在 requirements.txt）
# 确保 pytest 已安装: pip install pytest pytest-asyncio

# 运行全部测试
pytest

# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/

# 运行 Agent 相关测试
pytest tests/unit/agents/

# 运行 QA 三层工具测试
pytest tests/unit/agents/qa/

# 详细输出
pytest -v --tb=short
```

### 测试结构

```
backend/tests/
├── unit/
│   ├── agents/           # Agent 系统测试
│   │   ├── qa/           # QA 三层工具测试
│   │   ├── test_main_agent_agent_mode.py
│   │   ├── test_tool_registry_atomic.py
│   │   └── ...
│   ├── api/              # API 端点测试
│   ├── services/         # 服务层测试
│   └── repositories/     # 仓储层测试
└── integration/          # 集成测试
```

---

## 部署

### Docker Compose 生产部署

```bash
# 1. 配置环境变量（必须修改所有默认值）
cp .env.compose.example .env.compose
cp backend/.env.example backend/app/.env
# 编辑两个文件，设置强密码和真实 API 密钥

# 2. 启动
docker compose --env-file .env.compose up -d

# 3. 执行迁移
docker compose exec backend alembic upgrade head

# 4. 查看日志
docker compose logs -f backend
docker compose logs -f celery-worker
```

### 关键生产配置

| 配置项 | 开发值 | 生产建议 |
|--------|--------|----------|
| `POSTGRES_PASSWORD` | `postgres` | 强随机密码 |
| `MINIO_ROOT_PASSWORD` | `minioadmin` | 强随机密码 |
| `NEO4J_AUTH` | `neo4j/neo4jpassword` | 强随机密码 |
| `SECRET_KEY` | `CHANGE-ME-...` | `secrets.token_urlsafe(64)` |
| `DB_SSLMODE` | `disable` | `require` |
| `CORS_ALLOWED_ORIGINS` | `localhost` | 实际域名 |

---

## 安全建议

1. **密钥管理**：使用密钥管理服务（AWS Secrets Manager、HashiCorp Vault 等），切勿将真实 `.env` 提交到版本控制。
2. **数据库连接**：生产环境必须启用 PostgreSQL SSL（`DB_SSLMODE=require`）。
3. **JWT 安全**：`SECRET_KEY` 长度至少 64 字节，定期轮换。
4. **文件上传**：已内置扩展名白名单和路径遍历防护，请勿关闭。
5. **CORS**：仅允许实际部署的域名，禁止通配符 `*`。
6. **MinIO**：生产环境启用 HTTPS，配置强访问密钥。
7. **API 限流**：已内置基于 Redis 的速率限制，根据负载调整阈值。

---

## 相关文档

- [架构文档](backend/docs/ARCHITECTURE.md) — 系统架构与模块关系
- [数据库模型](backend/docs/DATABASE_MODELS.md) — 实体关系与字段定义
- [技能与工具](backend/docs/SKILLS_AND_TOOLS.md) — Agent 能力清单
- [工作流文档](backend/docs/WORKFLOWS.md) — 业务流程说明

---

## 技术细节补充

### 三层 RAG 检索策略

`qa_research` SubAgent 采用 ReAct 循环自主决策三层检索：

```text
vector_search(query, space_id, top_k)
  └─ 评估 confidence（high / medium / low）
     ├─ high  → 直接 rerank
     ├─ medium → 补充 graph_search
     └─ low   → 必须 graph_search

rerank(query, candidate_refs)  ← 去重、hydrate、远程重排
  └─ 返回最终候选

qa_generate_answer(query, contexts)  ← 生成可溯源回答
```

### 三层 Skill 加载架构

| 层级 | 加载时机 | 内容 |
|------|----------|------|
| L1 | 始终 | Frontmatter（名称、描述、工具列表） |
| L2 | Skill 触发时 | Body（角色定义、执行流程、约束） |
| L3 | 按需 | Linked files（示例、参考文档） |

### L0-L5 记忆架构

| 层级 | 存储 | 用途 |
|------|------|------|
| L0 | `backend/app/agents/rules/*.md` | 组织策略（静态规则） |
| L1 | `CLAUDE.md` | 项目章程 |
| L2 | `backend/app/agents/rules/*.md` | 领域规则 |
| L3 | Redis | 会话工作记忆 |
| L4 | PostgreSQL | 情节与流程记忆 |
| L5 | PostgreSQL + pgvector + Neo4j | 语义与长期记忆 |

---

<p align="center">
  Built with ❤️ using FastAPI, React, LangGraph, and DeepSeek.
</p>
