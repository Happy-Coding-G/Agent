# 分层记忆管理系统架构设计

## 1. 问题分析

### 1.1 当前项目记忆管理现状

| 层级 | 现状 | 问题 |
|------|------|------|
| **短期记忆** | LangGraph MemorySaver (内存) | 服务重启丢失 |
| **中期记忆** | 无统一设计 | 对话历史未持久化 |
| **长期记忆** | Neo4j + pgvector (知识图谱) | 仅结构化知识，无用户交互记忆 |
| **Trade 交易** | 已实现分层上下文 | 独立实现，未推广 |

### 1.2 缺失的关键功能

```
┌─────────────────────────────────────────────────────────────────┐
│                    记忆管理缺失分析                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  场景              当前状态              缺失                     │
│  ──────────────────────────────────────────────────────────    │
│  Chat 对话                                                    │
│  ├─ 对话历史      仅内存，无持久化      完整对话存储              │
│  ├─ 上下文连贯    每轮独立              跨轮次上下文传递           │
│  └─ 用户偏好      无                    个性化偏好学习            │
│                                                                  │
│  Agent 工作流                                                 │
│  ├─ 执行状态      AgentTasks (已持久化)  ✅ 已完善               │
│  ├─ 决策历史      无                    决策回溯能力              │
│  └─ 中间结果      无                    结果复用                  │
│                                                                  │
│  知识管理                                                     │
│  ├─ RAG 向量      pgvector (未优化)     HNSW/IVFFlat 索引        │
│  ├─ 知识图谱      Neo4j (较好)          增量更新                 │
│  └─ 用户知识      无                    个人知识库                │
│                                                                  │
│  Trade 交易                                                 │
│  └─ 分层上下文    已实现                可推广到其他场景          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 分层记忆架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        分层记忆管理系统                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  L0: 瞬时记忆 (In-Flight)                                   │   │
│   │  ┌─────────────────────────────────────────────────────┐    │   │
│   │  │  当前请求的输入/输出                                 │    │   │
│   │  │  • 函数参数、返回值                                 │    │   │
│   │  │  • LLM 生成的中间结果                               │    │   │
│   │  └─────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                              │                                        │
│                              ▼                                        │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  L1: 短期记忆 (Working Memory)                              │   │
│   │  ┌─────────────────────────────────────────────────────┐    │   │
│   │  │  当前会话上下文                                     │    │   │
│   │  │  • 对话历史 (最近 N 轮)                             │    │   │
│   │  │  • 当前任务状态                                     │    │   │
│   │  │  • 临时变量                                          │    │   │
│   │  │  存储: Redis (TTL: 会话期间)                         │    │   │
│   │  └─────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                              │                                        │
│                              ▼ (定期摘要)                             │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  L2: 中期记忆 (Episodic Memory)                            │   │
│   │  ┌─────────────────────────────────────────────────────┐    │   │
│   │  │  历史会话记录                                        │    │   │
│   │  │  • 完整对话历史 (按会话组织)                          │    │   │
│   │  │  • 会话摘要 (LLM 生成)                               │    │   │
│   │  │  • 关键决策点                                        │    │   │
│   │  │  存储: PostgreSQL (conversation_sessions)            │    │   │
│   │  └─────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                              │                                        │
│                              ▼ (信息提取)                             │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  L3: 长期记忆 (Semantic Memory)                             │   │
│   │  ┌─────────────────────────────────────────────────────┐    │   │
│   │  │  结构化知识                                          │    │   │
│   │  │  • 用户偏好 (偏好表)                                 │    │   │
│   │  │  • 用户知识 (Neo4j)                                 │    │   │
│   │  │  • 资产关系 (知识图谱)                               │    │   │
│   │  │  存储: PostgreSQL + Neo4j + pgvector                 │    │   │
│   │  └─────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 各层级详细设计

#### L0: 瞬时记忆 (In-Flight)

**特点**: 单次请求内的临时数据，函数调用结束后自动释放

**实现**: 代码中的局部变量，无需特殊处理

```python
# 示例：函数调用链中的临时数据
async def process(user_input):
    # L0: 瞬时记忆 - 函数参数
    parsed = parse_input(user_input)  # 临时变量

    # L0: 瞬时记忆 - 中间结果
    context = await fetch_context(parsed)

    # 返回后自动释放
    return await generate_response(context)
