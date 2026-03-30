from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Any, Iterable, Optional

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.circuit_breakers import (
    embedding_circuit_breaker,
    rerank_circuit_breaker,
    embedding_fallback,
)


DB_VECTOR_DIMENSION = 1536
EMBEDDING_MODEL_FALLBACKS = (
    "text-embedding-v2",
    "text-embedding-v1",
    "text-embedding-v4",
    "text-embedding-v3",
)


def candidate_embedding_models() -> list[str]:
    candidates = [settings.QWEN_EMBEDDING, *EMBEDDING_MODEL_FALLBACKS]
    result: list[str] = []
    for item in candidates:
        name = (item or "").strip()
        if not name or name in result:
            continue
        result.append(name)
    return result


def choose_target_dimension(vectors: Iterable[list[float]]) -> int | None:
    dims = [len(vec) for vec in vectors if vec]
    if not dims:
        return None
    return Counter(dims).most_common(1)[0][0]


def _local_hash_embedding(text: str, dimensions: int) -> list[float]:
    if dimensions <= 0:
        return []

    vector = [0.0] * dimensions
    tokens = re.findall(r"\w+", (text or "").lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if (digest[4] % 2 == 0) else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


# ============================================================================
# Remote Embedding Client (Qwen3-Embedding-4B)
# ============================================================================


class RemoteEmbeddingClient:
    """
    远程 Embedding 服务客户端 (Qwen3-Embedding-4B)

    使用方式:
        client = RemoteEmbeddingClient(
            base_url="http://10.211.77.10:27701",
            model="/gemini/data-1/Qwen3-emb-4b/Qwen/Qwen3-Embedding-4B/"
        )
        result = client.embed(["text1", "text2"])
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> dict[str, Any]:
        """
        调用远程 embedding 服务获取向量

        Args:
            texts: 待向量化的文本列表

        Returns:
            包含 data 字段的响应，data[0]["embedding"] 为向量列表
        """
        url = f"{self.base_url}/v1/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def aembed(self, texts: list[str]) -> dict[str, Any]:
        """
        异步调用远程 embedding 服务获取向量
        """
        url = f"{self.base_url}/v1/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()


# ============================================================================
# Remote Rerank Client (Qwen3-Reranker-4B)
# ============================================================================


class RemoteRerankClient:
    """
    远程 Rerank 服务客户端 (Qwen3-Reranker-4B)

    使用方式:
        client = RemoteRerankClient(
            base_url="http://10.211.77.10:29639",
            model="/gemini/data-1/Qwen3-rerank-4b/Qwen/Qwen3-Reranker-4B/"
        )
        result = client.rerank(
            query="查询文本",
            documents=["文档1", "文档2", ...],
            top_n=5
        )
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: Optional[int] = None,
        return_documents: bool = True,
    ) -> dict[str, Any]:
        """
        调用远程 rerank 服务重排序文档

        Args:
            query: 查询文本
            documents: 待重排序的文档列表
            top_n: 返回前 N 个结果，None 表示返回全部
            return_documents: 是否在返回结果中包含文档内容

        Returns:
            包含 results 字段的响应
        """
        url = f"{self.base_url}/v1/rerank"
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": return_documents,
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def arerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: Optional[int] = None,
        return_documents: bool = True,
    ) -> dict[str, Any]:
        """
        异步调用远程 rerank 服务重排序文档
        """
        url = f"{self.base_url}/v1/rerank"
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": return_documents,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()


# ============================================================================
# 全局客户端实例 (单例模式)
# ============================================================================


_remote_embedding_client: Optional[RemoteEmbeddingClient] = None
_remote_rerank_client: Optional[RemoteRerankClient] = None


def get_remote_embedding_client() -> RemoteEmbeddingClient:
    """获取远程 Embedding 客户端单例"""
    global _remote_embedding_client
    if _remote_embedding_client is None:
        _remote_embedding_client = RemoteEmbeddingClient(
            base_url=settings.REMOTE_EMBEDDING_BASE_URL,
            model=settings.REMOTE_EMBEDDING_MODEL,
        )
    return _remote_embedding_client


def get_remote_rerank_client() -> RemoteRerankClient:
    """获取远程 Rerank 客户端单例"""
    global _remote_rerank_client
    if _remote_rerank_client is None:
        _remote_rerank_client = RemoteRerankClient(
            base_url=settings.REMOTE_RERANK_BASE_URL,
            model=settings.REMOTE_RERANK_MODEL,
        )
    return _remote_rerank_client


# ============================================================================
# Embedding 函数 (带远程/本地fallback + 熔断保护)
# ============================================================================


