# Agent 编排架构设计文档

## 1. 概述

### 1.1 设计目标

将独立的 SubAgent 组合成完整的业务流程，实现：
- **自动化**: 用户只需描述需求，系统自动选择和执行合适的Agent流程
- **编排**: 支持Agent间的顺序执行、条件分支、并行处理
- **状态管理**: 工作流状态持久化，支持暂停/恢复/中断
- **用户体验**: 实时进度通知、错误自动恢复、用户干预点

### 1.2 核心组件

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            用户交互层                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │  Web UI        │    │  API Client     │    │  Chat Interface │        │
│  │  (前端界面)     │    │  (API调用)       │    │  (聊天输入)      │        │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘        │
│           │                          │                          │               │
│           └──────────────────────────┼──────────────────────────┘               │
│                                      ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │                    SmartIntentRouter (智能意图路由)                    │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │  用户输入: "帮我找一些关于机器学习的资产并购买"                   │ │   │
│  │  │                           ↓                                      │ │   │
│  │  │  意图分析: { intent: "asset_search_buy", confidence: 0.92 }    │ │   │
│  │  │                           ↓                                      │ │   │
│  │  │  工作流选择: asset_search_buy (搜索→分析→购买→结算)             │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                      │                                          │
└──────────────────────────────────────┼──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WorkflowOrchestrator (工作流编排器)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │ WorkflowEngine │    │  AgentRegistry   │    │ WorkflowEngine  │        │
│  │ (执行引擎)      │    │ (Agent注册表)    │    │ (持久化)        │        │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘        │
│           │                        │                        │                  │
│           ▼                        ▼                        ▼                  │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │                    WorkflowExecution (执行状态)                         │   │
│  │  execution_id: "exec_xxx"                                            │   │
│  │  status: "running"                                                   │   │
│  │  current_step: 2                                                      │   │
│  │  step_results: { step1: {...}, step2: {...} }                        │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SubAgents (子Agent)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐  │
│  │    QAAgent  │   │DataProcess  │   │   Review    │   │ AssetOrg    │  │
│  │   (问答)    │   │   Agent     │   │   Agent    │   │   Agent     │  │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘  │
│                                                                             │
│  ┌─────────────┐   ┌─────────────┐                                       │
│  │ FileQuery  │   │   Trade     │                                       │
│  │   Agent    │   │   Agent     │                                       │
│  └─────────────┘   └─────────────┘                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. 核心概念

### 2.1 工作流定义 (WorkflowDefinition)

```python
@dataclass
class WorkflowDefinition:
    workflow_id: str           # 工作流唯一标识
    workflow_type: WorkflowType  # 工作流类型
    name: str                  # 名称
    description: str           # 描述
    steps: List[WorkflowStep]  # 执行步骤列表
    on_complete: str            # 完成回调
    on_failure: str            # 失败处理
```

### 2.2 工作流步骤 (WorkflowStep)

```python
@dataclass
class WorkflowStep:
    step_id: str               # 步骤ID
    agent_type: AgentType       # 使用的Agent类型
    input_mapping: Dict[str, str]  # 输入参数映射
    output_key: str            # 输出存储键
    condition: Optional[str]   # 执行条件
    retry_on_fail: bool       # 失败重试
    max_retries: int          # 最大重试次数
    notify_on_complete: bool   # 完成通知
```

### 2.3 工作流执行 (WorkflowExecution)

```python
@dataclass
class WorkflowExecution:
    execution_id: str          # 执行ID
    workflow_id: str           # 工作流ID
    user_id: int               # 用户ID
    space_id: str              # 空间ID
    status: str                # pending/running/completed/failed/paused
    current_step: int          # 当前步骤
    step_results: Dict         # 步骤结果
    error: Optional[str]       # 错误信息
    context: Dict              # 上下文
```

## 3. 预定义工作流

### 3.1 文档完整生命周期 (document_lifecycle)

