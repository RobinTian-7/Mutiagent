"""LLM client interfaces and usage accounting."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    """Token/call accounting for one model invocation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def combine_usage(usages: list[LLMUsage]) -> LLMUsage:
    """Combine usage from an initial call and any retry calls."""
    return LLMUsage(
        prompt_tokens=sum(usage.prompt_tokens for usage in usages),
        completion_tokens=sum(usage.completion_tokens for usage in usages),
        model_calls=sum(usage.model_calls for usage in usages),
    )


class LLMResponse(BaseModel):
    """Raw text plus usage from an LLM client."""

    text: str
    usage: LLMUsage = LLMUsage()
    raw_responses: list[str] = Field(default_factory=list)
    raw_prompts: list[str] = Field(default_factory=list)


class LLMClient(Protocol):
    """Minimal synchronous LLM interface."""

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Return a JSON-only completion for a prompt."""
        ...


def estimate_tokens(text: str) -> int:
    """Cheap token estimate for accounting when provider usage is unavailable."""
    return max(1, len(text.split()))
