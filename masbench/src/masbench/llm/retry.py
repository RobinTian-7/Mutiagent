"""Bounded retry for TRANSIENT connection failures on real-LLM clients.

A single network blip (``openai.APIConnectionError`` after the SDK's own
retries) killed round-3C's paired eval at 32/72 runs: ``verify_evolve.py`` is
the frozen judgment target, its eval pool has no per-run isolation, so the
pipeline client absorbs transient failures instead.

Scope is deliberately narrow:
* Connection-class errors are retried (matched by exception-type NAME
  anywhere in the MRO, so no hard dependency on openai/httpx imports).
* The wall-clock guard's ``LLMTimeoutError`` gets exactly ONE bounded retry
  (phase-3 dev-4: a single sporadic 120s call crashed a whole judge run via
  the frozen eval pool's lack of isolation). One fresh attempt is bounded by
  the same guard; unbounded piling on a wedged endpoint stays forbidden.
* Real API errors (auth, bad request, rate-limit-with-retry-after handled by
  the SDK) propagate immediately.
"""
from __future__ import annotations

import time
from typing import Any, Callable

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


class RetryLLMClient:
    """Wrap an (already timeout-guarded) LLM client with bounded retry."""

    def __init__(
        self,
        inner: Any,
        *,
        attempts: int = 3,
        base_delay: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._attempts = max(1, int(attempts))
        self._base_delay = float(base_delay)
        self._sleep = sleep

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        return any(t.__name__ in TRANSIENT_ERROR_NAMES for t in type(exc).__mro__)

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        return type(exc).__name__ == "LLMTimeoutError"

    def _attempts_for(self, exc: BaseException) -> int:
        if self._is_timeout(exc):
            return min(2, self._attempts)
        if self._is_transient(exc):
            return self._attempts
        return 1

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
