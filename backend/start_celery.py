#!/usr/bin/env python3
"""
Celery Worker 启动脚本
使用 subprocess 调用 celery 命令
"""

import sys
import os
import subprocess

# 添加 backend 到路径
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.environ["PYTHONPATH"] = backend_dir + os.pathsep + os.environ.get("PYTHONPATH", "")

if __name__ == "__main__":
    """
    启动 Celery Worker
    """
    # 默认配置
    queues = "celery,ingest,default"
    loglevel = "info"
    concurrency = 1

    # 解析简单参数
    args = sys.argv[1:]
    if "-Q" in args:
        idx = args.index("-Q")
        queues = args[idx + 1] if idx + 1 < len(args) else queues
    if "-l" in args:
        idx = args.index("-l")
        loglevel = args[idx + 1] if idx + 1 < len(args) else loglevel
    if "-c" in args:
        idx = args.index("-c")
        concurrency = int(args[idx + 1]) if idx + 1 < len(args) else concurrency

    print(f"Starting Celery Worker...")
    print(f"  PYTHONPATH: {backend_dir}")
    print(f"  Queues: {queues}")
    print(f"  Log Level: {loglevel}")
    print(f"  Concurrency: {concurrency}")
    print("-" * 60)

    # 使用当前 Python 解释器运行 celery
    # 直接使用 app.core.celery_config 模块
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "app.core.celery_config.celery_app",
        "worker",
        "-Q", queues,
        "-l", loglevel,
        "-c", str(concurrency),
        "-P", "solo",
    ]

    # 启动 worker
    result = subprocess.run(cmd, cwd=backend_dir)
    sys.exit(result.returncode)