```
用户上传文档
     │
     ▼
┌─────────────┐
│ DataProcess │  1. 下载/读取文件
│   Agent     │  2. 文本提取
└──────┬──────┘  3. Markdown转换
       │ 4. 分块
       │ 5. 向量化
       ▼
┌─────────────┐
│   Review    │  1. 质量检查
│   Agent     │  2. 合规检查
└──────┬──────┘  3. 完整性检查
       │
       │ 通过?
       ├──── Yes ────┐
       │              ▼
       │    ┌─────────────┐
       │    │  AssetOrg    │  1. 特征提取
       │    │   Agent     │  2. 聚类分析
       └────┤ 3. 生成报告  │
            └──────┬──────┘
                   │
                   │ 优质资产?
                   ├──── Yes ────┐
                   │              ▼
                   │    ┌─────────────┐
                   │    │   Trade     │  1. 创建上架
                   │    │   Agent     │  2. 发布到市场
                   └────┤ 3. 等待交易  │
                        └─────────────┘
                               │
                               │ 失败
                               ▼
                          返回修改
```

### 3.2 搜索并购买 (asset_search_buy)

```
用户搜索需求
     │
     ▼
┌─────────────┐
│    QA      │  1. 向量检索
│   Agent    │  2. 图谱检索
└──────┬──────┘  3. 混合排序
       │
       ▼
┌─────────────┐
│  AssetOrg   │  1. 关联分析
│   Agent     │  2. 推荐排名
└──────┬──────┘  3. 价格建议
       │
       ▼
┌─────────────┐
│   Trade     │  1. 发起交易
│   Agent     │  2. 多轮议价
└──────┬──────┘  3. 达成一致
       │
       │ 成交
       ▼
┌─────────────┐
│ Settlement  │  1. 支付结算
│   Agent     │  2. 资产转移
└──────┬──────┘  3. 授予权限
       │
       ▼
   用户获得资产访问权
```

### 3.3 批量处理 (document_batch_process)

```
批量上传文件
     │
     ▼
┌─────────────┐
│ DataProcess │     ┌─────┐ ┌─────┐ ┌─────┐
│   Agent     │ ──► │Doc 1│ │Doc 2│ │Doc N│
└──────┬──────┘     └──┬──┘ └──┬──┘ └──┬──┘
       │                │       │       │
       ▼                ▼       ▼       ▼
┌─────────────┐      并行处理 (Celery Workers)
│   Review    │
│   Agent     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  AssetOrg   │     ┌────────────────┐
│   Agent     │ ──► │ Cluster Report │
└─────────────┘     └────────────────┘
```

## 4. Agent依赖关系

### 4.1 依赖图

```
                    MainAgent
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
   QAAgent       DataProcess       FileQuery
                        │               │
                        │               │
                        ▼               │
                      Review            │
                        │               │
          ┌─────────────┼───────────────┤
          │             │               │
          ▼             │               ▼
    AssetOrganize ◄─────┘           (End)
          │
          │ (聚类完成)
          ▼
       Trade
          │
          │ (交易完成)
          ▼
      Settlement
```

### 4.2 数据流向

| 上游Agent | 下游Agent | 传递数据 |
|-----------|-----------|----------|
| DataProcess | Review | doc_id, markdown_text, chunks |
| Review | AssetOrganize | doc_id, review_result (approved/rejected) |
| AssetOrganize | Trade | asset_ids, cluster_info, price_suggestion |
| QAAgent | AssetOrganize | related_asset_ids |
| Trade | Settlement | order_id, final_price |

## 5. 智能意图路由

### 5.1 路由决策流程

```
用户输入
    │
    ▼
┌─────────────────┐
│  关键词提取      │
│ "上传", "处理"  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  意图匹配        │
│  confidence: 0.9│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  工作流选择      │
│                 │
│ ┌─────────────┐│
│ │ 有附件?      ││  Yes ──► document_lifecycle
│ └─────────────┘│
│       │ No      │
│       ▼         │
│ ┌─────────────┐│
│ │ 购买意图?   ││  Yes ──► asset_search_buy
│ └─────────────┘│
│       │ No      │
│       ▼         │
│ ┌─────────────┐│
│ │ 搜索意图?   ││  Yes ──► knowledge_query
│ └─────────────┘│
│       │ No      │
│       ▼         │
│    knowledge_query (默认)
│
└─────────────────┘
```

### 5.2 意图识别示例

| 用户输入 | 识别意图 | 置信度 | 工作流 |
|----------|---------|--------|--------|
| "上传我的PDF文档" | document_lifecycle | 0.92 | 文档完整生命周期 |
| "帮我找机器学习相关的资产" | asset_search_buy | 0.88 | 搜索并购买 |
| "什么是向量数据库" | knowledge_query | 0.85 | 知识问答 |
| "批量导入这10个文件" | document_batch_process | 0.94 | 批量文档处理 |
| "购买这个资产" | asset_purchase | 0.90 | 资产购买 |

