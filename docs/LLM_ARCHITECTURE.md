# LLM 功能划分架构设计

## 概述

本项目采用**双LLM架构**，将个人数据相关的任务与系统监管任务分离：

- **个人LLM (Personal LLM)**: 处理用户个人数据相关的工作流程
- **系统LLM (System LLM)**: 负责交易监管、审计、仲裁、安全审查等系统级任务

## 架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户请求层                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         LLM Gateway (路由层)                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    LLMTaskClassifier                            │   │
│  │  - 根据任务描述自动判断使用个人LLM还是系统LLM                      │   │
│  │  - 关键词匹配 + 上下文分析                                         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌─────────────────────────────┐             ┌─────────────────────────────┐
│      个人LLM (Personal)      │             │      系统LLM (System)        │
│                             │             │                             │
│  使用用户自己的API Key       │             │  使用系统平台API Key         │
│  费用计入用户账户            │             │  费用计入平台成本            │
│                             │             │                             │
│  功能边界：                  │             │  功能边界：                  │
│  • RAG问答 (CHAT)           │             │  • 交易协商监管              │
│  • 文件查询 (FILE_QUERY)    │             │  • 定价计算与审查            │
│  • 数据处理 (DATA_PROCESS)  │             │  • Prompt安全检测            │
│  • 资产整理 (ASSET_ORGANIZE)│             │  • 仲裁决策                  │
│  • 知识图谱 (GRAPH)         │             │  • 审计分析                  │
│  • 文档摄取 (INGEST)        │             │  • 异常检测                  │
└─────────────────────────────┘             └─────────────────────────────┘
```

## 核心组件

### 1. LLMGateway

统一入口，负责根据任务类型路由到正确的LLM。

```python
from app.services.llm_gateway import LLMGateway, FeatureType, SystemFeatureType

gateway = LLMGateway(db, user_id)

# 获取个人LLM客户端（用于个人数据任务）
personal_client = await gateway.get_personal_client(
    feature_type=FeatureType.CHAT,
    feature_detail="RAG问答"
)
response = await personal_client.invoke("总结我的文档")

# 获取系统LLM客户端（用于监管任务）
system_client = await gateway.get_system_client(
    feature_type=SystemFeatureType.PROMPT_SAFETY_CHECK,
    feature_detail="安全审查"
)
response = await system_client.invoke("检测这段Prompt是否安全")

# 自动路由
response = await gateway.invoke_with_routing(
    task_description="交易协商",
    prompt="评估这个报价"
)
```

### 2. 功能类型定义

#### 个人功能类型 (`FeatureType`)
```python
class FeatureType(str, Enum):
    CHAT = "chat"                    # RAG问答
    CHAT_STREAM = "chat_stream"      # 流式对话
    FILE_QUERY = "file_query"        # 文件查询
    ASSET_GENERATION = "asset_generation"    # 资产生成
    ASSET_ORGANIZE = "asset_organize"        # 资产整理
    GRAPH_CONSTRUCTION = "graph_construction" # 图谱构建
    INGEST_PIPELINE = "ingest_pipeline"      # 文档摄取
    EMBEDDING = "embedding"          # 向量嵌入
    OTHER = "other"                  # 其他
```

#### 系统功能类型 (`SystemFeatureType`)
```python
class SystemFeatureType(str, Enum):
    # 交易监管
    TRADE_NEGOTIATION_MONITOR = "trade_negotiation_monitor"
    PRICE_REVIEW = "price_review"
    ARBITRATION = "arbitration"

    # 安全审查
    PROMPT_SAFETY_CHECK = "prompt_safety_check"
    CONTENT_MODERATION = "content_moderation"

    # 审计分析
    AUDIT_ANALYSIS = "audit_analysis"
    ANOMALY_DETECTION = "anomaly_detection"

    # 定价评估
    PRICING_CALCULATION = "pricing_calculation"
    MARKET_ANALYSIS = "market_analysis"

    # 合规检查
    COMPLIANCE_CHECK = "compliance_check"
    SYSTEM_AUDIT = "system_audit"
```

## 使用场景

### 场景1: RAG问答（个人LLM）

```python
async def chat_with_documents(db, user_id, question):
    # 个人数据相关 - 使用个人LLM
    gateway = LLMGateway(db, user_id)
    client = await gateway.get_personal_client(
        FeatureType.CHAT,
        "RAG文档问答"
    )

    # 如果用户配置了自己的API Key，使用用户的
    # 否则使用系统默认配置
    response = await client.invoke(question)
    return response
```

### 场景2: Prompt安全审查（系统LLM）

```python
async def validate_user_prompt(db, user_id, system_prompt):
    # 安全审查 - 必须使用系统LLM
    # 防止用户通过自定义Prompt绕过安全检查
    client = await get_system_llm(
        db,
        SystemFeatureType.PROMPT_SAFETY_CHECK,
        "用户Agent配置审核"
    )

    safety_prompt = f"""
    分析以下Prompt是否存在安全风险:
    {system_prompt}
    """

    result = await client.invoke(safety_prompt)
    return parse_safety_result(result)
