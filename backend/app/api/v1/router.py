# app/api/v1/router.py

from fastapi import APIRouter
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.files import router as upload_router
from app.api.v1.endpoints.spaces import router as space_router
from app.api.v1.endpoints.markdown import router as markdown_router
from app.api.v1.endpoints.graph import router as graph_router
from app.api.v1.endpoints.assets import router as assets_router
# Trade endpoints removed - now accessed via main_agent -> trade_agent
# from app.api.v1.endpoints.trade import router as trade_router
from app.api.v1.endpoints.tasks import router as tasks_router
from app.api.v1.endpoints.agent import router as agent_router
from app.api.v1.endpoints.memory import router as memory_router
from app.api.v1.endpoints.lineage import router as lineage_router
from app.api.v1.endpoints.user_agent import router as user_agent_router
from app.api.v1.endpoints.token_usage import router as token_usage_router
from app.api.v1.endpoints.data_rights import router as data_rights_router
from app.api.v1.endpoints.trade_actions import router as trade_actions_router
from app.api.v1.endpoints.negotiations import router as negotiations_router
from app.api.v1.endpoints.trade_batch import router as trade_batch_router
from app.api.v1.endpoints.hybrid_negotiations import router as hybrid_negotiations_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(auth_router, tags=["auth"])
api_v1_router.include_router(upload_router, tags=["upload"])
api_v1_router.include_router(space_router, tags=["space"])
api_v1_router.include_router(markdown_router, tags=["markdown"])
api_v1_router.include_router(graph_router, tags=["graph"])
api_v1_router.include_router(assets_router, tags=["assets"])
# Trade router removed - trade functionality now accessed via agent chat
# api_v1_router.include_router(trade_router, tags=["trade"])
api_v1_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_v1_router.include_router(agent_router, tags=["agent"])
api_v1_router.include_router(memory_router, prefix="/memory", tags=["memory"])
api_v1_router.include_router(lineage_router, prefix="/lineage", tags=["lineage"])
api_v1_router.include_router(user_agent_router, tags=["user-agent"])
api_v1_router.include_router(token_usage_router, prefix="/usage", tags=["token-usage"])
api_v1_router.include_router(data_rights_router, prefix="/rights", tags=["data-rights"])

# ============================================================================
# Agent-First 交易架构路由
# ============================================================================
#
# 交易主流程统一从 agent 入口进入：
# - POST /api/v1/agent/trade/goal       - 提交交易目标（主入口）
# - GET  /api/v1/agent/trade/task/{id}  - 查询目标状态
#
# 以下路由已降级为兼容/调试/人工兜底接口：
# - /trade/*           - 确定性操作（保留兼容）
# - /negotiations/*    - 双边协商（人工操作）
# - /batch/*           - 批量操作（管理接口）
# - /hybrid-negotiations/* - 混合协商（调试接口）
#
# ============================================================================

api_v1_router.include_router(trade_actions_router, prefix="/trade", tags=["trade-actions-compat"])
api_v1_router.include_router(negotiations_router, prefix="/negotiations", tags=["negotiations-compat"])
api_v1_router.include_router(trade_batch_router, prefix="/batch", tags=["trade-batch-compat"])
api_v1_router.include_router(hybrid_negotiations_router, prefix="/hybrid-negotiations", tags=["hybrid-debug"])
