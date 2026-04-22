# Agent 数据空间平台 - 数据库模型文档

本文档详细描述后端 PostgreSQL 数据库中的所有表结构、字段含义及关系。数据库使用 SQLAlchemy 2.0 映射，配合 pgvector 扩展存储向量嵌入。

---

## 1. 用户与认证模块

### 1.1 `users` — 用户主表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 内部自增主键 |
| `user_key` | `String(64) UQ` | 全局唯一用户标识符 |
| `display_name` | `String(128)` | 用户显示昵称 |
| `created_at` | `DateTime` | 注册时间 |

**关系**：一个用户可拥有多个 Space、多个认证方式、多个数据资产、交易记录等。

### 1.2 `user_auth` — 用户认证信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `user_id` | `BigInteger FK` | 关联 `users.id` |
| `identity_type` | `Enum` | 认证类型：`password` / `phone` / `wechat` / `github` |
| `identifier` | `String(128)` | 标识值（如手机号、邮箱、GitHub ID） |
| `credential` | `String(255)` | 密码哈希或凭证 |
| `verified` | `Boolean` | 是否已验证 |

---

## 2. Space（空间）模块

### 2.1 `spaces` — 空间主表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 对外暴露的空间唯一标识 |
| `name` | `String(128)` | 空间名称 |
| `owner_user_id` | `BigInteger FK` | 空间所有者 |
| `created_at` / `updated_at` | `DateTime` | 创建/更新时间 |

### 2.2 `space_members` — 空间成员与权限

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `space_id` | `String(32) FK` | 关联空间 public_id |
| `user_id` | `BigInteger FK` | 成员用户ID |
| `role` | `String(16)` | 角色：`owner` / `admin` / `editor` / `viewer` |
| `permissions` | `JSONB` | 细粒度权限覆盖（JSON对象） |
| `invited_by` | `BigInteger FK` | 邀请人用户ID |
| `invite_status` | `String(16)` | 邀请状态：`pending` / `active` / `removed` |
| `joined_at` | `DateTime` | 加入时间 |
| `last_accessed_at` | `DateTime` | 最后访问时间 |
| `notification_preferences` | `JSONB` | 通知偏好设置 |

---

## 3. 文件管理模块

### 3.1 `files` — 文件主表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 文件对外唯一标识 |
| `space_id` | `BigInteger` | 所属空间ID |
| `folder_id` | `BigInteger` | 所属文件夹ID |
| `name` | `String(255)` | 文件名 |
| `created_by` | `BigInteger` | 创建用户ID |
| `mime` | `String(128)` | MIME 类型 |
| `size_bytes` | `BigInteger` | 文件大小（字节） |
| `sha256` | `String(64)` | 文件内容哈希 |
| `status` | `Enum` | 状态：`active` / `archived` / `deleted` |
| `current_version_id` | `BigInteger FK` | 指向当前生效的版本（延迟外键） |
| `created_at` | `DateTime` | 上传时间 |

### 3.2 `file_versions` — 文件版本表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 版本唯一标识 |
| `file_id` | `BigInteger FK` | 关联文件 |
| `version_no` | `Integer` | 版本号 |
| `object_key` | `String(512)` | MinIO 对象存储键 |
| `size_bytes` | `BigInteger` | 版本文件大小 |
| `created_by` | `BigInteger` | 上传用户 |
| `sha256` | `String(64)` | 版本内容哈希 |
| `created_at` | `DateTime` | 版本创建时间 |

### 3.3 `folders` — 文件夹表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 文件夹唯一标识 |
| `space_id` | `BigInteger` | 所属空间 |
| `name` | `String(255)` | 文件夹名称 |
| `created_by` | `BigInteger` | 创建用户 |
| `parent_id` | `BigInteger` | 父文件夹ID（`NULL` 为根目录） |
| `path_cache` | `String(2048)` | 路径缓存（加速树查询） |
| `created_at` / `updated_at` | `DateTime` | 创建/更新时间 |
| `deleted_at` | `DateTime` | 软删除时间 |

### 3.4 `uploads` — 上传会话记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 上传会话标识 |
| `space_id` | `BigInteger` | 目标空间 |
| `folder_id` | `BigInteger` | 目标文件夹 |
| `filename` | `String(255)` | 原始文件名 |
| `size_bytes` | `BigInteger` | 文件大小 |
| `created_by` | `BigInteger` | 上传用户 |
| `status` | `Enum` | 状态：`init` / `uploading` / `completed` / `failed` |
| `created_at` | `DateTime` | 创建时间 |

