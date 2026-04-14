"""
State definitions for the multi-agent system.
These will be fleshed out by the background agents.
"""
from typing import TypedDict, Optional, List, Dict, Any
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_REVIEW = "waiting_review"

class AgentType(str, Enum):
    FILE_QUERY = "file_query"
    DATA_PROCESS = "data_process"
    REVIEW = "review"
    QA = "qa"
    ASSET_ORGANIZE = "asset_organize"
    TRADE = "trade"
    CHAT = "chat"  # fallback for general chat

class MainAgentState(TypedDict, total=False):
    """State for the MainAgent orchestrator - tracks user request, intent, and delegation."""
    user_request: str  # Raw user input
    space_id: Optional[str]  # Current space context
    user_id: Optional[int]  # Current user ID
    intent: Optional[AgentType]  # Detected intent
    active_subagent: Optional[AgentType]  # Currently executing sub-agent
    subagent_result: Optional[Dict[str, Any]]  # Result from sub-agent
    task_id: Optional[str]  # Unique task identifier
    task_status: TaskStatus  # Current task status
    task_result: Optional[Dict[str, Any]]  # Final aggregated result
    conversation_history: List[Dict[str, Any]]  # Previous conversation turns
    context: Optional[Dict[str, Any]]  # Additional context from request
    error: Optional[str]  # Error message if any
    retry_count: int  # Number of retries attempted
    # Agent-First Tool Calling fields
    tool_calls: List[Dict[str, Any]]  # LLM 选择的工具调用序列
    tool_results: List[Dict[str, Any]]  # 工具执行结果
    active_tool: Optional[Dict[str, Any]]  # 当前待执行的工具
    final_answer: Optional[str]  # 最终自然语言回复


class SubAgentInput(TypedDict, total=False):
    """Standard input format for invoking subagents via invoke_subagent()."""
    user_request: str  # The user's original request/query
    space_id: Optional[str]  # Space public ID for permission filtering
    user_id: Optional[int]  # Current user ID
    top_k: int  # Number of results to retrieve (for QA)
    source_type: str  # Source type (for data processing)
    source_path: str  # Source path/identifier
    doc_id: str  # Document ID (for review)
    asset_ids: List[str]  # Asset IDs (for asset organization)
    # Trade-specific fields
    action: str  # Trade action type
    listing_id: Optional[str]
    budget_max: float
    bid_amount: float
    pricing_strategy: str
    reserve_price: float
    mechanism_hint: str
    # Generic extension field
    extra: Optional[Dict[str, Any]]

class FileQueryState(TypedDict):
    query: str
    interpreted_path: Optional[str]
    interpreted_pattern: Optional[str]
    file_results: List[Dict[str, Any]]
    error: Optional[str]

class DataProcessState(TypedDict):
    source_type: str
    source_path: Optional[str]
    source_content: Optional[str]
    extracted_text: Optional[str]
    markdown_content: Optional[str]
    chunks: List[Any]
    embedding_ids: List[str]
    graph_nodes: int
    doc_id: Optional[str]
    status: str
    error: Optional[str]

class ReviewState(TypedDict):
    doc_id: str
    review_type: str
    review_result: Dict[str, Any]
    rework_needed: bool
    rework_count: int
    max_rework: int
    final_status: str

class QAState(TypedDict):
    """State for the QA agent - knowledge retrieval and answering."""
    # Input fields
    query: str
    space_id: Optional[str]  # Space public ID for permission filtering
    user_id: Optional[int]  # User ID for permission checking
    top_k: int  # Number of results to retrieve
    context_items: Optional[List[Dict[str, Any]]]  # Pre-fetched context items

    # Processing fields
    intent: Optional[str]
    vector_results: List[Dict[str, Any]]
    graph_results: List[Dict[str, Any]]
    hybrid_results: List[Dict[str, Any]]

    # Output fields
    answer: Optional[str]
    sources: List[Dict[str, Any]]  # Changed from List[str] to List[Dict] for richer source info
    retrieval_debug: Optional[Dict[str, Any]]  # Debug info for retrieval process
    error: Optional[str]

class AssetOrganizeState(TypedDict):
    asset_ids: List[str]
    clustering_result: Dict[str, Any]
    graph_updates: List[Dict[str, Any]]
    summary_report: Optional[str]
    publication_ready: bool

class TradeState(TypedDict):
    """Enhanced TradeState for hybrid market negotiation architecture."""
    # Basic fields (backward compatible)
    action: str  # "listing", "purchase", "yield", "negotiate"
    asset_to_list: Optional[Dict]
    policy: Optional[Dict]
    listing: Optional[Dict]
    listing_id: Optional[str]
    order: Optional[Dict]
    delivery: Optional[Dict]

    # Market mechanism fields
    mechanism_type: Optional[str]  # "contract_net", "auction", "bilateral", "fixed_price"
    negotiation_id: Optional[str]  # Unique negotiation session ID

    # Shared state board (共享状态板)
    shared_board: Optional[Dict[str, Any]]  # Quotes, conditions, logs, evidence

    # Seller/Buyer specific
    seller_agent_state: Optional[Dict[str, Any]]
    buyer_agent_state: Optional[Dict[str, Any]]

    # Negotiation progress
    negotiation_round: int
    max_rounds: int
    negotiation_status: Optional[str]  # "announcing", "bidding", "awarding", "negotiating", "settled", "cancelled"

    # Settlement
    settlement_result: Optional[Dict[str, Any]]
    audit_log: Optional[List[Dict[str, Any]]]


# ============================================================================
# Hybrid Market Negotiation Architecture - New State Types
# ============================================================================

