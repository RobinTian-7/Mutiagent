"""Metrics summaries for topology-effect experiments."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from exp_graph.aggregator.final_reducer import FinalResult
from exp_graph.configs.runtime import ExperimentConfig
from exp_graph.tasks.base import TaskAdapter


class MetricsSummary(BaseModel):
    """One compact metrics record for an experiment run."""

    task_name: str
    topology_name: str
    n_agents: int
    seed: int
    max_rounds: int
    final_accuracy: bool
    consensus_reached: bool
    rounds_to_consensus: int | None = None
    total_model_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_token_cost: int
    final_result_summary: dict[str, Any]
    per_round_top_key: list[str | None] = Field(default_factory=list)
    per_round_top_ratio: list[float] = Field(default_factory=list)
    per_round_active_key_count: list[int] = Field(default_factory=list)


def build_metrics_summary(
    *,
    config: ExperimentConfig,
    global_task: dict[str, Any],
    task_adapter: TaskAdapter,
    final_result: FinalResult,
    round_logs: list[Any],
) -> MetricsSummary:
    """Build a metrics summary from immutable experiment outputs."""
    total_prompt_tokens = sum(int(log.prompt_tokens) for log in round_logs)
    total_completion_tokens = sum(int(log.completion_tokens) for log in round_logs)
    total_model_calls = sum(int(log.model_calls) for log in round_logs)

    final_accuracy = task_adapter.evaluate_final_answer(
        global_task,
        final_result.final_key,
    )
    rounds_to_consensus = (
        final_result.round_idx
        if final_result.consensus_reached
        else None
    )

    return MetricsSummary(
        task_name=str(global_task.get("task_name", task_adapter.task_name)),
        topology_name=config.topology_name,
        n_agents=config.n_agents,
        seed=config.seed,
        max_rounds=config.max_rounds,
        final_accuracy=final_accuracy,
        consensus_reached=final_result.consensus_reached,
        rounds_to_consensus=rounds_to_consensus,
        total_model_calls=total_model_calls,
        total_prompt_tokens=total_prompt_tokens,
        total_completion_tokens=total_completion_tokens,
        total_token_cost=total_prompt_tokens + total_completion_tokens,
        final_result_summary=final_result.model_dump(),
        per_round_top_key=[log.consensus.top_key for log in round_logs],
        per_round_top_ratio=[log.consensus.top_ratio for log in round_logs],
        per_round_active_key_count=[
            len(log.consensus.active_keys) for log in round_logs
        ],
    )
