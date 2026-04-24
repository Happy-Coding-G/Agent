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
    skill_calls: List[Dict[str, Any]]  # LLM 选择的 skill 调用序列
    skill_results: List[Dict[str, Any]]  # skill 执行结果
    active_skill: Optional[Dict[str, Any]]  # 当前待执行的 skill
    subagent_calls: List[Dict[str, Any]]  # LLM 选择的 subagent 调用序列
    subagent_results: List[Dict[str, Any]]  # subagent 执行结果
    active_subagent_call: Optional[Dict[str, Any]]  # 当前待执行的 subagent
    decision_mode: Optional[str]  # direct/tool/skill/subagent
    final_answer: Optional[str]  # 最终自然语言回复


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
    conversation_history: Optional[List[Dict[str, str]]]  # Recent conversation turns

    # Processing fields
    intent: Optional[str]
    vector_results: List[Dict[str, Any]]
    graph_results: List[Dict[str, Any]]
    hybrid_results: List[Dict[str, Any]]

    # Output fields
    answer: Optional[str]
    sources: List[
        Dict[str, Any]
    ]  # Changed from List[str] to List[Dict] for richer source info
    retrieval_debug: Optional[Dict[str, Any]]  # Debug info for retrieval process
    error: Optional[str]


class AssetOrganizeState(TypedDict):
    asset_ids: List[str]
    space_id: str
    user: Any
    clustering_result: Dict[str, Any]
    graph_updates: List[Dict[str, Any]]
    summary_report: Optional[str]
    publication_ready: bool


class TradeState(TypedDict):
    """TradeState for direct trade mode."""

    # Basic fields
    action: str  # "listing", "purchase"
    asset_to_list: Optional[Dict]
    policy: Optional[Dict]
    listing: Optional[Dict]
    listing_id: Optional[str]
    order: Optional[Dict]
    delivery: Optional[Dict]

    # Market mechanism fields (direct mode only)
    mechanism_type: Optional[str]  # "direct"

    # Settlement
    settlement_result: Optional[Dict[str, Any]]
    audit_log: Optional[List[Dict[str, Any]]]


