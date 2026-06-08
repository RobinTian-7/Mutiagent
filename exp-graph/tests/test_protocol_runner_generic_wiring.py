from exp_graph.aggregator.cf_final import CFProtocolFinalResult
from exp_graph.runner.protocol import ProtocolRunner, ProtocolRunnerConfig
from exp_graph.tasks.count_frequency import CountFrequencyTaskAdapter


def test_cf_protocol_runner_still_returns_cf_result():
    adapter = CountFrequencyTaskAdapter()
    gt = adapter.build_global_task(array=[1, 2, 1, 3], value_min=0, value_max=3)
    cfg = ProtocolRunnerConfig(
        topology_name="tree", n_agents=4, merge_mode="deterministic", init_mode="deterministic"
    )
    result = ProtocolRunner(config=cfg, task_adapter=adapter, global_task=gt).run()
    assert isinstance(result.final_result, CFProtocolFinalResult)  # CF path preserved
    summary = result.to_summary_dict()
    assert "FinalRMSE" in summary
