import ssl

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

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
