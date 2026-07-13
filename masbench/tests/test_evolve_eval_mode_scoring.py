from __future__ import annotations

from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.evolve import _run_fixed_one
from masbench.llm.fake import BenchmarkFakeLLMClient


def _global_max_instance() -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",
        case_name="Global Max",
        n_agents=2,
        shards=[[3], [9]],
        ground_truth=9,
        task_prompt="Find the maximum over all private shards.\nYour data: {input_shard}\n",
        meta={
            "num_agents": 2,
            "is_segmented": False,
            "output_type": "scalar",
            "expected_outputs": [9, 9],
        },
    )


def _cfg(goal: str) -> RunConfig:
    return RunConfig(
        n_agents=2,
        llm_provider="fake",
        model_name="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        silo_eval_mode=goal,
        task_feature_source="heuristic",
    )


def test_evolution_evidence_uses_configured_all_agent_scorer() -> None:
    instance = _global_max_instance()
    client = BenchmarkFakeLLMClient()

    sink = _run_fixed_one(
        instance,
        _cfg("sink"),
        topology="chain",
        seed=0,
        llm_client=client,
    )
    all_agents = _run_fixed_one(
        instance,
        _cfg("all_agents"),
        topology="chain",
        seed=0,
        llm_client=client,
    )

    # Agent 1 (the chain sink) sees both local maxima and is correct. Agent 0
    # retains 3, so the same run passes sink scoring but must fail paper S=1.
    assert sink["ExactMatchRate"] == 1.0
    assert all_agents["ExactMatchRate"] == 0.0
    assert all_agents["paper_S"] == 0.5
    assert all_agents["per_agent_correct"] == [False, True]
    assert sink["evolution_stage"] == "success"
    assert sink["mean_primary_loss"] == 0.0
    assert all_agents["evolution_stage"] == "coverage"
    assert all_agents["structural_coverage"] == 0.5
    assert all_agents["mean_primary_loss"] == 0.9