## 6. API 设计

### 6.1 工作流管理

```http
# 启动工作流
POST /api/v1/workflows/start
{
    "workflow_type": "document_lifecycle",
    "space_id": "space_xxx",
    "initial_input": {
        "source_type": "file",
        "source_path": "/uploads/doc.pdf"
    }
}

# 获取工作流状态
GET /api/v1/workflows/{execution_id}/status

# 暂停工作流
POST /api/v1/workflows/{execution_id}/pause

# 恢复工作流
POST /api/v1/workflows/{execution_id}/resume

# 列出用户工作流
GET /api/v1/workflows/?status_filter=running&limit=20
```

### 6.2 智能处理

```http
# 智能处理入口
POST /api/v1/workflows/smart
{
    "user_input": "帮我找机器学习相关的资产并购买",
    "space_id": "space_xxx",
    "context": {
        "has_attachments": false
    }
}

# 响应
{
    "mode": "workflow",
    "workflow_type": "asset_search_buy",
    "execution_id": "exec_abc123",
    "intent": "asset_search_buy",
    "confidence": 0.88,
    "message": "已启动5步工作流处理"
}
```

### 6.3 流式处理

```http
# SSE流式处理
POST /api/v1/workflows/smart/stream

# SSE事件流
event: status
data: {"content": "analyzing_intent"}

event: intent_detected
data: {"intent": "asset_search_buy", "confidence": 0.88}

event: workflow_started
data: {"execution_id": "exec_abc123", "workflow_type": "asset_search_buy"}

event: workflow_progress
data: {"current_step": 1, "status": "running"}

event: workflow_completed
data: {"result": {...}}
```

## 7. 用户体验优化

### 7.1 实时通知

```
┌─────────────────────────────────────────────────────────────────┐
│                      通知推送机制                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │ WebSocket  │     │   Webhook  │     │   数据库    │       │
│  │  (在线用户) │     │  (外部系统) │     │  (离线用户) │       │
│  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘       │
│         │                   │                   │              │
│         └───────────────────┼───────────────────┘              │
│                             ▼                                   │
│                   ┌─────────────────────┐                        │
│                   │   消息通知服务       │                        │
│                   │ NotificationService │                        │
│                   └──────────┬──────────┘                        │
│                              │                                  │
│         ┌────────────────────┼────────────────────┐           │
│         ▼                    ▼                    ▼            │
│   ┌──────────┐         ┌──────────┐         ┌──────────┐      │
│   │ 工作流   │         │  新消息  │         │ 交易    │      │
│   │ 进度更新 │         │   提醒   │         │ 结果通知 │      │
│   └──────────┘         └──────────┘         └──────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 进度展示

```
┌─────────────────────────────────────────────────────────────────┐
│  工作流: 文档完整生命周期                                    [暂停]│
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─[✓]─[✓]─[○]─[○]──────────────────────────────┐            │
│  │    │    │   │                                   │            │
│  │    │    │   │                                   │            │
│  ▼    ▼    ▼   ▼                                   ▼            │
│  处理 审查 整理 上架                                  │            │
│  ✓     ✓   ▶   ○                                   │            │
│                                                              │
│  当前: AssetOrganize Agent - 正在分析资产聚类                   │
│  进度: 60%                                                    │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ 📊 步骤 1/4: DataProcess 完成                          │    │
│  │    - 提取文本: 1,234 字                                 │    │
│  │    - 生成向量: 12 个 chunks                              │    │
│  │    - 知识图谱: 8 个实体                                  │    │
│  ├────────────────────────────────────────────────────────┤    │
│  │ 📊 步骤 2/4: Review 完成                                │    │
│  │    - 质量评分: 0.85 ✓                                    │    │
│  │    - 合规检查: 通过 ✓                                    │    │
│  ├────────────────────────────────────────────────────────┤    │
│  │ 📊 步骤 3/4: AssetOrganize 进行中...                    │    │
│  │    - 已分析: 8/12 资产                                   │    │
│  │    - 当前聚类: 技术文档 (5个)                             │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                              │
│  [取消工作流]                               [查看详细日志]       │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 错误恢复

