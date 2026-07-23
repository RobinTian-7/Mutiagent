from exp_graph.mas.evolution import TraceAnalystMinister
from exp_graph.mas.schemas import EvidenceRecord


def test_trace_analyst_extracts_relative_dynamics_not_exact_match_gate():
    records = [
        EvidenceRecord(
            evidence_id="trace:run-1",
            source_type="trace",
            topology_name="one_peer_exponential_dag_star",
            n_agents=8,
            seed=1,
            dynamics={
                "coverage_growth": {
                    "mean_coverage_gain": 0.2,
                    "final_mean_coverage": 0.6,
                },
                "aggregation_reliability": {
                    "sink_best_rmse_gap": 0.3,
                    "sink_coverage_ratio": 0.75,
                },
                "merge_quality": {
                    "retry_attempts": 2,
                    "parse_error_count": 0,
                },
            },
            risk_tags=["non_exact_final", "sink_quality_gap", "merge_retry_burden"],
        )
    ]

    patches = TraceAnalystMinister().analyze_evidence(records)

    assert len(patches) == 1
    patch = patches[0]
    assert patch.action == "merge"
    assert patch.target_skill_id == "cf_accuracy_peer_star"
    assert patch.evidence_refs == ["trace:run-1"]
    assert "expected_dynamics" in patch.update
    assert "risk_notes" in patch.update
    assert patch.update["fallback"]["if_sink_quality_gap_high"] == (
        "cf_middle_ground_mesh_star"
    )
