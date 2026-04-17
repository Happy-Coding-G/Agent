from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_v1_router
from app.core.exception_handlers import setup_exception_handlers
from app.core.rate_limit import RateLimitMiddleware
from app.core.config import settings
from app.core.logging_config import setup_logging

import logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    # 初始化日志（仅首次调用生效）
    log_dir = Path(settings.LOG_DIR) if settings.LOG_DIR else None
    setup_logging(
        log_dir=log_dir,
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        json_format=settings.LOG_JSON_FORMAT,
    )

    app = FastAPI(title="dataspace", version="1.0")

    # Emit startup validation warnings
    for warning in settings.validate_critical_settings():
        logger.warning(warning)

    # 注册 API 路由
    app.include_router(api_v1_router, prefix="/api/v1")

    # 设置全局异常处理器（必须在限流之前）
    setup_exception_handlers(app)

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册限流中间件
    app.add_middleware(
        RateLimitMiddleware,
        exempt_paths=["/healthz", "/api/v1/healthz", "/api/v1/health/cache-stats"],
    )

    return app


app = create_app()
