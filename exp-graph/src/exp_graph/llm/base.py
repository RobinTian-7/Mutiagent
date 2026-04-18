"""LLM client interfaces and usage accounting."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMUsage(BaseModel):
    """Token/call accounting for one model invocation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMResponse(BaseModel):
    """Raw text plus usage from an LLM client."""

    text: str
    usage: LLMUsage = LLMUsage()


class LLMClient(Protocol):
    """Minimal synchronous LLM interface."""

    def complete(self, prompt: str, model_name: str) -> LLMResponse:
        """Return a JSON-only completion for a prompt."""
        ...


def estimate_tokens(text: str) -> int:
    """Cheap token estimate for accounting when provider usage is unavailable."""
    return max(1, len(text.split()))
