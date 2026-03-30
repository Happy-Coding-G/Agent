from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, quote

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Database (Supabase Postgres)
    DATABASE_URL: str = Field(
        default="postgresql://postgres.sphuojdyeskgqlqiseui:%40200211Gxl123@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"
    )
    DB_SSLMODE: str = Field(default="require")

    # MinIO
    MINIO_ENDPOINT: str = Field(default="127.0.0.1:9000")
    MINIO_ACCESS_KEY: str = Field(default="admin")
    MINIO_SECRET_KEY: str = Field(default="minio123")
    MINIO_SECURE: bool = Field(default=False)

    # LLM / Embeddings (LangChain)
    DEEPSEEK_API_KEY: str = Field(default="sk-c228bcaa54c744f18043175cbab357ff")
    DEEPSEEK_BASE_URL: str = Field(default="https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = Field(default="deepseek-chat")

    QWEN_API_KEY: str = Field(default="sk-b38421b22b814606a99e0a70e589ddbf")
    QWEN_BASE_URL: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    QWEN_EMBEDDING: str = Field(default="text-embedding-v2")

    # Remote Embedding (Qwen3-Embedding-4B)
    REMOTE_EMBEDDING_ENABLED: bool = Field(default=True)
    REMOTE_EMBEDDING_BASE_URL: str = Field(default="http://10.211.77.10:27701")
    REMOTE_EMBEDDING_MODEL: str = Field(default="/gemini/data-1/Qwen3-emb-4b/Qwen/Qwen3-Embedding-4B/")

    # Remote Rerank (Qwen3-Reranker-4B)
    REMOTE_RERANK_ENABLED: bool = Field(default=True)
    REMOTE_RERANK_BASE_URL: str = Field(default="http://10.211.77.10:29639")
    REMOTE_RERANK_MODEL: str = Field(default="/gemini/data-1/Qwen3-rerank-4b/Qwen/Qwen3-Reranker-4B/")

    # Neo4j
    NEO4J_URI: str = Field(default="bolt://127.0.0.1:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="neo4j123")
    NEO4J_DATABASE: str = Field(default="neo4j")

    # Redis / Celery
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # 数据库连接池配置
    DB_POOL_SIZE: int = Field(default=20, description="连接池大小")
    DB_MAX_OVERFLOW: int = Field(default=40, description="最大溢出连接数")
    DB_POOL_TIMEOUT: int = Field(default=30, description="连接池超时(秒)")
    DB_POOL_RECYCLE: int = Field(default=3600, description="连接回收时间(秒)")

    # 只读副本配置（可选，用于读写分离）
    READ_REPLICA_URL: str | None = Field(default=None, description="只读副本数据库URL")

    # 文档摄取配置 - 默认异步摄取提高并发吞吐
    SYNC_INGEST: bool = Field(default=False, description="是否使用同步摄取(默认异步)")

    # 聊天队列配置 - 高并发场景使用队列削峰
    CHAT_QUEUE_ENABLED: bool = Field(default=False, description="是否启用聊天队列模式")
    CHAT_QUEUE_MODE: str = Field(default="sync", description="聊天队列模式: sync/queue")
    CHAT_QUEUE_POLL_INTERVAL: float = Field(default=0.5, description="队列结果轮询间隔(秒)")
    CHAT_QUEUE_MAX_POLLS: int = Field(default=120, description="队列结果最大轮询次数")
    CHAT_QUEUE_SYNC_THRESHOLD: int = Field(default=100, description="低于此并发量用同步模式")

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
            password = parsed.password or ''
            # Only re-encode if the @ symbol appears unencoded (not as %40)
            if '@' in password and '%40' not in password and '%2540' not in password:
                # Password contains raw @, need to encode it
                username = quote(parsed.username, safe='')
                password = quote(password, safe='')
                if parsed.port:
                    netloc = f"{username}:{password}@{parsed.hostname}:{parsed.port}"
                else:
                    netloc = f"{username}:{password}@{parsed.hostname}"
                normalized = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
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
    SECRET_KEY: str = Field(default="secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
