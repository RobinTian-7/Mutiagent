"""Capability-floor diagnostics that are not competitive benchmark arms."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from exp_graph.llm.base import LLMClient

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.engine import run_fixed_protocol


def full_information_single_agent_instance(
    instance: BenchmarkInstance,
) -> BenchmarkInstance:
    """Collapse all ordered private shards into one agent without changing truth."""
    if all(isinstance(shard, list) for shard in instance.shards):
        full_shard: Any = [
            value
            for shard in instance.shards
            for value in shard
        ]
    else:
        full_shard = list(instance.shards)
    meta = dict(instance.meta)
    meta.update(
        {
            "num_agents": 1,
            "expected_outputs": [instance.ground_truth],
            "capability_diagnostic": "full_information_single_agent",
            "original_n_agents": instance.n_agents,
        }
    )
    return BenchmarkInstance(
        benchmark=instance.benchmark,
        case_id=instance.case_id,
        case_name=instance.case_name,
        n_agents=1,
        shards=[full_shard],
        ground_truth=instance.ground_truth,
        task_prompt=instance.task_prompt,
        meta=meta,
    )


def run_full_information_single_agent(
    instance: BenchmarkInstance,
    cfg: RunConfig,
    *,
    llm_client: LLMClient | None = None,
) -> ScoreResult:
    """Test whether one worker can solve the task when communication is removed."""
    diagnostic = full_information_single_agent_instance(instance)
    diagnostic_cfg = replace(
        cfg,
        use_planner=False,
        n_agents=1,
        silo_eval_mode="all_agents",
    )
    score = run_fixed_protocol(
        diagnostic,
        diagnostic_cfg,
        topology="tree",
        llm_client=llm_client,
    )
    score.extra.update(
        {
            "diagnostic": "full_information_single_agent",
            "original_n_agents": instance.n_agents,
        }
    )
    return score
