"""Transient-connection retry for real-LLM clients.

Round-3C's paired eval crashed at 32/72 runs on a single
``openai.APIConnectionError`` (the SDK's own retries exhausted by a network
blip): verify_evolve's eval phase is the frozen judgment target and has no
per-run isolation, so the PIPELINE client must absorb transient connection
failures. Retry is bounded (3 attempts, linear backoff) and applies ONLY to
connection-class errors -- a deliberate ``LLMTimeoutError`` from the wall-clock
guard keeps its fail-fast semantics, and real API errors (auth, bad request)
propagate immediately.
"""
import pytest

from masbench.llm.retry import RetryLLMClient


class _Boom(Exception):
    pass


class APIConnectionError(Exception):
    """Name-matched like openai.APIConnectionError (no openai import needed)."""


class LLMTimeoutError(Exception):
    """Name-matched like the wall-clock guard's error."""


class _Flaky:
    def __init__(self, failures, exc):
        self.failures = failures
        self.exc = exc
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        return f"ok after {self.calls}"


def test_transient_error_is_retried_with_backoff():
    sleeps: list[float] = []
    inner = _Flaky(2, APIConnectionError("connection error"))
    client = RetryLLMClient(inner, attempts=3, base_delay=2.0, sleep=sleeps.append)
    assert client.complete("p") == "ok after 3"
    assert inner.calls == 3
    assert sleeps == [2.0, 4.0]


def test_non_transient_error_propagates_immediately():
    inner = _Flaky(5, _Boom("bad request"))
    client = RetryLLMClient(inner, attempts=3, sleep=lambda s: None)
    with pytest.raises(_Boom):
        client.complete("p")
    assert inner.calls == 1


def test_wallclock_timeout_keeps_fail_fast():
    inner = _Flaky(5, LLMTimeoutError("hard wall-clock timeout"))
    client = RetryLLMClient(inner, attempts=3, sleep=lambda s: None)
    with pytest.raises(LLMTimeoutError):
        client.complete("p")
    assert inner.calls == 1


def test_exhausted_attempts_raise_last_error():
    inner = _Flaky(99, APIConnectionError("still down"))
    client = RetryLLMClient(inner, attempts=3, sleep=lambda s: None)
    with pytest.raises(APIConnectionError):
        client.complete("p")
    assert inner.calls == 3


def test_fake_provider_is_not_wrapped():
    from masbench.core.config import RunConfig
    from masbench.engine import _build_llm_client
    from masbench.llm.fake import BenchmarkFakeLLMClient

    client = _build_llm_client(RunConfig(llm_provider="fake"))
    assert isinstance(client, BenchmarkFakeLLMClient)
