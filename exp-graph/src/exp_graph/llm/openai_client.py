"""OpenAI-backed LLM client."""

from __future__ import annotations

import os

from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens


def _is_reasoning_model(model_name: str) -> bool:
    """Models that reject an explicit sampling temperature."""

    name = model_name.lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _supports_reasoning_effort(model_name: str) -> bool:
    return model_name.lower().startswith("gpt-5")


class OpenAIChatClient:
    """Small OpenAI chat-completions wrapper.

    The dependency is optional so tests can run without network access or API
    keys. Use this client for real LLM-backed experiments.
    """

    def __init__(self, *, reasoning_effort: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install exp-graph[openai] to use OpenAIChatClient") from exc
        timeout = float(os.environ.get("OPENAI_TIMEOUT", "120"))
        max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))
        self._client = OpenAI(timeout=timeout, max_retries=max_retries)
        # gpt-5-family reasoning effort; the CF workloads are mechanical
        # structured merges, so the default is the cheapest tier.
        self._reasoning_effort = (
            reasoning_effort
            or os.environ.get("OPENAI_REASONING_EFFORT")
            or "minimal"
        )

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        request: dict = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        if _is_reasoning_model(model_name):
            # Reasoning models only accept the default temperature; sending
            # an explicit one is a hard 400.
            if _supports_reasoning_effort(model_name):
                request["reasoning_effort"] = self._reasoning_effort
        else:
            request["temperature"] = 0.0 if temperature is None else temperature
        response = self._client.chat.completions.create(**request)
        text = response.choices[0].message.content or "{}"
        usage = response.usage
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", estimate_tokens(prompt)),
                completion_tokens=getattr(usage, "completion_tokens", estimate_tokens(text)),
            ),
        )
