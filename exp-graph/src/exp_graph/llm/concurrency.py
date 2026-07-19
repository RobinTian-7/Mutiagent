"""Process-wide concurrency limiting for real LLM calls.

Concurrent test harnesses (several benchmark case runs in flight, each running
several agents in parallel) multiply in-flight provider requests: 3 concurrent
case runs x ``max_parallel_agents=5`` is already 15 sockets. Providers throttle
by concurrent connections as much as by tokens, and an unbounded fan-out turns
one slow case into a rate-limit storm that poisons every other run in the
process. This module gives the process ONE shared admission gate so the total
number of in-flight LLM calls stays under an explicit cap no matter how many
harness layers fan out above it.

The gate lives in ``exp_graph`` (not the caller) for the same reason the
wall-clock guard does: several engine-internal sites build their own clients
via :func:`exp_graph.llm.factory.create_llm_client`, so wrapping only the
client a caller threads in would leave those internal calls unlimited.

Wrapper ordering law: the limiter must sit OUTSIDE the wall-clock timeout
guard.  ``TimeoutLLMClient`` abandons a hung call on a daemon thread; if the
limiter were inside the guard, the abandoned thread would hold its slot
forever and leak the semaphore toward deadlock.  Outside the guard, a timed-out
call releases its slot immediately (the abandoned daemon may still drain in
the background — a bounded, rare over-admission, never a leak).  Retry
wrappers go outside the limiter so backoff sleeps never hold a slot.
"""
# ============================================================
# 【模块导读】真实 LLM 调用的进程级并发限流。
# 背景：并发测试线束(多个 case 同时跑、每个 case 内多个 agent 并行)会把在途请求数
# 相乘放大——3 个并发 case × max_parallel_agents=5 已是 15 个连接。供应商按并发
# 连接数与 token 双重限流，无界扇出会让一次慢 case 演变为整进程的限流风暴。
# 本模块提供全进程唯一的准入闸门：无论上层线束怎样扇出，总在途调用数不超过显式上限。
# 与墙钟守卫同理，闸门放在 exp_graph 的 create_llm_client 统一接入，覆盖引擎内部
# 自建客户端。包装顺序法则：限流器必须在墙钟守卫之外(被放弃的挂死 daemon 线程
# 不能永久占用信号量槽位)；重试包装在限流器之外(退避睡眠不占槽位)。
# ============================================================

from __future__ import annotations

import os
import threading
from typing import Any

from exp_graph.llm.base import LLMResponse

#: Env var holding the process-wide cap on concurrent in-flight real-LLM
#: calls. Unset/empty/``0`` disables limiting (back-compat). Harness drivers
#: may instead call :func:`configure_global_llm_concurrency` explicitly.
LLM_MAX_CONCURRENCY_ENV = "EXP_GRAPH_LLM_MAX_CONCURRENCY"


class LLMConcurrencyLimiter:
    """Shared admission gate bounding concurrent in-flight LLM calls.

    ``in_flight``/``peak_in_flight`` are observability counters so a harness
    can assert after a run that its configured ceiling was actually respected
    (and actually exercised) instead of trusting the wiring blindly.
    """

    def __init__(self, max_concurrent: int) -> None:
        if (
            isinstance(max_concurrent, bool)
            or not isinstance(max_concurrent, int)
            or max_concurrent < 1
        ):
            raise ValueError("max_concurrent must be a positive integer")
        self._max_concurrent = max_concurrent
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._counter_lock = threading.Lock()
        self._in_flight = 0
        self._peak_in_flight = 0

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def in_flight(self) -> int:
        with self._counter_lock:
            return self._in_flight

    @property
    def peak_in_flight(self) -> int:
        with self._counter_lock:
            return self._peak_in_flight

    def acquire(self) -> None:
        self._semaphore.acquire()
        with self._counter_lock:
            self._in_flight += 1
            if self._in_flight > self._peak_in_flight:
                self._peak_in_flight = self._in_flight

    def release(self) -> None:
        with self._counter_lock:
            self._in_flight -= 1
        self._semaphore.release()

    def __enter__(self) -> "LLMConcurrencyLimiter":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


class ConcurrencyLimitedLLMClient:
    """Wrap an ``LLMClient`` so every ``complete`` holds one limiter slot.

    Arguments pass through ``*args``/``**kwargs`` untouched (mirroring
    ``RetryLLMClient``), so inner clients that predate any new parameter keep
    working and explicit ``json_mode``-style kwargs reach them unchanged.
    """

    def __init__(self, inner: Any, limiter: LLMConcurrencyLimiter) -> None:
        if not isinstance(limiter, LLMConcurrencyLimiter):
            raise TypeError("limiter must be an LLMConcurrencyLimiter")
        self._inner = inner
        self._limiter = limiter

    @property
    def limiter(self) -> LLMConcurrencyLimiter:
        return self._limiter

    def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        with self._limiter:
            return self._inner.complete(*args, **kwargs)


_GLOBAL_LOCK = threading.Lock()
_GLOBAL_LIMITER: LLMConcurrencyLimiter | None = None
_GLOBAL_CONFIGURED = False


def configure_global_llm_concurrency(
    max_concurrent: int | None,
) -> LLMConcurrencyLimiter | None:
    """Set (or disable, with ``None``) the process-wide limiter explicitly.

    An explicit configuration wins over the environment variable and applies
    to clients constructed AFTER the call; already-wrapped clients keep the
    limiter they were built with. Returns the active limiter.
    """

    global _GLOBAL_LIMITER, _GLOBAL_CONFIGURED
    with _GLOBAL_LOCK:
        _GLOBAL_LIMITER = (
            None if max_concurrent is None else LLMConcurrencyLimiter(max_concurrent)
        )
        _GLOBAL_CONFIGURED = True
        return _GLOBAL_LIMITER


def global_llm_limiter() -> LLMConcurrencyLimiter | None:
    """Return the active process-wide limiter, if any.

    Explicit configuration wins; otherwise the limiter is built lazily from
    ``LLM_MAX_CONCURRENCY_ENV`` (unset/empty/``0``/invalid disables limiting).
    The env read happens once — later env changes need an explicit
    :func:`configure_global_llm_concurrency`.
    """

    global _GLOBAL_LIMITER, _GLOBAL_CONFIGURED
    with _GLOBAL_LOCK:
        if _GLOBAL_CONFIGURED:
            return _GLOBAL_LIMITER
        raw = os.environ.get(LLM_MAX_CONCURRENCY_ENV, "").strip()
        try:
            value = int(raw) if raw else 0
        except ValueError:
            value = 0
        _GLOBAL_LIMITER = LLMConcurrencyLimiter(value) if value > 0 else None
        _GLOBAL_CONFIGURED = True
        return _GLOBAL_LIMITER


def maybe_limit_concurrency(client: Any) -> Any:
    """Wrap ``client`` in the global limiter when one is active.

    Identity pass-through when limiting is disabled, so the default
    (unconfigured) path stays byte-identical in behavior.
    """

    limiter = global_llm_limiter()
    if limiter is None:
        return client
    return ConcurrencyLimitedLLMClient(client, limiter)


__all__ = [
    "LLM_MAX_CONCURRENCY_ENV",
    "ConcurrencyLimitedLLMClient",
    "LLMConcurrencyLimiter",
    "configure_global_llm_concurrency",
    "global_llm_limiter",
    "maybe_limit_concurrency",
]
