from fastapi import APIRouter, Depends
from app.api.deps.auth import get_current_user
from app.core.cache import cache_manager
from app.db.models import Users

router = APIRouter(tags=["Health"])


@router.get("/healthz")
def healthz():
    return {"status": "OK"}


@router.get("/health/cache-stats")
async def cache_stats(current_user: Users = Depends(get_current_user)):
    """获取缓存统计信息"""
    return {"status": "OK", "cache_stats": cache_manager.get_stats()}


@router.post("/health/cache/clear")
async def clear_cache(current_user: Users = Depends(get_current_user)):
    """清空所有缓存（管理用途）"""
    cache_manager.clear_all()
    return {"status": "OK", "message": "All caches cleared"}
