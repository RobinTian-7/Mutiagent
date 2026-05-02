"""Deterministic fake LLM client for tests and offline smoke runs."""

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


EMPEROR_PROMPT_MARKER = "EMPEROR_PLANNING_PROMPT_V1"
EMPEROR_RETRY_PROMPT_MARKER = "EMPEROR_PLANNING_RETRY_PROMPT_V1"
SUBORDINATE_PROMPT_MARKER = "SUBORDINATE_DISPATCH_PROMPT_V1"


class FakeLLMClient:
    """A deterministic client for offline topology and runner smoke tests."""

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        if EMPEROR_PROMPT_MARKER in prompt or EMPEROR_RETRY_PROMPT_MARKER in prompt:
            return _build_emperor_planning_response(prompt)
        if SUBORDINATE_PROMPT_MARKER in prompt:
            return _build_subordinate_dispatch_response(prompt)

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


def _build_emperor_planning_response(prompt: str) -> LLMResponse:
    """Produce a deterministic emperor plan from a planning prompt."""
    constraints = _extract_optional_json_block(
        prompt, "PLANNING_CONSTRAINTS_JSON:"
    ) or {}
    task = _extract_optional_json_block(
        prompt, "TASK_DESCRIPTION_JSON:"
    ) or {}

    array_length = 0
    for key in ("array_length", "array_size", "n_items", "length"):
        if key in task:
            try:
                array_length = int(task[key])
                break
            except (TypeError, ValueError):
                pass
    if not array_length and isinstance(task.get("array"), list):
        array_length = len(task["array"])

    max_depth = int(constraints.get("max_depth", 4))
    max_n_agents = int(constraints.get("max_n_agents", 64))
    max_fanout_per_layer = int(constraints.get("max_fanout_per_layer", 32))

    if array_length <= 0:
        candidate_fanout = [4]
        rationale = "no array length found; defaulting to a small flat star"
    elif array_length <= 256:
        candidate_fanout = [4]
        rationale = (
            f"array_length={array_length} is small; one flat layer of "
            "soldiers minimises rounds"
        )
    elif array_length <= 2048:
        candidate_fanout = [8]
        rationale = (
            f"array_length={array_length} is moderate; flat layer of 8 "
            "soldiers balances rounds and cost"
        )
    elif array_length <= 8192:
        candidate_fanout = [2, 4]
        rationale = (
            f"array_length={array_length} is larger; one minister layer "
            "groups 8 soldiers and limits emperor fan-in"
        )
    else:
        candidate_fanout = [4, 4]
        rationale = (
            f"array_length={array_length} is large; deeper hierarchy keeps "
            "per-node fan-in manageable"
        )

    candidate_fanout = _clamp_fanout(
        candidate_fanout,
        max_depth=max_depth,
        max_n_agents=max_n_agents,
        max_fanout_per_layer=max_fanout_per_layer,
    )

    payload = {
        "fanout_schedule": candidate_fanout,
        "split_strategy": "equal_shard_by_index",
        "rationale": rationale,
        "dispatch": None,
    }
    text = json.dumps(payload)
    return LLMResponse(
        text=text,
        usage=LLMUsage(
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(text),
        ),
    )


def _clamp_fanout(
    fanout: list[int],
    *,
    max_depth: int,
    max_n_agents: int,
    max_fanout_per_layer: int,
) -> list[int]:
    """Clip fanout to satisfy the emperor planning constraints."""
    if max_depth < 2:
        max_depth = 2
    cleaned = [
        max(1, min(int(value), max(1, max_fanout_per_layer)))
        for value in fanout
    ]
    cleaned = cleaned[: max(1, max_depth - 1)]
    while cleaned and _expected_total(cleaned) > max_n_agents:
        last = cleaned[-1]
        if last > 1:
            cleaned[-1] = last - 1
        else:
            cleaned.pop()
    if not cleaned:
        cleaned = [1]
    return cleaned


def _expected_total(fanout: list[int]) -> int:
    sizes = [1]
    for value in fanout:
        sizes.append(sizes[-1] * int(value))
    return sum(sizes)


