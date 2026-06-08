from exp_graph.aggregator.protocol_final import ProtocolFinalResult
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks.global_max import GlobalMaxTaskAdapter


def test_global_max_runs_through_protocol_runner():
    adapter = GlobalMaxTaskAdapter()
    gt = adapter.build_global_task(values=[3, 1, 9, 2, 5, 8, 4, 0])
    cfg = ProtocolRunnerConfig(
        topology_name="mesh_star", n_agents=8, merge_mode="deterministic", init_mode="deterministic"
    )
    result = ProtocolRunner(config=cfg, task_adapter=adapter, global_task=gt).run()
    assert isinstance(result.final_result, ProtocolFinalResult)
    assert result.final_result.final_key == "9"
    assert result.final_result.exact_match is True
    assert result.final_result.primary_metric == 1.0
