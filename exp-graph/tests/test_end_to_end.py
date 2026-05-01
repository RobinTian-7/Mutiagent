import json
from pathlib import Path

from exp_graph.configs import ExperimentConfig
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import ArraySearchTaskAdapter, CountFrequencyTaskAdapter


def test_minimal_end_to_end_smoke_with_one_peer_exponential(tmp_path) -> None:
    adapter = ArraySearchTaskAdapter()
    global_task = adapter.build_global_task(
        array=[0, 1, 2, 3, 4, 5, 6, 7],
        target=6,
    )
    config = ExperimentConfig(
        topology_name="one_peer_exponential",
        n_agents=8,
        max_rounds=5,
        seed=1,
        llm_provider="fake",
        consensus_threshold=0.8,
        trace_dir=str(tmp_path),
        run_id="smoke-trace",
    )

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.final_result.final_key == "FOUND:6"
    assert result.final_result.consensus_reached is True
    assert result.stop_reason == "runtime_consensus"
    assert result.metrics.stop_reason == "runtime_consensus"
    assert result.metrics.final_accuracy is True
    assert result.metrics.total_model_calls > 0
    assert result.metrics.rounds_to_consensus == result.final_result.round_idx + 1
    assert result.agent_step_traces == []
    assert result.trace_path is not None
    assert "smoke-trace.jsonl" in result.trace_path
    trace_lines = Path(result.trace_path).read_text(encoding="utf-8").splitlines()
    first_trace = json.loads(trace_lines[0])
    assert first_trace["prompt"]
    assert first_trace["raw_prompts"]
    assert first_trace["llm_calls"]
    assert first_trace["llm_calls"][0]["prompt"] == first_trace["raw_prompts"][0]
    assert first_trace["llm_calls"][0]["raw_response"] == first_trace["raw_responses"][0]
    assert len(trace_lines) == result.metrics.total_model_calls
    assert len(result.round_logs) <= 5


def test_topology_switching_does_not_break_trace_or_final_generation() -> None:
    adapter = ArraySearchTaskAdapter()
    global_task = adapter.build_global_task(
        array=[10, 11, 12, 13, 14, 15, 16, 17],
        target=12,
    )

    for topology_name in ["chain", "star", "mesh", "static_exponential"]:
        config = ExperimentConfig(
            topology_name=topology_name,
            n_agents=4,
            max_rounds=4,
            seed=2,
            llm_provider="fake",
        )
        result = SynchronousRunner(
            config=config,
            task_adapter=adapter,
            global_task=global_task,
        ).run()

        assert result.round_logs
        assert result.final_result.round_idx >= 0
        assert len(result.final_agent_states) == 4


def test_runner_finalizes_with_rule_based_merge_after_max_rounds() -> None:
    adapter = ArraySearchTaskAdapter()
    global_task = adapter.build_global_task(
        array=[0, 1, 2, 3],
        target=0,
    )
    config = ExperimentConfig(
        topology_name="chain",
        n_agents=4,
        max_rounds=1,
        seed=3,
        llm_provider="fake",
        consensus_threshold=1.1,
        final_accept_threshold=0.2,
    )

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.stop_reason == "max_rounds"
    assert result.metrics.stop_reason == "max_rounds"
    assert len(result.round_logs) == 1
    assert result.final_result.final_key == "FOUND:0"
    assert result.final_result.aggregation_method == "rule_based_final"
    assert result.metrics.final_accuracy is True


def test_count_frequency_end_to_end_smoke_with_one_peer_exponential() -> None:
    adapter = CountFrequencyTaskAdapter()
    global_task = adapter.build_global_task(
        array=[0, 1, 0, 2, 1, 2, 2, 3],
    )
    config = ExperimentConfig(
        topology_name="one_peer_exponential",
        n_agents=4,
        max_rounds=3,
        seed=4,
        llm_provider="fake",
        consensus_threshold=0.8,
    )

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.final_result.final_key == global_task["answer_key"]
    assert result.final_result.consensus_reached is True
    assert result.metrics.final_accuracy is True
    assert result.stop_reason == "runtime_consensus"
    assert "Global frequency counts" in result.final_result.final_answer_text
