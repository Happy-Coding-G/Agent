from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Database (Supabase Postgres)
    DATABASE_URL: str = Field(default="postgresql://postgres.sphuojdyeskgqlqiseui:%40200211Gxl123@aws-1-ap-south-1.pooler.supabase.com:6543/postgres")
    DB_SSLMODE: str = Field(default="require")

    # MinIO
    MINIO_ENDPOINT: str = Field(default="127.0.0.1:9000")
    MINIO_ACCESS_KEY: str = Field(default="admin")
    MINIO_SECRET_KEY: str = Field(default="minio123")
    MINIO_SECURE: bool = Field(default=False)

    # LLM / Embeddings (LangChain)
    DEEPSEEK_API_KEY: str = Field(default="sk-c228bcaa54c744f18043175cbab357ff")
    DEEPSEEK_BASE_URL: str = Field(default="https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = Field(default="deepseek-reasoner")

    QWEN_API_KEY: str = Field(default="sk-b38421b22b814606a99e0a70e589ddbf")
    QWEN_BASE_URL: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    QWEN_EMBEDDING: str = Field(default="text-embedding-v4")

    # Neo4j
    NEO4J_URI: str = Field(default="127.0.0.1/7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_DATABASE: str = Field(default="neo4j")

    def _normalize_async_database_url(self, raw_url: str) -> str:
        if raw_url.startswith("postgresql+asyncpg://"):
            normalized = raw_url
        elif raw_url.startswith("postgresql://"):
            normalized = f"postgresql+asyncpg://{raw_url[len('postgresql://'):]}"
        elif raw_url.startswith("postgres://"):
            normalized = f"postgresql+asyncpg://{raw_url[len('postgres://'):]}"
        else:
            normalized = raw_url

        parsed = urlsplit(normalized)
        if not parsed.query:
            return normalized

        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() != "sslmode"
        ]
        query = urlencode(query_pairs, doseq=True)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


    @property
    def ASYNC_DATABASE_URL(self) -> str:
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is required")
        return self._normalize_async_database_url(self.DATABASE_URL)

    # Security
    SECRET_KEY: str = Field(default="secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
