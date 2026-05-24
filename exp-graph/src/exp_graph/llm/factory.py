"""LLM client factory."""

from __future__ import annotations

import os

from exp_graph.llm.base import LLMClient
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.llm.openai_client import OpenAIChatClient


def create_llm_client(
    provider: str,
    *,
    base_url: str | None = None,
    api_key_env: str | None = None,
    thinking_enabled: bool | None = None,
) -> LLMClient:
    """Create an LLM client.

    ``auto`` uses OpenAI when `OPENAI_API_KEY` is available, otherwise the fake
    deterministic client for offline smoke runs.
    """
    if provider == "fake":
        return FakeLLMClient()
    if provider == "openai":
        return OpenAIChatClient(
            base_url=base_url,
            api_key_env=api_key_env,
            platform=provider,
            thinking_enabled=thinking_enabled,
        )
    if provider in {"deepseek", "bailian", "dashscope", "qwen", "alibaba"}:
        return OpenAIChatClient(
            base_url=base_url,
            api_key_env=api_key_env,
            platform=provider,
            thinking_enabled=thinking_enabled,
        )
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIChatClient(thinking_enabled=thinking_enabled)
        return FakeLLMClient()
    raise ValueError(
        "provider must be one of: auto, fake, openai, deepseek, bailian, dashscope, qwen, alibaba"
    )