```

#### L1: 短期记忆 (Working Memory)

**特点**: 维持当前会话的连贯性，服务重启后丢失

**存储**: Redis

```python
class SessionMemory:
    """短期会话记忆"""

    def __init__(self, redis_client):
        self.redis = redis_client

    def get_key(self, user_id: int, session_id: str) -> str:
        return f"memory:session:{user_id}:{session_id}"

    async def add_message(
        self,
        user_id: int,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None
    ):
        """添加对话消息到短期记忆"""
        key = self.get_key(user_id, session_id)
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }

        # 追加到列表
        await self.redis.rpush(key, json.dumps(msg))

        # 限制长度（只保留最近 20 轮）
        await self.redis.ltrim(key, -40, -1)  # 每轮2条：user + assistant

        # 设置过期时间（1小时无活动）
        await self.redis.expire(key, 3600)

    async def get_history(
        self,
        user_id: int,
        session_id: str,
        limit: int = 10
    ) -> List[dict]:
        """获取最近 N 轮对话"""
        key = self.get_key(user_id, session_id)
        messages = await self.redis.lrange(key, -limit*2, -1)
        return [json.loads(m) for m in messages]

    async def get_full_context(
        self,
        user_id: int,
        session_id: str
    ) -> str:
        """构建 LLM 上下文字符串"""
        history = await self.get_history(user_id, session_id, limit=20)
        return "\n".join([
            f"{m['role']}: {m['content']}"
            for m in history
        ])
```

#### L2: 中期记忆 (Episodic Memory)

**特点**: 完整的会话历史，支持回溯和检索

**存储**: PostgreSQL

```python
class ConversationSession(Base):
    """会话记录"""
    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 会话元数据
    title: Mapped[str] = mapped_column(String(255))  # LLM 生成
    status: Mapped[str] = mapped_column(String(16))  # active/archived
    space_id: Mapped[Optional[str]] = mapped_column(String(32))

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_message_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 统计
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    # 摘要（定期生成）
    summary: Mapped[Optional[str]] = mapped_column(Text)  # LLM 生成
    summary_tokens: Mapped[Optional[int]] = mapped_column(Integer)


class ConversationMessage(Base):
    """对话消息"""
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(32), unique=True)
    session_id: Mapped[str] = mapped_column(String(32))

    # 消息内容
    role: Mapped[str] = mapped_column(String(16))  # user/assistant/system
    content: Mapped[str] = mapped_column(Text)

    # 关联
    agent_type: Mapped[Optional[str]] = mapped_column(String(32))  # QA/DataProcess/...

    # 向量嵌入（用于检索）
    embedding: Mapped[Optional[object]] = mapped_column(Vector(1536))

    # 元数据
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime)

    # 索引
    __table_args__ = (
        Index("idx_msg_session_time", "session_id", "created_at"),
        Index("idx_msg_embedding", "embedding"),
    )
```

#### L3: 长期记忆 (Semantic Memory)

**特点**: 用户偏好、知识和模式，跨会话保持

**存储**: PostgreSQL + Neo4j + pgvector

```python
class UserPreference(Base):
    """用户偏好"""
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 偏好类型
    pref_type: Mapped[str] = mapped_column(String(32))  # search/style/response/...

    # 偏好内容
    key: Mapped[str] = mapped_column(String(64))  # preference key
    value: Mapped[str] = mapped_column(Text)     # JSON encoded value

    # 置信度
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(16))  # explicit/implicit/inferred

    updated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("user_id", "pref_type", "key"),
    )