class NegotiationStatus(str, Enum):
    """Status of a negotiation session."""
    PENDING = "pending"                 # 待开始
    ANNOUNCING = "announcing"           # 合同网: 发布公告
    BIDDING = "bidding"                 # 合同网/拍卖: 投标/出价
    EVALUATING = "evaluating"           # 评估 bids
    AWARDING = "awarding"               # 合同网:  awarding
    NEGOTIATING = "negotiating"         # 双边协商: 多轮议价
    FINALIZING = "finalizing"           # 最终确认
    SETTLED = "settled"                 # 已成交
    CANCELLED = "cancelled"             # 已取消
    DISPUTED = "disputed"               # 争议中


class SellerAgentState(TypedDict):
    """State for Seller Agent in market negotiation."""
    # Identity
    seller_user_id: int
    seller_alias: str

    # Asset information
    asset_id: str
    asset_summary: Dict[str, Any]       # 脱敏后的资产摘要
    asset_metadata: Dict[str, Any]      # 元数据

    # Pricing strategy
    reserve_price: float                # 底价
    target_price: float                 # 目标价格
    pricing_strategy: str               # "fixed", "negotiable", "auction"

    # License conditions
    license_scope: List[str]            # 许可范围
    usage_restrictions: Dict[str, Any]  # 使用限制
    redistribution_allowed: bool        # 是否允许再分发
    max_usage_count: Optional[int]      # 最大使用次数

    # Privacy controls
    desensitization_level: str          # 脱敏级别: "none", "partial", "full"
    visible_fields: List[str]           # 可见字段
    hidden_fields: List[str]            # 隐藏字段

    # Negotiation state
    current_quote: Optional[float]      # 当前报价
    quote_history: List[Dict[str, Any]] # 报价历史
    is_open_to_negotiate: bool         # 是否接受议价
    min_acceptable_price: Optional[float]  # 最低可接受价格

    # Contract net specific
    announced_tasks: List[Dict[str, Any]]   # 发布的任务
    received_bids: List[Dict[str, Any]]     # 收到的投标
    awarded_buyers: List[int]               # 已授予的买方


class BuyerAgentState(TypedDict):
    """State for Buyer Agent in market negotiation."""
    # Identity
    buyer_user_id: int
    buyer_alias: str

    # Requirements
    requirements: Dict[str, Any]        # 需求描述
    quality_preferences: Dict[str, Any] # 质量偏好
    risk_constraints: Dict[str, Any]    # 风险约束
    intended_use: str                   # 预期用途

    # Budget
    budget_max: float                   # 最高预算
    budget_preferred: float             # 偏好预算
    payment_terms: str                  # 支付条款

    # Evaluation
    candidate_sellers: List[Dict[str, Any]]  # 候选卖方
    comparing_offers: List[Dict[str, Any]]   # 正在比较的报价
    shortlisted: List[Dict[str, Any]]        #  shortlisted

    # Negotiation state
    current_bid: Optional[float]        # 当前出价
    bid_history: List[Dict[str, Any]]   # 出价历史
    counter_offer_ready: bool          # 是否准备好反报价
    max_rounds_acceptable: int         # 可接受的最大轮数

    # Bidding
    submitted_bids: List[Dict[str, Any]]     # 已提交的投标
    awarded_contracts: List[Dict[str, Any]]  # 已获得的合同


    # Current offers
    seller_offer: Optional[Dict[str, Any]]   # 卖方当前报价
    buyer_offer: Optional[Dict[str, Any]]    # 买方当前出价

    # Concession tracking
    seller_concession_rate: float        # 卖方让步率
    buyer_concession_rate: float         # 买方让步率

    # Term negotiation
    proposed_terms: Dict[str, Any]       # 提议的条款
    term_acceptance: Dict[str, bool]     # 条款接受状态

    # Deadlines
    offer_deadline: Optional[str]        # 报价截止
    response_deadline: Optional[str]     # 回应截止

    # Status
    status: str                          # "active", "accepted", "rejected", "expired"
    termination_reason: Optional[str]    # 终止原因


class SharedStateBoard(TypedDict):
    """Shared state board visible to all parties (共享状态板)."""
    # Session info
    negotiation_id: str
    created_at: str
    updated_at: str

    # Public quotes (visible to all)
    public_quotes: List[Dict[str, Any]]  # 公开报价（拍卖/合同网）

    # Conditions
    announced_conditions: Dict[str, Any]     # 公告的条件
    current_conditions: Dict[str, Any]       # 当前协商的条件
    agreed_conditions: Dict[str, Any]        # 已同意的条件

    # Logs
    event_log: List[Dict[str, Any]]          # 事件日志
    message_log: List[Dict[str, Any]]        # 消息日志（脱敏）

    # Evidence
    commitment_hashes: List[str]             # 承诺哈希（防篡改）
    timestamp_proofs: List[Dict[str, Any]]   # 时间戳证明

    # Status summary
    active_participants: List[int]           # 活跃参与者
    current_phase: str                       # 当前阶段
    estimated_completion: Optional[str]      # 预计完成时间


class SettlementState(TypedDict):
    """State for Settlement Layer (可信执行与结算层)."""
    # Delivery verification
    delivery_verified: bool
    verification_details: Optional[Dict[str, Any]]
    integrity_proof: Optional[str]

    # Access control
    access_token_generated: bool
    access_token: Optional[str]
    access_constraints: Optional[Dict[str, Any]]
    expiry_time: Optional[str]

    # Financial settlement
    payment_initiated: bool
    payment_completed: bool
    payment_amount: Optional[float]
    platform_fee: Optional[float]
    seller_proceeds: Optional[float]

    # Order status
    order_status: str                    # "pending", "delivered", "completed", "disputed"
    completion_time: Optional[str]

    # Audit trail
    audit_hash: Optional[str]            # 审计哈希
    dispute_flag: bool
    dispute_reason: Optional[str]
