# 业务需求分析报告

**项目名称**: Agent 数据空间平台
**分析日期**: 2026-04-13
**分析师**: 资深业务需求分析师

---

## 一、执行摘要

经过深入分析当前项目的架构和功能实现，从业务需求角度发现**系统性设计缺陷**和**潜在业务风险**。主要问题集中在：

1. **交易业务逻辑不完整** - 协商、托管、结算流程存在断点
2. **数据权益模型与实际业务脱节** - 权益定义模糊，执行机制缺失
3. **定价系统过度复杂但实用性不足** - 技术驱动而非业务驱动
4. **安全与合规设计存在重大隐患** - 资金风险、数据泄露风险
5. **用户Agent配置与业务场景错配** - LLM划分逻辑不清晰

---

## 二、详细问题分析

### 2.1 交易系统业务逻辑缺陷

#### 2.1.1 协商流程与资金托管脱节

**现状分析**:
```python
# TradeNegotiationService.initiate_negotiation_by_buyer()
# 创建协商会话时完全没有涉及资金托管

session = NegotiationSessions(
    negotiation_id=negotiation_id,
    listing_id=listing_id,
    seller_user_id=listing.seller_user_id,
    buyer_user_id=buyer_id,
    status="pending",
    # ... 缺少 escrow_id 关联
)
```

**业务问题**:
1. **协商创建时不锁定资金** - 买方可以无限创建协商会话而不付出任何成本
2. **恶意DDOS风险** - 攻击者可以对同一商品创建数千个协商，耗尽卖方资源
3. **诚意金机制缺失** - 真实交易场景中，买方通常需要支付诚意金或保证金

**业务需求建议**:
```python
# 改进方案：协商创建时锁定诚意金
async def initiate_negotiation_by_buyer(...):
    # 1. 检查并锁定诚意金（如交易金额的5%）
    escrow = await escrow_service.lock_funds(
        negotiation_id=negotiation_id,
        buyer_id=buyer_id,
        seller_id=seller_id,
        listing_id=listing_id,
        amount=listing.price * 0.05,  # 诚意金为标价5%
        escrow_type="EARNEST_MONEY"
    )

    # 2. 协商成功时诚意金转为部分货款
    # 3. 协商失败时诚意金按规则处理（如扣除1%作为平台补偿给卖方）
```

#### 2.1.2 资金托管金额不明确

**现状分析**:
```python
# EscrowService.lock_funds() 参数
async def lock_funds(
    self,
    negotiation_id: str,
    buyer_id: int,
    seller_id: int,
    listing_id: str,
    amount: float,  # 这个amount是谁决定的？
    # ...
):
```

**业务问题**:
- 托管金额应该是**协商达成的价格**，但协商过程中价格会变动
- 当前设计无法支持**分期托管**（如按里程碑付款）
- 缺少**超额托管**场景（买方愿意托管比当前报价更高的金额以示诚意）

**风险等级**: 🔴 **高风险** - 可能导致资金纠纷

#### 2.1.3 多轮协商中的资金状态管理缺失

**业务场景**:
- 买方报价: 800元 → 卖方还价: 950元 → 买方接受

**当前问题**:
1. 托管是在哪个环节创建？
2. 如果协商破裂，资金如何退还？
3. 协商过程中价格变动如何反映到托管金额？

**代码检查**:
```python
# TradeNegotiationService 中没有任何与 escrow 相关的调用
# 协商状态流转与资金状态完全独立
```

### 2.2 数据权益交易系统设计缺陷

#### 2.2.1 权益定义与实际使用场景脱节

**现状模型**:
```python
class DataRightsTransactions(Base):
    rights_types = Column(JSONB, nullable=False)  # 权益类型列表
    usage_scope = Column(JSONB, nullable=False)  # 使用范围
    restrictions = Column(JSONB, default=list)   # 限制条件
    computation_method = Column(Enum(ComputationMethod), nullable=False)
```

**业务问题**:
1. **rights_types 缺少标准化定义** - 只是JSONB，没有业务层面的枚举约束
2. **权益与定价脱节** - 不同权益类型应有不同定价权重，当前模型未体现
3. **权益执行无技术保障** - 购买了"只读"权益，系统如何确保买方不能下载？