class UserMemory(Base):
    """用户长期记忆"""
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(32), unique=True)

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 记忆内容
    content: Mapped[str] = mapped_column(Text)

    # 类型
    memory_type: Mapped[str] = mapped_column(String(32))  # fact/preference/event/...

    # 向量（用于语义检索）
    embedding: Mapped[Optional[object]] = mapped_column(Vector(1536))

    # 元数据
    source: Mapped[str] = mapped_column(String(32))  # conversation/document/manual
    importance: Mapped[int] = mapped_column(Integer, default=5)  # 1-10

    # 有效期（可选）
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_memory_user_type", "user_id", "memory_type"),
        Index("idx_memory_embedding", "embedding"),
    )
```

## 3. 各场景最佳方案

### 3.1 Chat 对话场景

```
┌─────────────────────────────────────────────────────────────────┐
│                    Chat 对话记忆方案                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  用户输入 ──► L1 短期记忆 ──► LLM 响应 ──► L1 存储               │
│                 │                                              │
│                 │ [会话结束时]                                   │
│                 ▼                                              │
│          L2 中期记忆 ──► 摘要 ──► L3 长期记忆                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**实现**:

```python
class ChatMemoryService:
    """Chat 场景的记忆服务"""

    def __init__(self, db, redis):
        self.db = db
        self.redis = redis

    async def chat_with_memory(
        self,
        user_id: int,
        session_id: str,
        user_input: str,
    ) -> Dict[str, Any]:
        """
        带记忆的对话处理
        """
        # 1. 从 L1 获取短期上下文
        recent_history = await self.session_memory.get_history(
            user_id, session_id, limit=10
        )

        # 2. 从 L3 获取用户偏好
        preferences = await self.get_user_preferences(user_id)

        # 3. 从 L2 检索相关历史
        related_memories = await self.retrieve_memories(
            user_id, user_input, limit=5
        )

        # 4. 构建完整上下文
        context = self.build_context(
            recent_history=recent_history,
            preferences=preferences,
            related_memories=related_memories,
        )

        # 5. LLM 生成响应
        response = await self.llm.chat(context, user_input)

        # 6. 存储到 L1
        await self.session_memory.add_message(
            user_id, session_id, "user", user_input
        )
        await self.session_memory.add_message(
            user_id, session_id, "assistant", response
        )

        # 7. 更新 L2
        await self.save_message(user_id, session_id, user_input, response)

        return {"response": response}

    async def end_session(self, user_id: int, session_id: str):
        """会话结束，生成摘要并清理"""
        # 1. 获取完整对话
        messages = await self.get_session_messages(session_id)

        # 2. LLM 生成摘要
        summary = await self.generate_summary(messages)

        # 3. 更新会话记录
        await self.update_session_summary(session_id, summary)

        # 4. 提取关键信息到 L3
        await self.extract_memories(user_id, messages, summary)

        # 5. 从 L1 清除（可选，保留一段时间）
        # await self.session_memory.delete(user_id, session_id)
```

### 3.2 Agent 工作流场景

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent 工作流记忆方案                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  工作流执行                                                      │
│  ├─ 步骤状态 ──► AgentTasks (已持久化) ✅                        │
│  ├─ 中间结果 ──► task_intermediate_results (新建)               │
│  └─ 决策历史 ──► agent_decision_log (新建)                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**实现**:

```python
class AgentMemory:
    """Agent 工作流的记忆管理"""

    # 中间结果存储
    async def save_intermediate_result(
        self,
        task_id: str,
        step_name: str,
        result: dict,
    ):
        """保存步骤中间结果"""
        key = f"agent:intermediate:{task_id}:{step_name}"
        await self.redis.setex(
            key,
            86400 * 7,  # 7 天过期
            json.dumps(result)
        )

    async def get_intermediate_result(
        self,
        task_id: str,
        step_name: str,
    ) -> Optional[dict]:
        """获取中间结果"""
        key = f"agent:intermediate:{task_id}:{step_name}"
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    # 决策日志
    async def log_decision(
        self,
        task_id: str,
        agent_type: str,
        decision: str,
        context: dict,
        reasoning: str,
    ):
        """记录 Agent 决策"""
        # 存储到数据库
        log = AgentDecisionLog(
            log_id=str(uuid.uuid4())[:32],
            task_id=task_id,
            agent_type=agent_type,
            decision=decision,
            context=context,
            reasoning=reasoning,
        )
        self.db.add(log)
        await self.db.commit()

    # 可回溯的上下文
    async def build_task_context(
        self,
        task_id: str,
    ) -> dict:
        """构建可回溯的任务上下文"""
        # 获取任务
        task = await self.get_task(task_id)

        # 获取所有中间结果
        intermediate = {}
        for step in task.steps:
            result = await self.get_intermediate_result(task_id, step)
            if result:
                intermediate[step] = result

        # 获取决策历史
        logs = await self.get_decision_logs(task_id)

        return {
            "task": task.to_dict(),
            "intermediate_results": intermediate,
            "decision_history": logs,
        }
```

