import ssl
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

def _build_connect_args() -> dict:
    # PgBouncer transaction/statement mode is incompatible with asyncpg prepared
    # statement caching. Keep both caches disabled for compatibility.
    base_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }

    mode = (settings.DB_SSLMODE or "require").strip().lower()

    if mode in {"disable", "off", "false", "0"}:
        return base_args

    if mode in {"require", "prefer", "allow"}:
        # Match common sslmode=require behavior: encrypt traffic without cert validation.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return {**base_args, "ssl": ctx}

    if mode == "verify-ca":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        return {**base_args, "ssl": ctx}

    if mode == "verify-full":
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return {**base_args, "ssl": ctx}

    raise ValueError(
        "Unsupported DB_SSLMODE. Use one of: disable, require, verify-ca, verify-full."
    )


connect_args = _build_connect_args()

# 数据库连接池配置
# 根据部署环境和并发需求调整这些参数
DB_POOL_SIZE = getattr(settings, 'DB_POOL_SIZE', 20)  # 默认连接池大小
DB_MAX_OVERFLOW = getattr(settings, 'DB_MAX_OVERFLOW', 40)  # 最大溢出连接
DB_POOL_TIMEOUT = getattr(settings, 'DB_POOL_TIMEOUT', 30)  # 连接池超时
DB_POOL_RECYCLE = getattr(settings, 'DB_POOL_RECYCLE', 3600)  # 连接回收时间

default_engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
    # 连接池配置
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    pool_recycle=DB_POOL_RECYCLE,
    # 连接池回收和重置
    echo=False,  # 设置为 True 可打印SQL语句（调试用）
)

# 只读操作引擎（用于只读副本）
# 在配置中设置 READ_REPLICA_URL 时使用
if hasattr(settings, 'READ_REPLICA_URL') and settings.READ_REPLICA_URL:
    read_engine = create_async_engine(
        settings.READ_REPLICA_URL,
        pool_pre_ping=True,
        connect_args=connect_args,
        pool_size=DB_POOL_SIZE // 2,  # 只读池较小
        max_overflow=DB_MAX_OVERFLOW // 2,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        echo=False,
    )
else:
    read_engine = default_engine

AsyncSessionLocal = async_sessionmaker(
    bind=default_engine,
    expire_on_commit=False,
)

AsyncSessionReadOnly = async_sessionmaker(
    bind=read_engine,
    expire_on_commit=False,
    readonly=True,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """数据库会话上下文管理器 - 用于流式响应内部"""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db_read_only():
    """获取只读数据库会话（用于读操作）"""
    async with AsyncSessionReadOnly() as session:
        try:
            yield session
        finally:
            await session.close()
