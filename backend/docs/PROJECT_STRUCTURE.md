# 项目目录结构说明

## 概述

本项目采用分层架构设计，遵循清晰的分层原则：
- **api**: 接口层，处理HTTP/WebSocket请求
- **services**: 业务逻辑层，实现核心业务功能
- **repositories**: 数据访问层，封装数据库操作
- **agents**: AI Agent层，实现多Agent协作系统
- **core**: 核心基础设施，配置、安全、工具等
- **db**: 数据库层，模型定义和连接管理

## 目录结构

```
backend/
├── alembic/                    # 数据库迁移
│   └── versions/               # 迁移脚本
├── app/                        # 应用主目录
│   ├── agents/                 # AI Agent系统
│   │   ├── core/              # Agent核心组件
│   │   │   ├── main_agent.py       # 主Agent入口
│   │   │   ├── enhanced_main_agent.py  # 增强版主Agent
│   │   │   ├── state.py           # Agent状态定义
│   │   │   ├── prompts.py         # Agent提示词模板
│   │   │   └── workflow_orchestrator.py  # 工作流编排器
│   │   ├── subagents/          # 子Agent集合
│   │   │   ├── data_process_agent.py     # 数据处理Agent
│   │   │   ├── asset_organize_agent.py   # 资产组织Agent
│   │   │   ├── qa_agent.py               # 问答Agent
│   │   │   ├── file_query_agent.py       # 文件查询Agent
│   │   │   ├── review_agent.py           # 审查Agent
│   │   │   ├── exchange_orchestrator.py  # 交易编排器
│   │   │   ├── trade_agent.py            # 交易Agent
│   │   │   └── market_mechanisms/        # 市场机制
│   │   │       ├── bilateral.py          # 双边协商
│   │   │       ├── auction.py            # 拍卖机制
│   │   │       └── contract_net.py       # 合同网
│   │   ├── trade/              # 交易相关
│   │   │   ├── trade_graph.py           # 交易图(LangGraph)
│   │   │   └── trade_agent_worker.py    # 交易Agent工作进程
│   │   └── negotiation/        # 协商相关
│   │       └── ...
│   ├── ai/                     # AI/ML核心功能
│   │   ├── chunking/          # 文本分块策略
│   │   │   └── strategies.py
│   │   ├── converters.py      # 文件转换器
│   │   ├── embedding_client.py # Embedding客户端
│   │   ├── graph_extractor.py  # 知识图谱抽取
│   │   ├── ingest_pipeline.py  # 文档摄入管道
│   │   └── markdown_utils.py   # Markdown工具
│   ├── api/                    # API接口层
│   │   ├── deps/              # 依赖注入
│   │   │   └── auth.py        # 认证依赖
│   │   └── v1/                # API v1版本
│   │       ├── endpoints/     # API端点
│   │       │   ├── agent.py       # Agent接口
│   │       │   ├── assets.py      # 资产接口
│   │       │   ├── auth.py        # 认证接口
│   │       │   ├── chat.py        # 聊天接口
│   │       │   ├── files.py       # 文件接口
│   │       │   ├── graph.py       # 图谱接口
│   │       │   ├── health.py      # 健康检查
│   │       │   ├── lineage.py     # 血缘接口
│   │       │   ├── markdown.py    # Markdown接口
│   │       │   ├── memory.py      # 记忆接口
│   │       │   ├── spaces.py      # Space接口
│   │       │   ├── tasks.py       # 任务接口
│   │       │   ├── trade.py       # 交易接口
│   │       │   └── workflow.py    # 工作流接口
│   │       └── router.py      # 路由注册
│   ├── core/                   # 核心基础设施
│   │   ├── security/          # 安全模块
│   │   │   ├── acl.py             # 访问控制
│   │   │   ├── audit.py           # 审计日志
│   │   │   ├── jwt.py             # JWT认证
│   │   │   └── password.py        # 密码处理
│   │   ├── cache.py           # 缓存管理
│   │   ├── celery_config.py   # Celery配置
│   │   ├── config.py          # 应用配置
│   │   ├── errors.py          # 错误定义
│   │   ├── exception_handlers.py # 异常处理
│   │   ├── rate_limit.py      # 限流熔断
│   │   └── task_manager.py    # 任务管理
│   ├── db/                     # 数据库层
│   │   ├── neo4j/             # Neo4j图数据库
│   │   │   ├── crud.py
│   │   │   ├── driver.py
│   │   │   └── models.py
│   │   ├── models.py          # SQLAlchemy模型
│   │   └── session.py         # 会话管理
│   ├── repositories/           # 数据仓库层
│   │   ├── file_repo.py
│   │   ├── folder_repo.py
│   │   ├── space_repo.py
│   │   ├── upload_repo.py
│   │   ├── user_repo.py
│   │   └── ...
│   ├── schemas/                # Pydantic模式定义
│   │   └── schemas.py
│   ├── services/               # 业务逻辑层
│   │   ├── base.py            # 服务基类
│   │   ├── auth/              # 认证服务
│   │   ├── chat/              # 聊天服务
│   │   ├── file/              # 文件服务
│   │   ├── graph/             # 图谱服务
│   │   ├── space/             # Space服务
│   │   ├── trade/             # 交易服务
│   │   │   ├── trade_service.py
│   │   │   ├── trade_agent_service.py
│   │   │   ├── trade_negotiation_service.py
│   │   │   └── unified_trade_service.py
│   │   ├── memory/            # 记忆服务
│   │   │   ├── unified_memory.py
│   │   │   ├── session_memory.py
│   │   │   ├── episodic_memory.py
│   │   │   ├── longterm_memory.py
│   │   │   └── checkpoint_service.py
│   │   ├── asset_service.py
│   │   ├── markdown_service.py
│   │   ├── ingest_service.py
│   │   ├── lineage_service.py
│   │   └── collaboration_service.py
│   ├── tasks/                  # Celery异步任务
│   │   └── ingest_tasks.py
│   ├── utils/                  # 工具函数
│   │   ├── MinIO.py
│   │   └── state_store.py
│   ├── celery_worker.py       # Celery工作进程入口
│   └── main.py                # FastAPI应用入口
├── docs/                       # 文档目录
│   ├── architecture/          # 架构文档
│   │   ├── MEMORY_ARCHITECTURE.md
│   │   ├── TRADE_ARCHITECTURE.md
│   │   ├── ORCHESTRATION_ARCHITECTURE.md
│   │   ├── BLACKBOARD_NEGOTIATION.md
│   │   ├── CROSS_USER_NEGOTIATION.md
│   │   └── OPTIMIZATION_SUMMARY.md
│   ├── api/                   # API文档
│   ├── guides/                # 使用指南
│   └── deployment/            # 部署文档
├── scripts/                    # 脚本工具
│   └── migrate_trade_data.py
├── tests/                      # 测试目录
│   ├── unit/                  # 单元测试
│   │   ├── services/
│   │   ├── repositories/
│   │   └── agents/
│   ├── integration/           # 集成测试
│   ├── benchmarks/            # 性能测试
│   │   ├── rag/
│   │   ├── chunking/
│   │   └── retrieval/
│   └── fixtures/              # 测试数据
├── requirements.txt           # Python依赖
└── README.md                  # 项目说明
```