---

## 4. 文档与向量模块

### 4.1 `documents` — 文档主表

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_id` | `UUID PK` | 文档唯一标识（默认 `uuid4`） |
| `space_id` | `BigInteger FK` | 所属空间 |
| `file_id` | `BigInteger FK` | 关联源文件（可为空） |
| `file_version_id` | `BigInteger FK` | 关联文件版本 |
| `graph_id` | `UUID` | 关联知识图谱ID |
| `title` | `Text` | 文档标题 |
| `source_url` | `Text` | 文档来源 URL |
| `object_key` | `String(512)` | MinIO 存储键（源文件） |
| `source_mime` | `String(128)` | 源文件 MIME |
| `markdown_object_key` | `String(512)` | Markdown 版本存储键 |
| `markdown_text` | `Text` | Markdown 文本内容缓存 |
| `content_hash` | `String(64)` | 内容哈希 |
| `status` | `Enum` | 状态：`pending` / `processing` / `completed` / `failed` |
| `created_by` | `BigInteger FK` | 创建用户 |
| `created_at` / `updated_at` | `DateTime` | 创建/更新时间 |

### 4.2 `ingest_jobs` — 文档摄入任务

| 字段 | 类型 | 说明 |
|------|------|------|
| `ingest_id` | `UUID PK` | 任务唯一标识 |
| `doc_id` | `UUID FK` | 关联文档 |
| `status` | `Enum` | 状态：`queued` / `running` / `succeeded` / `failed` / `cancelled` |
| `error` | `Text` | 失败原因 |
| `started_at` / `finished_at` | `DateTime` | 开始/结束时间 |
| `created_at` | `DateTime` | 创建时间 |

### 4.3 `doc_chunks` — 文档分块表

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_id` | `UUID PK` | 分块唯一标识 |
| `doc_id` | `UUID FK` | 关联文档 |
| `chunk_index` | `Integer` | 分块序号 |
| `content` | `Text` | 分块文本内容 |
| `token_count` | `Integer` | Token 数量 |
| `start_offset` / `end_offset` | `Integer` | 在原文中的起止偏移 |
| `section_path` | `Text` | 章节路径（如 `# 标题 / ## 子标题`） |
| `metadata` | `JSONB` | 分块元数据 |
| `created_at` | `DateTime` | 创建时间 |

### 4.4 `doc_chunk_embeddings` — 向量嵌入表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `chunk_id` | `UUID FK` | 关联分块 |
| `model` | `Text` | 嵌入模型名称 |
| `embedding` | `Vector(1536)` | 1536 维向量（pgvector） |
| `created_at` | `DateTime` | 创建时间 |

---

## 5. Agent 任务模块

### 5.1 `agent_tasks` — Agent 执行任务跟踪

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 任务对外标识 |
| `agent_type` | `String(32)` | Agent 类型：`file_query` / `qa` / `review` / `trade` 等 |
| `status` | `Enum` | 状态：`pending` / `running` / `completed` / `failed` / `cancelled` |
| `intent` | `String(32)` | 检测到的意图 |
| `input_data` | `JSONB` | 输入参数 |
| `output_data` | `JSONB` | 输出结果 |
| `subagent_result` | `JSONB` | 子 Agent 返回结果 |
| `error` | `Text` | 错误信息 |
| `retry_count` | `Integer` | 重试次数 |
| `created_by` | `BigInteger` | 创建用户 |
| `space_id` | `BigInteger` | 关联空间 |
| `started_at` / `finished_at` / `created_at` | `DateTime` | 时间戳 |

### 5.2 `agent_decision_logs` — Agent 决策日志

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `log_id` | `String(32) UQ` | 日志唯一标识 |
| `task_id` | `String(32)` | 关联任务 |
| `agent_type` | `String(32)` | Agent 类型 |
| `decision` | `String(64)` | 实际采取的动作 |
| `context` | `JSONB` | 决策时上下文 |
| `reasoning` | `Text` | LLM 决策理由 |
| `input_data` / `output_data` | `JSONB` | 输入输出快照 |
| `result_status` | `String(16)` | 最终结果：`success` / `failure` |
| `result_feedback` | `Text` | 结果反馈 |
| `created_at` | `DateTime` | 记录时间 |

