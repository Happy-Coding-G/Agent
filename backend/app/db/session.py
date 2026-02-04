from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

# 创建异步引擎
engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    pool_pre_ping=True,  # 解决数据库连接超时导致的“Server has gone away”问题
)

# 创建 Session 工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False
)

# FastAPI 依赖注入函数
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()