## 设计原则

### 1. 分层架构
- **api层**: 只处理请求/响应，不包含业务逻辑
- **services层**: 实现业务逻辑，不直接操作数据库
- **repositories层**: 封装数据访问，返回模型对象
- **agents层**: 自包含的AI Agent系统

### 2. 依赖方向
```
api → services → repositories → db/models
      ↓
      agents → ai
      ↓
      core (config, security, utils)
```

### 3. 模块组织
- **功能内聚**: 相同功能的文件放在同一目录
- **接口隔离**: API端点与业务逻辑分离
- **单一职责**: 每个模块只做一件事

### 4. 命名规范
- 文件: `snake_case.py`
- 类: `PascalCase`
- 函数/变量: `snake_case`
- 常量: `UPPER_SNAKE_CASE`

## 快速导航

### 添加新API端点
1. 在 `app/api/v1/endpoints/` 创建端点文件
2. 在 `app/api/v1/router.py` 注册路由
3. 在 `app/services/` 实现业务逻辑

### 添加新Agent
1. 在 `app/agents/subagents/` 创建Agent
2. 在 `app/agents/core/workflow_orchestrator.py` 注册Agent
3. 更新 `app/agents/core/state.py` 添加状态定义

### 添加新数据库模型
1. 在 `app/db/models.py` 定义模型
2. 创建Alembic迁移: `alembic revision --autogenerate -m "描述"`
3. 在 `app/repositories/` 创建仓库类

## 开发规范

1. **导入顺序**:
   - 标准库
   - 第三方库
   - 本地模块 (from app.xxx)

2. **类型注解**: 所有函数参数和返回值都必须有类型注解

3. **文档字符串**: 所有公共函数和类都必须有docstring

4. **错误处理**: 使用 `app.core.errors` 中定义的异常类

5. **日志记录**: 使用 `logging.getLogger(__name__)` 获取logger
