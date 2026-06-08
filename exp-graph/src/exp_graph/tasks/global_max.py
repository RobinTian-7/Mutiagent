"""Minimal generic protocol task: global maximum over sharded integers.

This adapter exists to prove the generalized ProtocolRunner/ProtocolTaskAdapter
engine runs a NON-count_frequency task end-to-end. It deliberately keeps the
per-agent belief tiny: each belief carries a single running maximum in
``structured_state={"task_name": "global_max", "max": <int>}`` and mirrors it in
``consensus_key=str(<int>)``. Merging is just ``max`` over the old belief and the
maxima carried by inbox messages, so a topology that lets information reach the
answer holder converges to the global maximum.
"""

from __future__ import annotations

import json
from typing import Any

from exp_graph.agents.schemas import BeliefState, BeliefStatus
from exp_graph.messaging import OutboxMessage
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter

GLOBAL_MAX_TASK_NAME = "global_max"


def _parse_int(value: Any) -> int | None:
    """Best-effort parse of an int from arbitrary JSON-ish input."""
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is an int subclass; treat as not-a-max-value to avoid surprises.
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text or text.upper() in {"UNKNOWN", "NONE", "NULL"}:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def _max_from_structured_state(value: Any) -> int | None:
    """Extract the running max from a global_max structured_state dict."""
    if not isinstance(value, dict):
        return None
    if value.get("task_name") != GLOBAL_MAX_TASK_NAME:
        return None
    return _parse_int(value.get("max"))


