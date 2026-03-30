# 聊天系统统一改造完成报告

## 概述

已将两套聊天能力（`/chat` 和 `/agent/chat`）收敛成一套，以 `/agent/chat` 作为唯一入口。

---

## 主要变更

### 1. 统一状态定义 (`app/agents/state.py`)

#### MainAgentState 更新
```python
# 新增字段
context: Optional[Dict[str, Any]]  # 来自请求的额外上下文
```

#### QAState 扩展
```python
# 输入字段
space_id: Optional[str]           # Space public ID for permission filtering
user_id: Optional[int]            # User ID for permission checking
top_k: int                        # Number of results to retrieve
context_items: Optional[List]     # Pre-fetched context items

# 输出字段
sources: List[Dict[str, Any]]     # Rich source info (was List[str])
retrieval_debug: Optional[Dict]   # Debug info for retrieval process
error: Optional[str]              # Error message
```

### 2. 统一请求模型 (`app/schemas/schemas.py`)

#### AgentChatRequest (统一模型)
```python
message: str                      # 用户消息 (替代 query)
space_id: str                     # 工作空间ID
context: Optional[Dict]           # 额外上下文
stream: bool = False              # 新增：是否使用流式响应
top_k: int = 5                    # 新增：检索结果数量

# 向后兼容
@property
def query(self) -> str:           # 返回 message
```

#### ChatRequest (标记为弃用)
```python
# 添加弃用标记和文档
"""[DEPRECATED] 请使用 AgentChatRequest"""
```

#### AgentChatResponse (增强返回)
```python
success: bool                     # 是否成功
intent: Optional[str]             # 识别到的意图
agent_type: str                   # 处理的Agent类型
result: Dict[str, Any]            # 完整结果
answer: Optional[str]             # 直接回答（QA类型）
sources: Optional[List[Dict]]     # 来源引用
error: Optional[str]              # 错误信息
retrieval_debug: Optional[Dict]   # 调试信息
```

### 3. 增强 QAAgent (`app/agents/subagents/qa_agent.py`)

#### 新增统一接口

**非流式调用：**
```python
async def run(
    self,
    query: str,
    space_public_id: str,
    user: Users,
    top_k: int = 5,
    context_items: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {
            "success": bool,
            "agent_type": "qa",
            "answer": str,
            "sources": List[Dict],
            "retrieval_debug": Dict,
            "error": Optional[str]
        }
    """
```

**流式调用：**
```python
async def stream(
    self,
    query: str,
    space_public_id: str,
    user: Users,
    top_k: int = 5,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Yields events:
        {"type": "status", "content": "retrieving"}
        {"type": "sources", "content": [...]}
        {"type": "token", "content": "..."}      # 新增
        {"type": "result", "content": {...}}
        {"type": "error", "content": "..."}
    """
```

#### 关键改进
- **空间权限校验**: 使用 `self._require_space()` 确保用户有权限
- **按 space_id 过滤**: `_retrieve_vector_context()` 现在只搜索指定空间
- **混合检索**: Vector + Neo4j Graph
- **流式支持**: 完整的 token-level 流式输出

### 4. 完善 MainAgent (`app/agents/main_agent.py`)

#### SubAgents.invoke_subagent() 更新
- QA agent 调用改为使用 `agent.run()` 接口
- 支持用户权限检查
- 统一的返回格式

#### chat() 方法增强
```python
async def chat(...) -> Dict[str, Any]:
    """
    Returns unified response:
        {
            "success": bool,
            "intent": str,
            "agent_type": str,
            "result": Dict,
            "answer": str,           # QA-specific
            "sources": List[Dict],   # QA-specific
            "error": Optional[str]
        }
    """
```

#### stream_chat() 重写
```python
async def stream_chat(...) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Unified SSE protocol:
        intent        -> 意图识别结果
        agent_type    -> 选中的 agent 类型
        status        -> 状态更新 (detecting_intent/running/completed)
        token         -> 流式 token (QA 类型)
        result        -> 最终结果
        error         -> 错误信息
    """
```

#### 新增 _stream_qa_agent()
专门处理 QA agent 的流式输出，将 QAAgent.stream() 的事件转发为统一的 SSE 事件。

### 5. 统一 API 端点 (`app/api/v1/endpoints/agent.py`)

#### POST /agent/chat
- 支持新的 `top_k` 参数
- 返回完整的 `AgentChatResponse`
- 包含 `success`, `intent`, `agent_type`, `answer`, `sources`

#### POST /agent/chat/stream
- 支持新的 `top_k` 参数
- 使用统一的 SSE 协议
- 对 QA 类型输出 `token` 事件

### 6. 旧接口兼容层 (`app/api/v1/endpoints/chat.py`)

所有旧接口（`/chat`, `/chat/complete`, `/chat/stream`）已重写为转发到 MainAgent：

```python
# 示例：旧 /chat 转发
@router.post("/chat")
async def rag_chat(req: ChatRequest, ...):
    """[DEPRECATED] 转发到 MainAgent"""
    result = await agent.chat(
        message=req.query,
        space_id=req.space_id,
        user_id=current_user.id,
        top_k=req.top_k,
    )
    return {
        "answer": result.get("answer"),
        "context": result.get("sources"),
        "_deprecated": True,
        "_new_endpoint": "/agent/chat",
    }
```

### 7. 路由配置 (`app/api/v1/router.py`)

