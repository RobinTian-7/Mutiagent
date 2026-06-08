from exp_graph.aggregator.protocol_final import ProtocolFinalResult
from exp_graph.metrics.protocol import ProtocolAgentStepMetric, ProtocolGlobalStepMetric
from exp_graph.tasks.protocol_adapter import ProtocolTaskAdapter


def test_protocol_final_result_fields():
    r = ProtocolFinalResult(
        final_key="9", final_answer=9, selected_primary="vote",
        aggregation_method="vote", primary_metric=1.0, exact_match=True,
        supporting_agents=[1], answer_agent_ids=[0, 1], top_ratio=1.0,
    )
    assert r.final_key == "9" and r.exact_match is True


def test_protocol_step_metric_fields():
    a = ProtocolAgentStepMetric(
        step_idx=0, phase="after_step", topology="mesh", agent_id=0,
        active_sender=True, active_receiver=False, coverage_ratio=0.5,
        primary_metric=1.0, exact_match=False, sent_count=1, received_count=0,
    )
    g = ProtocolGlobalStepMetric(
        step_idx=0, phase="after_step", topology="mesh", mean_coverage=0.5,
        min_coverage=0.0, max_coverage=1.0, mean_primary_metric=0.5,
        best_primary_metric=1.0, worst_primary_metric=0.0,
        exact_match_agents=0, full_coverage_agents=0, vote_top_ratio=1.0,
    )
    assert a.coverage_ratio == 0.5 and g.mean_coverage == 0.5


def test_protocol_task_adapter_is_abstract():
    assert hasattr(ProtocolTaskAdapter, "finalize_protocol")
    assert hasattr(ProtocolTaskAdapter, "build_protocol_step_metrics")
    assert getattr(ProtocolTaskAdapter.finalize_protocol, "__isabstractmethod__", False) is False  # has a default
