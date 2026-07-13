"""LLM client interfaces and usage accounting."""
# ============================================================
# 【模块导读】LLM 客户端接口与用量(token 计数)统计。
# - LLMUsage：单次模型调用的 token/调用次数记账。
# - combine_usage：合并首次调用与各次重试调用的用量。
# - LLMResponse：LLM 客户端返回的原始文本 + 用量。
# - LLMClient：最小同步 LLM 接口(Protocol)。
# - estimate_tokens：供应商未返回用量时的粗略 token 估算兜底。
# ============================================================

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


# 【职责】单次模型调用的用量(token 计数)记账。
# - prompt_tokens/completion_tokens：提示与补全 token 数；model_calls：模型调用次数(默认 1)。
class LLMUsage(BaseModel):
    """Token/call accounting for one model invocation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# 【职责】合并多次调用的用量(token 计数)，逐字段求和。
# - 典型场景：合并首次调用与各次重试调用产生的用量。
def combine_usage(usages: list[LLMUsage]) -> LLMUsage:
    """Combine usage from an initial call and any retry calls."""
    return LLMUsage(
        prompt_tokens=sum(usage.prompt_tokens for usage in usages),
        completion_tokens=sum(usage.completion_tokens for usage in usages),
        model_calls=sum(usage.model_calls for usage in usages),
    )


# 【职责】承载 LLM 客户端返回的原始文本与用量(token 计数)。
# - text：原始文本；usage：用量；raw_responses/raw_prompts：原始应答与原始提示列表。
class LLMResponse(BaseModel):
    """Raw text plus usage from an LLM client."""

    text: str
    usage: LLMUsage = LLMUsage()
    raw_responses: list[str] = Field(default_factory=list)
    raw_prompts: list[str] = Field(default_factory=list)


# 【职责】最小同步 LLM 接口(Protocol)，所有客户端实现的统一契约。
class LLMClient(Protocol):
    """Minimal synchronous LLM interface."""

    # 【职责】对给定提示返回补全结果；json_mode(默认)约束仅输出 JSON 对象，
    #   json_mode=False 走自由文本(PythonGen 架构师需返回原始 Python 源码)。
    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        """Return a completion for a prompt.

        With ``json_mode`` (the default) the provider is constrained to emit a
        single JSON object, which every existing caller relies on. Set
        ``json_mode=False`` for free-form text output — the PythonGen architect
        and repair calls need raw Python source, not a JSON object.
        """
        ...


# 【职责】廉价 token 估算：供应商未返回用量(token 计数)时的记账兜底。
# - 按空白分词计数，至少返回 1。
def estimate_tokens(text: str) -> int:
    """Cheap token estimate for accounting when provider usage is unavailable."""
    return max(1, len(text.split()))
