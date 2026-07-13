"""JSON retry prompts for structured belief-state outputs."""
# ============================================================
# 【模块导读】结构化信念状态(belief state)输出的 JSON 重试提示词。
# - BELIEF_STATE_SCHEMA_HINT：重试时随附给模型的目标 JSON schema 示例。
# - build_json_retry_prompt：JSON 解析/校验失败后构造紧凑的重试提示。
# ============================================================

from __future__ import annotations


BELIEF_STATE_SCHEMA_HINT = """{
  "analysis": {
    "reasoning": "step-by-step reasoning leading to this belief",
    "key_observations": ["short observation"]
  },
  "status": "unknown | candidate | final",
  "proposal": "short answer proposal",
  "consensus_key": "task-specific grouping key | UNKNOWN | null",
  "support": ["short evidence item"],
  "uncertainty": "short uncertainty statement",
  "open_questions": ["short question"],
  "private_notes": "optional short private note",
  "structured_state": {}
}"""


# 【职责】在 JSON 解析或校验失败后构造紧凑的重试提示词。
# - 依次包含：失败说明与重试序号、只输出单个 JSON 对象的要求、目标 schema、
# - 截断后的校验错误(≤1200 字符)与上次非法应答(≤2000 字符)、作为事实来源的原始提示。
def build_json_retry_prompt(
    *,
    original_prompt: str,
    invalid_response: str,
    error_message: str,
    attempt_idx: int,
) -> str:
    """Build a compact retry prompt after JSON parsing or validation fails."""
    return (
        "Your previous response could not be parsed as a valid belief_state JSON object.\n"
        f"Retry attempt: {attempt_idx}\n"
        "Return exactly one JSON object and nothing outside it. No markdown "
        "fences, no prose before or after. Reasoning belongs inside the "
        "`analysis` field of the JSON, not outside.\n"
        "Required schema:\n"
        f"{BELIEF_STATE_SCHEMA_HINT}\n"
        "Validation error:\n"
        f"{_truncate(error_message, 1200)}\n"
        "Invalid previous response:\n"
        f"{_truncate(invalid_response, 2000)}\n"
        "Original task prompt follows. Use it as the source of truth and regenerate "
        "a valid belief_state JSON object.\n"
        "ORIGINAL_PROMPT:\n"
        f"{original_prompt}"
    )


# 【职责】把文本截断到 max_chars 以内，超长时收尾附 "..."。
def _truncate(value: str, max_chars: int) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