### 3.3 知识管理场景

```
┌─────────────────────────────────────────────────────────────────┐
│                    知识管理记忆方案                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  RAG 检索                                                       │
│  ├─ 向量检索 ──► pgvector (优化: HNSW 索引)                     │
│  ├─ 图谱检索 ──► Neo4j (已有)                                   │
│  └─ 混合检索 ──► RRF 融合 (已有)                                │
│                                                                  │
│  知识更新                                                       │
│  ├─ 增量更新 ──► 只更新变化的 chunk                             │
│  └─ 版本管理 ──► DocVersions (已有)                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**实现**:

```python
class KnowledgeMemory:
    """知识管理服务"""

    async def vector_search_with_filter(
        self,
        query_embedding: list,
        space_id: str,
        top_k: int = 10,
        min_similarity: float = 0.7,
    ):
        """
        优化的向量检索

        1. 使用 HNSW 索引加速检索
        2. 空间过滤在检索时应用（而非后过滤）
        """
        # 使用 pgvector 的 HNSW 索引
        query = text("""
            SELECT
                dce.chunk_id,
                d.content,
                1 - (dce.embedding <=> :query_embedding) AS similarity
            FROM doc_chunk_embeddings dce
            JOIN doc_chunks dc ON dc.id = dce.chunk_id
            JOIN files f ON f.id = dc.file_id
            WHERE f.space_id = :space_id
            ORDER BY dce.embedding <=> :query_embedding
            LIMIT :top_k
        """)

        result = await self.db.execute(query, {
            "query_embedding": query_embedding,
            "space_id": space_id,
            "top_k": top_k * 3,  # 多取一些用于后过滤
        })

        # 后过滤相似度
        filtered = [
            row for row in result
            if row.similarity >= min_similarity
        ][:top_k]

        return filtered

    async def update_knowledge_chunk(
        self,
        chunk_id: int,
        new_content: str,
    ):
        """
        增量更新知识块
        """
        # 1. 更新内容
        chunk = await self.get_chunk(chunk_id)
        old_content = chunk.content
        chunk.content = new_content
        chunk.updated_at = datetime.now(timezone.utc)

        # 2. 重新生成嵌入
        new_embedding = await self.embedding_service.embed(new_content)
        chunk.embedding = new_embedding

        # 3. 记录变更（用于追踪）
        change = KnowledgeChangeLog(
            chunk_id=chunk_id,
            change_type="update",
            old_content=old_content[:500],  # 保留摘要
            new_content=new_content[:500],
            reason="user_correction",
        )
        self.db.add(change)

        await self.db.commit()
