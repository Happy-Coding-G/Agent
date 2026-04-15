# Agent 数据空间平台 - 功能工作流文档

本文档详细描述平台中各核心功能的具体实现工作流，涵盖数据流、调用链和关键节点。

---

## 1. 文件上传与文档摄入工作流

### 1.1 整体流程

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

### 1.2 详细步骤

1. **上传初始化** (`upload-init`)
   - 前端请求上传接口
   - 后端生成 MinIO presigned URL，创建 `Uploads` 记录（状态 `init`）
   - 返回 presigned URL 和 upload public_id 给前端

2. **直传对象存储**
   - 前端使用 presigned URL 直接 PUT 文件到 MinIO
   - 上传完成后，前端调用 `upload-complete`

3. **完成上传** (`upload-complete`)
   - `SpaceFileService.complete_upload` 被调用
   - 创建 `Files` 记录和 `FileVersions` 记录
   - 更新 `Uploads` 状态为 `completed`
   - 调用 `IngestService.create_ingest_job_from_version`
   - **注意**：`create_ingest_job_from_version` 内部已将 job 提交到 Celery，外层不应重复提交

4. **异步摄入 Pipeline** (Celery Worker)
   - `LangChainIngestPipeline.run(ingest_id)` 执行以下步骤：
     - `load_file_runnable`：从 MinIO/URL/本地读取文件
     - `extract_text_runnable`：PDF/DOCX/TXT -> 文本
     - `convert_to_markdown_runnable`：转换为标准 Markdown
     - `chunk_document_runnable`：使用 `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` 分块
     - `embed_chunks_runnable`：调用 Qwen Embedding 生成 1536 维向量
     - `store_embeddings_runnable`：写入 `doc_chunk_embeddings` 表
     - `build_graph_runnable`（可选）：提取实体关系，写入 Neo4j

5. **状态更新**
   - 更新 `IngestJobs` 状态为 `succeeded` 或 `failed`
   - 更新 `Documents` 状态为 `completed`

---

## 2. Agent Chat 流式响应工作流

### 2.1 整体流程

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

### 2.2 MainAgent ReAct 循环

```
entry -> plan -> [conditional]
              |
              +-- direct -> respond -> END
              +-- tool -> execute_tool -> [continue/done/error]
              +-- skill -> execute_skill -> respond -> END
              +-- subagent -> execute_subagent -> respond -> END
              +-- error -> handle_error -> END
```

### 2.3 详细步骤

1. **用户发送消息**
   - 前端通过 SSE 建立 `/agent/chat/stream` 连接
   - 后端 `AgentEndpoint` 创建 `MainAgent` 实例

2. **规划节点** (`_plan_step`)
   - 收集当前可用的 tools、skills、subagents 的 schema
   - 构造 `CAPABILITY_ROUTING_SYSTEM_PROMPT`
   - 调用 LLM 输出 JSON 格式的 `decision`
   - 若 LLM 不可用，回退到 `_fallback_plan`（关键词硬编码匹配）

3. **路由分发** (`_plan_router`)
   - `decision.mode == "direct"`：直接进入 `respond` 节点
   - `decision.mode == "tool"`：提取 `active_tool`，进入 `execute_tool`
   - `decision.mode == "skill"`：提取 `active_skill`，进入 `execute_skill`
   - `decision.mode == "subagent"`：提取 `active_subagent_call`，进入 `execute_subagent`

4. **执行节点**
   - `execute_tool`：通过 `AgentToolRegistry.get_tool(name).ainvoke(args)` 调用工具
   - `execute_skill`：通过 `SkillRegistry.execute(name, args)` 调用
   - `execute_subagent`：通过 `SubAgentRegistry.execute(name, args)` 调用

5. **响应节点** (`_respond_step`)
   - 将工具/技能/子 Agent 的执行结果融入上下文
   - 调用 LLM 生成最终中文自然语言回复

6. **SSE 输出**
   - 发送 `status` 事件：指示当前阶段（planning/executing/responding）
   - 发送 `token` 事件：流式输出回复文本
   - 发送 `result` 事件：结构化工具结果预览
   - 发送 `[DONE]` 事件：标志流结束

### 2.4 QA 特殊透传路径

- 若 `_plan_step` 判定为 QA 意图，且配置了流式透传
- `MainAgent.stream_chat` 直接代理调用 `QAAgent.stream(query, space_public_id, user)`
- 不经过 LangGraph ReAct 循环，减少延迟