添加移除计划注释：
```python
# TODO: Phase 3 - Remove chat_router after all clients migrate
# Phase 1 (Current): chat_router forwards to MainAgent (compatibility layer)
# Phase 2 (2026-Q1): Frontend switches to /agent/chat
# Phase 3 (2026-Q2): Remove chat_router
```

### 8. 服务层弃用标记 (`app/services/chat_service.py`)

添加 Python DeprecationWarning 和文档字符串：
```python
warnings.warn(
    "RagChatService is deprecated. Use QAAgent instead.",
    DeprecationWarning,
    stacklevel=2
)
```

---

## 迁移指南

### 前端迁移 (Phase 2)

#### 请求模型变更
```javascript
// 旧请求
const oldRequest = {
    space_id: "xxx",
    query: "What is...",
    top_k: 5
};

// 新请求
const newRequest = {
    space_id: "xxx",
    message: "What is...",    // 替代 query
    top_k: 5,
    stream: false,            // 可选
    context: {}               // 可选
};
```

#### 响应模型变更
```javascript
// 旧响应
const oldResponse = {
    answer: "...",
    context: [...]
};

// 新响应
const newResponse = {
    success: true,
    intent: "qa",
    agent_type: "qa",
    result: {...},
    answer: "...",
    sources: [...],
    error: null
};
```

#### SSE 流式消费变更
```javascript
// 旧 SSE 消费 (仅 token)
eventSource.onmessage = (e) => {
    if (e.data === "[DONE]") return;
    appendText(e.data);  // 直接是 token
};

// 新 SSE 消费 (统一协议)
eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    switch (event.type) {
        case "intent":
            console.log("Intent:", event.data);
            break;
        case "token":
            appendText(event.data);  // QA token
            break;
        case "result":
            handleResult(event.data);
            break;
        case "error":
            handleError(event.data);
            break;
    }
};
```

### 后端调用变更

```python
# 旧调用
from app.services.chat_service import RagChatService
service = RagChatService(db)
answer, context = await service.generate_answer(
    space_public_id=space_id,
    query=query,
    user=user,
)

# 新调用
from app.agents.subagents.qa_agent import QAAgent
agent = QAAgent(db)
result = await agent.run(
    query=query,
    space_public_id=space_id,
    user=user,
    top_k=5,
)
answer = result["answer"]
sources = result["sources"]
```

---

## API 端点对照表

| 旧端点 | 新端点 | 状态 |
|--------|--------|------|
| POST /chat | POST /agent/chat | 旧端点已弃用，转发到新端点 |
| POST /chat/complete | POST /agent/chat | 旧端点已弃用 |
| POST /chat/stream | POST /agent/chat/stream | 旧端点已弃用，转发到新端点 |
| - | POST /agent/chat | **推荐** 统一聊天入口 |
| - | POST /agent/chat/stream | **推荐** 流式聊天入口 |

---

## 测试验收标准

### P0 核心功能

- [ ] 普通知识问答路由到 QA Agent
  ```bash
  curl -X POST /agent/chat \
    -d '{"message":"What is AI?","space_id":"xxx"}'
  # 应返回 intent="qa", agent_type="qa"
  ```

- [ ] 文件检索路由到 FileQuery
  ```bash
  curl -X POST /agent/chat \
    -d '{"message":"查找文件 report.pdf","space_id":"xxx"}'
  # 应返回 intent="file_query"
  ```

- [ ] 非流式返回包含完整字段
  ```json
  {
    "success": true,
    "intent": "qa",
    "agent_type": "qa",
    "result": {...},
    "answer": "...",
    "sources": [...]
  }
  ```

- [ ] QA 严格按 space_id 过滤数据
  - 用户 A 访问 Space 1 的数据
  - 同一查询在 Space 2 应返回不同/无结果

### P1 流式和兼容

- [ ] SSE 稳定返回所有事件类型
  ```
  intent -> status -> token -> result -> status
  ```

- [ ] 旧 /chat 兼容期仍能工作
  - 返回包含 `_deprecated` 标记
  - 数据正确转发到 MainAgent

---

## 时间线

| 阶段 | 时间 | 行动 |
|------|------|------|
| Phase 1 | 2026-Q1 (当前) | 保留旧接口，转发到 MainAgent |
| Phase 2 | 2026-Q1-Q2 | 前端迁移到 /agent/chat |
| Phase 3 | 2026-Q2 | 删除 /chat 端点，清理代码 |

---

## 文件变更清单

### 修改文件
1. `app/agents/state.py` - 更新状态定义
2. `app/schemas/schemas.py` - 统一请求/响应模型
3. `app/agents/subagents/qa_agent.py` - 重写为统一接口
4. `app/agents/main_agent.py` - 完善返回结构和流式协议
5. `app/api/v1/endpoints/agent.py` - 支持新参数
6. `app/api/v1/endpoints/chat.py` - 添加兼容层
7. `app/api/v1/router.py` - 添加移除计划注释
8. `app/services/chat_service.py` - 添加弃用标记

### 删除计划 (Phase 3)
- `app/api/v1/endpoints/chat.py` - 移除旧接口
- `app/services/chat_service.py` - 移除旧服务

---

## 注意事项

1. **RAG 不再独立存在**: QA 功能完全整合到 QAAgent，通过 MainAgent 路由
2. **一套 SSE 协议**: 所有流式响应使用统一的事件类型 (intent/status/token/result/error)
3. **显式权限检查**: QAAgent.run() 需要传入 user 对象进行空间权限校验
4. **上下文支持**: MainAgent 现在正确消费 request.context 并写入 state