```

### 3.4 Trade 交易场景 (已有方案扩展)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Trade 交易记忆方案 (已实现)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  交易上下文                                               │
│  ├─ 交易历史 ──► TradeTransactionLog ✅                   │
│  ├─ 定价策略 ──► TradeListings ✅                         │
│  └─ 决策建议 ──► analysis 字段 ✅                                │
│                                                                  │
│  扩展：智能让步策略学习                                          │
│  └─ 记录每次交易的成功/失败模式                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 4. 统一记忆服务接口

```python
class UnifiedMemoryService:
    """
    统一记忆服务接口

    提供跨场景的统一记忆管理 API
    """

    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

        # 各层级服务
        self.session_memory = SessionMemory(redis)
        self.episodic_memory = EpisodicMemory(db)
        self.longterm_memory = LongTermMemory(db)
        self.hierarchical = HierarchicalContextManager(db)

    # ==================== 存储接口 ====================

    async def store(
        self,
        layer: str,  # "L1", "L2", "L3"
        user_id: int,
        content: Any,
        **kwargs,
    ):
        """统一的存储接口"""
        if layer == "L1":
            return await self.session_memory.add_message(**kwargs)
        elif layer == "L2":
            return await self.episodic_memory.save(**kwargs)
        elif layer == "L3":
            return await self.longterm_memory.save(user_id, content, **kwargs)

    # ==================== 检索接口 ====================

    async def retrieve(
        self,
        layer: str,
        user_id: int,
        query: str,
        **kwargs,
    ):
        """统一的检索接口"""
        if layer == "L1":
            return await self.session_memory.get_history(**kwargs)
        elif layer == "L2":
            return await self.episodic_memory.search(user_id, query, **kwargs)
        elif layer == "L3":
            return await self.longterm_memory.retrieve(user_id, query, **kwargs)

    # ==================== 上下文构建 ====================

    async def build_context(
        self,
        user_id: int,
        session_id: Optional[str] = None,
        layers: List[str] = ["L1", "L3"],
        max_history: int = 10,
    ) -> dict:
        """
        构建分层上下文

        返回各层级的相关记忆，用于 LLM 决策
        """
        context = {"layers": {}}

        if "L1" in layers and session_id:
            context["layers"]["L1"] = {
                "recent_history": await self.session_memory.get_history(
                    user_id, session_id, limit=max_history
                ),
            }

        if "L2" in layers:
            context["layers"]["L2"] = {
                "session_summary": await self.episodic_memory.get_recent_sessions(
                    user_id, limit=5
                ),
            }

        if "L3" in layers:
            context["layers"]["L3"] = {
                "preferences": await self.longterm_memory.get_preferences(user_id),
                "relevant_memories": await self.longterm_memory.get_relevant(
                    user_id, session_id, limit=5
                ),
            }

        return context
```

## 5. 数据库迁移

需要创建的新表：

```sql
-- 1. 会话记录表
CREATE TABLE conversation_sessions (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(32) UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    title VARCHAR(255),
    status VARCHAR(16) DEFAULT 'active',
    space_id VARCHAR(32),
    message_count INT DEFAULT 0,
    summary TEXT,
    summary_tokens INT,
    created_at TIMESTAMP DEFAULT now(),
    last_message_at TIMESTAMP DEFAULT now(),
    ended_at TIMESTAMP
);