**需求建议**:
```python
class DataRightType(str, Enum):
    READ_ONLY = "read_only"                    # 只读查询
    ANALYTICS = "analytics"                    # 分析使用（聚合结果）
    DERIVED_WORK = "derived_work"              # 衍生作品
    FULL_ACCESS = "full_access"                # 完全访问
    EXCLUSIVE = "exclusive"                    # 独占权益

class DataRightsTransactions(Base):
    right_type: DataRightType  # 标准化权益类型
    right_tier: int  # 权益等级（影响定价系数）
    technical_enforcement: JSONB  # 技术执行策略（查询限制、水印等）
```

#### 2.2.2 权益审计日志流于形式

**现状**:
```python
class DataAccessAuditLogs(Base):
    query_fingerprint = Column(String(64), nullable=False)
    query_complexity_score = Column(Float, nullable=True)
    # 缺少：实际查询内容、返回结果摘要、违规检测结果
```

**业务问题**:
- `query_fingerprint` 只是哈希值，无法还原实际查询内容
- 发生纠纷时无法提供有效证据
- 缺少**实时违规检测**机制

**风险等级**: 🟡 **中风险** - 合规证据不足

### 2.3 定价系统过度工程化

#### 2.3.1 技术驱动而非业务驱动

**现状架构**:
```
UnifiedPricingService
├── GNN图嵌入分析
├── 数据血缘分析
├── DeepFM特征融合
├── 三档价格阈值生成
└── 博弈策略建议
```

**业务问题**:

1. **GNN图嵌入的实际业务价值存疑**
   - 技术上说可以通过关联分析定价
   - 但业务上：买方只关心数据本身的质量和实用性
   - 关联数据的定价应该由**市场供需**决定，而非算法

2. **定价过于复杂导致不可解释**
   ```python
   # PricingRecommendation 包含：
   - conservative_price (P10)
   - moderate_price (P50)
   - aggressive_price (P90)
   - overall_confidence
   - confidence_breakdown
   - price_adjustments
   - adjustment_reasoning
   ```
   卖方看到这么多数字会困惑：到底应该定多少钱？

3. **缺少市场验证机制**
   - 定价算法没有考虑历史成交数据
   - 没有A/B测试框架验证定价策略效果

**需求建议**:
```python
# 简化定价模型
class SimplePricingRecommendation:
    """
    业务导向的定价建议
    """
    suggested_price: float           # 建议价格
    price_range: Tuple[float, float] # 合理区间
    market_average: float            # 市场均价（同类数据）
    urgency_discount: float          # 急售折扣建议

    # 定价依据（可解释）
    reasoning: str  # 如："基于5个同类数据，平均成交价1200元，您的数据质量评分高于均值15%"
```

#### 2.3.2 动态定价与固定定价冲突

**现状**:
```python
# UnifiedTradeService.create_listing()
pricing_strategy: str = "fixed"  # "fixed", "negotiable", "auction"
```

**业务问题**:
- 选择`"fixed"`时，`UnifiedPricingService`计算的三档价格完全被忽略
- 选择`"auction"`时，起拍价、保留价如何与定价建议关联？
- 定价系统和交易系统的策略未打通

**风险等级**: 🟡 **中风险** - 系统能力浪费，用户体验不一致

### 2.4 安全与合规隐患

#### 2.4.1 资金托管过期机制不完善

**现状**:
```python
class EscrowService:
    DEFAULT_EXPIRY_HOURS = 24  # 默认24小时过期
```

**业务问题**:
1. **24小时过短** - 复杂B2B数据交易协商可能需要数天
2. **过期前无提醒** - 买方可能不知道资金即将被退回
3. **过期后自动退款无审核** - 如果协商接近达成，自动退款会破坏交易

**需求建议**:
```python
class EscrowExpiryPolicy:
    """托管过期策略"""
    standard_period_hours: int = 72  # 标准3天
    extension_allowed: bool = True   # 允许延期
    reminder_schedule: List[int] = [24, 12, 4, 1]  # 过期前提醒（小时）

    # 智能延期：如果协商活跃（最近24小时有报价），自动延期
    auto_extension_on_activity: bool = True
```

#### 2.4.2 Prompt安全审查可被绕过

**现状**:
```python
# UserAgentService.update_config()
if "system_prompt" in config_data and not skip_safety_check:
    safety_result = await safety_service.validate_system_prompt(...)
```

