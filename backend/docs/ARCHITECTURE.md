# Agent 数据空间平台 - 后端架构文档

## 1. 项目概述

Agent 数据空间平台是一个以 **Agent-First** 为核心理念的数据管理与 AI 协作平台。系统通过最小化的公开 API 表面，将绝大多数业务能力下沉为 Agent 可调用的工具（Tool）、技能（Skill）和子代理（SubAgent），人类主要通过自然语言聊天与系统交互。

## 2. 技术栈

| 层级 | 技术选型 |
|------|---------|
| Web 框架 | FastAPI |
| 数据库 | PostgreSQL + pgvector |
| ORM | SQLAlchemy 2.0 (Async) |
| 对象存储 | MinIO (S3-compatible) |
| 缓存 | Redis + TTLCache |
| 异步任务 | Celery + Redis Broker |
| 知识图谱 | Neo4j |
| LLM | DeepSeek API + Qwen Embedding |
| Agent 编排 | LangGraph + LangChain LCEL |
| 向量维度 | 1536 |

## 3. 代码目录结构

```
backend/app/
├── main.py                    # FastAPI 应用工厂 create_app()
├── api/
│   └── v1/
│       ├── router.py          # API 路由统一收口
│       ├── deps/
│       │   └── auth.py        # JWT 鉴权依赖
│       └── endpoints/         # 各模块端点实现
├── core/
│   ├── config.py              # 环境变量与配置
│   ├── security.py            # JWT、密码哈希
│   ├── caching.py             # 缓存封装
│   ├── errors.py              # 统一异常类 ServiceError
│   ├── exception_handlers.py  # 全局异常处理
│   └── rate_limit.py          # 限流中间件
├── db/
│   ├── models.py              # SQLAlchemy 全量模型定义
│   ├── session.py             # AsyncSession 工厂
│   └── base.py                # 基础 CRUD 类
├── repositories/              # 数据访问层（按实体分目录）
│   ├── space_repo.py
│   ├── file_repo.py
│   ├── folder_repo.py
│   └── ...
├── services/                  # 业务逻辑层
│   ├── base.py                # SpaceAwareService 基类
│   ├── auth_service.py
│   ├── file/
│   │   └── file_service.py
│   ├── graph/
│   │   └── graph_service.py
│   ├── skills/                # Skill 后端实现
│   ├── trade/                 # 交易、协商、定价、托管
│   ├── memory/                # 统一记忆服务
│   └── ...
├── ai/
│   ├── ingest_pipeline.py     # LCEL 文档摄入 Pipeline
│   ├── embedding_client.py    # Embedding 客户端
│   ├── chunking.py            # 文本分块
│   ├── markdown_utils.py      # Markdown 规范化
│   └── converters.py          # PDF/DOCX/... 转 Markdown
├── agents/
│   ├── core/
│   │   ├── main_agent.py      # MainAgent 编排器
│   │   ├── state.py           # LangGraph 状态定义
│   │   └── prompts.py         # Prompt 模板
│   ├── tools/                 # StructuredTool 集合
│   │   ├── registry.py        # AgentToolRegistry
│   │   ├── file_tools.py
│   │   ├── space_tools.py
│   │   ├── graph_tools.py
│   │   └── ... (12 个模块)
│   ├── skills/                # SKILL.md 工作流文档
│   │   ├── docs/              # markdown 工作流定义
│   │   ├── parser.py          # SkillMDParser
│   │   ├── executor.py        # 通用执行桥接
│   │   └── registry.py        # SkillRegistry
│   └── subagents/             # SubAgent 实现
│       ├── registry.py        # SubAgentRegistry (现也读 SKILL.md)
│       ├── qa_agent.py
│       ├── review_agent.py
│       ├── trade/
│       │   └── agent.py
│       └── ...
├── schemas/
│   └── schemas.py             # Pydantic DTO
├── tasks/
│   └── celery_tasks.py        # Celery 异步任务
├── utils/
│   └── MinIO.py               # MinIO 客户端封装
└── celery_worker.py           # Celery App 定义
```

## 4. 分层架构

### 4.1 API 层（FastAPI Endpoints）

当前公开 API 遵循 **Agent-First + 必要结构化 API** 的混合策略：

