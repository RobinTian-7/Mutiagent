"""LLM client factory."""

from __future__ import annotations

import os

from exp_graph.llm.base import LLMClient
from exp_graph.llm.fake import FakeLLMClient
from exp_graph.llm.openai_client import OpenAIChatClient


def create_llm_client(provider: str) -> LLMClient:
    """Create an LLM client.

    ``auto`` uses OpenAI when `OPENAI_API_KEY` is available, otherwise the fake
    deterministic client for offline smoke runs.
    """
    if provider == "fake":
        return FakeLLMClient()
    if provider == "openai":
        return OpenAIChatClient()
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIChatClient()
        return FakeLLMClient()
    raise ValueError("provider must be one of: auto, fake, openai")