**业务问题**:
- `skip_safety_check` 参数存在，虽然默认False，但这是**架构级漏洞**
- 内部服务调用时可能不小心传入`skip_safety_check=True`
- 安全审查应该是**强制性**的，不可跳过

**风险等级**: 🔴 **高风险** - 系统级安全漏洞

#### 2.4.3 钱包初始化默认余额过高

**现状**:
```python
class TradeWallets(Base):
    liquid_credits: Mapped[int] = mapped_column(
        BigInteger, server_default=text("100000")  # 默认1000元
    )
```

**业务问题**:
- 新用户自动获得1000元，可能被羊毛党利用
- 缺少**实名认证**与钱包功能的关联
- 没有**充值来源追踪**（法币充值、加密货币、平台奖励）

### 2.5 LLM功能划分与业务场景错配

#### 2.5.1 个人LLM与系统LLM边界模糊

**现状设计**:
```
个人LLM: RAG问答、文件查询、数据处理等
系统LLM: 交易监管、审计、仲裁、安全审查
```

**业务问题**:

1. **交易协商到底用哪个LLM？**
   ```
   场景：买方Agent向卖方Agent发起协商

   问题：
   - 买方Agent的策略生成 → 个人LLM（买方配置）
   - 卖方Agent的响应生成 → 个人LLM（卖方配置）
   - 但协商监管 → 系统LLM

   矛盾点：一次对话中如何切换？
   ```

2. **定价计算使用系统LLM，但定价策略需要个性化**
   - 系统LLM提供基准价格
   - 但卖方可能希望根据自身的资金需求、库存压力调整
   - 个人LLM如何参与定价决策？

**需求建议**:
```python
# 明确的三层架构
class LLMUsageLayer:
    """
    LLM使用三层架构
    """

    # 第一层：个人策略层（Personal Strategy Layer）
    # 使用个人LLM，处理用户个性化的策略、偏好
    async def generate_personal_strategy(self, context):
        # 例如：根据用户的资金状况决定是激进还是保守
        pass

    # 第二层：业务逻辑层（Business Logic Layer）
    # 使用系统LLM，处理标准化的业务规则
    async def evaluate_business_rules(self, context):
        # 例如：检查报价是否在合理范围内
        pass

    # 第三层：监管审计层（Regulatory Layer）
    # 使用系统LLM，处理合规、安全、审计
    async def compliance_check(self, context):
        # 例如：检测是否涉及洗钱
        pass
```

#### 2.5.2 Token用量追踪的分类不够业务化

**现状**:
```python
class FeatureType(str, Enum):
    CHAT = "chat"
    CHAT_STREAM = "chat_stream"
    TRADE_NEGOTIATION = "trade_negotiation"
    # ...
```

**业务问题**:
- `TRADE_NEGOTIATION` 没有区分是买方还是卖方
- 无法追踪**单次协商的总成本**（买方LLM + 卖方LLM + 系统监管LLM）
- 不利于后续的**成本分摊**和**定价优化**

### 2.6 API设计与业务场景不匹配

#### 2.6.1 交易API过度拆分

**现状**:
```python
class UnifiedTradeService:
    async def create_negotiation(...)  # 创建协商
    async def make_offer(...)          # 提交报价
    async def respond_to_offer(...)    # 响应报价
    # ... 共20+个方法
```

**业务问题**:
- API粒度太细，前端需要多次调用完成一个业务动作
- 例如：买方接受卖方报价需要：
  1. `get_negotiation_status` 获取最新状态
  2. `respond_to_offer` 发送接受
  3. `get_escrow_status` 检查资金状态
  4. 可能还需要调用结算API

**需求建议**:
```python
# 业务动作导向的API
async def execute_trade_action(
    self,
    negotiation_id: str,
    action: TradeAction,  # ACCEPT_OFFER | COUNTER_OFFER | REJECT | WITHDRAW
    params: Dict[str, Any]
) -> TradeResult:
    """
    统一的业务动作入口

    内部自动处理：
    - 状态检查
    - 资金操作
    - 通知发送
    - 日志记录
    """
    pass
```

#### 2.6.2 缺少批量操作API

**业务场景**:
- 卖方需要管理100个上架商品，批量调整价格
- 买方需要查看所有进行中的协商状态