-- 2. 对话消息表
CREATE TABLE conversation_messages (
    id BIGSERIAL PRIMARY KEY,
    message_id VARCHAR(32) UNIQUE NOT NULL,
    session_id VARCHAR(32) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    agent_type VARCHAR(32),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_msg_session_time ON conversation_messages(session_id, created_at);

-- 3. 用户偏好表
CREATE TABLE user_preferences (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    pref_type VARCHAR(32) NOT NULL,
    key VARCHAR(64) NOT NULL,
    value TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    source VARCHAR(16) DEFAULT 'implicit',
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(user_id, pref_type, key)
);

-- 4. 用户长期记忆表
CREATE TABLE user_memories (
    id BIGSERIAL PRIMARY KEY,
    memory_id VARCHAR(32) UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    memory_type VARCHAR(32) NOT NULL,
    source VARCHAR(32) DEFAULT 'conversation',
    importance INT DEFAULT 5,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_memory_user_type ON user_memories(user_id, memory_type);

-- 5. Agent 决策日志表
CREATE TABLE agent_decision_logs (
    id BIGSERIAL PRIMARY KEY,
    log_id VARCHAR(32) UNIQUE NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    agent_type VARCHAR(32) NOT NULL,
    decision VARCHAR(64) NOT NULL,
    context JSONB,
    reasoning TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_decision_task ON agent_decision_logs(task_id);
```

## 6. 实施优先级

| 优先级 | 功能 | 复杂度 | 收益 |
|--------|------|--------|------|
| **P0** | Chat 对话历史持久化 | 中 | 高 |
| **P0** | L1 短期记忆 (Redis) | 低 | 高 |
| **P1** | L2 中期记忆 (会话摘要) | 中 | 中 |
| **P1** | 用户偏好学习 | 低 | 中 |
| **P2** | Agent 决策日志 | 低 | 中 |
| **P2** | pgvector HNSW 索引优化 | 中 | 中 |
| **P3** | L3 长期记忆自动提取 | 高 | 低 |

## 8. 实现状态 (Implementation Status)

### 8.1 已完成的组件

| 组件 | 状态 | 文件路径 |
|------|------|----------|
| **数据库模型** | ✅ 已完成 | `app/db/models.py` |
| `ConversationSessions` | ✅ | L2 会话表 |
| `ConversationMessages` | ✅ | L2 消息表（含向量） |
| `UserPreferences` | ✅ | L3 用户偏好 |
| `UserMemories` | ✅ | L3 长期记忆 |
| `AgentDecisionLogs` | ✅ | Agent 决策日志 |
| `AgentIntermediateResults` | ✅ | 工作流检查点 |
| **L1 短期记忆服务** | ✅ 已完成 | `app/services/memory/session_memory.py` |
| Redis 连接管理 | ✅ | SessionMemory 类 |
| 消息存储/检索 | ✅ | add_message / get_recent_messages |
| 会话状态管理 | ✅ | set_session_state / get_session_state |
| 工作记忆 | ✅ | set_working_memory / get_working_memory |
| TTL 自动过期 | ✅ | Redis 原生支持 |
| **L2 中期记忆服务** | ✅ 已完成 | `app/services/memory/episodic_memory.py` |
| 会话管理 | ✅ | create_session / get_session |
| 消息持久化 | ✅ | add_message（自动生成嵌入） |
| 语义检索 | ✅ | search_similar（pgvector 余弦相似度） |
| 会话摘要 | ✅ | update_session_summary |
| **L3 长期记忆服务** | ✅ 已完成 | `app/services/memory/longterm_memory.py` |
| 用户偏好 | ✅ | set_preference / get_preference |
| 长期记忆 | ✅ | add_memory / get_memories |
| 记忆检索 | ✅ | search_memories（语义搜索） |
| 决策日志 | ✅ | log_decision / get_decision_history |
| **统一记忆服务** | ✅ 已完成 | `app/services/memory/unified_memory.py` |
| 分层存储 | ✅ | remember（L1+L2） |
| 分层检索 | ✅ | recall（L1+L2+L3） |
| 上下文组装 | ✅ | _assemble_messages |
| 记忆增强 | ✅ | MemoryAugmentedContext |
| **工作流检查点** | ✅ 已完成 | `app/services/memory/checkpoint_service.py` |
| 检查点保存 | ✅ | save_step |
| 状态恢复 | ✅ | restore_workflow |
| 可恢复工作流 | ✅ | ResumableWorkflow 基类 |
| **API 端点** | ✅ 已完成 | `app/api/v1/endpoints/memory.py` |
| 会话管理 API | ✅ | POST/GET/DELETE /sessions |
| 消息管理 API | ✅ | GET/POST /sessions/{id}/messages |
| 语义搜索 API | ✅ | POST /search |
| 用户偏好 API | ✅ | GET/POST/DELETE /preferences |
| 长期记忆 API | ✅ | GET/POST/DELETE /memories |
| 记忆统计 API | ✅ | GET /stats |
| **路由注册** | ✅ 已完成 | `app/api/v1/router.py` |
| Memory Router | ✅ | prefix=/memory |

### 8.2 文件清单

```
app/
├── db/
│   └── models.py                              # 6 个新记忆相关模型
├── services/memory/
│   ├── __init__.py                            # 模块导出
│   ├── session_memory.py                      # L1 短期记忆 (Redis)
│   ├── episodic_memory.py                     # L2 中期记忆 (PostgreSQL)
│   ├── longterm_memory.py                     # L3 长期记忆
│   ├── unified_memory.py                      # 统一记忆接口
│   └── checkpoint_service.py                  # 工作流检查点
├── api/v1/endpoints/
│   └── memory.py                              # 记忆管理 API
└── core/
    └── MEMORY_ARCHITECTURE.md                 # 架构文档
```

### 8.3 使用方法

#### 基础用法 - 统一记忆服务

```python
from app.services.memory import UnifiedMemoryService

async def chat_handler(db: AsyncSession, user_id: int, session_id: str, message: str):
    # 创建记忆服务
    memory = UnifiedMemoryService(db)

    # 记录用户消息
    await memory.remember(session_id, user_id, "user", message)

    # 检索相关上下文
    context = await memory.recall(session_id, user_id, query=message)

    # 使用上下文调用 LLM
    response = await llm.chat(context["messages"])

    # 记录助手回复
    await memory.remember(session_id, user_id, "assistant", response)

    return response
```

#### 单独使用 L1 短期记忆

```python
from app.services.memory import get_session_memory

session_memory = get_session_memory()

# 添加消息
await session_memory.add_message(session_id, "user", "你好")

# 获取最近历史
messages = await session_memory.get_recent_messages(session_id, limit=10)

# 设置工作记忆（临时上下文）
await session_memory.set_working_memory(session_id, "current_topic", "Python")
```

#### 单独使用 L2 中期记忆

```python
from app.services.memory import EpisodicMemory

episodic = EpisodicMemory(db)

# 创建会话
session = await episodic.create_session(user_id, title="技术支持")

# 添加消息（自动向量化）
msg = await episodic.add_message(session.session_id, "user", "问题描述...")

# 语义搜索历史
similar = await episodic.search_similar(
    query="Python 错误",
    user_id=user_id,
    limit=5,
)
```

#### 工作流检查点

```python
from app.services.memory import WorkflowCheckpointService, ResumableWorkflow

# 创建检查点服务
checkpoint_service = WorkflowCheckpointService(db)

# 创建可恢复工作流
workflow = ResumableWorkflow(task_id, checkpoint_service)
await workflow.initialize()

# 执行步骤（自动保存检查点）
result = await workflow.run_step(
    "data_processing",
    process_data_func,
    raw_data
)

# 如果工作流中断，下次初始化时会自动恢复状态
```

### 8.4 API 端点列表

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/v1/memory/sessions` | 创建会话 |
| GET | `/api/v1/memory/sessions` | 列表会话 |
| GET | `/api/v1/memory/sessions/{id}` | 获取会话详情 |
| POST | `/api/v1/memory/sessions/{id}/archive` | 归档会话 |
| DELETE | `/api/v1/memory/sessions/{id}` | 删除会话 |
| GET | `/api/v1/memory/sessions/{id}/messages` | 获取消息列表 |
| POST | `/api/v1/memory/sessions/{id}/messages` | 添加消息 |
| POST | `/api/v1/memory/search` | 语义搜索 |
| GET | `/api/v1/memory/preferences` | 获取用户偏好 |
| POST | `/api/v1/memory/preferences` | 设置用户偏好 |
| DELETE | `/api/v1/memory/preferences/{key}` | 删除偏好 |
| GET | `/api/v1/memory/memories` | 获取长期记忆 |
| POST | `/api/v1/memory/memories` | 添加长期记忆 |
| DELETE | `/api/v1/memory/memories/{id}` | 删除记忆 |
| GET | `/api/v1/memory/stats` | 记忆统计 |
| GET | `/api/v1/memory/context/{session_id}` | 获取完整上下文 |

### 8.5 下一步建议

1. **数据库迁移**: 运行 Alembic 迁移创建新表
2. **Redis 配置**: 确保 `REDIS_URL` 环境变量已配置
3. **集成到 Agent**: 在 MainAgent 和 SubAgents 中使用 UnifiedMemoryService
4. **前端对接**: 调用新的 `/memory` API 端点
5. **定期任务**: 添加清理过期记忆和生成摘要的定时任务

---

*文档版本: 2.0 | 最后更新: 2026-03-29 | 状态: 核心实现完成*
