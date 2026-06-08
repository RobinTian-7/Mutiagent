"""Per-request hard-timeout wrapper for masbench LLM calls (Plan 5 Task 1).

A real ``masbench bench`` once hung 91 minutes on a single stalled OpenAI call
(ESTABLISHED socket, 0% CPU); the OpenAI client's own httpx timeout never freed
it. ``TimeoutLLMClient`` adds a hard wall-clock guard that abandons such a hung
call on a daemon thread and raises ``LLMTimeoutError`` so the run fails fast.
"""

from __future__ import annotations

import time

from exp_graph.llm.base import LLMResponse, LLMUsage

from masbench.llm.timeout import LLMTimeoutError, TimeoutLLMClient


class SlowClient:
    """Inner client that blocks longer than the wrapper's timeout."""

    def complete(self, prompt, model_name, temperature=None) -> LLMResponse:
        time.sleep(2)
        return LLMResponse(text="{}", usage=LLMUsage())


class FastClient:
    """Inner client that returns immediately; records the args it saw."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.response = LLMResponse(
            text='{"answer": 1}',
            usage=LLMUsage(prompt_tokens=3, completion_tokens=2),
        )

    def complete(self, prompt, model_name, temperature=None) -> LLMResponse:
        self.calls.append((prompt, model_name, temperature))
        return self.response


class BoomClient:
    """Inner client whose ``complete`` raises a domain error."""

    def complete(self, prompt, model_name, temperature=None) -> LLMResponse:
        raise ValueError("boom")


def test_slow_call_times_out_fast():
    # A 2s inner call wrapped with a 0.2s budget must raise LLMTimeoutError and
    # return well before the inner call would have finished (the hung daemon
    # thread is abandoned, not awaited).
    start = time.perf_counter()
    client = TimeoutLLMClient(SlowClient(), 0.2)
    try:
        client.complete("p", "m")
    except LLMTimeoutError as exc:
        elapsed = time.perf_counter() - start
        assert elapsed < 1.5, f"timed-out call blocked {elapsed:.3f}s (should be ~0.2s)"
        assert "0.2" in str(exc)
    else:
        raise AssertionError("expected LLMTimeoutError")


def test_fast_call_returns_inner_response_unchanged():
    inner = FastClient()
    client = TimeoutLLMClient(inner, 5)
    out = client.complete("hello", "gpt-x", temperature=0.5)
    assert out is inner.response
    assert out.text == '{"answer": 1}'
    assert out.usage.prompt_tokens == 3
    # Args are forwarded verbatim to the inner client.
    assert inner.calls == [("hello", "gpt-x", 0.5)]


def test_inner_exception_is_reraised_not_swallowed():
    client = TimeoutLLMClient(BoomClient(), 5)
    try:
        client.complete("p", "m")
    except ValueError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected the inner ValueError to propagate")


def test_zero_timeout_delegates_straight_through():
    inner = FastClient()
    client = TimeoutLLMClient(inner, 0)
    out = client.complete("p", "m", temperature=0.0)
    assert out is inner.response
    assert inner.calls == [("p", "m", 0.0)]


def test_none_timeout_delegates_straight_through():
    inner = FastClient()
    client = TimeoutLLMClient(inner, None)
    out = client.complete("p", "m")
    assert out is inner.response
    assert inner.calls == [("p", "m", None)]
