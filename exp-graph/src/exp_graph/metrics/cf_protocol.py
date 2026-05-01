"""Per-step metrics for CF protocol experiments."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.agents.schemas import AgentState
from exp_graph.aggregator.cf_final import build_average_head, build_vote_head
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter


class CFAgentStepMetric(BaseModel):
    """Per-agent local CF accuracy at one protocol step."""

    step_idx: int
    phase: str
    topology: str
    agent_id: int
    active_sender: bool
    active_receiver: bool
    known_sources: list[int] = Field(default_factory=list)
    known_source_count: int
    known_item_count: int
    coverage_ratio: float
    local_normalized_l1_error: float
    global_normalized_l1_error: float
    normalized_l1_error: float
    local_rmse: float
    global_rmse: float
    rmse: float
    local_exact_match: bool
    global_exact_match: bool
    exact_match: bool
    sent_count: int
    received_count: int


class CFGlobalStepMetric(BaseModel):
    """Global summary of all agent CF metrics at one protocol step."""

    step_idx: int
    phase: str
    topology: str
    mean_coverage: float
    min_coverage: float
    max_coverage: float
    mean_agent_rmse: float
    median_agent_rmse: float
    best_agent_rmse: float
    worst_agent_rmse: float
    mean_agent_global_rmse: float
    median_agent_global_rmse: float
    best_agent_global_rmse: float
    worst_agent_global_rmse: float
    mean_normalized_l1_error: float
    mean_global_normalized_l1_error: float
    exact_match_agents: int
    global_exact_match_agents: int
    full_coverage_agents: int
    vote_top_ratio: float
    vote_rmse: float
    average_rmse: float | None = None


def build_cf_step_metrics(
    *,
    agent_states: list[AgentState],
    global_task: dict[str, Any],
    task_adapter: CountFrequencyTaskAdapter,
    topology_name: str,
    step_idx: int,
    phase: str,
    send_counts: Counter[int],
    receive_counts: Counter[int],
    average_include_min_coverage: float,
) -> tuple[list[CFAgentStepMetric], CFGlobalStepMetric]:
    agent_rows = []
    for agent_id, state in enumerate(agent_states):
        task_metrics = task_adapter.compute_protocol_agent_metrics(
            belief_state=state.belief_state,
            global_task=global_task,
            n_agents=len(agent_states),
        )
        sent_count = int(send_counts.get(agent_id, 0))
        received_count = int(receive_counts.get(agent_id, 0))
        agent_rows.append(
            CFAgentStepMetric(
                step_idx=step_idx,
                phase=phase,
                topology=topology_name,
                agent_id=agent_id,
                active_sender=sent_count > 0,
                active_receiver=received_count > 0,
                known_sources=task_metrics["known_sources"],
                known_source_count=int(task_metrics["known_source_count"]),
                known_item_count=int(task_metrics["known_item_count"]),
                coverage_ratio=float(task_metrics["coverage_ratio"]),
                local_normalized_l1_error=float(
                    task_metrics["local_normalized_l1_error"]
                ),
                global_normalized_l1_error=float(
                    task_metrics["global_normalized_l1_error"]
                ),
                normalized_l1_error=float(task_metrics["normalized_l1_error"]),
                local_rmse=float(task_metrics["local_rmse"]),
                global_rmse=float(task_metrics["global_rmse"]),
                rmse=float(task_metrics["rmse"]),
                local_exact_match=bool(task_metrics["local_exact_match"]),
                global_exact_match=bool(task_metrics["global_exact_match"]),
                exact_match=bool(task_metrics["exact_match"]),
                sent_count=sent_count,
                received_count=received_count,
            )
        )

    vote = build_vote_head(
        agent_states=agent_states,
        agent_ids=list(range(len(agent_states))),
        global_task=global_task,
        task_adapter=task_adapter,
    )
    average = build_average_head(
        agent_states=agent_states,
        global_task=global_task,
        task_adapter=task_adapter,
        min_coverage=average_include_min_coverage,
    )
    global_row = CFGlobalStepMetric(
        step_idx=step_idx,
        phase=phase,
        topology=topology_name,
        mean_coverage=statistics.fmean(row.coverage_ratio for row in agent_rows),
        min_coverage=min(row.coverage_ratio for row in agent_rows),
        max_coverage=max(row.coverage_ratio for row in agent_rows),
        mean_agent_rmse=statistics.fmean(row.rmse for row in agent_rows),
        median_agent_rmse=statistics.median(row.rmse for row in agent_rows),
        best_agent_rmse=min(row.rmse for row in agent_rows),
        worst_agent_rmse=max(row.rmse for row in agent_rows),
        mean_agent_global_rmse=statistics.fmean(
            row.global_rmse for row in agent_rows
        ),
        median_agent_global_rmse=statistics.median(
            row.global_rmse for row in agent_rows
        ),
        best_agent_global_rmse=min(row.global_rmse for row in agent_rows),
        worst_agent_global_rmse=max(row.global_rmse for row in agent_rows),
        mean_normalized_l1_error=statistics.fmean(
            row.normalized_l1_error for row in agent_rows
        ),
        mean_global_normalized_l1_error=statistics.fmean(
            row.global_normalized_l1_error for row in agent_rows
        ),
        exact_match_agents=sum(1 for row in agent_rows if row.exact_match),
        global_exact_match_agents=sum(
            1 for row in agent_rows if row.global_exact_match
        ),
        full_coverage_agents=sum(1 for row in agent_rows if row.coverage_ratio >= 1.0),
        vote_top_ratio=vote.top_ratio or 0.0,
        vote_rmse=vote.rmse,
        average_rmse=average.rmse if average is not None else None,
    )
    return agent_rows, global_row