---

## 3. 交易协商工作流

### 3.1 整体流程

```
User Chat: "我要卖这份数据，底价 1000"
    -> MainAgent -> trade_goal Tool
    -> TradeAgent.run_goal
    -> TradeGoal (intent=sell_asset, min_price=1000)
    -> mechanism_selection_policy
    -> 选择 mechanism (fixed_price / auction / bilateral / contract_net)
    -> 创建/推进 NegotiationSession
    -> SellerAgent / BuyerAgent 通过 AgentMessageQueue 异步协商
    -> 达成后更新 TradeListing / TradeOrder / EscrowRecord
```

### 3.2 详细步骤

1. **目标解析**
   - `trade_goal` Tool 接收用户自然语言意图
   - 映射为 `TradeIntent`：`sell_asset`、`buy_asset`、`price_inquiry`、`market_analysis`
   - 构造 `TradeGoal` 对象，提取约束条件（底价、预算、资产ID等）

2. **机制选择** (`select_mechanism`)
   - 输入：`goal` + `constraints` + `MarketContext` + `RiskContext`
   - 输出：最优协商机制
     - `fixed_price`：一口价
     - `auction`：拍卖
     - `bilateral`：双边协商
     - `contract_net`：合同网

3. **协商会话创建**
   - 若不存在，创建 `NegotiationSessions` 记录
   - 设置初始价格参数（`starting_price`、`reserve_price`、`seller_floor_price` 等）
   - 创建 `EscrowRecord` 锁定买方资金

4. **Agent 间异步协商** (Blackboard 模式)
   - `SellerAgent` 和 `BuyerAgent` 轮询 `AgentMessageQueue`
   - 通过 `msg_type` 交换报价：`OFFER` -> `COUNTER` -> `ACCEPT` / `REJECT`
   - 每次消息更新 `NegotiationSessions.shared_board`（完整上下文）
   - `NegotiationHistorySummary` 定期生成摘要，控制上下文长度

5. **事件溯源记录**
   - 每个关键动作写入 `BlackboardEvents`（不可变事件流）
   - 支持通过 `BlackboardSnapshots` 快速恢复协商状态

6. **结算**
   - 达成一致后，更新 `NegotiationSessions.status = "settled"`
   - 释放 `EscrowRecord` 资金给卖方
   - 创建 `TradeOrders` 和 `TradeHoldings`
   - 记录 `TradeTransactionLog` 资金流水

---

## 4. RAG 问答工作流

### 4.1 整体流程

```
用户提问
    -> QAAgent.run / QAAgent.stream
    -> 向量检索 (pgvector)
    -> 图谱检索 (Neo4j)
    -> 混合重排序
    -> LLM 生成可溯源回答
    -> 返回答案 + 引用来源
```

### 4.2 详细步骤

1. **查询嵌入**
   - 用户问题通过 `embedding_client` 生成 1536 维向量

2. **向量检索**
   - 使用 `pgvector` 的相似度搜索（如 cosine similarity）
   - 从 `doc_chunk_embeddings` 检索 top-k 最相关的 `DocChunks`
   - 通过 `doc_id` 关联到 `Documents`，获取元数据

3. **图谱检索**
   - 从 Neo4j 查询与问题相关的实体和关系
   - 使用关键词匹配或向量相似度找到相关 `graph_node_id`

4. **上下文合并**
   - 向量检索结果和图谱检索结果按相关性重排序
   - 去除重复文档，限制总 Token 数

5. **答案生成**
   - 构造 Prompt：系统角色 + 检索到的上下文 + 用户问题
   - 调用 LLM（DeepSeek）生成回答
   - 要求 LLM 在回答中标注引用来源（`doc_id` / `chunk_id`）

6. **流式输出**（`stream_chat` 路径）
   - 通过 SSE 逐 token 返回到前端
   - 前端 `ChatTab` 实时渲染

---

## 5. 文档审查工作流

### 5.1 整体流程

```
用户请求: "审查这份文档"
    -> MainAgent -> review_document Tool
    -> ReviewAgent.run(doc_id)
    -> 加载文档内容和元数据
    -> LLM 多维度审查
    -> 生成 ReviewLogs 记录
    -> 返回审查报告
```

### 5.2 详细步骤

