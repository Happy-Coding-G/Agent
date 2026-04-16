from fastapi import APIRouter
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.agent import router as agent_router
from app.api.v1.endpoints.spaces import router as spaces_router
from app.api.v1.endpoints.files import router as files_router
from app.api.v1.endpoints.markdown import router as markdown_router
from app.api.v1.endpoints.graph import router as graph_router
from app.api.v1.endpoints.assets import router as assets_router
from app.api.v1.endpoints.tasks import router as tasks_router
from app.api.v1.endpoints.user_agent import router as user_agent_router
from app.api.v1.endpoints.memory import router as memory_router
from app.api.v1.endpoints.lineage import router as lineage_router
from app.api.v1.endpoints.token_usage import router as token_usage_router
from app.api.v1.endpoints.negotiations import router as negotiations_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(auth_router, tags=["auth"])
api_v1_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_v1_router.include_router(spaces_router, tags=["spaces"])
api_v1_router.include_router(files_router, tags=["files"])
api_v1_router.include_router(markdown_router, tags=["markdown"])
api_v1_router.include_router(graph_router, tags=["graph"])
api_v1_router.include_router(assets_router, tags=["assets"])
api_v1_router.include_router(tasks_router, tags=["tasks"])
api_v1_router.include_router(user_agent_router, tags=["user-agent"])
api_v1_router.include_router(memory_router, tags=["memory"])
api_v1_router.include_router(lineage_router, tags=["lineage"])
api_v1_router.include_router(token_usage_router, prefix="/token-usage", tags=["token-usage"])
api_v1_router.include_router(negotiations_router, prefix="/negotiations", tags=["negotiations"])
