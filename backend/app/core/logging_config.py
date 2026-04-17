"""
项目日志配置

提供统一的日志初始化，支持：
- 控制台输出（开发调试）
- 文件滚动存储（按大小分割，保留最近 7 个备份）
- 按级别分离：info/access 与 error
- 结构化 JSON 格式选项（生产环境可开启）
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

from app.core.config import settings


DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
MAX_BYTES = 20 * 1024 * 1024  # 20 MB
BACKUP_COUNT = 7


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    json_format: bool = False,
) -> None:
    """
    初始化全局日志配置。

    Args:
        log_dir: 日志文件存储目录，默认 backend/logs/
        level: 根日志级别
        json_format: 是否使用 JSON 格式（便于日志收集系统解析）
    """
    log_dir = Path(log_dir or DEFAULT_LOG_DIR)
    _ensure_dir(log_dir)

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有 handler，避免重复挂载
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 通用 formatter
    if json_format:
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # 1. 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. 综合文件 handler (INFO+)
    app_log_path = log_dir / "app.log"
    file_handler = logging.handlers.RotatingFileHandler(
        app_log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 3. 错误文件 handler (ERROR+)
    error_log_path = log_dir / "error.log"
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # 4. 第三方库日志级别抑制，避免刷屏
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)

    root_logger.info(f"Logging initialized: log_dir={log_dir}, level={logging.getLevelName(level)}")


class _JsonFormatter(logging.Formatter):
    """极简 JSON formatter，供生产环境集成 ELK/Loki 使用。"""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
