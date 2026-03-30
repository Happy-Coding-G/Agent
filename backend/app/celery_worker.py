#!/usr/bin/env python
"""
Celery Worker 启动入口
用法：
    python -m app.celery_worker worker -Q ingest,default -l info
"""

import os
import sys

# 添加 backend 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 启动 Celery
if __name__ == "__main__":
    from app.core.celery_config import celery_app

    celery_app.start()
