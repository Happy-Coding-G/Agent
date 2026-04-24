# Agent 数据空间平台 - Skills 与 Tools 文档

本文档介绍后端的 Agent 能力层：包括 **Tools（结构化工具）**、**Skills（轻量工作流）** 和 **SubAgents（复杂工作流）**。这些能力通过 `AgentToolRegistry`、`SkillRegistry` 和 `SubAgentRegistry` 统一管理，供 `MainAgent` 在 ReAct 循环中调用。

---

## 1. 能力分层概述

| 层级 | 定位 | 典型执行时间 | 示例 |
|------|------|-------------|------|
| **Tools** | 显式原子操作，直接调用 Service 或原子查询组件 | 毫秒 ~ 秒级 | 文件搜索、空间切换 |
| **Skills** | 轻量工作流，由 SKILL.md 定义 | 秒级 | 快速定价、市场概览 |
| **SubAgents** | 复杂多步工作流，可能异步执行 | 秒 ~ 分钟级 | RAG问答、交易 |

Tools 只承载原子能力；QA、文档审查、交易、资产整理等复杂流程统一建模为 Agent，**不走 HTTP**。

---

## 2. Tools（结构化工具）

Tools 通过 `AgentToolRegistry` 统一注册。注册时接收 `(db, user, space_id)`，使用 `StructuredTool.from_function()` 包装为 LangChain 工具。

### 2.1 工具总览

| 工具名 | 来源模块 | 核心能力 |
|--------|---------|---------|
| `file_search` | `file_tools.py` | 自然语言搜索文件内容 |
| `file_manage` | `file_tools.py` | 列出目录树、创建/重命名文件夹 |
| `space_manage` | `space_tools.py` | 列出、创建、删除、切换空间 |
| `markdown_manage` | `markdown_tools.py` | 列出/读取 Markdown 文档 |
| `graph_manage` | `graph_tools.py` | 获取/更新知识图谱节点和边 |
| `asset_manage` | `asset_tools.py` | 列出、获取、生成数字资产 |
| `create_listing` | `trade_tools.py` | 创建交易挂单 |
| `memory_manage` | `memory_tools.py` | 会话、偏好、长期记忆管理 |
| `user_config_manage` | `user_config_tools.py` | LLM配置、交易偏好配置 |
| `token_usage_query` | `token_usage_tools.py` | Token用量查询统计 |
| `process_document` | `ingest_pipeline.py` | 文档处理（通过上传 API 触发 LCEL 摄入链路） |

### 2.2 各工具详解

#### `file_search` / `file_manage`

- **file_search**：包装 `FileQueryAgent`，基于自然语言查询在指定空间路径下搜索文件。
  - 输入：`query: str`
  - 输出：匹配文件列表

- **file_manage**：包装 `SpaceFileService`。
  - `action=list_tree`：返回空间文件目录树
  - `action=create_folder`：在指定父文件夹下创建新文件夹
  - `action=rename_folder`：重命名现有文件夹

#### `space_manage`

- 包装 `SpaceService`
- `action=list`：列出用户有权限的所有空间
- `action=create`：创建新空间
- `action=delete`：删除指定空间
- `action=switch`：切换当前活跃空间

#### `markdown_manage`

- 包装 `MarkdownDocumentService`
- **当前仅支持只读操作**（编辑功能已移除）
- `action=list`：列出空间内所有 Markdown 文档
- `action=get`：读取指定文档内容

#### `graph_manage`

- 包装 `KnowledgeGraphService`
- `action=get`：获取完整知识图谱（节点+边）
- `action=update_node`：更新节点标签、描述、标签列表
- `action=create_edge`：创建两个文档节点之间的关系
- `action=update_edge`：更新关系类型和描述
- `action=delete_edge`：删除指定关系边

#### `asset_manage`

- **asset_manage**：包装 `AssetService`
  - `action=list`：列出空间资产
  - `action=get`：获取单个资产详情
  - `action=generate`：根据 prompt 生成新资产

#### `create_listing`

- 包装 `TradeService`
- 输入：`asset_id`, `price`, `rights_type`, `license_term`, `description`, `tags`, `is_public`
- 输出：创建后的挂单信息

#### `memory_manage`

- 包装 `UnifiedMemoryService` / `EpisodicMemory` / `LongTermMemory`
- 支持的 `action`：
  - 会话管理：`create_session`, `list_sessions`, `get_session`, `archive_session`, `delete_session`
  - 消息管理：`get_messages`, `add_message`
  - 记忆搜索：`search`（语义搜索消息+长期记忆）
  - 偏好管理：`get_preferences`, `set_preference`
  - 长期记忆：`get_memories`, `add_memory`
  - 统计：`get_stats`
  - 上下文召回：`get_context`

