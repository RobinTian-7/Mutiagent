"""Deterministic fake LLM client for tests and offline smoke runs."""
# ============================================================
# 【模块导读】面向测试与离线冒烟运行的离线假客户端(确定性、零成本)。
# 从提示词中按标记(LOCAL_OBSERVATION_JSON: 等)截取 JSON 块，本地规则求解，不调用任何模型：
# - count_frequency 任务：合并各来源的部分计数(可结合归约)，覆盖全部智能体后给出最终答案；
# - 其余任务按数组搜索处理：在本地分片查找目标，或传播旧信念/收件箱中的 FOUND 证据。
# 提示词缺少预期标记或 JSON 非法时直接抛错(ValueError 等)，不做静默兜底。
# ============================================================

from __future__ import annotations

import json
import re
from typing import Any

from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens
from exp_graph.tasks.count_frequency import (
    build_cf_structured_state,
    canonicalize_counts,
    count_frequency_consensus_key,
    counts_to_json,
    encode_cf_state,
    extract_cf_structured_state,
    local_frequency_counts,
    parse_cf_state_payload,
)


# 【职责】离线假客户端(确定性、零成本)：面向离线拓扑与运行器冒烟测试。
class FakeLLMClient:
    """A deterministic client for offline topology and runner smoke tests."""

    # 【职责】从提示中截取本地观测/旧信念状态/收件箱三段 JSON，规则求解并返回信念 JSON。
    # - task_name == "count_frequency" 走计数合并求解，否则走数组搜索求解。
    # - 用量(token 计数)以 estimate_tokens 估算填充。
    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        # json_mode is accepted for interface parity; this deterministic fake
        # always returns a JSON belief object regardless of the flag.
        local_observation = _extract_first_json_block(
            prompt,
            [
                ("LOCAL_OBSERVATION_JSON:", "OLD_BELIEF_STATE_JSON:"),
                ("LOCAL_CONTEXT_JSON:", "OLD_BELIEF_STATE_JSON:"),
            ],
        )
        old_belief = _extract_json_block(
            prompt,
            "OLD_BELIEF_STATE_JSON:",
            "INBOX_JSON:",
        )
        inbox_end_marker = (
            "VERIFIED_MERGE_BELIEF_JSON:"
            if "VERIFIED_MERGE_BELIEF_JSON:" in prompt
            else None
        )
        inbox = _extract_json_block(prompt, "INBOX_JSON:", inbox_end_marker)

        if local_observation.get("task_name") == "count_frequency":
            belief = _solve_count_frequency_like(local_observation, old_belief, inbox)
        else:
            belief = _solve_array_search_like(local_observation, old_belief, inbox)
        text = json.dumps(belief)
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
            ),
        )


# 【职责】截取 start_marker 与 end_marker 之间的文本并按 JSON 解析。
# - end_marker 为 None 时取到提示末尾；标记不存在时 index 抛 ValueError。
def _extract_json_block(prompt: str, start_marker: str, end_marker: str | None) -> Any:
    start = prompt.index(start_marker) + len(start_marker)
    if end_marker is None:
        raw = prompt[start:].strip()
    else:
        end = prompt.index(end_marker, start)
        raw = prompt[start:end].strip()
    return json.loads(raw)


# 【职责】按(起始, 结束)标记对依次尝试，返回第一个命中的 JSON 块。
# - 所有标记都不存在时抛 ValueError：无法解析的提示显式失败，不静默兜底。
def _extract_first_json_block(
    prompt: str,
    marker_pairs: list[tuple[str, str | None]],
) -> Any:
    for start_marker, end_marker in marker_pairs:
        if start_marker in prompt:
            return _extract_json_block(prompt, start_marker, end_marker)
    raise ValueError(f"none of the markers were found: {marker_pairs}")


