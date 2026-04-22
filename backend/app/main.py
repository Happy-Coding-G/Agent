from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_v1_router
from app.core.exception_handlers import setup_exception_handlers, SecurityHeadersMiddleware
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

    # 关键配置检查 — 空 SECRET_KEY 会导致所有 JWT 令牌完全不安全，拒绝启动
    if not settings.SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is not set. "
            "Generate a strong key with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(64))\" "
            "and set it via the SECRET_KEY environment variable."
        )
    if len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY is too short (< 32 chars). "
            "Use a strong random secret of at least 32 characters."
        )

    app = FastAPI(title="dataspace", version="1.0")

    # Emit startup validation warnings for non-fatal settings
    for warning in settings.validate_critical_settings():
        logger.warning(warning)

    # 注册 API 路由
    app.include_router(api_v1_router, prefix="/api/v1")

    # 设置全局异常处理器（必须在限流之前）
    setup_exception_handlers(app)

    # HTTP 安全响应头（在 CORS 之后注册，优先级最高）
    app.add_middleware(SecurityHeadersMiddleware)

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