**保留直接暴露的 API**：
- `/auth/*` — 注册、登录、JWT
- `/healthz` — 健康检查
- `/agent/*` — 统一聊天入口（`/chat`, `/chat/stream`, `/tasks/{id}`）
- `/spaces/*` — 空间 CRUD、切换
- `/spaces/{id}/tree` — 文件目录树
- `/spaces/{id}/files/upload-init` / `upload-complete` — 文件上传
- `/spaces/{id}/markdown-docs` — Markdown 列表/读取（只读）
- `/spaces/{id}/graph` — 知识图谱读取
- `/spaces/{id}/assets` — 资产列表/读取/生成

**已收口至 Agent Chat 的能力**：
- 交易买卖、协商
- 文档审查
- 资产整理聚类
- 图谱写操作
- 复杂问答（RAG 通过 chat/stream 透传）

### 4.2 Service 层

所有 Service 继承自 `SpaceAwareService`（`services/base.py`），提供：
- 空间权限校验 `_require_space(space_public_id, user)`
- 当前空间上下文缓存
- LLM 客户端统一获取 `get_llm_client()`

### 4.3 Repository 层

按实体组织，封装原始数据库操作。例如：
- `SpaceRepository` — 空间查询
- `FileRepository` / `FileVersionRepository` — 文件与版本
- `FolderRepository` — 文件夹树操作

### 4.4 AI / Pipeline 层

#### LCEL Ingest Pipeline (`ai/ingest_pipeline.py`)

文档处理的核心链路，基于 LangChain Expression Language：

```
IngestContext
    -> load_file_runnable        (从 MinIO/URL/本地读取)
    -> extract_text_runnable     (PDF/DOCX/TXT -> 文本)
    -> convert_to_markdown_runnable
    -> chunk_document_runnable   (MarkdownHeader + RecursiveCharacter)
    -> embed_chunks_runnable     (Qwen Embedding)
    -> store_embeddings_runnable (写入 doc_chunk_embeddings)
    -> build_graph_runnable      (可选：构建 Neo4j 知识图谱)
```

Pipeline 状态通过 `IngestContext` dataclass 在各 runnable 间传递。

#### Chunking 策略 (`ai/chunking.py`)

- Markdown 文档：先用 `MarkdownHeaderTextSplitter` 按标题拆分，再对过长的块使用 `RecursiveCharacterTextSplitter` 二次拆分
- 普通文本：直接使用 `RecursiveCharacterTextSplitter`
- 块大小：默认 1000 字符，重叠 200 字符

## 5. Agent 架构

### 5.1 MainAgent — 四层能力路由

`agents/core/main_agent.py` 中的 `MainAgent` 是整个系统的编排中心。它通过 LangGraph 构建了一个 ReAct 风格的状态机：

```
entry -> plan -> [conditional]
              |
              +-- direct -> respond -> END
              +-- tool -> execute_tool -> [continue/done/error]
              +-- skill -> execute_skill -> respond -> END
              +-- subagent -> execute_subagent -> respond -> END
              +-- error -> handle_error -> END
```

**决策流程**：
1. `_plan_step` 收集当前可用的 tool/skill/subagent schema
2. 构造 `CAPABILITY_ROUTING_SYSTEM_PROMPT`，让 LLM 输出 JSON 格式的 `decision`
3. `_plan_router` 根据 `decision.mode` 分发到对应执行节点
4. 若 LLM 不可用，回退到 `_fallback_plan`（基于关键词的硬编码意图匹配）

### 5.2 Tools — 显式操作接口

通过 `AgentToolRegistry` 统一管理，现有 12 个工具包：

| 工具包 | 核心能力 |
|--------|---------|
| `file_tools` | 文件搜索、文件管理（目录树、创建文件夹） |
| `space_tools` | 空间列表、创建、删除、切换 |
| `markdown_tools` | Markdown 文档列表、读取 |
| `graph_tools` | 知识图谱获取、节点/边更新 |
| `asset_tools` | 资产列表、获取、生成、整理聚类 |
| `qa_tools` | RAG 问答（QAAgent 代理） |
| `ingest_tools` | 文档摄入（通过上传 API 触发） |
| `review_tools` | 文档审查 |
| `trade_tools` | 交易目标执行（sell/buy/yield） |
| `memory_tools` | 会话、消息、偏好、长期记忆管理 |
| `user_config_tools` | 用户 LLM 配置、Agent 配置 |
| `token_usage_tools` | Token 用量查询 |

所有 Tool 内部直接调用 `services/` 层，**不走 HTTP**。

### 5.3 Skills — Markdown 驱动的工作流

