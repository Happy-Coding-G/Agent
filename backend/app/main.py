from fastapi import FastAPI
from app.api.v1.router import api_v1_router
from app.core.exception_handlers import setup_exception_handlers
from app.core.rate_limit import RateLimitMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="dataspace", version="1.0")

    # 注册 API 路由
    app.include_router(api_v1_router, prefix="/api/v1")

    # 设置全局异常处理器（必须在限流之前）
    setup_exception_handlers(app)

    # 注册限流中间件
    app.add_middleware(
        RateLimitMiddleware,
        exempt_paths=["/healthz", "/api/v1/healthz", "/api/v1/health/cache-stats"],
    )

    return app


app = create_app()