@embedding_circuit_breaker(fallback=embedding_fallback)
async def _embed_with_remote(texts: list[str], target_dimension: int | None) -> tuple[list[list[float]], str] | None:
    """内部函数：使用远程embedding服务（带熔断保护）"""
    if not settings.REMOTE_EMBEDDING_ENABLED:
        return None

    client = get_remote_embedding_client()
    response = await client.aembed(texts)

    vectors = [item["embedding"] for item in response["data"]]
    if vectors:
        actual_dim = len(vectors[0])
        # 如果维度不匹配，需要调整
        if target_dimension is not None and actual_dim != target_dimension:
            import logging
            logging.warning(
                f"Remote embedding dimension {actual_dim} != expected {target_dimension}, "
                f"{'truncating' if actual_dim > target_dimension else 'padding'} to {target_dimension}"
            )
            adjusted_vectors = []
            for vec in vectors:
                if actual_dim > target_dimension:
                    adjusted_vectors.append(vec[:target_dimension])
                else:
                    adjusted = vec + [0.0] * (target_dimension - actual_dim)
                    adjusted_vectors.append(adjusted)
            vectors = adjusted_vectors
        return vectors, f"remote:{settings.REMOTE_EMBEDDING_MODEL}"
    return None


async def _embed_with_local(texts: list[str], target_dimension: int | None) -> tuple[list[list[float]], str]:
    """内部函数：使用本地API作为fallback"""
    client = AsyncOpenAI(
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
    )

    errors: list[str] = []

    for model_name in candidate_embedding_models():
        try:
            response = await client.embeddings.create(model=model_name, input=texts)
            vectors = [[float(x) for x in item.embedding] for item in response.data]
            if not vectors:
                errors.append(f"{model_name}: empty embedding response")
                continue

            dim = len(vectors[0])
            if any(len(vec) != dim for vec in vectors):
                errors.append(f"{model_name}: inconsistent embedding dimensions")
                continue
            if target_dimension is not None and dim != target_dimension:
                errors.append(f"{model_name}: dimension {dim} != expected {target_dimension}")
                continue
            return vectors, model_name
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{model_name}: {exc}")
            continue

    # 最终fallback：本地哈希嵌入
    fallback_dimension = target_dimension or DB_VECTOR_DIMENSION
    vectors = [_local_hash_embedding(text, fallback_dimension) for text in texts]
    return vectors, "local-hash-fallback"


async def embed_documents_with_fallback(
    texts: list[str],
    *,
    target_dimension: int | None = DB_VECTOR_DIMENSION,
) -> tuple[list[list[float]], str]:
    """
    文档向量化函数，支持远程 Embedding 服务，带熔断保护

    优先使用远程 Embedding 服务（带熔断），失败时回退到本地 Qwen API
    """
    if not texts:
        return [], ""

    # 尝试远程服务（带熔断）
    if settings.REMOTE_EMBEDDING_ENABLED:
        try:
            # 使用熔断器保护的内部函数
            result = await _embed_with_remote(texts, target_dimension)
            if result:
                return result
        except Exception as exc:
            # 远程服务失败，记录日志，继续fallback
            import logging
            logging.warning(f"Remote embedding failed: {exc}, falling back to local API")

    # 回退到本地 API
    return await _embed_with_local(texts, target_dimension)


async def embed_query_with_fallback(
    query: str,
    *,
    target_dimension: int | None = None,
) -> tuple[list[float], str]:
    """查询向量化函数"""
    vectors, model_name = await embed_documents_with_fallback(
        [query],
        target_dimension=target_dimension,
    )
    if not vectors:
        raise RuntimeError("Embedding API returned empty vector for query")
    return vectors[0], model_name


# ============================================================================
# Rerank 函数 (带熔断保护)
# ============================================================================


@rerank_circuit_breaker()
async def rerank_documents(
    query: str,
    documents: list[str],
    *,
    top_n: Optional[int] = None,
    return_documents: bool = True,
) -> dict[str, Any]:
    """
    文档重排序函数，带熔断保护

    Args:
        query: 查询文本
        documents: 待重排序的文档列表
        top_n: 返回前 N 个结果，None 表示返回全部
        return_documents: 是否在返回结果中包含文档内容

    Returns:
        rerank 响应，包含 results 字段

    Raises:
        ServiceError: 服务熔断时抛出503错误
    """
    if not documents:
        return {"results": []}

    if not settings.REMOTE_RERANK_ENABLED:
        raise RuntimeError("Remote rerank is not enabled")

    client = get_remote_rerank_client()
    return await client.arerank(
        query=query,
        documents=documents,
        top_n=top_n,
        return_documents=return_documents,
    )
