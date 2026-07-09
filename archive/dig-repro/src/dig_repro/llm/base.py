"""LLM client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class UsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 0


class LLMResponse(BaseModel):
    text: str
    usage: UsageStats = UsageStats()


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, *, model_name: str, temperature: float) -> LLMResponse:
        ...

