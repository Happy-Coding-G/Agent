from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime


# --- 用户相关 ---
class AuthRequest(BaseModel):
    identifier: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Login identifier (username, email, phone)",
    )
    credential: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password or auth credential (minimum 8 characters)",
    )
    identity_type: str = Field(
        default="password",
        pattern=r"^(password|phone|wechat|github)$",
        description="Authentication method",
    )
    display_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="User display name",
    )


class AuthResponse(BaseModel):
    status: str
    user_id: int
    message: str


class UserResponse(BaseModel):
    id: int
    user_key: str
    display_name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: int
    user_key: str


# --- 空间相关 ---
class SpaceCreate(BaseModel):
    name: str


class SpaceResponse(BaseModel):
    id: int
    public_id: str
    name: str
    owner_user_id: int

    class Config:
        from_attributes = True


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="文件夹名称")
    parent_id: Optional[int] = Field(None, description="父文件夹ID，根目录传空")


class FileRenameRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=255)


class FolderRenameRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=255)


class FileBrief(BaseModel):
    id: int
    public_id: str
    name: str
    size_bytes: Optional[int]
    mime: Optional[str]


class TreeFolderResponse(BaseModel):
    id: int
    public_id: str
    name: str
    path_cache: str
    # 嵌套自身，形成树结构
    children: List["TreeFolderResponse"] = []
    # 包含该目录下的文件
    files: List[FileBrief] = []

    class Config:
        from_attributes = True


class MarkdownDocSummary(BaseModel):
    doc_id: str
    title: str
    status: str
    updated_at: datetime
    content_hash: Optional[str] = None
    chunk_count: int = 0


class MarkdownDocDetail(BaseModel):
    doc_id: str
    title: str
    status: str
    markdown_text: str
    markdown_object_key: Optional[str] = None
    updated_at: datetime
    content_hash: Optional[str] = None
    chunk_count: int = 0


class MarkdownDocSaveRequest(BaseModel):
    markdown_text: str
    title: Optional[str] = None


class GraphNodePayload(BaseModel):
    doc_id: str
    label: str
    description: str = ""
    tags: List[str] = []
    status: str
    updated_at: datetime


class GraphEdgePayload(BaseModel):
    edge_id: str
    source_doc_id: str
    target_doc_id: str
    relation_type: str
    description: str = ""
    created_at: str
    updated_at: str


class GraphDataResponse(BaseModel):
    nodes: List[GraphNodePayload]
    edges: List[GraphEdgePayload]


class GraphNodeUpdateRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class GraphEdgeCreateRequest(BaseModel):
    source_doc_id: str
    target_doc_id: str
    relation_type: str = Field(default="related_to", min_length=1, max_length=64)
    description: Optional[str] = None


class GraphEdgeUpdateRequest(BaseModel):
    relation_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    description: Optional[str] = None


# --- Chat 相关 (已统一为 AgentChat) ---
# 注意：旧版 ChatRequest 已被弃用，请使用 AgentChatRequest
# 保留此类仅用于向后兼容，将在未来版本中删除
class ChatRequest(BaseModel):
    """[DEPRECATED] 请使用 AgentChatRequest"""

    space_id: str
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=12)

    class Config:
        json_schema_extra = {
            "deprecated": True,
            "description": "已弃用，请使用 AgentChatRequest",
        }


class AssetGenerateRequest(BaseModel):
    prompt: Optional[str] = None
    source_asset_ids: Optional[List[str]] = Field(default=None)
    publish_to_trade: Optional[bool] = Field(
        default=None,
        description="[DEPRECATED] 生成与上架已分离，此字段不再生效",
        deprecated=True,
    )


class AssetSummary(BaseModel):
    asset_id: str
    title: str
    summary: str
    created_at: str


class AssetDetail(BaseModel):
    asset_id: str
    space_public_id: str
    title: str
    summary: str
    created_at: str
    updated_at: str
    prompt: str
    content_markdown: str
    graph_snapshot: dict
    asset_type: Optional[str] = None
    asset_origin: Optional[str] = None
    asset_status: Optional[str] = None
    data_type: Optional[str] = None
    sensitivity_level: Optional[str] = None
    quality_overall_score: Optional[float] = None
    lineage_root: Optional[str] = None


class TradeCreateListingRequest(BaseModel):
    asset_id: str = Field(..., min_length=1)
    price_credits: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = Field(default="knowledge_report", max_length=64)
    tags: List[str] = Field(default_factory=list)


class TradePrivacyPolicyResponse(BaseModel):
    policy_id: str
    version: str
    principles: List[str]
    buyer_visibility: dict
    redaction_rules: List[str]
    delivery_terms: List[str]
    notes: List[str]


