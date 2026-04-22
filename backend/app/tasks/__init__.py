"""
Celery 任务注册表
定义所有可用的 Celery 任务
"""

from celery import Task
from app.core.celery_config import celery_app


class DatabaseTask(Task):
    """数据库任务基类"""

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        """任务完成后清理资源"""
        # 可以在这里添加资源清理逻辑
        pass


# ==================== 导出任务 ====================


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.export.export_documents",
    queue="default",
    max_retries=2,
    time_limit=1800,  # 30 分钟
)
def export_documents(self, space_id: str, format: str = "json"):
    """
    导出文档任务

    Args:
        space_id: 空间 ID
        format: 导出格式 (json, markdown, csv)
    """
    import asyncio
    import json
    from datetime import datetime, timezone

    try:
        # 异步执行导出逻辑
        result = asyncio.run(_export_documents_impl(space_id, format))

        return {
            "status": "success",
            "space_id": space_id,
            "format": format,
            "file_count": result.get("count", 0),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        return {"status": "failed", "error": str(exc)}


async def _export_documents_impl(space_id: str, format: str):
    """导出文档实现"""
    from app.db.session import AsyncSessionLocal
    from app.db.models import Documents
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        stmt = select(Documents).where(Documents.space_id == space_id)
        result = await session.execute(stmt)
        docs = result.scalars().all()

        return {"count": len(docs), "documents": docs}


# ==================== 通知任务 ====================


@celery_app.task(
    bind=True,
    name="app.tasks.notification.send_email",
    queue="default",
    max_retries=3,
)
def send_email(self, to: str, subject: str, body: str):
    """发送邮件任务"""
    import smtplib
    from email.mime.text import MIMEText

    # 邮件发送逻辑
    # ...

    return {"status": "sent", "to": to, "subject": subject}


# ==================== 清理任务 ====================


@celery_app.task(
    name="app.tasks.maintenance.cleanup_temp_files",
    queue="default",
)
def cleanup_temp_files(days: int = 7):
    """
    清理临时文件任务

    Args:
        days: 保留天数，超过此天数的临时文件将被删除
    """
    import os
    import time
    from pathlib import Path

    cleaned_count = 0
    cleaned_size = 0

    # 清理临时目录
    temp_dirs = [
        Path("backend/state"),
        Path("backend/temp"),
    ]

    for temp_dir in temp_dirs:
        if not temp_dir.exists():
            continue

        now = time.time()
        max_age = days * 24 * 3600

        for file in temp_dir.rglob("*"):
            if file.is_file():
                file_age = now - file.stat().st_mtime
                if file_age > max_age:
                    size = file.stat().st_size
                    file.unlink()
                    cleaned_count += 1
                    cleaned_size += size

    return {
        "status": "success",
        "files_cleaned": cleaned_count,
        "size_cleaned": cleaned_size,
    }


# ==================== 缓存任务 ====================


@celery_app.task(
    name="app.tasks.cache.warmup_user_cache",
    queue="default",
)
def warmup_user_cache(user_ids: list[int]):
    """
    预热用户缓存

    Args:
        user_ids: 需要预热的用户 ID 列表
    """
    import asyncio
    from app.core.cache import cache_manager
    from app.db.session import AsyncSessionLocal
    from app.repositories.user_repo import UserRepository

    async def _warmup():
        async with AsyncSessionLocal() as session:
            repo = UserRepository(session)
            for user_id in user_ids:
                user = await repo.get_by_id(user_id)
                if user:
                    await cache_manager.set_user(user_id, user)

    asyncio.run(_warmup())

    return {"status": "success", "users_warmed": len(user_ids)}


# ==================== 同步任务 ====================


@celery_app.task(
    bind=True,
    name="app.tasks.sync.sync_external_data",
    queue="default",
    max_retries=2,
)
def sync_external_data(self, source: str, params: dict = None):
    """
    同步外部数据

    Args:
        source: 数据源标识
        params: 同步参数
    """
    params = params or {}

    # 根据不同数据源执行同步
    if source == "github":
        return _sync_github_data(params)
    elif source == "notion":
        return _sync_notion_data(params)
    elif source == "dropbox":
        return _sync_dropbox_data(params)
    else:
        return {"status": "error", "message": f"Unknown source: {source}"}


def _sync_github_data(params: dict):
    """同步 GitHub 数据"""
    # 实现 GitHub 数据同步逻辑
    return {"status": "success", "source": "github", "items_synced": 0}


def _sync_notion_data(params: dict):
    """同步 Notion 数据"""
    return {"status": "success", "source": "notion", "items_synced": 0}


def _sync_dropbox_data(params: dict):
    """同步 Dropbox 数据"""
    return {"status": "success", "source": "dropbox", "items_synced": 0}


# ==================== 报表任务 ====================


@celery_app.task(
    bind=True,
    name="app.tasks.report.generate_space_report",
    queue="default",
    max_retries=1,
    time_limit=3600,  # 1 小时
)
def generate_space_report(self, space_id: str, report_type: str = "weekly"):
    """
    生成空间报告

    Args:
        space_id: 空间 ID
        report_type: 报告类型 (daily, weekly, monthly)
    """
    import asyncio
    from datetime import datetime, timezone, timedelta

    # 计算时间范围
    if report_type == "daily":
        days = 1
    elif report_type == "weekly":
        days = 7
    else:  # monthly
        days = 30

    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # 生成报告逻辑
    report_data = {
        "space_id": space_id,
        "report_type": report_type,
        "start_date": start_date.isoformat(),
        "end_date": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "total_documents": 0,
            "total_chats": 0,
            "total_uploads": 0,
        },
    }

    return {"status": "success", "report": report_data}


# ==================== 任务注册表 ====================

TASK_REGISTRY = {
    # 导出
    "export_documents": export_documents,
    # 通知
    "send_email": send_email,
    # 维护
    "cleanup_temp_files": cleanup_temp_files,
    # 缓存
    "warmup_user_cache": warmup_user_cache,
    # 同步
    "sync_external_data": sync_external_data,
    # 报表
    "generate_space_report": generate_space_report,
}


def get_task_by_name(name: str):
    """根据任务名称获取任务"""
    return TASK_REGISTRY.get(name)
