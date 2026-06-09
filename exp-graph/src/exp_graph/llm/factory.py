"""LLM client factory."""

from __future__ import annotations

import os

from exp_graph.llm.base import LLMClient
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.llm.openai_client import OpenAIChatClient
from exp_graph.llm.timeout import TimeoutLLMClient

#: Env var holding the per-request hard wall-clock budget (seconds) applied to
#: EVERY non-fake client built here. masbench sets it from ``cfg.request_timeout``
#: so engine-internal sites that build their own clients (role clients, the
#: graph-generation candidate evaluator, the insight minister, the
#: ``ProtocolRunner`` fallback) are guarded too -- not just the client a caller
#: explicitly threads in. ``0``/unset disables the guard (back-compat).
WALLCLOCK_TIMEOUT_ENV = "EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT"

_REAL_PROVIDERS = {
    "openai",
    "deepseek",
    "bailian",
    "dashscope",
    "qwen",
    "alibaba",
    "xiaomi",
}


def _wallclock_timeout(timeout_s: float | None) -> float:
    """Resolve the effective wall-clock budget (explicit arg overrides env)."""
    if timeout_s is not None:
        return float(timeout_s)
    try:
        return float(os.environ.get(WALLCLOCK_TIMEOUT_ENV, "0") or 0)
    except ValueError:
        return 0.0


def _guarded(client: LLMClient, timeout_s: float | None) -> LLMClient:
    """Wrap a real client in a hard wall-clock timeout when one is configured."""
    budget = _wallclock_timeout(timeout_s)
    if budget > 0:
        return TimeoutLLMClient(client, budget)
    return client


def create_llm_client(
    provider: str,
    *,
    base_url: str | None = None,
    api_key_env: str | None = None,
    thinking_enabled: bool | None = None,
    timeout_s: float | None = None,
) -> LLMClient:
    """Create an LLM client.

    ``auto`` uses OpenAI when `OPENAI_API_KEY` is available, otherwise the fake
    deterministic client for offline smoke runs.

    Every non-fake client is wrapped in a hard wall-clock
    :class:`~exp_graph.llm.timeout.TimeoutLLMClient` when a budget is configured
    (``timeout_s`` arg or the ``EXP_GRAPH_LLM_WALLCLOCK_TIMEOUT`` env var), so a
    hung provider call fails fast instead of freezing the run -- no matter which
    code path constructed the client. The fake client is never wrapped.
    """
    if provider == "fake":
        return FakeLLMClient()
    if provider in _REAL_PROVIDERS:
        return _guarded(
            OpenAIChatClient(
                base_url=base_url,
                api_key_env=api_key_env,
                platform=provider,
                thinking_enabled=thinking_enabled,
            ),
            timeout_s,
        )
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            return _guarded(
                OpenAIChatClient(thinking_enabled=thinking_enabled), timeout_s
            )
        return FakeLLMClient()
    raise ValueError(
        "provider must be one of: auto, fake, openai, deepseek, bailian, dashscope, qwen, alibaba, xiaomi"
    )
