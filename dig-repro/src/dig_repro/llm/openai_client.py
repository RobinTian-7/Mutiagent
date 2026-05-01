"""OpenAI client wrapper."""

from __future__ import annotations

from dig_repro.llm.base import LLMClient, LLMResponse, UsageStats


class OpenAIClient(LLMClient):
    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install dig-repro with the [openai] extra.") from exc
        self._client = OpenAI()

    def complete(self, prompt: str, *, model_name: str, temperature: float) -> LLMResponse:
        response = self._client.responses.create(
            model=model_name,
            temperature=temperature,
            input=prompt,
        )
        text = getattr(response, "output_text", "")
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            usage=UsageStats(
                prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                model_calls=1,
            ),
        )

