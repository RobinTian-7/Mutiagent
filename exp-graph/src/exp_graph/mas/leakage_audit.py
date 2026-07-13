"""Leakage audit for model-visible prompts.

Every prompt the Silo evaluation sends to an LLM (architect graph prompts,
soldier init/merge prompts, minister/classifier contexts) must pass this
audit. It forbids (case-insensitively) the tokens that would leak the answer
key, the benchmark's stated optimal topology, or a copyable fixed-topology
construction into model context:

``expected_output``/``expected_outputs``/``answer_key``/``ground_truth``,
``optimal_topology``/``optimal_message_count``, the benchmark's
``Communication Protocol`` section, and the fixed-arm construction vocabulary
``one_peer``/``exponential``/``distance-doubling``/``pow2``.

The real Silo task statements contain none of these tokens (checked across
the shipped benchmark files), so an audit failure always means OUR pipeline
re-introduced a leak -- fail loud, never send.
"""
# ============================================================
# 【模块导读】模型可见提示词的泄漏审计。任何要发给 LLM 的 Silo 提示词都必须
# 先通过本审计：禁止出现答案键、基准标注的最优拓扑、Communication Protocol
# 原文段落、以及可复制的固定拓扑构造词汇(one_peer/exponential/
# distance-doubling/pow2)。真实 Silo 题面不含这些 token，故审计失败一定意味着
# 我们的流水线重新引入了泄漏——宁可失败也不发送。
# ============================================================

from __future__ import annotations

# 中文：统一的禁令 token 表（大小写不敏感）。测试与运行时审计共用同一份，
#   保证"测试通过"与"运行期真正发送的提示词干净"是同一命题。
# One shared, case-insensitive forbidden-token list for both tests and the
# runtime audit, so "tests pass" and "sent prompts are clean" are the same claim.
FORBIDDEN_PROMPT_TOKENS: tuple[str, ...] = (
    "expected_output",
    "expected_outputs",
    "answer_key",
    "ground_truth",
    "optimal_topology",
    "optimal_message_count",
    "communication protocol",
    "one_peer",
    "distance-doubling",
    "pow2",
    "exponential",
)


class PromptLeakageError(ValueError):
    """A model-visible prompt contains a forbidden leakage token."""


# 【职责】返回提示词中命中的禁令 token 列表（空列表 = 干净）。
def find_leakage_tokens(
    prompt: str,
    *,
    allowed_tokens: tuple[str, ...] | list[str] = (),
) -> list[str]:
    lowered = prompt.lower()
    allowed = {str(token).lower() for token in allowed_tokens}
    return [
        token
        for token in FORBIDDEN_PROMPT_TOKENS
        if token in lowered and token not in allowed
    ]


# 【职责】断言提示词干净；命中任何禁令 token 即抛 PromptLeakageError（绝不发送）。
def assert_prompt_clean(
    prompt: str,
    *,
    context: str = "prompt",
    allowed_tokens: tuple[str, ...] | list[str] = (),
) -> str:
    """Raise :class:`PromptLeakageError` if the prompt contains a leak.

    Returns the prompt unchanged so call sites can wrap prompt construction:
    ``client.complete(assert_prompt_clean(build_prompt(...)))``.
    """
    hits = find_leakage_tokens(prompt, allowed_tokens=allowed_tokens)
    if hits:
        raise PromptLeakageError(
            f"leakage audit failed for {context}: forbidden tokens {hits}"
        )
    return prompt
