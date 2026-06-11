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


def test_aggregate_row_passes_through_protocol_spec():
    # A2 (Silo select_then_refine): rows that carry the EXECUTED schedule keep it
    # through evidence conversion so _best_protocol_spec can store it on skills.
    spec = {"name": "tree", "n_agents": 2, "steps": [{"transmissions": [[1, 0]]}]}
    with_spec = aggregate_rows_to_evidence([_cf_row(protocol_spec=spec)])
    assert with_spec[0]["protocol_spec"] == spec
    # CF rows without a spec stay byte-identical (no new key).
    without = aggregate_rows_to_evidence([_cf_row()])
    assert "protocol_spec" not in without[0]


def _silo_skill(skill_id: str, success: float, n_evidence: int = 1) -> SkillCard:
    """A generic-benchmark skill: bridged evidence puts SUCCESS into mean_rmse
    (higher better) and the converted loss into mean_primary_loss."""
    return SkillCard(
        skill_id=skill_id,
        objective="accuracy_first",
        task_family="silo",
        trigger={"task_family": "silo", "min_agents": 1, "max_agents": 999,
                 "condition_key": "a10__arr0"},
        organization_policy={"topology_name": skill_id},
        expected_tradeoff={
            "mean_rmse": success,                  # bridged success (higher better)
            "mean_primary_loss": 1.0 - success,    # uniform loss (lower better)
            "active_evidence_count": n_evidence,
        },
        tags=["mas", "emperor-skill"],
    )


def test_retrieval_orders_generic_skills_by_loss_not_raw_rmse():
    """P2 confirmatory-1 root cause: the retrieval sort key read raw
    ``mean_rmse`` ascending (CF semantics) -- on generic benchmarks that field
    holds bridged SUCCESS, so retrieval returned WORST-first and deployment
    replayed a train-loss-1.0 design. Skills carrying ``mean_primary_loss``
    must rank by THAT (ascending)."""
    from exp_graph.mas.schemas import PlannerRequest
    from exp_graph.mas.skill_bank import SkillBank

    bank = SkillBank(skills=[
        _silo_skill("always_fails", success=0.0),
        _silo_skill("always_wins", success=1.0),
        _silo_skill("middling", success=0.5),
    ])
    request = PlannerRequest(
        task_family="silo", n_agents=10,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )
    order = [s.skill_id for s in bank.retrieve(request)]
    assert order == ["always_wins", "middling", "always_fails"], order


def test_retrieval_cf_ordering_unchanged():
    """CF skills carry no mean_primary_loss -> raw mean_rmse ascending (the
    historical key) must be byte-identical."""
    from exp_graph.mas.schemas import PlannerRequest
    from exp_graph.mas.skill_bank import SkillBank

    def cf_skill(skill_id: str, rmse: float) -> SkillCard:
        return SkillCard(
            skill_id=skill_id, objective="accuracy_first",
            task_family="count_frequency",
            trigger={"task_family": "count_frequency", "min_agents": 1, "max_agents": 999},
            organization_policy={"topology_name": skill_id},
            expected_tradeoff={"mean_rmse": rmse},
            tags=["mas", "emperor-skill"],
        )

    bank = SkillBank(skills=[cf_skill("bad", 0.9), cf_skill("good", 0.1)])
    request = PlannerRequest(
        task_family="count_frequency", n_agents=2,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )
    assert [s.skill_id for s in bank.retrieve(request)] == ["good", "bad"]


def test_probe_row_converts_generic_primary_metric_to_loss():
    """P2 bundle-screen root cause: ``_probe_row`` stuffed Silo's PrimaryMetric
    (SUCCESS, higher=better) into ``mean_rmse`` (lower=better), so under
    ``_objective_score`` (``exact - rmse``) the success signal cancelled itself
    and probe selection degenerated to cheapest-wins. Generic summaries must
    bridge through ``primary_loss``; CF (FinalRMSE present) stays byte-identical."""
    from exp_graph.mas.graph_generation import _objective_score, _probe_row

    class _Result:
        def __init__(self, summary):
            self._summary = summary

        def to_summary_dict(self):
            return self._summary

    def generic(success: float, messages: float):
        return _Result({
            "PrimaryMetric": success, "PrimaryMetricName": "primary",
            "FinalExactMatch": success >= 1.0, "TotalMessages": messages,
            "TotalModelCalls": 5, "TotalPromptTokens": 1000,
            "TotalCompletionTokens": 200,
        })

    win = _probe_row(generic(1.0, 30.0), "accuracy_first")
    fail_cheap = _probe_row(generic(0.0, 2.0), "accuracy_first")
    assert win["mean_rmse"] == 0.0, "success must convert to loss 0"
    assert fail_cheap["mean_rmse"] == 1.0, "failure must convert to loss 1"
    assert _objective_score(win) > _objective_score(fail_cheap), (
        "a succeeding candidate must outrank a failing-but-cheaper one"
    )

    cf = _Result({
        "FinalRMSE": 0.25, "FinalExactMatch": False, "TotalMessages": 4,
        "TotalModelCalls": 2, "TotalPromptTokens": 10, "TotalCompletionTokens": 2,
    })
    assert _probe_row(cf, "accuracy_first")["mean_rmse"] == 0.25, "CF unchanged"