### 5.3 `agent_intermediate_results` — 中间结果缓存

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `result_id` | `String(32) UQ` | 结果标识 |
| `task_id` | `String(32)` | 关联任务 |
| `step_name` | `String(64)` | 步骤名称 |
| `step_order` | `Integer` | 步骤顺序 |
| `result_type` | `String(32)` | 结果类型：`text` / `json` / `file` |
| `result_data` | `JSONB` | 结果内容 |
| `metadata` | `JSONB` | 元数据 |
| `expires_at` | `DateTime` | 过期时间 |
| `created_at` | `DateTime` | 创建时间 |

---

## 6. 资产与审查模块

### 6.1 `asset_clusters` — 资产聚类结果

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUID PK` | 聚类唯一标识 |
| `public_id` | `String(32) UQ` | 对外标识 |
| `space_id` | `BigInteger` | 所属空间 |
| `name` | `String(255)` | 聚类名称 |
| `description` | `Text` | 聚类描述 |
| `summary_report` | `Text` | Markdown 格式聚类报告 |
| `graph_cluster_id` | `String(128)` | Neo4j 中对应的聚类 ID |
| `cluster_method` | `String(32)` | 聚类方法 |
| `asset_count` | `Integer` | 包含资产数量 |
| `publication_ready` | `Boolean` | 是否可发布 |
| `created_by` / `created_at` / `updated_at` | — | 审计字段 |

### 6.2 `asset_cluster_memberships` — 聚类成员关系

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `cluster_id` | `UUID FK` | 关联聚类 |
| `asset_id` | `String(32)` | 资产标识 |
| `similarity_score` | `Float` | 与聚类中心的相似度 |
| `cluster_role` | `String(32)` | 角色：`core` / `peripheral` / `outlier` |
| `created_at` | `DateTime` | 加入时间 |

### 6.3 `review_logs` — 文档审查日志

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 审查记录标识 |
| `doc_id` | `UUID FK` | 关联文档 |
| `review_type` | `String(32)` | 审查类型：`quality` / `compliance` / `completeness` |
| `score` | `Float` | 综合评分 |
| `passed` | `Boolean` | 是否通过 |
| `issues` | `JSONB` | 发现的问题列表 |
| `recommendations` | `JSONB` | 改进建议 |
| `rework_needed` | `Boolean` | 是否需要返工 |
| `rework_count` / `max_rework` | `Integer` | 当前/最大返工次数 |
| `final_status` | `Enum` | 最终状态：`pending` / `approved` / `rejected` / `manual_review` |
| `reviewer_notes` | `Text` | 审查员备注 |
| `created_by` / `created_at` | — | 审计字段 |

---

## 7. 交易与经济模块

### 7.1 `trade_listings` — 数字资产挂牌

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 挂牌唯一标识 |
| `asset_id` | `String(32)` | 关联资产ID |
| `space_public_id` | `String(32)` | 关联空间 |
| `seller_user_id` | `BigInteger FK` | 卖方用户 |
| `seller_alias` | `String(64)` | 卖方别名 |
| `title` | `String(255)` | 挂牌标题 |
| `category` | `String(64)` | 分类（默认 `knowledge_report`） |
| `tags` | `ARRAY(String(32))` | 标签数组 |
| `price_credits` | `Integer` | 价格（单位：分，避免浮点误差） |
| `public_summary` | `Text` | 公开摘要 |
| `preview_excerpt` | `Text` | 预览摘录 |
| `delivery_payload_encrypted` | `LargeBinary` | 加密交付内容 |
| `status` | `Enum` | 状态：`draft` / `active` / `paused` / `sold_out` / `delisted` / `suspended` |
| `purchase_count` / `market_view_count` / `revenue_total` | `Integer` / `BigInteger` | 统计数据 |
| `auto_reprice_enabled` | `Boolean` | 是否启用自动重定价 |
| `last_reprice_at` | `DateTime` | 最后重定价时间 |
| `demand_score` | `Float` | 需求评分 |
| `created_at` / `updated_at` | `DateTime` | 时间戳 |

### 7.2 `trade_orders` — 交易订单

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 订单标识 |
| `listing_id` | `String(32)` | 关联挂牌 |
| `buyer_user_id` / `seller_user_id` | `BigInteger FK` | 买卖双方 |
| `asset_title_snapshot` / `seller_alias_snapshot` | `String` | 购买时快照 |
| `price_credits` | `Integer` | 成交价格（分） |
| `platform_fee` | `Integer` | 平台手续费（分） |
| `seller_income` | `Integer` | 卖方实际收入（分） |
| `delivery_payload_encrypted` | `LargeBinary` | 加密交付快照 |
| `status` | `Enum` | 状态：`pending` / `completed` / `cancelled` / `refunded` / `disputed` |
| `completed_at` / `created_at` | `DateTime` | 完成/创建时间 |

### 7.3 `trade_wallets` — 用户钱包（乐观锁）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `user_id` | `BigInteger FK UQ` | 用户唯一 |
| `liquid_credits` | `BigInteger` | 可用余额（分），默认 0 |
| `cumulative_sales_earnings` | `BigInteger` | 累计销售收入 |
| `cumulative_yield_earnings` | `BigInteger` | 累计收益 |
| `total_spent` | `BigInteger` | 总支出 |
| `auto_yield_enabled` | `Boolean` | 自动理财开关 |
| `yield_strategy` | `Enum` | 策略：`conservative` / `balanced` / `aggressive` |
| `last_yield_run_at` | `DateTime` | 上次收益计算时间 |
| `version` | `Integer` | 乐观锁版本号 |
| `created_at` / `updated_at` | `DateTime` | 时间戳 |

### 7.4 `trade_holdings` — 用户持有资产

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `user_id` | `BigInteger FK` | 持有者 |
| `order_id` | `String(32) UQ` | 来源订单 |
| `listing_id` | `String(32)` | 来源挂牌 |
| `asset_title` / `seller_alias` | `String` | 资产标题/卖方别名 |
| `access_expires_at` | `DateTime` | 访问过期时间 |
| `download_count` | `Integer` | 下载次数 |
| `last_accessed_at` | `DateTime` | 最后访问时间 |
| `purchased_at` / `created_at` | `DateTime` | 购买/创建时间 |

### 7.5 `trade_yield_runs` — 收益执行记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 记录标识 |
| `user_id` | `BigInteger FK` | 用户 |
| `strategy` | `Enum` | 执行策略 |
| `annual_rate` | `Float` | 年化收益率 |
| `elapsed_days` | `Float` | 持有天数 |
| `yield_amount` | `BigInteger` | 收益金额（分） |
| `liquid_credits_before` / `liquid_credits_after` | `BigInteger` | 执行前后余额快照 |
| `listing_adjustments` | `JSONB` | 关联的调价记录 |
| `created_at` | `DateTime` | 创建时间 |

### 7.6 `trade_transaction_log` — 交易资金流水

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `public_id` | `String(32) UQ` | 流水号 |
| `tx_type` | `String(32)` | 类型：`deposit` / `purchase` / `sale_income` / `yield_accrual` / `refund` |
| `user_id` | `BigInteger FK` | 用户 |
| `order_id` / `listing_id` | `String(32)` | 关联业务单号 |
| `amount_delta` | `BigInteger` | 变动金额（分） |
| `balance_before` / `balance_after` | `BigInteger` | 余额快照 |
| `record_metadata` | `JSONB` | 扩展元数据 |
| `ip_address` / `user_agent` | `String` / `Text` | 客户端信息 |
| `created_at` | `DateTime` | 记录时间 |

---

## 9. 记忆管理模块

### 9.1 `conversation_sessions` — 对话会话

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `session_id` | `String(32) UQ` | 会话唯一标识 |
| `user_id` | `BigInteger FK` | 用户 |
| `title` | `String(255)` | LLM 生成的会话标题 |
| `status` | `String(16)` | 状态：`active` / `archived` / `deleted` |
| `space_id` | `String(32)` | 关联空间 |
| `message_count` | `Integer` | 消息数量 |
| `summary` / `summary_tokens` | `Text` / `Integer` | 会话摘要及 Token 数 |
| `created_at` / `last_message_at` / `ended_at` | `DateTime` | 时间戳 |

### 9.2 `conversation_messages` — 对话消息

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `message_id` | `String(32) UQ` | 消息唯一标识 |
| `session_id` | `String(32) FK` | 关联会话 |
| `user_id` | `BigInteger FK` | 用户 |
| `role` | `String(16)` | 角色：`user` / `assistant` / `system` |
| `content` | `Text` | 消息内容 |
| `agent_type` | `String(32)` | 关联 Agent 类型 |
| `embedding` | `Vector(1536)` | 语义向量（可选） |
| `metadata` | `JSONB` | 消息元数据 |
| `created_at` | `DateTime` | 发送时间 |

### 9.3 `user_preferences` — 用户偏好（L3 长期记忆）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `user_id` | `BigInteger FK` | 用户 |
| `pref_type` | `String(32)` | 偏好类型：`search` / `response` / `style` / `price` |
| `key` | `String(64)` | 偏好键 |
| `value` | `Text` | 偏好值（JSON 编码） |
| `confidence` | `Float` | 置信度（0-1） |
| `source` | `String(16)` | 来源：`explicit` / `implicit` / `inferred` |
| `context` | `Text` | 推导上下文 |
| `updated_at` | `DateTime` | 更新时间 |

### 9.4 `user_memories` — 用户长期记忆

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `memory_id` | `String(32) UQ` | 记忆标识 |
| `user_id` | `BigInteger FK` | 用户 |
| `content` | `Text` | 记忆内容 |
| `memory_type` | `String(32)` | 类型：`fact` / `preference` / `goal` / `relationship` |
| `embedding` | `Vector(1536)` | 语义向量 |
| `source` | `String(32)` | 来源：`conversation` / `document` / `manual` |
| `source_session_id` | `String(32)` | 来源会话 |
| `importance` | `Integer` | 重要性（1-10） |
| `access_count` | `Integer` | 被引用次数 |
| `last_accessed_at` | `DateTime` | 最后访问时间 |
| `expires_at` | `DateTime` | 过期时间（可选） |
| `created_at` | `DateTime` | 创建时间 |

---

## 10. 安全与审计模块

### 10.1 `resource_acl` — 资源访问控制列表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `acl_id` | `String(32) UQ` | ACL 标识 |
| `resource_type` | `String(32)` | 资源类型：`space` / `file` / `asset` / `knowledge` |
| `resource_id` | `String(32)` | 资源标识 |
| `user_id` / `role_id` | `BigInteger` / `String(32)` | 被授权主体 |
| `is_public` | `Boolean` | 是否公开 |
| `can_read` / `can_write` / `can_delete` / `can_share` / `can_execute` | `Boolean` | 权限位 |
| `conditions` | `JSONB` | ABAC 条件（如时间范围、IP 白名单） |
| `inherit_from` | `String(32)` | 继承自父资源 |
| `priority` | `Integer` | 优先级（高覆盖低） |
| `expires_at` | `DateTime` | 过期时间 |
| `granted_by` | `BigInteger FK` | 授权人 |

### 10.2 `audit_logs` — 审计日志（按时间分区）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `log_id` | `String(32) UQ` | 日志标识 |
| `user_id` / `user_email` | `BigInteger FK` / `String(255)` | 用户及邮箱快照 |
| `client_ip` / `user_agent` / `session_id` | `String` | 客户端信息 |
| `action` | `String(64)` | 操作类型，如 `user.login`、`file.download` |
| `resource_type` / `resource_id` | `String` | 操作对象 |
| `previous_state` / `new_state` | `JSONB` | 变更前后状态 |
| `request_payload` | `JSONB` | 请求参数（脱敏） |
| `result` | `String(16)` | 结果：`success` / `failure` / `denied` / `error` |
| `error_message` | `Text` | 错误详情 |
| `risk_score` | `Float` | 风险评分（0-1） |
| `risk_reasons` | `JSONB` | 风险原因列表 |
| `alert_sent` / `reviewed_by` / `review_notes` | `Boolean` / `BigInteger` / `Text` | 告警与复核 |
| `created_at` | `DateTime` | 记录时间 |

### 10.3 `asset_provenance` — 资产来源记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `provenance_id` | `String(32) UQ` | 来源标识 |
| `asset_id` | `String(32)` | 资产标识 |
| `asset_type` | `String(32)` | 资产类型 |
| `source_type` | `String(32)` | 来源类型：`upload` / `import` / `generation` |
| `source_id` / `source_url` / `source_description` | `String` / `Text` | 来源详情 |
| `origin_date` / `creator_name` / `license_type` | `DateTime` / `String` | 元数据 |
| `verification_hash` / `verification_method` | `String` | 验证信息 |
| `record_metadata` | `JSONB` | 扩展元数据 |
| `created_at` | `DateTime` | 记录时间 |

### 10.4 `data_lineage` — 数据血缘追踪

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `lineage_id` | `String(32) UQ` | 血缘标识 |
| `source_type` / `source_id` | `String(32)` | 来源类型/ID |
| `source_metadata` | `JSONB` | 来源元数据 |
| `transformations` | `JSONB` | 转换链（数组） |
| `current_entity_type` / `current_entity_id` | `String(32)` | 当前实体 |
| `parent_lineage_id` | `String(32) FK` | 父血缘记录（树形结构） |
| `created_by` / `created_at` | `BigInteger FK` / `DateTime` | 审计字段 |

---

## 11. 事件溯源与基础设施模块

### 11.1 `blackboard_events` — 黑板事件流

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `event_id` | `String(32) UQ` | 事件唯一标识 |
| `session_id` | `String(32) Index` | 关联会话 |
| `session_type` | `String(16)` | 会话类型：`data_rights` / `audit` |
| `sequence_number` | `Integer` | 全局递增序列号（乐观锁） |
| `event_type` | `Enum` | 事件类型：数据权益相关事件 |
| `agent_id` | `BigInteger` | 发起者 user_id |
| `agent_role` | `String(16)` | 角色：`owner` / `buyer` / `auditor` |
| `payload` | `JSONB` | 事件载荷 |
| `event_timestamp` | `DateTime` | 业务时间戳 |
| `vector_clock` | `JSONB` | 逻辑时钟（因果排序） |
| `graph_node_id` | `String(64)` | 关联图谱节点（可选） |
| `created_at` | `DateTime` | 写入时间 |

### 11.2 `blackboard_snapshots` — 黑板状态快照

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `session_id` | `String(32) Index` | 关联会话 |
| `sequence_number` | `Integer` | 快照对应序列号 |
| `state` | `JSONB` | 状态快照 |
| `event_count` | `Integer` | 包含的事件数量 |
| `created_at` | `DateTime` | 创建时间 |

### 11.3 `agent_rate_limits` — Agent 限流

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `agent_id` | `BigInteger Index` | Agent 标识 |
| `limit_type` | `String(32)` | 限流类型：`bid` / `offer` / `message` |
| `window_start` | `DateTime` | 滑动窗口开始时间 |
| `request_count` | `Integer` | 窗口内请求数 |
| `rejected_count` | `Integer` | 被拒绝数 |
| `is_throttled` | `Boolean` | 是否被限流 |
| `throttle_until` | `DateTime` | 限流解除时间 |

### 11.4 `outbox_events` — 事务 Outbox

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | `String(32) PK` | 事件标识 |
| `event_type` | `String(50)` | 事件类型 |
| `aggregate_type` / `aggregate_id` | `String(50)` / `String(32)` | 聚合根信息 |
| `payload` | `JSONB` | 事件载荷 |
| `status` | `String(20)` | 状态：`pending` / `processing` / `completed` / `failed` |
| `retry_count` / `max_retries` | `Integer` | 重试次数/上限 |
| `created_at` / `processed_at` | `DateTime` | 创建/处理时间 |
| `error` / `processor_id` | `Text` / `String(64)` | 错误信息/处理者 |

---

## 12. 数据权益与隐私模块

### 12.1 `data_assets` — 数据资产

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `asset_id` | `String(64) UQ Index` | 资产唯一标识 |
| `owner_id` | `Integer FK` | 所有者 |
| `asset_name` | `String(200)` | 资产名称 |
| `asset_description` | `Text` | 资产描述 |
| `data_type` | `String(50)` | 数据类型 |
| `sensitivity_level` | `Enum` | 敏感度：`low` / `medium` / `high` / `critical` |
| `default_anonymization_level` | `Integer` | 默认匿名化级别 |
| `quality_*` (6个字段) | `Float` | 数据质量维度评分 |
| `raw_data_source` | `String(500)` | 原始数据来源 |
| `lineage_root` | `String(64)` | 血缘根节点 |
| `processing_chain_hash` | `String(64)` | 处理链哈希 |
| `storage_location` | `String(500)` | 存储位置 |
| `data_size_bytes` / `record_count` | `Integer` | 数据规模 |
| `related_entities` | `JSONB` | 相关实体 |
| `is_active` / `is_available_for_trade` | `Boolean` | 状态开关 |

### 12.2 `data_rights_transactions` — 数据权益交易

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `transaction_id` | `String(64) UQ Index` | 交易标识 |
| `negotiation_id` | `String(64)` | 遗留字段（协商表已移除） |
| `data_asset_id` | `String(64) FK` | 关联资产 |
| `owner_id` / `buyer_id` | `Integer FK` | 交易双方 |
| `rights_types` | `JSONB` | 权益类型列表 |
| `usage_scope` | `JSONB` | 使用范围 |
| `restrictions` | `JSONB` | 使用限制 |
| `computation_method` | `Enum` | 隐私计算方式 |
| `anonymization_level` | `Integer` | 匿名化级别 |
| `computation_constraints` | `JSONB` | 计算约束 |
| `valid_from` / `valid_until` | `DateTime` | 有效期 |
| `agreed_price` / `currency` | `Float` / `String(10)` | 成交价格/货币 |
| `status` | `Enum` | 交易状态 |
| `settlement_tx_hash` / `settlement_time` | `String(128)` / `DateTime` | 结算信息 |

### 12.3 `data_access_audit_logs` — 数据访问审计

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `log_id` | `String(64) UQ Index` | 日志标识 |
| `transaction_id` | `String(64) FK` | 关联权益交易 |
| `negotiation_id` / `data_asset_id` / `buyer_id` | `String` / `Integer FK` | 关联信息 |
| `access_timestamp` | `DateTime` | 访问时间 |
| `access_purpose` | `String(200)` | 访问目的 |
| `computation_method_used` | `Enum` | 实际使用的计算方式 |
| `query_fingerprint` | `String(64)` | 查询指纹 |
| `query_complexity_score` | `Float` | 查询复杂度 |
| `result_size_bytes` / `result_row_count` / `result_aggregation_level` | `Integer` / `String` | 结果规模 |
| `policy_compliance_check` | `JSONB` | 合规检查结果 |
| `risk_score` | `Float` | 风险评分 |
| `anomaly_flags` | `JSONB` | 异常标记 |

### 12.4 `policy_violations` — 策略违规记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `violation_id` | `String(64) UQ Index` | 违规标识 |
| `transaction_id` | `String(64) FK` | 关联交易 |
| `negotiation_id` / `data_asset_id` | `String(64)` | 关联信息 |
| `violation_type` | `String(100)` | 违规类型 |
| `severity` | `String(20)` | 严重级别 |
| `violation_details` / `evidence` | `JSONB` | 违规详情/证据 |
| `potential_data_exposure` | `Float` | 潜在数据暴露量 |
| `affected_records_estimate` | `Integer` | 受影响记录数估计 |
| `automatic_action_taken` | `String(200)` | 自动采取措施 |
| `manual_review_status` | `String(50)` | 人工复核状态 |
| `resolution_notes` | `Text` | 解决备注 |
| `detected_at` / `resolved_at` | `DateTime` | 检测/解决时间 |

### 12.5 `data_lineage_nodes` — 数据血缘节点

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `node_id` | `String(64) UQ Index` | 节点标识 |
| `asset_id` | `String(64) FK` | 关联资产 |
| `node_type` | `String(50)` | 节点类型 |
| `parent_nodes` | `JSONB` | 父节点列表 |
| `processing_logic_hash` | `String(64)` | 处理逻辑哈希 |
| `quality_metrics` | `JSONB` | 质量指标 |
| `provenance_hash` | `String(64)` | 来源哈希 |
| `created_at` | `DateTime` | 创建时间 |

---

## 13. 用户配置与计费模块

### 13.1 `user_agent_configs` — 用户 Agent 配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `user_id` | `Integer FK UQ` | 用户唯一 |
| `provider` | `Enum` | LLM 提供商：`deepseek` / `openai` / `qwen` / `custom` |
| `model` | `String(100)` | 模型名称 |
| `api_key_encrypted` | `Text` | 加密后的 API Key |
| `base_url` | `String(500)` | 自定义 Base URL |
| `temperature` | `Float` | 采样温度（默认 0.2） |
| `max_tokens` | `Integer` | 最大 Token 数（默认 2048） |
| `system_prompt` | `Text` | 自定义系统提示词 |
| `trade_min_profit_margin` | `Float` | 卖方最小利润率 |
| `trade_max_budget_ratio` | `Float` | 买方最大预算比例 |
| `is_active` / `is_default` | `Boolean` | 状态/默认标志 |

### 13.2 `token_usages` — Token 用量统计

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `user_id` | `Integer FK` | 用户 |
| `provider` | `Enum` | 模型提供商 |
| `model` | `String(100)` | 模型名称 |
| `is_custom_api` | `Boolean` | 是否使用自定义 API |
| `feature_type` | `Enum` | 功能类型（见 `FeatureType` 枚举） |
| `feature_detail` | `String(200)` | 功能详情 |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | `Integer` | Token 数量 |
| `prompt_cost` / `completion_cost` / `total_cost` | `Float` | 成本（美元） |
| `request_id` / `session_id` | `String(100) Index` | 关联ID |
| `latency_ms` | `Integer` | 请求延迟 |
| `status` | `String(20)` | 状态：`success` / `error` |
| `error_message` | `Text` | 错误信息 |
| `metadata_json` | `JSONB` | 扩展元数据 |
| `created_at` | `DateTime` | 记录时间 |

### 13.3 `model_prices` — 模型定价表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer PK` | 自增主键 |
| `provider` / `model` | `Enum` / `String(100)` | 提供商和模型（联合唯一） |
| `prompt_price_per_1k` | `Float` | 输入单价（每 1K tokens，美元） |
| `completion_price_per_1k` | `Float` | 输出单价（每 1K tokens，美元） |
| `currency` | `String(10)` | 货币（默认 USD） |
| `effective_from` / `effective_to` | `DateTime` | 生效起止时间 |
| `is_active` | `Boolean` | 是否有效 |
| `description` | `Text` | 描述 |