class GlobalMaxTaskAdapter(ProtocolTaskAdapter):
    """Find the maximum of a list of ints sharded across agents."""

    task_name = GLOBAL_MAX_TASK_NAME

    # ------------------------------------------------------------------ #
    # Base TaskAdapter methods
    # ------------------------------------------------------------------ #
    def build_global_task(self, *, values: list[int], **kwargs: Any) -> dict[str, Any]:
        ints = [int(value) for value in values]
        if not ints:
            raise ValueError("global_max requires at least one value")
        answer = max(ints)
        return {
            "task_name": self.task_name,
            "values": ints,
            "n_values": len(ints),
            "answer": answer,
            "answer_key": str(answer),
            "primary_metric_name": "exact_match",
            "description": (
                "Find the global maximum integer across all agents' value shards."
            ),
        }

    def split_into_local_observations(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> list[dict[str, Any]]:
        if n_agents < 1:
            raise ValueError("n_agents must be positive")
        values = [int(value) for value in global_task["values"]]
        observations: list[dict[str, Any]] = []
        base_size, remainder = divmod(len(values), n_agents)
        offset = 0
        for agent_id in range(n_agents):
            shard_size = base_size + (1 if agent_id < remainder else 0)
            shard = values[offset : offset + shard_size]
            observations.append(
                {
                    "task_name": self.task_name,
                    "agent_id": agent_id,
                    "value_shard": shard,
                    "n_agents": n_agents,
                }
            )
            offset += shard_size
        return observations

    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        agent_id = int(local_observation["agent_id"])
        n_agents = int(local_observation["n_agents"])
        shard = [int(value) for value in local_observation.get("value_shard", [])]
        local_max = max(shard) if shard else None
        all_covered = n_agents == 1
        consensus_key = str(local_max) if local_max is not None else "UNKNOWN"
        status = "final" if all_covered and local_max is not None else "candidate"
        if local_max is None:
            proposal = f"Agent {agent_id} has an empty shard (no candidate maximum)."
        elif all_covered:
            proposal = f"Global maximum is {local_max}."
        else:
            proposal = (
                f"Partial maximum from agent {agent_id} is {local_max}; "
                "other shards may hold a larger value."
            )
        return {
            "status": status,
            "proposal": proposal,
            "consensus_key": consensus_key,
            "support": [f"agent {agent_id} shard max={local_max}"],
            "uncertainty": (
                "" if all_covered else "Need maxima from the remaining agents."
            ),
            "open_questions": (
                [] if all_covered else ["Share your shard maximum."]
            ),
            "private_notes": "local shard maximum only",
            "structured_state": {
                "task_name": self.task_name,
                "max": local_max,
            },
        }

    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        parsed = _parse_int(key_or_proposal)
        return str(parsed) if parsed is not None else "UNKNOWN"

    def evaluate_final_answer(
        self,
        global_task: dict[str, Any],
        final_key: str | None,
    ) -> bool:
        return self.normalize_consensus_key(final_key) == str(int(global_task["answer"]))

    def format_task_prompt_context(
        self,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        return (
            f"Task: {global_task['description']}\n"
            f"Total agents: {local_observation['n_agents']}\n"
            f"Your value_shard: {local_observation['value_shard']}\n"
            "Report the maximum integer you can justify from known shards."
        )

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: per-agent belief lifecycle
    # ------------------------------------------------------------------ #
    def initial_protocol_belief(self, local_observation: dict[str, Any]) -> BeliefState:
        return BeliefState(**self.initial_local_solve(local_observation))

    def format_protocol_init_prompt(
        self,
        *,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        task_context = self.format_adjudication_context(global_task)
        local_context = dict(local_observation)
        return f"""You are one agent solving a local Global Maximum shard.

Find the maximum integer in LOCAL_CONTEXT_JSON.value_shard. This is only your
local shard, not necessarily the global maximum.

Rules: output exactly one JSON object and nothing outside it (no markdown
fences, no prose). Put your local maximum in structured_state.max as an integer.

Return belief_state:
{{
  "status": "candidate",
  "proposal": "short local maximum summary",
  "consensus_key": "UNKNOWN",
  "support": ["short"],
  "uncertainty": "need other agents",
  "open_questions": ["share other shard maxima"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "global_max",
    "max": 0
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

LOCAL_CONTEXT_JSON:
{json.dumps(local_context, ensure_ascii=True, sort_keys=True)}

OLD_BELIEF_STATE_JSON:
{{}}

INBOX_JSON:
[]
"""

    def validate_protocol_initial_belief_state(
        self,
        *,
        belief_state: BeliefState,
        local_observation: dict[str, Any],
        global_task: dict[str, Any],
    ) -> BeliefState:
        n_agents = int(local_observation["n_agents"])
        llm_max = _max_from_structured_state(belief_state.structured_state)
        if llm_max is None:
            llm_max = _parse_int(belief_state.consensus_key)
        if llm_max is None:
            shard = [int(value) for value in local_observation.get("value_shard", [])]
            llm_max = max(shard) if shard else None
        if llm_max is None:
            raise ValueError(
                "global_max initial belief must provide structured_state.max"
            )
        all_covered = n_agents == 1
        return belief_state.model_copy(
            update={
                "status": (
                    BeliefStatus.FINAL if all_covered else BeliefStatus.CANDIDATE
                ),
                "consensus_key": str(llm_max),
                "structured_state": {
                    "task_name": self.task_name,
                    "max": llm_max,
                },
            }
        )

    def merge_protocol_inbox(
        self,
        *,
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        global_task: dict[str, Any],
    ) -> BeliefState:
        current_max = _max_from_structured_state(old_belief_state.structured_state)
        if current_max is None:
            current_max = _parse_int(old_belief_state.consensus_key)
        for message in inbox:
            message_max = _max_from_structured_state(message.structured_payload)
            if message_max is None:
                message_max = _parse_int(message.consensus_key)
            if message_max is None:
                continue
            current_max = (
                message_max if current_max is None else max(current_max, message_max)
            )
        return self._belief_from_max(current_max, global_task=global_task)

    def format_protocol_merge_prompt(
        self,
        *,
        merge_mode: str,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
        old_belief_state: BeliefState,
        inbox: list[OutboxMessage],
        deterministic_belief: BeliefState | None = None,
    ) -> str:
        task_context = self.format_adjudication_context(global_task)
        old_max = _max_from_structured_state(old_belief_state.structured_state)
        inbox_maxes = [
            _max_from_structured_state(message.structured_payload)
            if _max_from_structured_state(message.structured_payload) is not None
            else _parse_int(message.consensus_key)
            for message in inbox
        ]
        verified_max = (
            _max_from_structured_state(deterministic_belief.structured_state)
            if deterministic_belief is not None
            else None
        )
        return f"""You are a Global Maximum protocol solver. Goal: the maximum
integer across all agents' shards.

Mode={merge_mode}. Combine OLD_MAX_JSON with the neighbor maxima in
INBOX_MAXES_JSON by taking the largest integer. Do not invent values.

Rules: output exactly one JSON object and nothing outside it. Put the running
maximum in structured_state.max as an integer. Always set consensus_key to the
same integer as a string.

Return belief_state:
{{
  "status": "candidate",
  "proposal": "short",
  "consensus_key": "0",
  "support": ["short"],
  "uncertainty": "short",
  "open_questions": ["short"],
  "private_notes": "short",
  "structured_state": {{
    "task_name": "global_max",
    "max": 0
  }}
}}

TASK_CONTEXT_JSON:
{json.dumps(task_context, ensure_ascii=True, sort_keys=True)}

OLD_MAX_JSON:
{json.dumps(old_max)}

INBOX_MAXES_JSON:
{json.dumps(inbox_maxes)}

VERIFIED_MAX_JSON:
{json.dumps(verified_max)}
"""

    def apply_verified_protocol_merge(
        self,
        *,
        llm_belief_state: BeliefState,
        verified_belief_state: BeliefState,
    ) -> BeliefState:
        # Keep the LLM's wording but trust the verified (deterministic) maximum.
        return BeliefState(
            status=verified_belief_state.status,
            proposal=llm_belief_state.proposal or verified_belief_state.proposal,
            consensus_key=verified_belief_state.consensus_key,
            support=llm_belief_state.support or verified_belief_state.support,
            uncertainty=(
                llm_belief_state.uncertainty
                if llm_belief_state.uncertainty
                else verified_belief_state.uncertainty
            ),
            open_questions=(
                []
                if verified_belief_state.status == BeliefStatus.FINAL
                else (
                    llm_belief_state.open_questions
                    or verified_belief_state.open_questions
                )
            ),
            private_notes=llm_belief_state.private_notes,
            confidence=llm_belief_state.confidence,
            structured_state=verified_belief_state.structured_state,
        )

    def validate_protocol_belief_state(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
        transport_belief_state: BeliefState | None = None,
    ) -> BeliefState:
        llm_max = _max_from_structured_state(belief_state.structured_state)
        if llm_max is None:
            llm_max = _parse_int(belief_state.consensus_key)
        if llm_max is None and transport_belief_state is not None:
            llm_max = _max_from_structured_state(
                transport_belief_state.structured_state
            )
        if llm_max is None:
            raise ValueError(
                "global_max belief must provide structured_state.max as an integer"
            )
        return belief_state.model_copy(
            update={
                "consensus_key": str(llm_max),
                "structured_state": {
                    "task_name": self.task_name,
                    "max": llm_max,
                },
            }
        )

    # ------------------------------------------------------------------ #
    # ProtocolTaskAdapter: answer extraction / scoring / metrics
    # ------------------------------------------------------------------ #
    def extract_protocol_answer(self, belief_state: BeliefState) -> int | None:
        answer = _max_from_structured_state(belief_state.structured_state)
        if answer is None:
            answer = _parse_int(belief_state.consensus_key)
        return answer

    def protocol_answer_key(self, answer: Any) -> str:
        parsed = _parse_int(answer)
        return str(parsed) if parsed is not None else "UNKNOWN"

    def score_protocol_answer(
        self, answer: Any, global_task: dict[str, Any]
    ) -> dict[str, Any]:
        parsed = _parse_int(answer)
        if parsed is None:
            return {"primary_metric": 0.0, "exact_match": False}
        exact = parsed == int(global_task["answer"])
        return {"primary_metric": 1.0 if exact else 0.0, "exact_match": exact}

    def compute_protocol_agent_metrics(
        self,
        *,
        belief_state: BeliefState,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> dict[str, Any]:
        answer = self.extract_protocol_answer(belief_state)
        global_answer = int(global_task["answer"])
        parsed = _parse_int(answer)
        exact = parsed is not None and parsed == global_answer
        # Honest coverage proxy: this belief reflects the full answer only once it
        # has seen the global maximum. Until then it carries strictly partial info.
        coverage = 1.0 if exact else 0.0
        return {
            "belief_max": parsed,
            "coverage_ratio": coverage,
            "primary_metric": 1.0 if exact else 0.0,
            "exact_match": exact,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _belief_from_max(
        self,
        current_max: int | None,
        *,
        global_task: dict[str, Any],
    ) -> BeliefState:
        if current_max is None:
            return BeliefState(
                status=BeliefStatus.CANDIDATE,
                proposal="No candidate maximum is known yet.",
                consensus_key="UNKNOWN",
                support=[],
                uncertainty="Need at least one shard maximum.",
                open_questions=["Share your shard maximum."],
                private_notes="global_max merge state (empty)",
                structured_state={"task_name": self.task_name, "max": None},
            )
        return BeliefState(
            status=BeliefStatus.CANDIDATE,
            proposal=f"Running maximum across known shards is {current_max}.",
            consensus_key=str(current_max),
            support=[f"running_max={current_max}"],
            uncertainty="Unmerged shards could still hold a larger value.",
            open_questions=["Share any larger shard maximum."],
            private_notes="global_max merge state",
            structured_state={"task_name": self.task_name, "max": current_max},
        )

    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "description": global_task["description"],
            "n_values": global_task["n_values"],
        }