class TradeMarketListing(BaseModel):
    listing_id: str
    title: str
    category: str
    tags: List[str] = Field(default_factory=list)
    price_credits: float
    public_summary: str
    preview_excerpt: str
    seller_alias: str
    purchase_count: int = 0
    status: str
    created_at: str
    updated_at: str


class TradeMarketListingDetail(TradeMarketListing):
    buyer_visibility: dict


class TradeListingOwnerDetail(TradeMarketListing):
    asset_id: str
    space_public_id: str
    market_view_count: int = 0
    revenue_total: float = 0.0


class TradeOrderSummary(BaseModel):
    order_id: str
    listing_id: str
    asset_title: str
    seller_alias: str
    price_credits: float
    purchased_at: str


class TradeOrderDetail(TradeOrderSummary):
    platform_fee: float
    seller_income: float
    delivery_scope: List[str]


class TradeDeliveryPayload(BaseModel):
    order_id: str
    listing_id: str
    asset_title: str
    purchased_at: str
    accessible_fields: List[str]
    content_markdown: str
    graph_snapshot: dict
    usage_terms: List[str]


class TradeWallet(BaseModel):
    liquid_credits: float
    cumulative_sales_earnings: float
    cumulative_yield_earnings: float
    total_spent: float
    auto_yield_enabled: bool
    yield_strategy: str
    last_yield_run_at: str
    updated_at: str


class TradeAutoYieldRequest(BaseModel):
    strategy: Optional[str] = Field(default=None, max_length=32)


class TradeYieldReport(BaseModel):
    run_id: str
    strategy: str
    annual_rate: float
    elapsed_days: float
    yield_amount: float
    wallet_before: dict
    wallet_after: dict
    listing_adjustments: List[dict] = Field(default_factory=list)
    generated_at: str


# --- Agent 相关 ---
class AgentChatRequest(BaseModel):
    """统一的聊天请求模型"""

    message: str = Field(..., min_length=1, description="用户消息")
    space_id: str = Field(..., description="工作空间ID")
    session_id: Optional[str] = Field(default=None, description="会话ID（为空时后端创建新会话）")
    context: Optional[Dict[str, Any]] = Field(default=None, description="额外上下文")
    stream: bool = Field(default=False, description="是否使用流式响应")
    top_k: int = Field(default=5, ge=1, le=12, description="检索结果数量（仅QA类请求）")
    history: Optional[List[Dict[str, str]]] = Field(
        default=None, description="[DEPRECATED] 已由服务端记忆接管，此字段保留仅用于兼容旧客户端"
    )

    # 向后兼容：允许使用旧版 query 参数
    @property
    def query(self) -> str:
        return self.message


class AgentChatResponse(BaseModel):
    """统一的聊天响应模型"""

    success: bool = Field(default=True, description="是否成功")
    intent: Optional[str] = Field(default=None, description="识别到的意图")
    agent_type: str = Field(..., description="处理的Agent类型")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    result: Dict[str, Any] = Field(default_factory=dict, description="处理结果")
    sources: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="来源引用（包含doc_id, title, score等）"
    )
    answer: Optional[str] = Field(default=None, description="直接回答文本（QA类型）")
    error: Optional[str] = Field(default=None, description="错误信息")
    retrieval_debug: Optional[Dict[str, Any]] = Field(
        default=None, description="检索调试信息"
    )


class AgentTaskCreate(BaseModel):
    agent_type: str = Field(..., description="Agent类型")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="输入数据")
    space_id: str = Field(..., description="工作空间ID")


class AgentTaskResponse(BaseModel):
    task_id: str
    agent_type: str
    status: str
    created_at: datetime


class FileQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="自然语言查询")
    space_id: str = Field(..., description="工作空间ID")


class FileQueryResult(BaseModel):
    files: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class AssetOrganizeRequest(BaseModel):
    asset_ids: List[str] = Field(default_factory=list, description="要整理的资产ID列表")
    space_id: str = Field(..., description="工作空间ID")
    generate_report: bool = Field(default=True, description="是否生成报告")


class AssetClusterResponse(BaseModel):
    cluster_id: str
    name: str
    description: Optional[str] = None
    summary_report: Optional[str] = None
    asset_count: int
    assets: List[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    doc_id: str = Field(..., description="要审查的文档ID")
    review_type: str = Field(
        default="quality", description="审查类型: quality/compliance/completeness"
    )


class ReviewResponse(BaseModel):
    doc_id: str
    review_type: str
    score: float
    passed: bool
    issues: List[str] = Field(default_factory=list)
    final_status: str
    rework_count: int = 0


