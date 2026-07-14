"""Bounded retry for TRANSIENT connection failures on real-LLM clients.

A single network blip (``openai.APIConnectionError`` after the SDK's own
retries) killed round-3C's paired eval at 32/72 runs: ``verify_evolve.py`` is
the frozen judgment target, its eval pool has no per-run isolation, so the
pipeline client absorbs transient failures instead.

Scope is deliberately narrow:
* Connection-class errors are retried (matched by exception-type NAME
  anywhere in the MRO, so no hard dependency on openai/httpx imports).
* The wall-clock guard's ``LLMTimeoutError`` gets a separately bounded number
  of attempts (two by default for compatibility). Long science runs may raise
  that ceiling explicitly; every fresh attempt remains protected by the same
  per-request wall-clock guard.
* Real API errors (auth, bad request, rate-limit-with-retry-after handled by
  the SDK) propagate immediately.
"""
# ============================================================
# 【模块导读】为真实 LLM 客户端的“瞬时”连接故障做有界重试。
# 一次网络抖动曾在 32/72 处终止 round-3C 的配对 eval（冻结的评测池无每次运行隔离，
# 故由流水线客户端吸收瞬时故障）。范围刻意收窄：
# - 连接类错误重试（按异常类型名在 MRO 中匹配，不硬依赖 openai/httpx）。
# - 挂钟守卫的 LLMTimeoutError 默认只给一次有界重试；长实验可显式提高次数，每次
#   新尝试仍受同一挂钟守卫约束。
# - 真实 API 错误（鉴权、错误请求、带 retry-after 的限流由 SDK 处理）立即上抛。
# ============================================================
from __future__ import annotations

import time
from typing import Any, Callable

# 中文：视为瞬时的异常类型名（在 MRO 中逐层检查）。
# Exception type NAMES considered transient (checked across the MRO).
TRANSIENT_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "PoolTimeout",
    }
)


# 【职责】给（已加超时守卫的）LLM 客户端包上有界重试。
class RetryLLMClient:
    """Wrap an (already timeout-guarded) LLM client with bounded retry."""

    def __init__(
        self,
        inner: Any,
        *,
        attempts: int = 3,
        timeout_attempts: int = 2,
        base_delay: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._attempts = max(1, int(attempts))
        self._timeout_attempts = max(1, int(timeout_attempts))
        self._base_delay = float(base_delay)
        self._sleep = sleep

    @staticmethod
    # 【职责】异常是否属于瞬时连接类（沿 MRO 匹配类型名）。
    def _is_transient(exc: BaseException) -> bool:
        return any(t.__name__ in TRANSIENT_ERROR_NAMES for t in type(exc).__mro__)

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        return type(exc).__name__ == "LLMTimeoutError"

    # 【职责】按异常类型决定最大尝试次数：timeout 最多 2 次，瞬时类 attempts 次，其余 1 次。
    def _attempts_for(self, exc: BaseException) -> int:
        if self._is_timeout(exc):
            return min(self._timeout_attempts, self._attempts)
        if self._is_transient(exc):
            return self._attempts
        return 1

    # 【职责】调用内层 complete，失败时按分类做有界重试（延迟随尝试次数线性增长）。
    def complete(self, *args: Any, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._inner.complete(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - classified below
                if attempt >= self._attempts_for(exc):
                    raise
                delay = self._base_delay * attempt
                print(
                    f"  [llm retry] {type(exc).__name__}; "
                    f"attempt {attempt}/{self._attempts_for(exc)}, retrying in {delay:.0f}s",
                    flush=True,
                )
                self._sleep(delay)
