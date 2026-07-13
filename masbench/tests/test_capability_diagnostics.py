from __future__ import annotations

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.diagnostics import (
    full_information_single_agent_instance,
    run_full_information_single_agent,
)


def _instance() -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",
        case_name="Global Max",
        n_agents=2,
        shards=[[3, 1], [9, 2]],
        ground_truth=9,
        task_prompt="Find the maximum. Your data: {input_shard}",
        meta={
            "num_agents": 2,
            "output_type": "scalar",
            "expected_outputs": [9, 9],
        },
    )


def test_full_information_diagnostic_collapses_shards_and_solves_offline() -> None:
    collapsed = full_information_single_agent_instance(_instance())
    assert collapsed.n_agents == 1
    assert collapsed.shards == [[3, 1, 9, 2]]
    score = run_full_information_single_agent(
        _instance(),
        RunConfig(llm_provider="fake", model_name="fake"),
    )
    assert score.success is True
    assert score.extra["diagnostic"] == "full_information_single_agent"