#### `user_config_manage`

- 包装 `UserAgentService`
- `action=get_config`：读取用户 LLM + 交易配置
- `action=update_llm`：更新模型、温度、最大Token等
- `action=update_trade`：更新利润率、预算比例
- `action=reset_config`：重置为系统默认
- `action=test_llm`：测试 LLM 连通性

#### `token_usage_query`

- 包装 `TokenUsageService`
- `action=summary`：按功能类型汇总用量
- `action=daily`：每日用量趋势
- `action=recent`：最近明细记录

---

## 3. Skills（SKILL.md 轻量工作流）

Skills 从 `backend/app/agents/skills/docs/*.md` 读取，由 `SkillMDParser` 解析 YAML frontmatter 和 Markdown 章节。

### 3.1 SKILL.md 格式

每个 `.md` 文件包含：

```markdown
---
skill_id: get_asset_price
name: 快速定价建议
capability_type: skill
description: 对单个数据资产给出快速定价建议
executor: app.services.asset_lineage_pricing_service:AssetLineagePricingService.calculate_price
input_schema:
  type: object
  properties:
    asset_id:
      type: string
  required:
    - asset_id
output_summary: 返回 fair_value、recommended price 和价格区间
---

## 适用场景
- 快速询价
- 交易前预估

## 工作流步骤
1. 解析权益范围
2. 调用定价引擎
3. 输出价格区间和置信信息
```

### 3.2 现有 Skills（7个）

| Skill ID | 名称 | Executor | 功能说明 |
|----------|------|----------|---------|
| `get_asset_price` | 快速定价建议 | `AssetLineagePricingService.calculate_quick_price` | 根据资产ID、权益类型、授权天数计算推荐价格区间 |
| `get_asset_lineage` | 血缘摘要 | `AssetLineagePricingService.get_summary` | 查询数据资产的上游血缘链路 |
| `verify_asset_lineage` | 血缘影响分析 | `AssetLineagePricingService.get_impact` | 分析数据资产变更对下游的影响范围 |
| `market_overview` | 市场概览 | `MarketSkill.get_overview` | 返回当前市场的总体统计信息 |
| `market_trend` | 市场趋势 | `MarketSkill.get_trend` | 按数据类型和天数统计市场趋势 |
| `privacy_protocol` | 隐私协议 | `PrivacySkill.generate_protocol` | 根据资产敏感度和要求生成隐私计算协议 |
| `audit_report` | 审计报告 | `AuditSkill.generate_report` | 为指定交易生成审计报告 |

### 3.3 执行机制

```python
# SkillRegistry.execute("get_asset_price", {"asset_id": "xxx"})
# 内部流程：
doc = parser.get_document("get_asset_price")
method = get_executor_method(doc.executor, db)  # 动态解析并实例化
result = await method(**arguments)
return {"skill": "get_asset_price", "result": result}
```

---

## 4. SubAgents（SKILL.md 复杂工作流）

SubAgents 与 Skills 使用相同的 `SKILL.md` 格式，只是 `capability_type: subagent`。它们通常代表更复杂、可能异步执行的工作流。

### 4.1 现有 SubAgents（5个）

| SubAgent ID | 名称 | Executor | 功能说明 |
|-------------|------|----------|---------|
| `qa_research` | 知识检索问答 | `QAAgent.run` | 多步骤知识检索与溯源回答（向量+图谱混合） |
| `review_workflow` | 文档审查工作流 | `ReviewAgent.run` | 完整的文档质量/合规性审查流程 |
| `asset_organize_workflow` | 资产整理工作流 | `AssetOrganizeAgent.run` | 资产特征提取、聚类、报告生成 |
| `trade_workflow` | 交易工作流 | `TradeAgent.run` | 复杂交易目标执行、上架、购买、结算 |
| `dynamic_workflow` | 动态工作流 | `DynamicWorkflowAgent.run` | 根据用户目标动态生成并执行多步任务模板 |

### 4.2 参数映射

`SubAgentRegistry.execute()` 对部分 subagent 做了参数映射：

- **qa_research**：
  - 自动注入 `user` 参数
  - 将 `space_id` 重命名为 `space_public_id`

- **trade_workflow**：
  - 自动注入 `user` 参数
  - 将 `space_id` 重命名为 `space_public_id`
  - 将 `payload` 扁平化展开为顶层参数

### 4.3 流式透传特殊处理

