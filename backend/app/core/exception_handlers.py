"""
全局异常处理器
提供统一的错误处理和日志记录
"""

import logging
import time
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class ServiceErrorResponse(JSONResponse):
    """服务错误响应"""

    def __init__(self, error: ServiceError, request_id: str):
        super().__init__(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.status_code,
                    "message": error.detail,
                    "request_id": request_id,
                    "timestamp": time.time(),
                }
            },
        )


class GlobalExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """全局异常处理中间件"""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:16]
        request.state.request_id = request_id

        start_time = time.perf_counter()

        try:
            response = await call_next(request)

            # 记录成功请求日志
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration, 2),
                },
            )

            # 添加请求 ID 到响应头
            response.headers["X-Request-ID"] = request_id
            return response

        except ServiceError as exc:
            # 业务错误，记录警告日志
            duration = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"Service error: {exc.detail}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": exc.status_code,
                    "duration_ms": round(duration, 2),
                },
            )

            response = ServiceErrorResponse(exc, request_id)
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as exc:
            # 未处理异常，记录错误日志
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Unhandled exception: {str(exc)}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "exception": traceback.format_exc(),
                    "duration_ms": round(duration, 2),
                },
            )

            # 生产环境不暴露详细错误信息
            error_message = "Internal server error"

            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": 500,
                        "message": error_message,
                        "request_id": request_id,
                        "timestamp": time.time(),
                    }
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response


def setup_exception_handlers(app: FastAPI) -> None:
    """设置全局异常处理器"""

    # 注册中间件
    app.add_middleware(GlobalExceptionHandlerMiddleware)

    # 注册显式异常处理器（作为中间件的补充）
    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:16])
        return ServiceErrorResponse(exc, request_id)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:16])
        logger.exception(f"Unhandled exception in handler: {exc}")

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": "Internal server error",
                    "request_id": request_id,
                    "timestamp": time.time(),
                }
            },
        )