**现状**: 只有单资源操作API

### 2.7 事件溯源设计过度

#### 2.7.1 事件溯源增加了不必要的复杂性

**现状**:
```python
class TradeNegotiationService:
    """基于事件溯源黑板模式重构后的服务"""

    def __init__(self, db):
        self.event_store = NegotiationEventStore(db)
        self.state_projector = StateProjector(db)
        # ...
```

**业务问题**:
1. **业务价值不明确** - 协商历史可以直接存在`negotiation_history` JSONB字段
2. **查询性能问题** - 每次获取当前状态都需要重放事件
3. **数据一致性风险** - 事件写入和状态投影可能出现不一致

**简化建议**:
```python
class NegotiationSessions(Base):
    # 当前状态（冗余但高效）
    current_status: str
    current_price: float

    # 完整历史（JSONB，只追加）
    history: JSONB  # [{round: 1, action: "offer", price: 100, by: "buyer", at: "..."}, ...]

    # 版本号（乐观锁）
    version: int
```

**风险等级**: 🟡 **中风险** - 维护成本高，学习曲线陡峭

---

## 三、优先级排序

### 🔴 P0 - 必须立即修复（阻止上线）

1. **资金托管与协商流程脱节** - 可能导致资金损失
2. **Prompt安全审查可被绕过** - 系统级安全漏洞
3. **钱包默认余额过高且无风控** - 可能被羊毛党利用

### 🟠 P1 - 高优先级（影响业务开展）

4. **定价系统过度复杂不可解释** - 影响用户体验
5. **数据权益执行无技术保障** - 权益购买后无法落地
6. **API设计过于细碎** - 影响开发效率

### 🟡 P2 - 中优先级（优化体验）

7. **事件溯源过度设计** - 维护成本高
8. **LLM边界模糊** - 架构不清晰
9. **缺少批量操作API** - 影响管理效率

### 🟢 P3 - 低优先级（长期改进）

10. **Token用量追踪不够细化** - 成本分析不够精准

---

## 四、架构改进建议

### 4.1 核心业务流程重构

```
交易创建流程:
┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  买方    │────▶│  创建协商    │────▶│  锁定诚意金  │────▶│  等待卖方   │
│         │     │  (检查余额)  │     │  (5%标价)   │     │  响应       │
└─────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                                                              │
                                    ┌───────────────────────────┘
                                    ▼
                              ┌─────────────┐
                              │  卖方接受/  │
                              │  拒绝/还价  │
                              └─────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌─────────────┐
              │ 拒绝     │   │ 接受     │   │ 还价        │
              │ (退诚意金)│   │ (锁全款) │   │ (继续协商)   │
              └──────────┘   └──────────┘   └─────────────┘
```

### 4.2 权益执行技术保障

```
数据访问控制:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  买方请求    │────▶│  权益验证   │────▶│  查询改写   │
│  访问数据   │     │  (检查有效期│     │  (添加限制)  │
│             │     │  和使用次数)│     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                ▼
                                         ┌─────────────┐
                                         │  实际查询   │
                                         │  带水印/限制 │
                                         └─────────────┘
```

### 4.3 简化定价系统

```
新定价流程:
1. 卖方输入期望价格
2. 系统基于以下给出建议区间:
   - 同类数据历史成交价
   - 数据质量评分
   - 市场供需指数
3. 卖方确认最终价格
4. 系统记录定价决策用于后续优化
```

---

## 五、总结与建议

### 5.1 立即行动项

1. **暂停上线** - 在资金托管和协商流程整合完成前，不建议上线交易功能
2. **安全加固** - 移除`skip_safety_check`参数，强制所有Prompt审核
3. **钱包风控** - 新用户默认余额设为0，需要实名认证后才可充值

### 5.2 中期改进项

1. **简化定价** - 移除GNN等复杂模块，使用基于规则的定价建议
2. **整合API** - 提供业务动作导向的高级API
3. **权益落地** - 实现查询改写和水印等权益执行技术

### 5.3 长期规划

1. **数据驱动** - 基于真实交易数据优化定价算法
2. **国际化** - 考虑跨境数据交易的合规要求
3. **自动化** - 引入智能合约实现自动结算

---

**报告结束**

*本报告基于代码静态分析，建议结合业务团队访谈进行进一步验证。*