`qa_research` 在 `MainAgent.stream_chat` 中有特殊路径：

- 若判定为 QA 意图，可直接透传 `QAAgent.stream()` 的 SSE 流
- 不经过完整的 LangGraph ReAct 循环，减少响应延迟

---

## 5. Prompts（提示模板）

除 Skills 和 SubAgents 外，SKILL.md 还可定义 `capability_type: prompt`，用于无后端执行逻辑的纯提示模板。

### 5.1 现有 Prompt（1个）

| Prompt ID | 名称 | 说明 |
|-----------|------|------|
| `asset_cluster_prompt` | 资产聚类提示 | 用于 `AssetOrganizeAgent` 的 LLM 提示模板，无独立 executor |

---

## 6. Registry 架构

### 6.1 AgentToolRegistry

```python
class AgentToolRegistry:
    def __init__(self, db, user, space_id=None, space_path=None)
    def get_tools() -> List[StructuredTool]
    def get_tool(name) -> Optional[StructuredTool]
    def get_tool_schemas() -> List[Dict]   # 供 LLM tool calling 使用
```

- 延迟初始化（`_lazy_init`），按需导入各工具模块
- 避免循环依赖和无效加载

### 6.2 SkillRegistry

```python
class SkillRegistry:
    def __init__(self, db, parser=None)
    def get_skill_schemas() -> List[Dict]
    async def execute(name, arguments) -> Dict
```

- 依赖 `SkillMDParser` 读取 `skills/docs/*.md`
- 执行时通过 `execute_skill_md` 动态解析 executor

### 6.3 SubAgentRegistry

```python
class SubAgentRegistry:
    def __init__(self, db, user, llm_client=None, space_path=None, parser=None)
    def get_subagent_schemas() -> List[Dict]
    async def execute(name, arguments) -> Dict
```

- 与 `SkillRegistry` 共享 `SkillMDParser`
- 自动注入 `user` 和 `space_public_id` 等上下文参数

---

## 7. MainAgent 中的能力路由

`MainAgent` 在 `_plan_step` 中收集以下 schema 列表，注入 LLM system prompt：

```python
schemas = []
schemas.extend(tool_registry.get_tool_schemas())
schemas.extend(skill_registry.get_skill_schemas())
schemas.extend(subagent_registry.get_subagent_schemas())
```

LLM 输出 JSON `decision`：

```json
{
  "mode": "tool",
  "active_tool": {
    "name": "file_search",
    "arguments": {"query": "项目计划书"}
  }
}
```

或：

```json
{
  "mode": "skill",
  "active_skill": {
    "name": "get_asset_price",
    "arguments": {"asset_id": "abc123"}
  }
}
```

或：

```json
{
  "mode": "direct",
  "response": "您好，请问有什么可以帮您？"
}
```

---

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
5. **无需修改任何 `.py` registry 文件，重启即可生效**

### 8.3 新增一个 SubAgent

1. 在 `agents/skills/docs/` 下新建 `{subagent_name}.md`
2. 设置 `capability_type: subagent`
3. 在 `agents/subagents/` 下实现具体的 Agent 类
4. 在 `SubAgentRegistry.execute` 中按需添加参数映射（如有特殊字段转换需求）
5. 重启生效

---

## 9. 工具/技能/子代理对照表

| 业务能力 | Tool | Skill | SubAgent |
|----------|------|-------|----------|
| 文件搜索 | `file_search` | — | — |
| 文件/文件夹管理 | `file_manage` | — | — |
| 空间管理 | `space_manage` | — | — |
| Markdown 读取 | `markdown_manage` | — | — |
| 知识图谱操作 | `graph_manage` | — | — |
| 资产 CRUD | `asset_manage` | — | — |
| 创建挂单 | `create_listing` | — | — |
| 资产聚类 | — | — | `asset_organize_workflow` |
| RAG 问答 | — | — | `qa_research` |
| 文档审查 | — | — | `review_workflow` |
| 交易目标 | — | — | `trade_workflow` |
| 快速定价 | — | `get_asset_price` | — |
| 血缘分析 | — | `get_asset_lineage` / `verify_asset_lineage` | — |
| 市场分析 | — | `market_overview` / `market_trend` | — |
| 隐私协议 | — | `privacy_protocol` | — |
| 审计报告 | — | `audit_report` | — |
| 动态任务 | — | — | `dynamic_workflow` |
| 记忆管理 | `memory_manage` | — | — |
| 用户配置 | `user_config_manage` | — | — |
| Token 查询 | `token_usage_query` | — | — |
| 文档处理 | `process_document` | — | — |
