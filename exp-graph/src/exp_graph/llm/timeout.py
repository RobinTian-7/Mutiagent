"""Per-request hard wall-clock timeout for LLM calls.

A real benchmark run once hung for over an hour on a single stalled provider call
(ESTABLISHED socket, ~0% CPU) routed through a flaky proxy; the OpenAI client's
own httpx timeout never freed it because the proxy trickled keep-alive bytes that
kept resetting the read deadline. ``TimeoutLLMClient`` adds a *hard* wall-clock
budget per ``complete`` call so a hung request fails fast instead of freezing the
whole run.

This guard lives in ``exp_graph`` (not the caller) so it can be applied
**universally at client construction** via :func:`exp_graph.llm.factory.create_llm_client`.
That matters because several engine-internal sites build their own clients
(role clients, the graph-generation candidate evaluator, the LLM insight
minister, and the ``ProtocolRunner`` fallback); wrapping only the client a caller
explicitly threads in would leave those internal calls unguarded.

Why a bare daemon thread (not ``concurrent.futures``): a Python thread cannot be
forcibly killed, so the only way to *abandon* a stuck blocking call is to run it
on a ``daemon=True`` thread and stop waiting via ``join(timeout)``. When we give
up, the worker keeps running in the background but, being a daemon, will NOT
block interpreter exit. A ``ThreadPoolExecutor`` used as a context manager (or
``shutdown(wait=True)``) would re-block on the hung worker at exit, reintroducing
the exact freeze we are trying to eliminate, so it is deliberately avoided here.
"""

from __future__ import annotations

import threading

from exp_graph.llm.base import LLMClient, LLMResponse


class LLMTimeoutError(RuntimeError):
    """Raised when a wrapped LLM ``complete`` call exceeds its time budget."""


class TimeoutLLMClient:
    """Wrap an inner ``LLMClient`` with a per-request hard wall-clock timeout.

    ``complete`` runs the inner call on a daemon thread and waits at most
    ``timeout_s`` seconds for it. If the thread is still alive after the join the
    call is abandoned (the daemon thread keeps running but cannot block process
    exit) and :class:`LLMTimeoutError` is raised. If the inner call finished, its
    return value is passed through and any exception it raised is re-raised
    unchanged. A non-positive or ``None`` ``timeout_s`` disables wrapping and
    delegates straight to the inner client (fakes are instant/deterministic).
    """

    def __init__(self, inner: LLMClient, timeout_s: float | None) -> None:
        self._inner = inner
        self._timeout_s = timeout_s

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        # No budget -> behave exactly like the inner client (no thread, no guard).
        if self._timeout_s is None or self._timeout_s <= 0:
            return self._inner.complete(prompt, model_name, temperature)

        # Holder for the worker's outcome. Lists are mutated in place so the
        # calling thread reads whatever the daemon thread stored before joining.
        result: list[LLMResponse] = []
        error: list[BaseException] = []

        def _run() -> None:
            try:
                result.append(
                    self._inner.complete(prompt, model_name, temperature)
                )
            except BaseException as exc:  # noqa: BLE001 - preserved + re-raised below
                error.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(self._timeout_s)

        if thread.is_alive():
            # Hung call: abandon the daemon thread and fail fast. We do NOT join
            # without a timeout (that would reintroduce the freeze).
            raise LLMTimeoutError(f"LLM call exceeded {self._timeout_s}s")

        if error:
            raise error[0]
        return result[0]
