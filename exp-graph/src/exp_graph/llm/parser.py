"""JSON parsing helpers for belief-state outputs."""
# ============================================================
# 【模块导读】信念状态(belief state)输出的 JSON 解析辅助。
# - extract_json_object：从 LLM 应答中提取首个 JSON 对象(剥 ``` 围栏、截取 {...})。
# - _loads_with_repair：标准解析失败后才动用 json-repair 做 JSON 修复。
# - parse_belief_state：LLM 应答文本 -> BeliefState 模型。
# ============================================================

from __future__ import annotations

import json
import re

from exp_graph.agents.schemas import BeliefState

try:
    from json_repair import repair_json
# 中文：json-repair 为可选依赖；仅在未安装时走此分支，置 None 表示后续跳过 JSON 修复兜底。
except ImportError:  # pragma: no cover - exercised only without optional package
    repair_json = None


# 【职责】从 LLM 应答中提取第一个 JSON 对象。
# - 先剥去 markdown 的 ``` / ```json 围栏；整体可解析为 dict 则直接返回。
# - 否则截取首个 "{" 到最后一个 "}" 的片段再解析；找不到对象或根不是对象则抛 ValueError。
def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        parsed = _loads_with_repair(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    candidate = stripped[start : end + 1]
    parsed = _loads_with_repair(candidate)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM response JSON root must be an object: {text[:200]}")
    return parsed


# 【职责】解析 JSON：仅在语法解析失败后才使用 json-repair 做 JSON 修复。
# - 依次尝试严格解析、strict=False 宽松解析、repair_json(若已安装)。
# - 全部失败时重新抛出最后一次 JSONDecodeError。
def _loads_with_repair(raw: str):
    """Parse JSON, using json-repair only after syntax parsing fails."""
    last_error: json.JSONDecodeError | None = None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        last_error = exc

    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        last_error = exc

    if repair_json is not None:
        try:
            return repair_json(raw, return_objects=True)
        except Exception:
            pass

    assert last_error is not None
    raise last_error


# 【职责】把 LLM 应答文本解析为 BeliefState(信念状态)。
# - 先提取 JSON 对象，再交由 BeliefState 模型做字段校验。
def parse_belief_state(text: str) -> BeliefState:
    """Parse an LLM response into a BeliefState."""
    return BeliefState(**extract_json_object(text))