---

## 15. 协作与同步模块

### 15.1 `collaboration_operations` — 协作操作记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `BigInteger PK` | 自增主键 |
| `operation_id` | `String(32) UQ` | 操作标识 |
| `space_id` | `String(32) FK` | 关联空间 |
| `user_id` | `BigInteger FK` | 操作者 |
| `operation_type` | `String(32)` | 操作类型：`edit` / `delete` / `create` / `move` |
| `entity_type` | `String(32)` | 实体类型：`file` / `markdown` / `graph_node` |
| `entity_id` | `String(32)` | 实体标识 |
| `previous_state` | `JSONB` | 变更前状态 |
| `new_state` | `JSONB` | 变更后状态 |
| `operation_summary` | `String(255)` | 可读摘要 |
| `vector_clock` | `JSONB` | 向量时钟（冲突检测） |
| `operation_timestamp` | `DateTime` | 操作时间 |
| `synced_to_clients` | `JSONB` | 已同步客户端列表 |

---

## 附录：枚举类型汇总

| 枚举名 | 可选值 |
|--------|--------|
| `identity_type` | `password`, `phone`, `wechat`, `github` |
| `file_status` | `active`, `archived`, `deleted` |
| `upload_status` | `init`, `uploading`, `completed`, `failed` |
| `document_status` | `pending`, `processing`, `completed`, `failed` |
| `ingest_status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `agent_task_status` | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `review_status` | `pending`, `approved`, `rejected`, `manual_review` |
| `listing_status` | `draft`, `active`, `paused`, `sold_out`, `delisted`, `suspended` |
| `order_status` | `pending`, `completed`, `cancelled`, `refunded`, `disputed` |
| `yield_strategy` | `conservative`, `balanced`, `aggressive` |
| `blackboard_event_type` | `DATA_ASSET_REGISTER`, `DATA_RIGHTS_NEGOTIATION_INIT`, `DATA_RIGHTS_GRANT`, `USAGE_SCOPE_DEFINE`, `COMPUTATION_AGREEMENT`, `DATA_ACCESS_AUDIT`, `POLICY_VIOLATION`, `RIGHTS_REVOKE` |
| `DataSensitivityLevel` | `low`, `medium`, `high`, `critical` |
| `ComputationMethod` | `federated_learning`, `mpc`, `tee`, `differential_privacy`, `raw_data` |
| `DataRightsStatus` | `pending`, `active`, `granted`, `expired`, `revoked`, `violated` |
| `LLMProvider` | `deepseek`, `openai`, `qwen`, `custom` |
| `FeatureType` | `chat`, `chat_stream`, `asset_generation`, `asset_organize`, `trade_pricing`, `ingest_pipeline`, `graph_construction`, `review`, `file_query`, `embedding`, `other` |
| `OperationType` (Python) | `create`, `edit`, `delete`, `move` |
| `SpaceRole` (Python) | `owner`, `admin`, `editor`, `viewer` |
| `DataLineageType` (Python) | `upload`, `api`, `agent_generation`, `import`, `transform`, `derived` |