```
┌─────────────────────────────────────────────────────────────────┐
│  工作流执行失败                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ⚠️ 步骤 2/4 (Review Agent) 执行失败                             │
│                                                                  │
│  错误原因: 文档内容过短 (123 字 < 最小要求 500 字)              │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  建议操作:                                                  │  │
│  │                                                             │  │
│  │  [1] 编辑文档内容，增加更多详细信息          [推荐]          │  │
│  │  [2] 降低审查标准，允许短文档               [谨慎]          │  │
│  │  [3] 跳过审查，直接整理资产                                 │  │
│  │  [4] 取消工作流                                           │  │
│  │                                                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  [选择操作]                                    [查看完整错误信息] │
└─────────────────────────────────────────────────────────────────┘
```

## 8. 数据库模型

### 8.1 工作流执行记录

```sql
-- AgentTasks 表已支持工作流记录
CREATE TABLE agent_tasks (
    id BIGSERIAL PRIMARY KEY,
    public_id VARCHAR(32) UNIQUE NOT NULL,
    agent_type VARCHAR(32) NOT NULL,  -- 'workflow' 或具体Agent类型
    status VARCHAR(32) NOT NULL,
    intent VARCHAR(32),               -- 工作流类型

    -- 输入输出
    input_data JSONB,
    output_data JSONB,
    subagent_result JSONB,

    -- 用户和空间
    created_by BIGINT NOT NULL,
    space_id BIGINT NOT NULL,

    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    -- 错误跟踪
    error TEXT,
    retry_count INT DEFAULT 0
);

-- 创建索引
CREATE INDEX idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX idx_agent_tasks_created_by ON agent_tasks(created_by);
CREATE INDEX idx_agent_tasks_intent ON agent_tasks(intent);
```

## 9. 部署架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Load Balancer                            │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   FastAPI    │    │   FastAPI    │    │   FastAPI    │
│  Instance 1  │    │  Instance 2  │    │  Instance 3  │
│               │    │               │    │               │
│ WorkflowEngine│    │ WorkflowEngine│    │ WorkflowEngine│
│  (可调度)     │    │  (可调度)     │    │  (可调度)     │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Redis (消息队列 + 缓存)                       │
└─────────────────────────────────────────────────────────────────┘
                             │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Celery Worker │    │ Celery Worker│    │ Celery Worker│
│ (DataProcess) │    │  (Review)   │    │ (AssetOrg)  │
└───────────────┘    └───────────────┘    └───────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL + Neo4j + MinIO                     │
└─────────────────────────────────────────────────────────────────┘
```

## 10. 扩展计划

### 10.1 条件分支支持

```python
# 未来版本支持
WorkflowStep(
    step_id="conditional_step",
    agent_type=AgentType.REVIEW,
    condition="doc_result.word_count > 1000",
    branches={
        "pass": [WorkflowStep(...)],  # 满足条件时执行
        "fail": [WorkflowStep(...)],   # 不满足时执行
    }
)
```

### 10.2 并行执行支持

```python
# 未来版本支持
WorkflowStep(
    step_id="parallel_process",
    parallel=True,
    steps=[
        WorkflowStep(agent_type=AgentType.DATA_PROCESS, ...),
        WorkflowStep(agent_type=AgentType.REVIEW, ...),
    ],
    aggregation="all_success"  # all_success / any_success / custom
)
```

### 10.3 LLM辅助决策

```python
# 未来版本支持
class LLMDecisionNode:
    """使用LLM决定后续流程"""

    async def decide(
        self,
        context: Dict[str, Any],
        available_next_steps: List[WorkflowStep],
    ) -> WorkflowStep:
        """
        基于当前上下文，LLM选择最佳下一步
        """
        prompt = f"""
        当前工作流状态: {context}
        可选的下一个步骤: {available_next_steps}
        请选择最合适的下一步并说明理由。
        """
        return await llm.decide(prompt)
```

## 11. 总结

通过工作流编排器，系统实现了：

1. **自动化**: 用户描述需求，系统自动选择和执行完整流程
2. **编排**: Agent间有序协作，数据流畅传递
3. **可靠性**: 错误重试、状态持久化、用户干预
4. **可观测性**: 实时进度、详细日志、统计报表
5. **可扩展性**: 易于添加新工作流和新Agent

用户只需说"上传我的文档并上架销售"，系统自动完成整个流程。
