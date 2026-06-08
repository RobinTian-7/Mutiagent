"""Generic bridge: a BenchmarkInstance -> an exp_graph TaskAdapter."""

from __future__ import annotations

import json
from typing import Any

import masbench  # noqa: F401  (ensures exp_graph is importable)
from exp_graph.tasks.base import TaskAdapter

from masbench.core.instance import BenchmarkInstance

GROUND_TRUTH_KEY = "answer_key"  # blocked by format_adjudication_context


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_answer(value: Any) -> str:
    """Canonical string form of an answer for grouping and exact-match.

    Numbers, lists, and dicts are normalized via canonical JSON. Numeric or
    JSON-looking strings are parsed first so that "9" and 9, or "[3, 1]" and
    [3, 1], compare equal. Python-style booleans ("True"/"False") are folded to
    JSON booleans ("true"/"false"). Empty/unknown sentinels collapse to ``UNKNOWN``.
    """
    if value is None:
        return "UNKNOWN"
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() in {"UNKNOWN", "NONE", "NULL"}:
            return "UNKNOWN"
        if text.lower() in {"true", "false"}:
            return _dumps(text.lower() == "true")
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
        return _dumps(parsed)
    return _dumps(value)


class BenchmarkTaskAdapter(TaskAdapter):
    """Wrap one BenchmarkInstance behind the exp_graph 6-method interface."""

    def __init__(self, instance: BenchmarkInstance) -> None:
        self.instance = instance
        self.task_name = f"benchmark::{instance.benchmark}::{instance.case_id}"

    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        # kwargs are accepted to satisfy the base signature; unused in Plan 1.
        inst = self.instance
        return {
            "task_name": self.task_name,
            "benchmark": inst.benchmark,
            "case_id": inst.case_id,
            "case_name": inst.case_name,
            "n_agents": inst.n_agents,
            "shards": list(inst.shards),
            "task_prompt": inst.task_prompt,
            "meta": dict(inst.meta),
            "output_type": inst.meta.get("output_type", "scalar"),
            # Per-agent (segmented) vs single-shared-answer task. The engine reads
            # this to decide whether to grade per agent or by the voted answer.
            "segmented": inst.segmented,
            GROUND_TRUTH_KEY: canonical_answer(inst.ground_truth),
        }

    def split_into_local_observations(
        self, global_task: dict[str, Any], n_agents: int
    ) -> list[dict[str, Any]]:
        shards = global_task["shards"]
        if n_agents != len(shards):
            raise ValueError(
                f"benchmark instance has {len(shards)} shards but n_agents={n_agents}; "
                "benchmark instances are pre-sharded and cannot be re-split"
            )
        return [
            {
                "task_name": global_task["task_name"],
                "benchmark": global_task["benchmark"],
                "case_id": global_task["case_id"],
                "agent_id": agent_id,
                "n_agents": n_agents,
                "input_shard": shards[agent_id],
            }
            for agent_id in range(n_agents)
        ]

    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        agent_id = int(local_observation["agent_id"])
        shard = local_observation["input_shard"]
        size = len(shard) if isinstance(shard, (list, tuple, str, dict)) else 1
        return {
            "status": "unknown",
            "proposal": (
                f"Agent {agent_id} holds a private shard (size {size}). "
                "The global answer is not yet known."
            ),
            "consensus_key": "UNKNOWN",
            "support": [f"agent {agent_id} local shard size={size}"],
            "uncertainty": "Need information from other agents for the global answer.",
            "open_questions": ["What do other agents' shards contribute?"],
            "private_notes": "local shard only",
        }

    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        return canonical_answer(key_or_proposal)

    def evaluate_final_answer(
        self, global_task: dict[str, Any], final_key: str | None
    ) -> bool:
        return self.normalize_consensus_key(final_key) == global_task[GROUND_TRUTH_KEY]

    def format_task_prompt_context(
        self, global_task: dict[str, Any], local_observation: dict[str, Any]
    ) -> str:
        agent_id = local_observation["agent_id"]
        shard_json = json.dumps(local_observation["input_shard"], ensure_ascii=True)
        template = global_task["task_prompt"] or f"Task: {global_task['case_name']}"
        had_shard_token = "{input_shard}" in template
        rendered = template.replace("{agent_id}", str(agent_id)).replace(
            "{input_shard}", shard_json
        )
        lines = [rendered, f"Total agents: {local_observation['n_agents']}"]
        if had_shard_token:
            lines.append(f"You are agent {agent_id}.")
        else:
            lines.append(f"You are agent {agent_id}. Your private shard: {shard_json}")
        return "\n".join(lines) + "\n"

    def format_consensus_key_instructions(self) -> str:
        return (
            "Put your current best GLOBAL answer in consensus_key as a compact "
            "canonical value (a JSON number, string, list, or object). Use "
            "UNKNOWN if you cannot yet determine the global answer."
        )

    def describe_task(self) -> str:
        """Short task brief for the graph-generating planner.

        Gives the emperor the ACTUAL task semantics (e.g. "Global Max: find the
        global maximum...") instead of exp_graph's hardcoded count_frequency
        notes. Placeholders are stripped and the text collapsed/truncated to keep
        the prompt compact. ``plan_free_graph`` picks this up duck-typed.
        """
        inst = self.instance
        prompt = (inst.task_prompt or "").replace("{agent_id}", "<id>").replace(
            "{input_shard}", "<shard>"
        )
        prompt = " ".join(prompt.split())
        brief = f"{inst.case_name}: {prompt}" if prompt else inst.case_name
        return brief[:400]

    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        # Base blocks answer/answer_key/ground_truth/label/...; also drop raw shards.
        base = super().format_adjudication_context(global_task)
        return {key: value for key, value in base.items() if key != "shards"}
