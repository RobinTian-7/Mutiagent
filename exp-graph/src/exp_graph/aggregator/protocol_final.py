"""Generic, task-agnostic final aggregation (vote-only) for protocol runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState


class ProtocolFinalResult(BaseModel):
    """Task-agnostic final aggregation result."""

    final_key: str
    final_answer: Any = None
    selected_primary: str = "vote"
    aggregation_method: str = "vote"
    primary_metric: float = 0.0          # task-defined; higher-is-better for success-rate tasks
    exact_match: bool = False
    supporting_agents: list[int] = Field(default_factory=list)
    answer_agent_ids: list[int] = Field(default_factory=list)
    top_ratio: float | None = None


class _VoteAdapter(Protocol):
    def extract_protocol_answer(self, belief_state: Any) -> Any: ...
    def protocol_answer_key(self, answer: Any) -> str: ...
    def score_protocol_answer(self, answer: Any, global_task: dict[str, Any]) -> dict[str, Any]: ...


def run_protocol_vote_aggregation(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: _VoteAdapter,
    answer_agent_ids: list[int],
) -> ProtocolFinalResult:
    """Group the holders' answers by canonical key, pick the majority, score it."""
    groups: dict[str, list[int]] = defaultdict(list)
    answer_by_key: dict[str, Any] = {}
    for agent_id in answer_agent_ids:
        answer = task_adapter.extract_protocol_answer(agent_states[agent_id].belief_state)
        key = task_adapter.protocol_answer_key(answer)
        groups[key].append(agent_id)
        answer_by_key[key] = answer

    if not groups:
        scored = task_adapter.score_protocol_answer(None, global_task)
        return ProtocolFinalResult(
            final_key="UNKNOWN", final_answer=None, primary_metric=float(scored.get("primary_metric", 0.0)),
            exact_match=bool(scored.get("exact_match", False)),
            answer_agent_ids=list(answer_agent_ids), top_ratio=0.0,
        )

    top_key, supporting = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
    answer = answer_by_key[top_key]
    scored = task_adapter.score_protocol_answer(answer, global_task)
    return ProtocolFinalResult(
        final_key=top_key,
        final_answer=answer,
        selected_primary="vote",
        aggregation_method="vote",
        primary_metric=float(scored.get("primary_metric", 0.0)),
        exact_match=bool(scored.get("exact_match", False)),
        supporting_agents=sorted(supporting),
        answer_agent_ids=list(answer_agent_ids),
        top_ratio=len(supporting) / max(1, len(answer_agent_ids)),
    )
