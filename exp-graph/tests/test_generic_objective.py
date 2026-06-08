"""Tests for the generalized self-evolution objective (Plan 3 Part C).

The QueenBee evolution machinery historically assumed a count-frequency RMSE
(lower-is-better) primary metric. These tests pin the generic bridge that lets
any benchmark's primary metric (e.g. Silo-Bench success-rate, higher-is-better)
flow through the SAME scoring/evolution machinery by converting it to a uniform
lower-is-better "primary loss".
"""

from __future__ import annotations

from exp_graph.mas.ingest import aggregate_rows_to_evidence
from exp_graph.mas.objective_metrics import primary_loss
from exp_graph.mas.scoring import score_skill
from exp_graph.mas.schemas import ObjectiveSpec, SkillCard


def _cf_row(**overrides):
    """A count-frequency aggregate row (carries MeanFinalRMSE)."""
    row = {
        "Topology": "one_peer_exponential_dag_star",
        "Agents": 2,
        "ArraySize": 64,
        "MergeMode": "deterministic",
        "InitMode": "deterministic",
        "Runs": 3,
        "MeanFinalRMSE": 0.25,
        "StdFinalRMSE": 0.0,
        "MeanFinalNormalizedL1Error": 0.02,
        "ExactMatchRate": 0.5,
        "MeanTotalSteps": 3.0,
        "MeanTotalMessages": 11.0,
        "MeanTotalModelCalls": 16.0,
        "MeanTokenCost": 1200.0,
        "MeanVoteTopRatio": 0.9,
    }
    row.update(overrides)
    return row


def _generic_row(**overrides):
    """A generic aggregate row WITHOUT MeanFinalRMSE (success-rate metric)."""
    row = {
        "Topology": "mesh_star",
        "Agents": 2,
        "ArraySize": 0,
        "MergeMode": "deterministic",
        "InitMode": "deterministic",
        "Runs": 1,
        "MeanPrimaryMetric": 1.0,
        "PrimaryMetricName": "success",
        "MeanFinalNormalizedL1Error": 0.0,
        "ExactMatchRate": 1.0,
        "MeanTotalSteps": 2.0,
        "MeanTotalMessages": 4.0,
        "MeanTotalModelCalls": 4.0,
        "MeanTokenCost": 100.0,
        "MeanVoteTopRatio": 0.0,
    }
    row.update(overrides)
    return row


def test_primary_loss_rmse_is_identity():
    assert primary_loss("rmse", 0.25) == 0.25
    assert primary_loss("rmse", 0.0) == 0.0
    # Absent / unknown lower-is-better metric name is treated as a raw loss.
    assert primary_loss("", 0.4) == 0.4
    assert primary_loss(None, 0.4) == 0.4


def test_primary_loss_higher_is_better_inverts():
    for name in ("success", "success_rate", "exact_match", "primary", "partial"):
        assert primary_loss(name, 1.0) == 0.0
        assert primary_loss(name, 0.0) == 1.0
        assert abs(primary_loss(name, 0.75) - 0.25) < 1e-12


def test_primary_loss_clamps_out_of_range_success():
    # Success above 1.0 must not produce a negative loss.
    assert primary_loss("success", 1.2) == 0.0
    # Negative success clamps loss at 1.0 (no value beyond the [0, 1] base range).
    assert primary_loss("success", -0.5) == 1.0


def test_aggregate_generic_row_bridges_to_mean_rmse():
    evidence = aggregate_rows_to_evidence([_generic_row(MeanPrimaryMetric=1.0)])
    assert len(evidence) == 1
    item = evidence[0]
    assert item["primary_metric_name"] == "success"
    assert item["mean_primary_loss"] == 0.0
    # Bridge: generic rows (no MeanFinalRMSE) slot their loss into mean_rmse.
    assert item["mean_rmse"] == 0.0


def test_aggregate_generic_row_low_success_is_high_loss():
    evidence = aggregate_rows_to_evidence([_generic_row(MeanPrimaryMetric=0.0)])
    item = evidence[0]
    assert item["mean_primary_loss"] == 1.0
    assert item["mean_rmse"] == 1.0


def test_aggregate_cf_row_mean_rmse_unchanged():
    evidence = aggregate_rows_to_evidence([_cf_row()])
    item = evidence[0]
    # CF rows must remain byte-identical: mean_rmse comes from MeanFinalRMSE.
    assert item["mean_rmse"] == 0.25
    assert item["std_rmse"] == 0.0
    assert item["exact_match_rate"] == 0.5


def test_aggregate_cf_row_with_primary_metric_keeps_rmse():
    # Even when a CF row also carries the generic keys (PrimaryMetricName=="rmse"),
    # mean_rmse stays driven by MeanFinalRMSE, never overwritten.
    evidence = aggregate_rows_to_evidence(
        [_cf_row(MeanPrimaryMetric=0.25, PrimaryMetricName="rmse")]
    )
    item = evidence[0]
    assert item["mean_rmse"] == 0.25
    assert item["mean_primary_loss"] == 0.25
    assert item["primary_metric_name"] == "rmse"


def _skill_from_evidence(skill_id: str, evidence: list[dict]) -> SkillCard:
    return SkillCard(
        skill_id=skill_id,
        organization_policy={"topology_name": skill_id},
        evidence=evidence,
    )


def test_score_skill_ranks_high_success_above_low_success():
    good = _skill_from_evidence(
        "good",
        aggregate_rows_to_evidence([_generic_row(Topology="good", MeanPrimaryMetric=1.0)]),
    )
    bad = _skill_from_evidence(
        "bad",
        aggregate_rows_to_evidence([_generic_row(Topology="bad", MeanPrimaryMetric=0.0)]),
    )
    objective = ObjectiveSpec.from_name("accuracy_first")
    peers = [good, bad]
    good_score, good_breakdown = score_skill(good, objective=objective, peers=peers)
    bad_score, _ = score_skill(bad, objective=objective, peers=peers)
    assert good_score > bad_score
    # The success=1.0 skill should be the accuracy winner (loss 0 -> accuracy 1.0).
    assert good_breakdown["accuracy"] == 1.0


def test_score_skill_cf_only_mean_rmse_still_works():
    # A CF skill that only has mean_rmse (no mean_primary_loss) keeps behaving.
    low = _skill_from_evidence(
        "low",
        aggregate_rows_to_evidence([_cf_row(Topology="low", MeanFinalRMSE=0.1)]),
    )
    high = _skill_from_evidence(
        "high",
        aggregate_rows_to_evidence([_cf_row(Topology="high", MeanFinalRMSE=0.9)]),
    )
    objective = ObjectiveSpec.from_name("accuracy_first")
    peers = [low, high]
    low_score, low_breakdown = score_skill(low, objective=objective, peers=peers)
    high_score, _ = score_skill(high, objective=objective, peers=peers)
    # Lower rmse = better accuracy = higher score.
    assert low_score > high_score
    assert low_breakdown["accuracy"] == 1.0