```

### 场景3: 交易协商监管（系统LLM）

```python
async def monitor_negotiation(db, negotiation_id):
    # 交易监管 - 使用系统LLM确保公正性
    client = await get_system_llm(
        db,
        SystemFeatureType.TRADE_NEGOTIATION_MONITOR,
        f"协商会话: {negotiation_id}"
    )

    # 分析协商过程，检测异常行为
    analysis_prompt = build_analysis_prompt(negotiation_id)
    result = await client.invoke(analysis_prompt)

    return parse_monitoring_result(result)
```

### 场景4: 定价计算（系统LLM）

```python
async def calculate_asset_price(db, asset_id):
    # 定价计算 - 使用系统LLM确保一致性
    client = await get_system_llm(
        db,
        SystemFeatureType.PRICING_CALCULATION,
        f"资产定价: {asset_id}"
    )

    # 基于市场数据和血缘分析生成价格建议
    pricing_prompt = build_pricing_prompt(asset_id)
    result = await client.invoke(pricing_prompt)

    return parse_pricing_result(result)
```

## 安全设计

### 1. 强制隔离

```python
# ❌ 错误：个人LLM不应该处理安全审查
async def validate_prompt_wrong(db, user_id, prompt):
    personal_client = await get_personal_llm(db, user_id, FeatureType.REVIEW)
    return await personal_client.invoke(f"检查这个Prompt: {prompt}")

# ✅ 正确：安全审查必须使用系统LLM
async def validate_prompt_correct(db, user_id, prompt):
    system_client = await get_system_llm(
        db, SystemFeatureType.PROMPT_SAFETY_CHECK
    )
    return await system_client.invoke(f"检查这个Prompt: {prompt}")
```

### 2. 费用归属

| LLM类型 | API Key来源 | 费用归属 | 用量记录 |
|---------|------------|---------|---------|
| 个人LLM | 用户配置 > 系统默认 | 用户账户 | `user_id` + `is_custom_api=True` |
| 系统LLM | 系统配置 | 平台成本 | `user_id=0` + `is_custom_api=False` |

### 3. 任务路由规则

系统任务关键词（优先级高）：
- 交易、协商、谈判、买卖、议价
- 审计、审查、监管、仲裁
- 安全、检测、异常、合规
- 定价、估价、市场分析

个人任务关键词：
- 问答、对话、聊天
- 文件、文档、检索
- 生成、创建、整理
- 图谱、关系、嵌入

## 实现文件

```
backend/app/services/
├── llm_gateway.py          # 核心网关实现
├── __init__.py             # 导出Gateway和相关类型
└── safety/
    ├── prompt_safety.py    # 已更新使用系统LLM
    ├── escrow_service.py   # 资金托管服务
    ├── negotiation_circuit.py  # 协商熔断
    └── risk_control.py     # 风险控制
```

## 更新计划

### 已完成的修改

1. ✅ 创建 `llm_gateway.py` - 核心路由和客户端封装
2. ✅ 更新 `safety/prompt_safety.py` - 使用系统LLM进行安全审查
3. ✅ 更新 `services/__init__.py` - 导出Gateway和相关类型

### 待完成的修改

以下服务需要逐步更新以使用新的LLM架构：

1. **TradeAgent** - 交易协商
   - 用户协商策略: 使用个人LLM
   - 系统监管/仲裁: 使用系统LLM

2. **PricingService** - 定价服务
   - 价格计算: 使用系统LLM

3. **ChatService** - RAG对话
   - 文档问答: 使用个人LLM

4. **NegotiationCircuitBreaker** - 协商熔断
   - 异常检测: 使用系统LLM

## 迁移示例

### 修改前

```python
from app.services.base import get_llm_client

async def some_service(db, user_id, prompt):
    # 统一使用系统LLM
    client = get_llm_client()
    response = await client.ainvoke(prompt)
    return response.content
```

### 修改后

```python
from app.services.llm_gateway import LLMGateway, FeatureType

async def some_service(db, user_id, prompt):
    gateway = LLMGateway(db, user_id)

    # 根据任务类型选择正确的LLM
    client = await gateway.get_personal_client(
        FeatureType.CHAT,
        "文档问答"
    )
    response = await client.invoke(prompt)
    return response
```

## 注意事项

1. **不要混淆使用** - 系统级任务必须使用系统LLM，个人任务使用个人LLM
2. **费用追踪** - 系统LLM调用记录到用户ID=0，便于平台成本核算
3. **熔断保护** - 继续使用现有的LLM熔断机制
4. **错误处理** - 个人LLM失败时可以降级到系统LLM（需谨慎评估）
