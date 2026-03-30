"""
部署配置示例 - 生产环境高并发配置

使用方法:
1. 复制此文件为 deployment_config.py
2. 根据实际硬件调整 WORKERS 和连接池参数
3. 使用 gunicorn 启动: gunicorn -c deployment_config.py app.main:app
"""

import multiprocessing
import os

# ============================================================================
# Gunicorn 配置
# ============================================================================

# 工作进程数
# 建议: 2-4 x CPU核心数
# 对于IO密集型应用(如本API服务),可以适当增加
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))

# 每个工作进程的线程数(用于同步worker)
# 使用uvicorn.workers.UvicornWorker时此配置不生效
threads = int(os.getenv("GUNICORN_THREADS", 1))

# 工作进程类型
# uvicorn.workers.UvicornWorker - 支持ASGI/异步
worker_class = "uvicorn.workers.UvicornWorker"

# 绑定地址
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# 连接等待队列大小
# 高并发场景建议增加
backlog = int(os.getenv("GUNICORN_BACKLOG", 2048))

# 工作进程超时(秒)
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))

# 优雅重启超时
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 30))

# Keep-Alive连接超时
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 5))

# 最大请求数(达到后工作进程自动重启,防止内存泄漏)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", 10000))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", 1000))

# 预加载应用(节省内存,但某些情况下可能导致问题)
preload_app = os.getenv("GUNICORN_PRELOAD", "false").lower() == "true"

# 工作进程名称
proc_name = "agent_api"

# 日志配置
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")  # "-" 表示输出到stdout
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# 进程PID文件
pidfile = os.getenv("GUNICORN_PIDFILE", "/tmp/gunicorn.pid")

# 守护模式(生产环境建议使用systemd/supervisor代替)
daemon = False

# ============================================================================
# Uvicorn 特定配置(通过worker_class传递)
# ============================================================================

# 注意: 以下配置在UvicornWorker中通过环境变量传递
# 或者在app.main:create_app()中设置

uvicorn_config = {
    # HTTP协议版本
    "http": "auto",  # auto, h11, httptools

    # WebSocket最大消息大小
    "ws_max_size": 16777216,  # 16MB

    # 是否使用生命周期协议
    "lifespan": "on",

    # 日志级别
    "log_level": loglevel,

    # 访问日志
    "access_log": True,

    # 代理头信任
    "proxy_headers": True,
    "forwarded_allow_ips": "*",
}

# ============================================================================
# 钩子函数
# ============================================================================

def on_starting(server):
    """服务启动前"""
    print(f"🚀 Gunicorn starting with {workers} workers...")


def on_reload(server):
    """配置重载时"""
    print("🔄 Gunicorn reloading...")


def when_ready(server):
    """服务就绪时"""
    print(f"✅ Gunicorn ready! Listening on {bind}")
    print(f"   Workers: {workers}")
    print(f"   Worker class: {worker_class}")
    print(f"   Database pool size: {os.getenv('DB_POOL_SIZE', 20)}")


def worker_int(worker):
    """工作进程接收到SIGINT/SIGQUIT时"""
    print(f"⚠️  Worker {worker.pid} interrupted")


def worker_abort(worker):
    """工作进程接收到SIGABRT时"""
    print(f"🚨 Worker {worker.pid} aborted")


# ============================================================================
# 不同场景的推荐配置
# ============================================================================

"""
场景1: 开发环境
    workers = 1
    reload = True
    loglevel = "debug"

场景2: 小型部署 (2核4G)
    workers = 4
    DB_POOL_SIZE = 10
    DB_MAX_OVERFLOW = 20

场景3: 中型部署 (4核8G)
    workers = 8
    DB_POOL_SIZE = 20
    DB_MAX_OVERFLOW = 40

场景4: 大型部署 (8核16G+)
    workers = 16
    DB_POOL_SIZE = 40
    DB_MAX_OVERFLOW = 80
    考虑使用多个实例+负载均衡

场景5: 高并发IO密集型
    workers = 4 x CPU核心数
    增加DB连接池
    启用Redis缓存
    使用异步任务队列
"""
