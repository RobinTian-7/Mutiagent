"""Bounded retry for TRANSIENT connection failures on real-LLM clients.

A single network blip (``openai.APIConnectionError`` after the SDK's own
retries) killed round-3C's paired eval at 32/72 runs: ``verify_evolve.py`` is
the frozen judgment target, its eval pool has no per-run isolation, so the
pipeline client absorbs transient failures instead.

Scope is deliberately narrow:
* Only connection-class errors are retried (matched by exception-type NAME
  anywhere in the MRO, so no hard dependency on openai/httpx imports).
* The wall-clock guard's ``LLMTimeoutError`` keeps its fail-fast semantics
  (its abandoned worker thread may still hold a connection; piling retries on
  top re-creates the freeze the guard exists to prevent).
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
        if type(exc).__name__ == "LLMTimeoutError":
            return False
        return any(t.__name__ in TRANSIENT_ERROR_NAMES for t in type(exc).__mro__)

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(1, self._attempts + 1):
            try:
                return self._inner.complete(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - classified below
                if attempt >= self._attempts or not self._is_transient(exc):
                    raise
                delay = self._base_delay * attempt
                print(
                    f"  [llm retry] transient {type(exc).__name__}; "
                    f"attempt {attempt}/{self._attempts}, retrying in {delay:.0f}s",
                    flush=True,
                )
                self._sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover
