"""
Celery 配置文件
任务队列配置
"""

from pathlib import Path
from celery import Celery
from celery.signals import celeryd_init
from app.core.config import settings

# 创建 Celery 应用
celery_app = Celery(
    "dataspace",
    broker=settings.REDIS_URL or "redis://localhost:6379/0",
    backend=settings.REDIS_URL or "redis://localhost:6379/0",
    include=[
        "app.tasks.ingest_tasks",
        "app.tasks",
    ],
)


@celeryd_init.connect
def init_celery_logging(**kwargs) -> None:
    """Worker 启动时初始化文件日志。"""
    from app.core.logging_config import setup_logging
    import logging

    log_dir = Path(settings.LOG_DIR) if settings.LOG_DIR else None
    setup_logging(
        log_dir=log_dir,
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        json_format=settings.LOG_JSON_FORMAT,
    )

# 配置 Celery
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 时区设置
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务执行设置
    task_track_started=True,
    task_time_limit=3600,  # 任务最长执行时间 1 小时
    task_soft_time_limit=3000,  # 软限制 50 分钟
    # 结果存储设置
    result_backend=settings.REDIS_URL or "redis://localhost:6379/0",
    result_expires=3600 * 24 * 7,  # 结果保留 7 天
    # 并发设置
    worker_pool="threads",  # Windows 下默认使用线程池（prefork 在 Windows 会崩溃）
    worker_prefetch_multiplier=1,  # 每次只取一个任务，避免任务阻塞
    worker_max_tasks_per_child=1000,  # 每个 worker 处理 1000 个任务后重启
    # 重试设置
    task_default_retry_delay=60,  # 默认 60 秒后重试
    task_max_retries=3,  # 最大重试次数
    # 队列设置
    task_default_queue="default",
    task_queues={
        "celery": {
            "exchange": "celery",
            "routing_key": "celery",
        },
        "ingest": {
            "exchange": "ingest",
            "routing_key": "ingest",
        },
        "high_priority": {
            "exchange": "high_priority",
            "routing_key": "high_priority",
        },
    },
    # 路由规则
    task_routes={
        "app.tasks.ingest_tasks.*": {"queue": "ingest"},
    },
    # 监控设置
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# 自动发现任务
celery_app.autodiscover_tasks()
