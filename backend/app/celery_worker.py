#!/usr/bin/env python
"""Celery 启动模块统一入口。

支持：
    python -m app.celery_worker worker -Q celery,ingest,high_priority -l info
    celery -A app.celery_worker.celery_app worker -Q celery,ingest,high_priority -l info
"""

from __future__ import annotations

from app.core.celery_config import celery_app


def main() -> int:
    celery_app.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
