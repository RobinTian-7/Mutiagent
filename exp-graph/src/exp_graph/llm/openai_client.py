"""OpenAI-backed LLM client."""

from __future__ import annotations

from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens


class OpenAIChatClient:
    """Small OpenAI chat-completions wrapper.

    The dependency is optional so tests can run without network access or API
    keys. Use this client for real LLM-backed experiments.
    """

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install exp-graph[openai] to use OpenAIChatClient") from exc
        self._client = OpenAI()

    def complete(self, prompt: str, model_name: str) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or "{}"
        usage = response.usage
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", estimate_tokens(prompt)),
                completion_tokens=getattr(usage, "completion_tokens", estimate_tokens(text)),
            ),
        )
