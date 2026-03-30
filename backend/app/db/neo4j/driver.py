"""
Neo4j Driver Management

Provides a singleton driver instance for Neo4j connections with circuit breaker support.
"""
import logging
from typing import Optional, Callable, TypeVar, Any
from functools import wraps

from neo4j import GraphDatabase, Driver, DriverError
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from app.core.config import settings
from app.core.circuit_breakers import (
    neo4j_circuit_breaker,
    neo4j_fallback,
    ServiceCircuitBreaker,
    NEO4J_CIRCUIT_CONFIG,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_driver: Optional[Driver] = None


def get_neo4j_driver() -> Driver:
    """
    Get or create the Neo4j driver singleton.

    Returns:
        Neo4j Driver instance

    Raises:
        RuntimeError: If Neo4j is not configured
    """
    global _driver

    if _driver is None:
        uri = settings.NEO4J_URI
        if not uri:
            raise RuntimeError("NEO4J_URI is not configured")

        user = settings.NEO4J_USER
        password = settings.NEO4J_PASSWORD

        logger.info(f"Connecting to Neo4j at {uri}")
        _driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_lifetime=3600,
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
        )

    return _driver


def close_neo4j_driver():
    """Close the Neo4j driver if it exists."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def with_neo4j_circuit_breaker(func: Callable[..., T]) -> Callable[..., T]:
    """
    装饰器：为Neo4j操作添加熔断保护

    使用示例:
        @with_neo4j_circuit_breaker
        async def get_graph_data(query: str):
            driver = get_neo4j_driver()
            with driver.session() as session:
                result = session.run(query)
                return result.data()
    """
    breaker = ServiceCircuitBreaker.get_breaker("neo4j", NEO4J_CIRCUIT_CONFIG)

    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        can_execute, reason = await breaker.can_execute()
        if not can_execute:
            logger.warning(f"Neo4j circuit breaker open: {reason}")
            return neo4j_fallback(query="", **kwargs)

        import time
        start_time = time.time()

        try:
            result = await func(*args, **kwargs)
            await breaker.record_success()
            return result
        except (ServiceUnavailable, SessionExpired, DriverError) as e:
            latency_ms = (time.time() - start_time) * 1000
            is_slow = latency_ms > NEO4J_CIRCUIT_CONFIG.slow_call_threshold_ms
            await breaker.record_failure(is_slow=is_slow)
            logger.error(f"Neo4j error: {e}")
            raise
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            is_slow = latency_ms > NEO4J_CIRCUIT_CONFIG.slow_call_threshold_ms
            await breaker.record_failure(is_slow=is_slow)
            logger.error(f"Neo4j unexpected error: {e}")
            raise

    return wrapper


class Neo4jDriver:
    """
    Neo4j driver wrapper for context management with circuit breaker support.
    """

    def __init__(self):
        self._driver = get_neo4j_driver()
        self._circuit_breaker = ServiceCircuitBreaker.get_breaker("neo4j", NEO4J_CIRCUIT_CONFIG)

    @property
    def driver(self) -> Driver:
        """Get the underlying driver."""
        return self._driver

    def session(self, **kwargs):
        """Create a new session."""
        database = kwargs.pop("database", settings.NEO4J_DATABASE)
        return self._driver.session(database=database, **kwargs)

    async def verify_connectivity(self) -> bool:
        """Verify the driver can connect with circuit breaker."""
        can_execute, reason = await self._circuit_breaker.can_execute()
        if not can_execute:
            logger.warning(f"Neo4j connectivity check skipped (circuit open): {reason}")
            return False

        try:
            with self.session() as session:
                result = session.run("RETURN 1")
                result.consume()
            await self._circuit_breaker.record_success()
            return True
        except Exception as e:
            await self._circuit_breaker.record_failure()
            logger.error(f"Neo4j connectivity check failed: {e}")
            return False

    def verify_connectivity_sync(self) -> bool:
        """Verify the driver can connect (synchronous version)."""
        try:
            with self.session() as session:
                result = session.run("RETURN 1")
                result.consume()
            return True
        except Exception as e:
            logger.error(f"Neo4j connectivity check failed: {e}")
            return False
