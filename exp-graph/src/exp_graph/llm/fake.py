"""Deterministic fake LLM client for tests and offline smoke runs."""

from __future__ import annotations

import json
import re
from typing import Any

from exp_graph.llm.base import LLMResponse, LLMUsage, estimate_tokens


class FakeLLMClient:
    """A deterministic client that follows the array-search prompt contract."""

    def complete(self, prompt: str, model_name: str) -> LLMResponse:
        local_observation = _extract_json_block(
            prompt,
            "LOCAL_OBSERVATION_JSON:",
            "OLD_BELIEF_STATE_JSON:",
        )
        old_belief = _extract_json_block(
            prompt,
            "OLD_BELIEF_STATE_JSON:",
            "INBOX_JSON:",
        )
        inbox = _extract_json_block(prompt, "INBOX_JSON:", None)

        belief = _solve_array_search_like(local_observation, old_belief, inbox)
        text = json.dumps(belief)
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
            ),
        )


def _extract_json_block(prompt: str, start_marker: str, end_marker: str | None) -> Any:
    start = prompt.index(start_marker) + len(start_marker)
    if end_marker is None:
        raw = prompt[start:].strip()
    else:
        end = prompt.index(end_marker, start)
        raw = prompt[start:end].strip()
    return json.loads(raw)


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


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