1. **触发审查**
   - `review_document` Tool 接收 `doc_id` 和 `review_type`
   - `review_type` 可选：`standard`（标准）、`strict`（严格）

2. **加载文档**
   - `ReviewAgent` 查询 `Documents` 和 `DocChunks`
   - 组装完整 Markdown 文本和结构信息

3. **LLM 审查**
   - 调用 LLM 对文档进行多维度评估：
     - **quality**：内容质量（完整性、准确性、可读性）
     - **compliance**：合规性（敏感信息、版权、法规）
     - **completeness**：结构完整性（标题、摘要、引用）
   - LLM 输出 JSON：评分、问题列表、改进建议

4. **结果持久化**
   - 创建 `ReviewLogs` 记录
   - 存储 `score`、`passed`、`issues`、`recommendations`
   - 若 `rework_needed = true`，标记需要返工

5. **返回报告**
   - 生成 Markdown 格式的审查报告
   - 通过 Agent Chat 返回给用户

---

## 6. 资产整理与聚类工作流

### 6.1 整体流程

```
用户请求: "帮我整理这些资产"
    -> MainAgent -> asset_organize Tool
    -> AssetOrganizeAgent.run(asset_ids)
    -> 加载资产特征
    -> 计算相似度并聚类
    -> 生成 AssetClusters 和 Memberships
    -> 返回聚类报告
```

### 6.2 详细步骤

1. **收集资产信息**
   - 根据 `asset_ids` 查询 `DataAssets`
   - 提取资产名称、描述、类型、标签、质量评分等特征

2. **特征向量化**
   - 对文本特征（名称、描述）生成 Embedding
   - 对数值特征（质量评分、大小）归一化
   - 拼接成统一特征向量

3. **聚类计算**
   - 使用相似度矩阵 + 社区发现（community detection）算法
   - 或调用 Neo4j 图算法进行聚类
   - 输出每个资产所属的簇和 `similarity_score`

4. **结果存储**
   - 创建 `AssetClusters` 记录（名称、描述、方法、数量）
   - 创建 `AssetClusterMembership` 记录关联资产
   - 生成 `summary_report`（Markdown 报告）

5. **可选：发布聚类**
   - 若 `publication_ready = true`，可将聚类结果转为 `TradeListings`

---

## 7. 记忆管理工作流

### 7.1 三层记忆架构

| 层级 | 存储 | 作用 |
|------|------|------|
| L1 工作记忆 | `SessionMemory` (内存/Redis) | 当前对话上下文 |
| L2 中期记忆 | `conversation_sessions` + `conversation_messages` | 会话历史和语义检索 |
| L3 长期记忆 | `user_preferences` + `user_memories` | 跨会话的偏好和事实 |

### 7.2 对话记忆工作流

```
用户发送消息
    -> UnifiedMemoryService.remember(session_id, role, content)
    -> 写入 conversation_messages
    -> 更新 conversation_sessions (message_count, last_message_at)
    -> 可选：生成会话摘要（当消息数超过阈值）
    -> 用户查询时 -> UnifiedMemoryService.recall(session_id, query)
        -> 检索最近消息 + 语义相似消息 + 长期记忆
```

### 7.3 长期记忆提取工作流

1. **定期摘要**
   - 当 `conversation_sessions.message_count` 超过阈值（如 20）
   - 调用 LLM 提取关键事实和偏好

2. **写入长期记忆**
   - `LongTermMemory.add_memory(user_id, content, memory_type, importance)`
   - 写入 `user_memories`，生成 Embedding 用于语义检索

3. **偏好学习**
   - `LongTermMemory.set_preference(user_id, key, value, pref_type)`
   - 写入 `user_preferences`

---

## 8. SKILL.md 驱动的工作流执行

### 8.1 解析流程

```
SKILL.md 文件 (agents/skills/docs/*.md)
    -> SkillMDParser._parse_file
    -> 提取 YAML frontmatter
    -> 提取 ## 适用场景 列表
    -> 提取 ## 工作流步骤 列表
    -> 生成 SkillMDDocument
```

### 8.2 执行流程

```
MainAgent 选择 skill/subagent
    -> SkillRegistry.execute(skill_id, args)
    -> 查找 SkillMDDocument
    -> 获取 executor 路径 (如 app.services.skills.pricing_skill:PricingSkill.calculate_quick_price)
    -> get_executor_method(executor_path, db)
        -> import_module -> instantiate class with db -> return bound method
    -> await method(**args)
    -> 返回 {"skill": skill_id, "result": result}
```

