from exp_graph.configs import ExperimentConfig
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import ArraySearchTaskAdapter


def test_minimal_end_to_end_smoke_with_one_peer_exponential() -> None:
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
    )

    result = SynchronousRunner(
        config=config,
        task_adapter=adapter,
        global_task=global_task,
    ).run()

    assert result.final_result.final_key == "FOUND:6"
    assert result.final_result.consensus_reached is True
    assert result.metrics.final_accuracy is True
    assert result.metrics.total_model_calls > 0
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
