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
