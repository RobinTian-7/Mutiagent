"""Final aggregation for Count Frequency protocol experiments."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState
from exp_graph.tasks.count_frequency import (
    CountFrequencyTaskAdapter,
    canonicalize_counts,
    count_frequency_consensus_key,
    compute_rmse,
    normalized_l1_error,
)


class CFHeadResult(BaseModel):
    """One final aggregation head for CF counts."""

    method: str
    final_counts: dict[str, float | int] = Field(default_factory=dict)
    final_counts_rounded: dict[str, int] | None = None
    included_agents: list[int] = Field(default_factory=list)
    supporting_agents: list[int] = Field(default_factory=list)
    top_ratio: float | None = None
    mean_coverage: float | None = None
    rmse: float
    normalized_l1_error: float
    exact_match: bool


class CFProtocolFinalResult(BaseModel):
    """Final result with vote and average heads recorded in parallel."""

    final_key: str
    final_counts: dict[str, int]
    selected_primary: str
    aggregation_method: str
    rmse: float
    normalized_l1_error: float
    exact_match: bool
    vote: CFHeadResult
    average: CFHeadResult | None = None
    vote_average_disagreement_rmse: float | None = None
    answer_agent_ids: list[int] = Field(default_factory=list)


def run_cf_final_aggregation(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: CountFrequencyTaskAdapter,
    topology_name: str,
    star_center: int = 0,
    average_include_min_coverage: float = 1.0,
    selected_primary: str = "topology_default",
    answer_agent_ids_override: list[int] | None = None,
) -> CFProtocolFinalResult:
    """Run holder/vote and average aggregation over final CF agent states."""
    if answer_agent_ids_override is None:
        answer_agent_ids = answer_agents_for_topology(
            topology_name=topology_name,
            n_agents=len(agent_states),
            star_center=star_center,
        )
    else:
        answer_agent_ids = normalize_answer_agent_ids(
            answer_agent_ids_override,
            n_agents=len(agent_states),
        )
    vote = build_vote_head(
        agent_states=agent_states,
        agent_ids=answer_agent_ids,
        global_task=global_task,
        task_adapter=task_adapter,
    )
    average = build_average_head(
        agent_states=agent_states,
        global_task=global_task,
        task_adapter=task_adapter,
        min_coverage=average_include_min_coverage,
    )

    primary = choose_primary(
        topology_name=topology_name,
        selected_primary=selected_primary,
        average=average,
    )
    if primary == "average" and average is not None:
        final_counts = canonicalize_counts(average.final_counts_rounded or {})
        method = "average"
    else:
        final_counts = canonicalize_counts(vote.final_counts)
        primary = "vote"
        method = vote.method

    domain = task_adapter.count_domain_keys(global_task)
    truth = canonicalize_counts(global_task["answer_counts"])
    disagreement = None
    if average is not None and average.final_counts_rounded is not None:
        disagreement = compute_rmse(vote.final_counts, average.final_counts_rounded, domain)

    return CFProtocolFinalResult(
        final_key=count_frequency_consensus_key(final_counts),
        final_counts=final_counts,
        selected_primary=primary,
        aggregation_method=method,
        rmse=compute_rmse(final_counts, truth, domain),
        normalized_l1_error=normalized_l1_error(
            final_counts,
            truth,
            array_size=int(global_task["array_length"]),
            domain_keys=domain,
        ),
        exact_match=final_counts == truth,
        vote=vote,
        average=average,
        vote_average_disagreement_rmse=disagreement,
        answer_agent_ids=answer_agent_ids,
    )


def build_vote_head(
    *,
    agent_states: list[AgentState],
    agent_ids: list[int],
    global_task: dict[str, Any],
    task_adapter: CountFrequencyTaskAdapter,
) -> CFHeadResult:
    domain = task_adapter.count_domain_keys(global_task)
    truth = canonicalize_counts(global_task["answer_counts"])
    groups: dict[str, list[int]] = defaultdict(list)
    counts_by_key: dict[str, dict[str, int]] = {}
    for agent_id in agent_ids:
        counts = task_adapter.extract_protocol_counts(agent_states[agent_id].belief_state)
        key = count_frequency_consensus_key(counts)
        groups[key].append(agent_id)
        counts_by_key[key] = counts

    if not groups:
        final_counts: dict[str, int] = {}
        supporting_agents: list[int] = []
        top_ratio = 0.0
    else:
        top_key, supporting_agents = max(
            groups.items(),
            key=lambda item: (len(item[1]), item[0]),
        )
        final_counts = counts_by_key[top_key]
        top_ratio = len(supporting_agents) / max(1, len(agent_ids))

    return CFHeadResult(
        method="vote",
        final_counts=canonicalize_counts(final_counts),
        final_counts_rounded=None,
        included_agents=agent_ids,
        supporting_agents=sorted(supporting_agents),
        top_ratio=top_ratio,
        mean_coverage=None,
        rmse=compute_rmse(final_counts, truth, domain),
        normalized_l1_error=normalized_l1_error(
            final_counts,
            truth,
            array_size=int(global_task["array_length"]),
            domain_keys=domain,
        ),
        exact_match=canonicalize_counts(final_counts) == truth,
    )


def build_average_head(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: CountFrequencyTaskAdapter,
    min_coverage: float,
) -> CFHeadResult | None:
    domain = task_adapter.count_domain_keys(global_task)
    truth = canonicalize_counts(global_task["answer_counts"])
    metrics_by_agent = [
        task_adapter.compute_protocol_agent_metrics(
            belief_state=state.belief_state,
            global_task=global_task,
            n_agents=len(agent_states),
        )
        for state in agent_states
    ]
    included = [
        idx
        for idx, metrics in enumerate(metrics_by_agent)
        if float(metrics["coverage_ratio"]) >= min_coverage
    ]
    if not included:
        return None

    counts_by_agent = [
        task_adapter.extract_protocol_counts(agent_states[agent_id].belief_state)
        for agent_id in included
    ]
    averaged = {
        key: statistics.fmean(float(counts.get(key, 0)) for counts in counts_by_agent)
        for key in domain
    }
    rounded = canonicalize_counts(
        {key: int(round(value)) for key, value in averaged.items()}
    )
    sparse_average = {
        key: value
        for key, value in averaged.items()
        if value != 0.0
    }
    mean_coverage = statistics.fmean(
        float(metrics_by_agent[agent_id]["coverage_ratio"])
        for agent_id in included
    )
    return CFHeadResult(
        method="average",
        final_counts=sparse_average,
        final_counts_rounded=rounded,
        included_agents=included,
        supporting_agents=[],
        top_ratio=None,
        mean_coverage=mean_coverage,
        rmse=compute_rmse(averaged, truth, domain),
        normalized_l1_error=normalized_l1_error(
            averaged,
            truth,
            array_size=int(global_task["array_length"]),
            domain_keys=domain,
        ),
        exact_match=rounded == truth,
    )


def answer_agents_for_topology(
    *,
    topology_name: str,
    n_agents: int,
    star_center: int,
) -> list[int]:
    topology = topology_name.strip().lower()
    if n_agents <= 0:
        return []
    if topology in {
        "chain",
        "tree",
        "dag_mesh",
        "random",
        "random_dag",
        "static_exponential_dag",
        "two_stage",
        "two_stage_layer",
        "layer_two_stage",
        "balanced_log",
        "balance_log",
        "balanced_log_layer",
        "balance_log_layer",
        "layer_balanced_log",
        "layer_balance_log",
        "one_peer_exponential_dag_tree",
        "one_peer_exponential_dag_star",
        "one_peer_exponential_dag_static",
        "one_peer_exponential_dag_static_exponential_dag",
        "static_exponential_star",
        "static_exponential_sink",
        "static_exponential_dag_star",
        "static_exponential_dag_sink",
        "mesh_star",
        "mesh_sink",
        "mesh_dag_star",
        "mesh_dag_sink",
    }:
        return [n_agents - 1]
    if topology in {"one_peer_exponential_dag", "one_peer_exponential_dag_vote"}:
        return list(range(n_agents))
    if topology == "star":
        return [star_center]
    return list(range(n_agents))


def normalize_answer_agent_ids(agent_ids: list[int], *, n_agents: int) -> list[int]:
    """Return validated unique answer holders in caller-provided order."""
    if n_agents <= 0:
        return []
    normalized: list[int] = []
    seen: set[int] = set()
    for raw_agent_id in agent_ids:
        agent_id = int(raw_agent_id)
        if agent_id < 0 or agent_id >= n_agents:
            raise ValueError(
                f"answer agent id {agent_id} is outside valid range 0..{n_agents - 1}"
            )
        if agent_id not in seen:
            normalized.append(agent_id)
            seen.add(agent_id)
    if not normalized:
        raise ValueError("answer_agent_ids_override must include at least one agent")
    return normalized


def choose_primary(
    *,
    topology_name: str,
    selected_primary: str,
    average: CFHeadResult | None,
) -> str:
    if selected_primary == "average":
        return "average" if average is not None else "vote"
    if selected_primary == "vote":
        return "vote"
    return "vote"