def _build_subordinate_dispatch_response(prompt: str) -> LLMResponse:
    """Produce a deterministic equal-split subordinate dispatch."""
    parent = _extract_optional_json_block(prompt, "AGENT_SELF_JSON:") or {}
    parent_slice = _extract_optional_json_block(prompt, "ASSIGNED_SLICE_JSON:") or {}
    children = _extract_optional_json_block(prompt, "CHILDREN_JSON:") or []

    start = int(parent_slice.get("start", 0))
    end = int(parent_slice.get("end", 0))
    length = max(0, end - start)
    n_children = len(children) if isinstance(children, list) else 0

    children_payload: dict[str, Any] = {}
    if n_children > 0:
        base, remainder = divmod(length, n_children)
        cursor = start
        for idx, child in enumerate(children):
            size = base + (1 if idx < remainder else 0)
            child_start = cursor
            child_end = cursor + size
            cursor = child_end
            agent_id = int(child.get("agent_id"))
            is_leaf = bool(child.get("is_leaf"))
            entry: dict[str, Any] = {
                "instruction": (
                    f"Count array[{child_start}:{child_end})."
                    if is_leaf
                    else f"Oversee array[{child_start}:{child_end})."
                ),
            }
            if is_leaf:
                entry["shard"] = [child_start, child_end]
            else:
                entry["slice"] = [child_start, child_end]
            children_payload[f"agent_{agent_id}"] = entry

    parent_id = parent.get("agent_id", "?")
    payload = {
        "rationale": (
            f"agent {parent_id} splits [{start}:{end}) evenly across "
            f"{n_children} subordinate(s)"
        ),
        "children": children_payload,
    }
    text = json.dumps(payload)
    return LLMResponse(
        text=text,
        usage=LLMUsage(
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(text),
        ),
    )


def _extract_optional_json_block(prompt: str, marker: str) -> Any:
    if marker not in prompt:
        return None
    start = prompt.index(marker) + len(marker)
    raw = prompt[start:].lstrip()
    try:
        payload, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        return None
    return payload


def _extract_json_block(prompt: str, start_marker: str, end_marker: str | None) -> Any:
    start = prompt.index(start_marker) + len(start_marker)
    if end_marker is None:
        raw = prompt[start:].strip()
    else:
        end = prompt.index(end_marker, start)
        raw = prompt[start:end].strip()
    return json.loads(raw)


def _extract_first_json_block(
    prompt: str,
    marker_pairs: list[tuple[str, str | None]],
) -> Any:
    for start_marker, end_marker in marker_pairs:
        if start_marker in prompt:
            return _extract_json_block(prompt, start_marker, end_marker)
    raise ValueError(f"none of the markers were found: {marker_pairs}")


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


def _select_lowest_found_key(keys: list[str]) -> str:
    parsed = []
    for key in keys:
        match = re.fullmatch(r"FOUND:(\d+)", key)
        if match:
            parsed.append((int(match.group(1)), key))
    return min(parsed)[1] if parsed else keys[0]


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


def _merge_cf_state_into_partials(
    partials: dict[str, dict[str, int]],
    text: Any,
) -> None:
    payload = parse_cf_state_payload(str(text or ""))
    if not payload:
        return
    for agent_id, counts in payload["partials"].items():
        partials[str(agent_id)] = counts


def _merge_cf_structured_into_partials(
    partials: dict[str, dict[str, int]],
    value: Any,
) -> None:
    structured = extract_cf_structured_state(value)
    if structured is None:
        return
    for agent_id, counts in structured["partials"].items():
        partials[str(agent_id)] = counts


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
            # With answer-level artifacts there is no source-level breakdown, so
            # overlapping aggregate answers cannot be safely added.
            continue
        total = _add_counts(total, counts)
        covered_sources.update(source_set)
    return canonicalize_counts(total), sorted(covered_sources)


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


def _add_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left)
    for key, count in canonicalize_counts(right).items():
        merged[key] = int(merged.get(key, 0)) + int(count)
    return canonicalize_counts(merged)


def _join_nonempty(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