Phase 7 重构后，Skills 的定义从 Python 代码迁移到了 `agents/skills/docs/*.md`（SKILL.md 格式）。每个文档包含：
- YAML frontmatter（`skill_id`, `name`, `capability_type`, `executor`, `input_schema`）
- Markdown 章节（`## 适用场景`, `## 工作流步骤`）

`SkillMDParser` 负责读取解析，`SkillRegistry` 将 schema 注入 LLM prompt，执行时通过 `executor.py` 中的 `get_executor_method` 将 `executor` 路径（如 `app.services.skills.pricing_skill:PricingSkill.calculate_quick_price`）解析为实际可调用的 Python 方法。

现有 7 个 Skills：
- `pricing_quick_quote` — 快速定价
- `lineage_summary` — 血缘摘要
- `lineage_impact` — 血缘影响分析
- `market_overview` — 市场概览
- `market_trend` — 市场趋势
- `privacy_protocol` — 隐私协议协商
- `audit_report` — 审计报告

### 5.4 SubAgents — 复杂工作流

同样通过 SKILL.md 文档定义，现有 5 个 SubAgents：
- `qa_research` — RAG 问答（保留流式透传特殊通道）
- `review_workflow` — 文档审查
- `asset_organize_workflow` — 资产整理
- `trade_workflow` — 交易协商
- `dynamic_workflow` — 动态生成复杂任务模板

## 6. 关键数据流

### 6.1 文件上传与文档摄入

```
Frontend UploadToolbar
    -> POST /spaces/{id}/files/upload-init
    -> PUT MinIO (presigned URL)
    -> POST /spaces/{id}/files/upload-complete
    -> FileService.complete_upload
    -> IngestService.create_ingest_job_from_version
    -> Celery Task (ingest_pipeline)
    -> LangChainIngestPipeline.run(ingest_id)
    -> 生成 DocChunks + Embeddings + Neo4j Graph
```

**注意**：`create_ingest_job_from_version` 内部已将 job 提交到 Celery，外层 `complete_upload` 不应重复提交。

### 6.2 Agent Chat 流式响应

```
Frontend ChatTab
    -> POST /agent/chat/stream
    -> AgentEndpoint.agent_chat_stream
    -> MainAgent.stream_chat
    -> [QA 意图?] 直接透传 QAAgent.stream
    -> [其他意图] LangGraph ReAct 循环
        -> plan -> execute_tool/skill/subagent -> respond
    -> SSE 事件流回前端 (status/token/result/[DONE])
```

### 6.3 交易协商流程

```
User Chat: "我要卖这份数据，底价 1000"
    -> MainAgent -> trade_goal Tool
    -> TradeAgent.run_goal
    -> TradeGoal (intent=sell_asset, min_price=1000)
    -> mechanism_selection_policy
    -> 选择 mechanism (fixed_price / auction / bilateral / direct)
    -> 创建/推进 NegotiationSession
    -> SellerAgent / BuyerAgent 通过 AgentMessageQueue 异步协商
    -> 达成后更新 TradeListing / TradeOrder / EscrowRecord
```

## 7. 安全配置

- **认证**：JWT Bearer Token，前端通过 localStorage 持久化
- **空间隔离**：所有 Service 通过 `SpaceAwareService` 强制校验用户-空间权限
- **Agent 权限边界**：`CAPABILITY_ROUTING_SYSTEM_PROMPT` 明确告知 LLM 不得越权访问其他用户/空间数据
- **乐观锁**：交易钱包（`TradeWallets.version`）、协商会话（`NegotiationSessions.version`）使用乐观锁防止并发竞争
- **资金托管**：`EscrowRecord` 在协商期间锁定买方资金，超时自动退还

## 8. 扩展指南

### 8.1 新增一个 Tool

1. 在 `agents/tools/` 下新建 `{domain}_tools.py`
2. 定义 Pydantic Input 模型
3. 实现 `build_tools(registry)`，返回 `List[StructuredTool]`
4. 在 `agents/tools/registry.py` 的 `_lazy_init` 中导入并注册

### 8.2 新增一个 Skill

1. 在 `agents/skills/docs/` 下新建 `{skill_name}.md`
2. 编写 YAML frontmatter（含 `executor` 路径）
3. 编写 `## 适用场景` 和 `## 工作流步骤` 章节
4. 确保 `executor` 指向的 Python 方法签名与 `input_schema` 匹配
5. 无需修改任何 `.py` registry 文件，重启即可生效

### 8.3 新增一个 SubAgent

与 Skill 类似，只是 `capability_type: subagent`，并在 `agents/subagents/` 下实现具体的 Agent 类。
