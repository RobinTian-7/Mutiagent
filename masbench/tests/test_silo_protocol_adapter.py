"""Tests for SiloProtocolAdapter: a BenchmarkInstance behind the protocol engine."""

from __future__ import annotations

from exp_graph.aggregator.protocol_final import ProtocolFinalResult
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter

from masbench.adapters.silo_protocol import SiloProtocolAdapter
from masbench.core.task_bridge import BenchmarkTaskAdapter, private_answer_key
from masbench.core.instance import BenchmarkInstance


def _global_max_instance() -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="I-01",
        case_name="Global Max",
        n_agents=2,
        shards=[[3, 1, 9, 2], [5, 8, 4]],
        ground_truth=9,
        task_prompt=(
            "Find the GLOBAL MAXIMUM across all agents' data. "
            "You are Agent {agent_id} and hold: {input_shard}"
        ),
        meta={"output_type": "distributed"},
    )


def _distributed_sort_instance() -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="silo_bench",
        case_id="III-21",
        case_name="Distributed Sort",
        n_agents=2,
        shards=[[3, 1], [4, 2]],
        ground_truth=[1, 2, 3, 4],
        task_prompt=(
            "Return the globally sorted ascending list of all agents' values. "
            "You are Agent {agent_id} and hold: {input_shard}"
        ),
        meta={"output_type": "distributed"},
    )


def test_silo_is_protocol_adapter():
    inst = _global_max_instance()
    adapter = SiloProtocolAdapter(inst)

    # MRO: it is both a generic protocol adapter and a benchmark task adapter.
    assert isinstance(adapter, ProtocolTaskAdapter)
    assert isinstance(adapter, BenchmarkTaskAdapter)

    # Inherited base TaskAdapter behaviour still works through BenchmarkTaskAdapter.
    global_task = adapter.build_global_task()
    assert private_answer_key(global_task) == "9"
    assert "answer_key" not in global_task
    assert global_task["case_id"] == "I-01"
    assert global_task["n_agents"] == 2


def test_silo_protocol_runs_through_protocol_runner_reduce():
    inst = _global_max_instance()
    adapter = SiloProtocolAdapter(inst)
    global_task = adapter.build_global_task()

    config = ProtocolRunnerConfig(
        topology_name="mesh_star",
        n_agents=2,
        merge_mode="deterministic",
        init_mode="deterministic",
    )
    runner = ProtocolRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
    )
    result = runner.run()

    assert isinstance(result.final_result, ProtocolFinalResult)
    # Associative-reduce case (max) converges offline on a topology whose holder
    # has full coverage.
    assert result.final_result.final_key == "9"
    assert result.final_result.exact_match is True


def test_silo_protocol_nonreduce_no_crash():
    inst = _distributed_sort_instance()
    adapter = SiloProtocolAdapter(inst)
    global_task = adapter.build_global_task()

    config = ProtocolRunnerConfig(
        topology_name="mesh_star",
        n_agents=2,
        merge_mode="deterministic",
        init_mode="deterministic",
    )
    runner = ProtocolRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
    )
    result = runner.run()

    # No deterministic offline solver for general sort: it must still run end to
    # end and produce a valid final result (success may be False offline).
    assert isinstance(result.final_result, ProtocolFinalResult)