### 8.3 动态扩展

- 新增 Skill：只需在 `docs/` 下新建 `.md` 文件
- 无需修改任何 Python registry 代码
- 重启服务后自动生效

---

## 9. 数据血缘追踪工作流

### 9.1 血缘创建

```
文件上传 / Agent 生成 / 数据转换
    -> DataLineageService.create_lineage
    -> 创建 DataLineage 记录
    -> source_type = upload | api | agent_generation | import | transform | derived
    -> current_entity_type = file | chunk | knowledge | asset
    -> 若存在父实体 -> parent_lineage_id 指向父记录
```

### 9.2 血缘查询

```
请求血缘摘要/影响分析
    -> SkillRegistry.execute("lineage_summary" / "lineage_impact")
    -> 查询 DataLineage 树
    -> 递归收集上游/下游节点
    -> 生成血缘报告
```

---

## 10. Token 用量统计工作流

### 10.1 记录流程

```
每次 LLM 调用
    -> TokenUsageService.record_usage(
           user_id, provider, model, feature_type,
           prompt_tokens, completion_tokens, latency_ms, ...
       )
    -> 查询 model_prices 获取当前定价
    -> 计算 prompt_cost / completion_cost / total_cost
    -> 写入 token_usages
```

### 10.2 查询流程

```
用户/Agent 查询用量
    -> token_usage_query Tool
    -> TokenUsageService.get_user_usage_summary / get_user_daily_usage / get_recent_usage
    -> 按 feature_type 或时间聚合
    -> 返回统计图表数据
```

---

## 11. 用户级 Agent 配置工作流

### 11.1 配置获取

```
用户请求/Agent 初始化
    -> UserAgentService.get_or_create_config(user_id, create_default=True)
    -> 查询 user_agent_configs
    -> 若无记录，创建默认配置（DeepSeek, deepseek-chat, temperature=0.2）
```

### 11.2 LLM 客户端实例化

```
Agent 需要调用 LLM
    -> UserAgentService.get_user_llm_client(user_id, temperature=0.2)
    -> 读取 user_agent_configs
    -> 若用户配置了自定义 API Key，使用用户自己的 API
    -> 否则使用系统默认配置
    -> 返回 LangChain ChatModel 实例
```

---

## 12. 安全与审计工作流

### 12.1 权限校验

```
每个 API / Tool 调用
    -> SpaceAwareService._require_space(space_public_id, user)
    -> 验证用户是否为 space 成员（space_members）
    -> 验证 resource_acl 权限位
    -> 不通过则抛出 ServiceError(403)
```

### 12.2 审计日志记录

```
敏感操作（登录、文件下载、交易、协商）
    -> AuditLogService.log_action(
           user_id, action, resource_type, resource_id,
           previous_state, new_state, request_payload
       )
    -> 写入 audit_logs（按 created_at 分区）
    -> 异步风险评分（异常IP、非工作时间访问等）
```

### 12.3 乐观锁并发控制

```
交易扣款 / 协商状态更新
    -> SELECT ... WHERE version = current_version
    -> 执行业务逻辑
    -> UPDATE ... SET version = version + 1
    -> 若影响行数 = 0，抛出并发冲突异常，重试或报错
```

---

## 附录：关键数据流图

### A. 文件上传与摄入

```
[Frontend] -> upload-init -> [FastAPI]
                |
                v
           presigned URL
                |
                v
           [MinIO] <- PUT file
                |
                v
           upload-complete -> [FastAPI]
                |
                v
           [FileService] -> [IngestService] -> Celery
                |
                v
           [Celery Worker] -> LangChainIngestPipeline
                |
                +-> PostgreSQL (doc_chunks, embeddings)
                +-> Neo4j (knowledge graph)
```

### B. Agent Chat

```
[Frontend ChatTab] -> SSE /agent/chat/stream
                |
                v
           [MainAgent]
                |
       +--------+--------+--------+--------+
       v                 v                v
  [Direct]          [Tool]          [SubAgent]
       |               |                |
       v               v                v
  Respond      AgentToolRegistry   SubAgentRegistry
       |               |                |
       v               v                v
   SSE token    Service/Agent      execute_skill_md
       |               |                |
       +---------------+----------------+
                       |
                       v
                 [Frontend]
```
