"""Final aggregation after the synchronous runner stops."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState
from exp_graph.aggregator.runtime_consensus import RuntimeConsensusResult
from exp_graph.llm.base import LLMClient
from exp_graph.llm.parser import extract_json_object
from exp_graph.tasks.base import TaskAdapter


UNKNOWN_GROUP = "UNKNOWN"


class AgentFinalState(BaseModel):
    """Compact final state used by the reducer."""

    agent_id: int
    status: str
    proposal: str
    consensus_key: str | None = None
    support: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    confidence: float | None = None


class GroupSummary(BaseModel):
    """Rule-level summary of one candidate answer group."""

    group_key: str
    member_agents: list[int]
    size: int
    size_ratio: float
    status_distribution: dict[str, int]
    representative_proposals: list[str] = Field(default_factory=list)
    merged_support: list[str] = Field(default_factory=list)
    uncertainty_summary: str = ""
    score: float


class RuleSelectionResult(BaseModel):
    """Output from deterministic cross-group selection."""

    selected_group_key: str | None = None
    decision: str
    reason: str
    needs_adjudication: bool = False


class OptionalAdjudicationResult(BaseModel):
    """Structured result from the optional final LLM adjudicator."""

    selected_group_key: str | None = None
    decision: str = "no_consensus"
    reason: str = ""
    confidence: float = 0.0


class FinalResult(BaseModel):
    """Final answer returned by one experiment."""

    final_key: str | None
    final_answer_text: str
    consensus_ratio: float
    consensus_reached: bool
    supporting_agents: list[int] = Field(default_factory=list)
    round_idx: int
    aggregation_method: str


def normalize_key_if_needed(
    key: str | None,
    task_adapter: TaskAdapter | None = None,
) -> str:
    """Normalize a consensus key with the task adapter when available."""
    if task_adapter is None:
        if key is None or str(key).strip() == "":
            return UNKNOWN_GROUP
        return str(key)
    return task_adapter.normalize_consensus_key(key)


def group_candidates(
    final_agent_states: list[AgentState | AgentFinalState],
    task_adapter: TaskAdapter | None = None,
) -> dict[str, list[AgentFinalState]]:
    """Group final agent states by normalized consensus key."""
    groups: dict[str, list[AgentFinalState]] = defaultdict(list)
    for idx, state in enumerate(final_agent_states):
        final_state = _to_agent_final_state(state, fallback_agent_id=idx)
        group_key = normalize_key_if_needed(final_state.consensus_key, task_adapter)
        final_state.consensus_key = group_key
        groups[group_key].append(final_state)
    return dict(groups)


def summarize_group(
    group_key: str,
    agent_states_in_group: list[AgentFinalState],
    num_agents: int,
) -> GroupSummary:
    """Build a compact, rule-friendly summary for one group."""
    status_counts = Counter(state.status for state in agent_states_in_group)
    member_agents = [state.agent_id for state in agent_states_in_group]
    size = len(agent_states_in_group)
    size_ratio = size / num_agents if num_agents else 0.0

    representative_proposals = _first_unique(
        [state.proposal for state in agent_states_in_group],
        limit=3,
        max_len=180,
    )
    merged_support = _first_unique(
        [
            support
            for state in agent_states_in_group
            for support in state.support
        ],
        limit=8,
        max_len=180,
    )
    uncertainties = _first_unique(
        [state.uncertainty for state in agent_states_in_group if state.uncertainty],
        limit=3,
        max_len=160,
    )

    # Keep the first reducer score intentionally simple and continuous across
    # groups. Optional confidence values are logged in agent states, but they do
    # not change the scoring formula unless the experiment explicitly opts into
    # a new reducer.
    score = size_ratio

    return GroupSummary(
        group_key=group_key,
        member_agents=member_agents,
        size=size,
        size_ratio=size_ratio,
        status_distribution=dict(status_counts),
        representative_proposals=representative_proposals,
        merged_support=merged_support,
        uncertainty_summary=" | ".join(uncertainties),
        score=score,
    )


def rule_based_select(
    groups: list[GroupSummary],
    config: Any,
) -> RuleSelectionResult:
    """Select a final group with deterministic, explainable rules."""
    valid_groups = [
        group
        for group in groups
        if group.group_key and group.group_key != UNKNOWN_GROUP
    ]
    if not valid_groups:
        return RuleSelectionResult(
            decision="no_consensus",
            reason="No resolved candidate group is available.",
        )

    sorted_groups = sorted(
        valid_groups,
        key=lambda group: (group.score, group.size_ratio, group.size),
        reverse=True,
    )
    top_1 = sorted_groups[0]
    top_2 = sorted_groups[1] if len(sorted_groups) > 1 else None

    final_accept_threshold = float(getattr(config, "final_accept_threshold", 0.7))
    adjudication_margin = float(getattr(config, "adjudication_margin", 0.1))

    if top_1.size_ratio >= final_accept_threshold:
        return RuleSelectionResult(
            selected_group_key=top_1.group_key,
            decision="accept",
            reason="Top group exceeds final_accept_threshold.",
        )

    if top_2 is None:
        return RuleSelectionResult(
            selected_group_key=top_1.group_key,
            decision="accept",
            reason="Only one resolved candidate group is available.",
        )

    score_gap = top_1.score - top_2.score
    if score_gap > adjudication_margin:
        return RuleSelectionResult(
            selected_group_key=top_1.group_key,
            decision="accept",
            reason="Top group has a clear rule-based score advantage.",
        )

    return RuleSelectionResult(
        decision="no_consensus",
        reason="Top candidate groups are too close for deterministic selection.",
        needs_adjudication=True,
    )


def maybe_run_llm_adjudicator(
    top_groups: list[GroupSummary],
    global_task: dict[str, Any],
    config: Any,
    llm_client: LLMClient | None = None,
    task_adapter: TaskAdapter | None = None,
) -> OptionalAdjudicationResult | None:
    """Optionally run one final LLM adjudication over compact group summaries."""
    if not bool(getattr(config, "use_llm_adjudicator", False)):
        return None
    if llm_client is None:
        return OptionalAdjudicationResult(
            decision="no_consensus",
            reason="LLM adjudication requested but no LLM client was provided.",
        )

    adjudication_context = (
        task_adapter.format_adjudication_context(global_task)
        if task_adapter is not None
        else _safe_adjudication_context(global_task)
    )
    prompt = (
        "You are the final adjudicator for a multi-agent experiment.\n"
        "Choose one candidate group only if the summaries justify it.\n"
        "Return only JSON with keys: selected_group_key, decision, reason, confidence.\n"
        "decision must be accept, reject, or no_consensus.\n"
        f"GLOBAL_TASK_JSON:\n{json.dumps(adjudication_context, sort_keys=True)}\n"
        f"TOP_GROUPS_JSON:\n{json.dumps([group.model_dump() for group in top_groups[:3]], sort_keys=True)}\n"
    )
    response = llm_client.complete(
        prompt,
        model_name=str(getattr(config, "model_name", "default")),
        temperature=float(getattr(config, "temperature", 0.0)),
    )
    try:
        raw = extract_json_object(response.text)
    except (TypeError, ValueError):
        return OptionalAdjudicationResult(
            decision="no_consensus",
            reason="LLM adjudicator did not return valid JSON.",
        )

    selected_key = raw.get("selected_group_key")
    decision = str(raw.get("decision", "no_consensus"))
    confidence = _coerce_confidence(raw.get("confidence"))
    valid_keys = {group.group_key for group in top_groups}
    if selected_key not in valid_keys:
        selected_key = None
        decision = "no_consensus"

    return OptionalAdjudicationResult(
        selected_group_key=selected_key,
        decision=decision,
        reason=str(raw.get("reason", "")),
        confidence=confidence,
    )


def build_final_result(
    *,
    selected_group: GroupSummary | None,
    round_idx: int,
    aggregation_method: str,
) -> FinalResult:
    """Build the public final result object."""
    if selected_group is None:
        return FinalResult(
            final_key=None,
            final_answer_text="No stable consensus was reached.",
            consensus_ratio=0.0,
            consensus_reached=False,
            supporting_agents=[],
            round_idx=round_idx,
            aggregation_method="no_consensus",
        )

    final_answer_text = (
        selected_group.representative_proposals[0]
        if selected_group.representative_proposals
        else f"Consensus key: {selected_group.group_key}"
    )
    return FinalResult(
        final_key=selected_group.group_key,
        final_answer_text=final_answer_text,
        consensus_ratio=selected_group.size_ratio,
        consensus_reached=True,
        supporting_agents=selected_group.member_agents,
        round_idx=round_idx,
        aggregation_method=aggregation_method,
    )


def run_final_reducer(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: TaskAdapter,
    runtime_consensus: RuntimeConsensusResult,
    round_idx: int,
    stopped_by_runtime_consensus: bool,
    config: Any,
    llm_client: LLMClient | None = None,
) -> FinalResult:
    """Run candidate grouping, group merge, and cross-group adjudication once."""
    grouped = group_candidates(agent_states, task_adapter)
    group_summaries = [
        summarize_group(group_key, states, len(agent_states))
        for group_key, states in grouped.items()
    ]
    groups_by_key = {group.group_key: group for group in group_summaries}

    if (
        stopped_by_runtime_consensus
        and runtime_consensus.consensus_reached
        and runtime_consensus.top_key in groups_by_key
        and runtime_consensus.top_key != UNKNOWN_GROUP
    ):
        return build_final_result(
            selected_group=groups_by_key[runtime_consensus.top_key],
            round_idx=round_idx,
            aggregation_method="runtime_consensus",
        )

    rule_result = rule_based_select(group_summaries, config)
    if rule_result.decision == "accept" and rule_result.selected_group_key in groups_by_key:
        return build_final_result(
            selected_group=groups_by_key[rule_result.selected_group_key],
            round_idx=round_idx,
            aggregation_method="rule_based_final",
        )

    if rule_result.needs_adjudication:
        top_groups = sorted(
            [
                group
                for group in group_summaries
                if group.group_key and group.group_key != UNKNOWN_GROUP
            ],
            key=lambda group: group.score,
            reverse=True,
        )[:3]
        adjudication = maybe_run_llm_adjudicator(
            top_groups=top_groups,
            global_task=global_task,
            config=config,
            llm_client=llm_client,
            task_adapter=task_adapter,
        )
        if (
            adjudication is not None
            and adjudication.decision == "accept"
            and adjudication.selected_group_key in groups_by_key
        ):
            return build_final_result(
                selected_group=groups_by_key[adjudication.selected_group_key],
                round_idx=round_idx,
                aggregation_method="llm_final_adjudication",
            )

    return build_final_result(
        selected_group=None,
        round_idx=round_idx,
        aggregation_method="no_consensus",
    )


def _to_agent_final_state(
    state: AgentState | AgentFinalState,
    fallback_agent_id: int,
) -> AgentFinalState:
    if isinstance(state, AgentFinalState):
        return state

    belief = state.belief_state
    agent_id = int(state.local_observation.get("agent_id", fallback_agent_id))
    status = getattr(belief.status, "value", str(belief.status))
    return AgentFinalState(
        agent_id=agent_id,
        status=status,
        proposal=belief.proposal,
        consensus_key=belief.consensus_key,
        support=belief.support,
        uncertainty=belief.uncertainty,
        confidence=belief.confidence,
    )


def _first_unique(items: list[str], *, limit: int, max_len: int) -> list[str]:
    seen = set()
    result = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        if len(value) > max_len:
            value = value[: max_len - 3].rstrip() + "..."
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _safe_adjudication_context(global_task: dict[str, Any]) -> dict[str, Any]:
    blocked_keys = {
        "answer",
        "answer_index",
        "answer_key",
        "expected_answer",
        "ground_truth",
        "label",
    }
    compact = {
        key: value
        for key, value in global_task.items()
        if key not in blocked_keys
    }
    if "array" in compact:
        array = list(compact["array"])
        compact["array_length"] = len(array)
        compact.pop("array", None)
    return compact


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