# 【职责】数组搜索类任务的确定性求解：查本地分片并融合旧信念/收件箱证据。
# - 旧信念或收件箱已有 FOUND:* 共识键 -> 取全局下标最小者，产出 final 信念。
# - 本地分片命中目标 -> 产出 FOUND:<全局下标> 的 final 信念(附分片范围等证据)。
# - 否则返回 unknown/UNKNOWN：仅凭本地缺失不宣称 NOT_FOUND，等待其他分片的证据。
def _solve_array_search_like(
    local_observation: dict[str, Any],
    old_belief: dict[str, Any],
    inbox: list[dict],
) -> dict:
    target = int(local_observation.get("target"))
    shard = list(local_observation.get("array_shard", []))
    offset = int(local_observation.get("global_offset", 0))

    found_keys = []
    support = []
    old_key = str(old_belief.get("consensus_key") or "")
    if old_key.startswith("FOUND:"):
        found_keys.append(old_key)
        support.extend([str(item) for item in old_belief.get("support", [])])

    for message in inbox:
        key = str(message.get("consensus_key") or "")
        if key.startswith("FOUND:"):
            found_keys.append(key)
            support.extend([str(item) for item in message.get("support", [])])

    if found_keys:
        key = _select_lowest_found_key(found_keys)
        index = key.split(":", 1)[1]
        return {
            "status": "final",
            "proposal": f"Neighbor evidence indicates target {target} is at global index {index}.",
            "consensus_key": key,
            "support": _dedupe(support)[:4],
            "uncertainty": "",
            "open_questions": [],
            "private_notes": "propagated found evidence from inbox",
        }

    for local_idx, value in enumerate(shard):
        if value == target:
            global_idx = offset + local_idx
            return {
                "status": "final",
                "proposal": f"Target {target} is present at global index {global_idx}.",
                "consensus_key": f"FOUND:{global_idx}",
                "support": [
                    f"local shard range [{offset}, {offset + len(shard)})",
                    f"local index {local_idx} equals target {target}",
                ],
                "uncertainty": "",
                "open_questions": [],
                "private_notes": "local shard contains target",
            }

    return {
        "status": "unknown",
        "proposal": f"Target {target} was not found in my local shard.",
        "consensus_key": "UNKNOWN",
        "support": [f"checked local shard range [{offset}, {offset + len(shard)})"],
        "uncertainty": "Need evidence from other shards before claiming NOT_FOUND.",
        "open_questions": ["Did any neighbor find the target?"],
        "private_notes": "local absence only",
    }


# 【职责】在多个 FOUND:<下标> 键中选全局下标最小者；无合法格式时退回第一个键。
def _select_lowest_found_key(keys: list[str]) -> str:
    parsed = []
    for key in keys:
        match = re.fullmatch(r"FOUND:(\d+)", key)
        if match:
            parsed.append((int(match.group(1)), key))
    return min(parsed)[1] if parsed else keys[0]


# 【职责】count_frequency 任务的确定性求解：合并各来源的部分计数(可结合归约)。
# - 计数来源：本地分片、旧信念/收件箱消息的结构化状态字段与 proposal 内嵌状态负载。
# - 若发现 cf-outbox-v1 答案工件：改用工件合并路径(来源集不重叠才相加)。
# - 覆盖到全部 n_agents -> final 信念(共识键由计数生成)；否则 candidate 并报告缺失智能体。
def _solve_count_frequency_like(
    local_observation: dict[str, Any],
    old_belief: dict[str, Any],
    inbox: list[dict],
) -> dict:
    agent_id = int(local_observation.get("agent_id", 0))
    n_agents = int(local_observation.get("n_agents", 1))
    shard = [int(value) for value in local_observation.get("array_shard", [])]

    partials: dict[str, dict[str, int]] = {}
    if shard:
        partials[str(agent_id)] = local_frequency_counts(shard)
    _merge_cf_structured_into_partials(partials, old_belief.get("structured_state"))
    _merge_cf_state_into_partials(partials, old_belief.get("proposal"))
    for message in inbox:
        _merge_cf_structured_into_partials(partials, message.get("structured_payload"))
        _merge_cf_state_into_partials(partials, message.get("proposal"))

    artifact_counts, artifact_sources = _merge_cf_answer_artifacts(old_belief, inbox)
    if artifact_sources:
        counts = artifact_counts
        covered_agents = artifact_sources
        # 中文：离线假客户端只输出与要求真实 LLM 相同的紧凑答案形态；
        #   运行时校验会保留隐藏的传输状态。
        # The fake client only outputs the same compact answer shape requested
        # from real LLMs. Runtime validation preserves hidden transport state.
        structured_state = {
            "task_name": "count_frequency",
            "merged_counts": counts,
        }
        state_payload = ""
    else:
        structured_state = build_cf_structured_state(
            partials=partials,
            n_agents=n_agents,
        )
        counts = structured_state["merged_counts"]
        covered_agents = sorted(int(agent) for agent in partials)
        state_payload = encode_cf_state(partials)

    if len(covered_agents) >= n_agents:
        key = count_frequency_consensus_key(counts)
        return {
            "status": "final",
            "proposal": _join_nonempty(
                f"Global frequency counts are {counts_to_json(counts)}.",
                state_payload,
            ),
            "consensus_key": key,
            "support": [
                f"covered_agents={covered_agents}",
                f"counts_json={counts_to_json(counts)}",
            ],
            "uncertainty": "",
            "open_questions": [],
            "private_notes": "merged all known CF partials",
            "structured_state": structured_state,
        }

    missing_agents = [
        agent for agent in range(n_agents) if agent not in set(covered_agents)
    ]
    return {
        "status": "candidate",
        "proposal": _join_nonempty(
            (
                f"Partial frequency counts over agents {covered_agents} are "
                f"{counts_to_json(counts)}."
            ),
            state_payload,
        ),
        "consensus_key": "UNKNOWN",
        "support": [
            f"covered_agents={covered_agents}",
            f"counts_json={counts_to_json(counts)}",
        ],
        "uncertainty": f"Missing partial counts from agents {missing_agents}.",
        "open_questions": ["Share any missing CF partial counts."],
        "private_notes": "partial CF merge state",
        "structured_state": structured_state,
    }


