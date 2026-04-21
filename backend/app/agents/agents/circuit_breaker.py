"""熔断器 - 防止故障 Agent 持续被调用。

状态转换：
CLOSED --失败阈值--> OPEN --超时--> HALF_OPEN --成功--> CLOSED
                          |
                          └──── 快速失败 ──────┘

用法：
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    result = await breaker.call(agent_session.execute(request))
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    """熔断器打开异常。"""

    pass


class CircuitBreaker:
    """熔断器：防止故障 Agent 持续被调用。"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "CLOSED"  # CLOSED | OPEN | HALF_OPEN
        self.half_open_calls = 0

    async def call(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """执行受保护的调用。"""
        if self.state == "OPEN":
            if self.last_failure_time and (time.time() - self.last_failure_time > self.recovery_timeout):
                self.state = "HALF_OPEN"
                self.half_open_calls = 0
                logger.info("Circuit breaker entering HALF_OPEN state")
            else:
                raise CircuitBreakerOpen(
                    f"Circuit breaker is OPEN for this agent. "
                    f"Retry after {self.recovery_timeout}s."
                )

        if self.state == "HALF_OPEN":
            if self.half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerOpen(
                    "Circuit breaker is HALF_OPEN but max concurrent calls reached."
                )
            self.half_open_calls += 1

        try:
            result = await coro
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """调用成功时的处理。"""
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            self.last_failure_time = None
            self.half_open_calls = 0
            logger.info("Circuit breaker closed after successful HALF_OPEN call")
        else:
            self.failure_count = max(0, self.failure_count - 1)

    def _on_failure(self):
        """调用失败时的处理。"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.half_open_calls = 0
            logger.warning(
                f"Circuit breaker reopened. Failure count: {self.failure_count}"
            )
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} consecutive failures"
            )

    def get_state(self) -> str:
        """获取当前状态。"""
        return self.state

    def reset(self):
        """手动重置熔断器。"""
        self.state = "CLOSED"
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0
        logger.info("Circuit breaker manually reset")
