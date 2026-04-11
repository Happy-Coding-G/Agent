#!/usr/bin/env python3
"""统一的 Celery 启动脚本。

默认启动 worker，并统一使用 app.celery_worker.celery_app 作为 Celery 应用入口。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CANONICAL_CELERY_APP = "app.celery_worker.celery_app"
DEFAULT_QUEUES = "celery,ingest,high_priority,default"
DEFAULT_LOGLEVEL = "info"
DEFAULT_CONCURRENCY = 1
DEFAULT_POOL = "solo"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一的 Celery Worker 启动脚本")
    parser.add_argument("command", nargs="?", default="worker", help="Celery 子命令，默认 worker")
    parser.add_argument("-Q", "--queues", default=DEFAULT_QUEUES, help="监听队列列表")
    parser.add_argument("-l", "--loglevel", default=DEFAULT_LOGLEVEL, help="日志级别")
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发数")
    parser.add_argument("-P", "--pool", default=DEFAULT_POOL, help="worker pool，Windows 默认 solo")
    parser.add_argument("--dry-run", action="store_true", help="仅打印启动命令，不实际执行")
    return parser


def build_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        CANONICAL_CELERY_APP,
        args.command,
    ]

    if args.command == "worker":
        command.extend([
            "-Q",
            args.queues,
            "-l",
            args.loglevel,
            "-c",
            str(args.concurrency),
            "-P",
            args.pool,
        ])
    elif args.command == "beat":
        command.extend(["-l", args.loglevel])

    return command


def main() -> int:
    backend_dir = Path(__file__).resolve().parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    os.environ["PYTHONPATH"] = str(backend_dir) + os.pathsep + os.environ.get("PYTHONPATH", "")

    parser = build_parser()
    args = parser.parse_args()
    command = build_command(args)

    print("Starting Celery...")
    print(f"  App: {CANONICAL_CELERY_APP}")
    print(f"  CWD: {backend_dir}")
    print(f"  Command: {' '.join(command)}")
    print("-" * 60)

    if args.dry_run:
        return 0

    result = subprocess.run(command, cwd=backend_dir)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