# 【职责】从 proposal 文本解析 CF 状态负载，把各智能体的部分计数并入 partials。
# - 解析不到负载时不做任何事(空操作兜底)。
def _merge_cf_state_into_partials(
    partials: dict[str, dict[str, int]],
    text: Any,
) -> None:
    payload = parse_cf_state_payload(str(text or ""))
    if not payload:
        return
    for agent_id, counts in payload["partials"].items():
        partials[str(agent_id)] = counts


# 【职责】从结构化字段提取 CF 结构化状态并把部分计数并入 partials。
# - 提取结果为 None 时不做任何事。
def _merge_cf_structured_into_partials(
    partials: dict[str, dict[str, int]],
    value: Any,
) -> None:
    structured = extract_cf_structured_state(value)
    if structured is None:
        return
    for agent_id, counts in structured["partials"].items():
        partials[str(agent_id)] = counts


# 【职责】合并旧信念与收件箱中的 cf-outbox-v1 答案工件，返回(规范化总计数, 已覆盖来源)。
def _merge_cf_answer_artifacts(
    old_belief: dict[str, Any],
    inbox: list[dict],
) -> tuple[dict[str, int], list[int]]:
    total: dict[str, int] = {}
    covered_sources: set[int] = set()
    for counts, source_ids in _iter_cf_answer_artifacts(old_belief, inbox):
        source_set = set(source_ids)
        if not source_set:
            continue
        if source_set & covered_sources:
            # 中文：答案级工件没有按来源的细分，来源集重叠的聚合答案无法安全相加，
            #   因此直接跳过。
            # With answer-level artifacts there is no source-level breakdown, so
            # overlapping aggregate answers cannot be safely added.
            continue
        total = _add_counts(total, counts)
        covered_sources.update(source_set)
    return canonicalize_counts(total), sorted(covered_sources)


# 【职责】按“旧信念在前、收件箱消息在后”的顺序收集所有可识别的答案工件。
def _iter_cf_answer_artifacts(
    old_belief: dict[str, Any],
    inbox: list[dict],
) -> list[tuple[dict[str, int], list[int]]]:
    items: list[tuple[dict[str, int], list[int]]] = []
    old_item = _extract_cf_answer_artifact(old_belief)
    if old_item is not None:
        items.append(old_item)
    for message in inbox:
        item = _extract_cf_answer_artifact(message)
        if item is not None:
            items.append(item)
    return items


# 【职责】校验并提取单条 cf-outbox-v1 答案工件 -> (规范化计数, 排序后的来源智能体 ID)。
# - 非 dict、schema_version 不符或 artifact/provenance 形态不对时返回 None(忽略该条)。
def _extract_cf_answer_artifact(value: Any) -> tuple[dict[str, int], list[int]] | None:
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") != "cf-outbox-v1":
        return None
    artifact = value.get("artifact")
    provenance = value.get("provenance")
    if isinstance(artifact, dict) and isinstance(provenance, dict):
        answer = artifact.get("answer")
        source_ids = provenance.get("source_agent_ids")
        if isinstance(answer, dict) and isinstance(source_ids, list):
            return (
                canonicalize_counts(answer),
                sorted(int(source_id) for source_id in source_ids),
            )
    return None


# 【职责】两个计数表逐键相加，右表与合并结果均做规范化。
def _add_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left)
    for key, count in canonicalize_counts(right).items():
        merged[key] = int(merged.get(key, 0)) + int(count)
    return canonicalize_counts(merged)


# 【职责】用空格拼接非空片段。
def _join_nonempty(*parts: str) -> str:
    return " ".join(part for part in parts if part)


# 【职责】保序去重，同时丢弃空字符串。
def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
