"""Distributed array search task adapter."""

from __future__ import annotations

import random
import re
from typing import Any

from exp_graph.tasks.base import TaskAdapter


class ArraySearchTaskAdapter(TaskAdapter):
    """Task adapter for searching a target in a sharded array."""

    task_name = "distributed_array_search"

    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        """Build a global array-search task.

        Accepted kwargs:
        - array: optional explicit list[int]
        - target: optional target int
        - array_size: generated array length, default 32
        - seed: random seed for generated task, default 0
        - ensure_present: whether generated target is present, default True
        """
        if "array" in kwargs:
            array = list(kwargs["array"])
        else:
            rng = random.Random(kwargs.get("seed", 0))
            array_size = int(kwargs.get("array_size", 32))
            array = [rng.randint(0, 999) for _ in range(array_size)]

        if "target" in kwargs:
            target = int(kwargs["target"])
        else:
            ensure_present = bool(kwargs.get("ensure_present", True))
            rng = random.Random(kwargs.get("seed", 0) + 17)
            if ensure_present and array:
                target = array[rng.randrange(len(array))]
            else:
                target = max(array, default=0) + 1001

        answer_index = next((idx for idx, value in enumerate(array) if value == target), None)
        answer_key = f"FOUND:{answer_index}" if answer_index is not None else "NOT_FOUND"
        return {
            "task_name": self.task_name,
            "array": array,
            "target": target,
            "answer_index": answer_index,
            "answer_key": answer_key,
            "description": (
                "Determine whether target exists in the global array. "
                "If present, return its first global index; otherwise return NOT_FOUND."
            ),
        }

    def split_into_local_observations(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> list[dict[str, Any]]:
        if n_agents < 1:
            raise ValueError("n_agents must be positive")

        array = list(global_task["array"])
        target = int(global_task["target"])
        observations = []
        base_size, remainder = divmod(len(array), n_agents)
        offset = 0
        for agent_id in range(n_agents):
            shard_size = base_size + (1 if agent_id < remainder else 0)
            shard = array[offset : offset + shard_size]
            observations.append(
                {
                    "task_name": self.task_name,
                    "agent_id": agent_id,
                    "array_shard": shard,
                    "global_offset": offset,
                    "target": target,
                    "shard_start": offset,
                    "shard_end_exclusive": offset + shard_size,
                    "n_agents": n_agents,
                }
            )
            offset += shard_size
        return observations

    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        shard = list(local_observation["array_shard"])
        target = int(local_observation["target"])
        offset = int(local_observation["global_offset"])
        agent_id = int(local_observation["agent_id"])

        for local_idx, value in enumerate(shard):
            if value == target:
                global_idx = offset + local_idx
                return {
                    "status": "final",
                    "proposal": f"Target {target} is present at global index {global_idx}.",
                    "consensus_key": f"FOUND:{global_idx}",
                    "support": [
                        f"agent {agent_id} checked shard [{offset}, {offset + len(shard)})",
                        f"local index {local_idx} contains target {target}",
                    ],
                    "uncertainty": "",
                    "open_questions": [],
                    "private_notes": "local shard contains the target",
                }

        return {
            "status": "unknown",
            "proposal": (
                f"Target {target} was not found in my local shard "
                f"[{offset}, {offset + len(shard)})."
            ),
            "consensus_key": "UNKNOWN",
            "support": [
                f"agent {agent_id} checked shard [{offset}, {offset + len(shard)})",
                "target absent from local shard",
            ],
            "uncertainty": "Other shards may still contain the target.",
            "open_questions": ["Did any neighbor find the target?"],
            "private_notes": "local absence is not global absence",
        }

    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        if key_or_proposal is None:
            return "UNKNOWN"

        text = str(key_or_proposal).strip().upper()
        if not text or text in {"NULL", "NONE"}:
            return "UNKNOWN"

        found_match = re.search(r"FOUND\s*:\s*(\d+)", text)
        if found_match:
            return f"FOUND:{int(found_match.group(1))}"

        index_match = re.search(r"GLOBAL\s+INDEX\s+(\d+)", text)
        if index_match and "NOT" not in text:
            return f"FOUND:{int(index_match.group(1))}"

        if "NOT_FOUND" in text or "NOT FOUND" in text:
            return "NOT_FOUND"
        if text == "UNKNOWN":
            return "UNKNOWN"
        return "UNKNOWN"

    def evaluate_final_answer(
        self,
        global_task: dict[str, Any],
        final_key: str | None,
    ) -> bool:
        return self.normalize_consensus_key(final_key) == global_task["answer_key"]

    def format_task_prompt_context(
        self,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        return (
            f"Task: {global_task['description']}\n"
            f"Target: {local_observation['target']}\n"
            f"Your shard global range: "
            f"[{local_observation['shard_start']}, "
            f"{local_observation['shard_end_exclusive']})\n"
            f"Your array_shard: {local_observation['array_shard']}\n"
            "Consensus keys for this task must be one of: "
            "FOUND:<global_index>, NOT_FOUND, UNKNOWN."
        )
