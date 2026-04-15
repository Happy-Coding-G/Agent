from __future__ import annotations
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, quote

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Database (Supabase Postgres)
    DATABASE_URL: str = Field(
        default="postgresql://user:password@localhost:5432/dbname",
        description="PostgreSQL connection URL (override via env var)",
    )
    DB_SSLMODE: str = Field(default="require")

    # MinIO
    MINIO_ENDPOINT: str = Field(default="127.0.0.1:9000")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin")
    MINIO_SECRET_KEY: str = Field(default="minioadmin")
    MINIO_SECURE: bool = Field(default=False)

    # LLM / Embeddings (LangChain)
    DEEPSEEK_API_KEY: str = Field(
        default="",
        description="DeepSeek API key",
    )
    DEEPSEEK_BASE_URL: str = Field(default="https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = Field(default="deepseek-chat")

    # Remote Embedding (Qwen3-Embedding-4B)
    REMOTE_EMBEDDING_ENABLED: bool = Field(default=False)
    REMOTE_EMBEDDING_BASE_URL: str = Field(default="http://localhost:27701")
    REMOTE_EMBEDDING_MODEL: str = Field(default="Qwen3-Embedding-4B")

    # Remote Rerank (Qwen3-Reranker-4B)
    REMOTE_RERANK_ENABLED: bool = Field(default=False)
    REMOTE_RERANK_BASE_URL: str = Field(default="http://localhost:29639")
    REMOTE_RERANK_MODEL: str = Field(default="Qwen3-Reranker-4B")

    # Neo4j
    NEO4J_URI: str = Field(default="bolt://127.0.0.1:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(
        default="",
        description="Neo4j password (required, set via NEO4J_PASSWORD env var)",
    )
    NEO4J_DATABASE: str = Field(default="neo4j")

    # Redis / Celery
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # 数据库连接池配置
    DB_POOL_SIZE: int = Field(default=20, description="连接池大小")
    DB_MAX_OVERFLOW: int = Field(default=40, description="最大溢出连接数")
    DB_POOL_TIMEOUT: int = Field(default=30, description="连接池超时(秒)")
    DB_POOL_RECYCLE: int = Field(default=3600, description="连接回收时间(秒)")

    # 只读副本配置（可选，用于读写分离）
    READ_REPLICA_URL: Optional[str] = Field(default=None, description="只读副本数据库URL")

    # 文档摄取配置 - 默认异步摄取提高并发吞吐
    SYNC_INGEST: bool = Field(default=False, description="是否使用同步摄取(默认异步)")

    # 聊天队列配置 - 高并发场景使用队列削峰
    CHAT_QUEUE_ENABLED: bool = Field(default=False, description="是否启用聊天队列模式")
    CHAT_QUEUE_MODE: str = Field(default="sync", description="聊天队列模式: sync/queue")
    CHAT_QUEUE_POLL_INTERVAL: float = Field(
        default=0.5, description="队列结果轮询间隔(秒)"
    )
    CHAT_QUEUE_MAX_POLLS: int = Field(default=120, description="队列结果最大轮询次数")
    CHAT_QUEUE_SYNC_THRESHOLD: int = Field(
        default=100, description="低于此并发量用同步模式"
    )

    def _normalize_async_database_url(self, raw_url: str) -> str:
        if raw_url.startswith("postgresql+asyncpg://"):
            normalized = raw_url
        elif raw_url.startswith("postgresql://"):
            normalized = f"postgresql+asyncpg://{raw_url[len('postgresql://') :]}"
        elif raw_url.startswith("postgres://"):
            normalized = f"postgresql+asyncpg://{raw_url[len('postgres://') :]}"
        else:
            normalized = raw_url

        parsed = urlsplit(normalized)

        # Check if credentials need encoding (contain unencoded special chars like @)
        if parsed.username is not None:
            password = parsed.password or ""
            # Only re-encode if the @ symbol appears unencoded (not as %40)
            if "@" in password and "%40" not in password and "%2540" not in password:
                # Password contains raw @, need to encode it
                username = quote(parsed.username, safe="")
                password = quote(password, safe="")
                if parsed.port:
                    netloc = f"{username}:{password}@{parsed.hostname}:{parsed.port}"
                else:
                    netloc = f"{username}:{password}@{parsed.hostname}"
                normalized = urlunsplit(
                    (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
                )
                parsed = urlsplit(normalized)

        if not parsed.query:
            return normalized

        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() != "sslmode"
        ]
        query = urlencode(query_pairs, doseq=True)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
        )

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is required")
        url = self._normalize_async_database_url(self.DATABASE_URL)
        # statement_cache_size is for psycopg2, not asyncpg - asyncpg uses server_settings
        # For asyncpg, we don't need to add statement_cache_size
        return url

    # Security
    SECRET_KEY: str = Field(
        default="",
        description="JWT signing secret (required, set via SECRET_KEY env var). "
                    "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\"",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ALLOWED_ORIGINS: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ALLOWED_ORIGINS into a list of origin strings."""
        return [
            origin.strip()
            for origin in self.CORS_ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_critical_settings(self) -> list[str]:
        """Return a list of warnings for missing/insecure settings."""
        warnings: list[str] = []
        if not self.SECRET_KEY:
            warnings.append(
                "SECRET_KEY is empty — JWT tokens will be insecure. "
                "Set SECRET_KEY env var (generate with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(64))\")"
            )
        elif len(self.SECRET_KEY) < 32:
            warnings.append(
                "SECRET_KEY is too short (< 32 chars). Use a strong random secret."
            )
        if self.DATABASE_URL == "postgresql://user:password@localhost:5432/dbname":
            warnings.append(
                "DATABASE_URL is using the placeholder default. "
                "Set DATABASE_URL env var to your real database."
            )
        if not self.DEEPSEEK_API_KEY:
            warnings.append("DEEPSEEK_API_KEY is empty — LLM features will not work.")
        return warnings


settings = Settings()
