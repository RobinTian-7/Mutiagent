"""Held-out falsification verification for LLM MAS design insights (Plan 3 H).

These tests pin two invariants:

* The default ``insight_report_to_patches(report)`` path is byte-identical to
  today (no ``require_verified`` => every non-rejected insight that produces an
  update still yields a patch). This keeps the counterfactual insight/evolution
  suites unchanged.
* The new evidence-grounded ``falsify_insights`` layer derives a checkable
  topology/condition claim from a (loosely-structured) ``MASInsight`` and tests
  it against held-out aggregate rows, flipping ``claim_status`` to ``observed``
  (verified), ``rejected`` (contradicted), or leaving ``hypothesis``
  (unverifiable). ``require_verified=True`` then only emits patches for
  ``observed`` insights.
"""

from __future__ import annotations

import json
from pathlib import Path

from exp_graph.mas.evidence import write_evidence_jsonl
from exp_graph.mas.evolution import infer_condition_scope
from exp_graph.mas.insights import (
    falsify_insights,
    insight_report_to_patches,
)
from exp_graph.mas.matrix import analyze_matrix_insights
from exp_graph.mas.schemas import EvidenceRecord, InsightReport, MASInsight

SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def _condition_buckets(*, n_agents: int, array_size: int) -> list[dict[str, object]]:
    """Build condition_buckets exactly as the deterministic minister would."""
    scope = infer_condition_scope(
        [{"n_agents": n_agents, "array_size": array_size}]
    )
    return [scope]


def _prefer_tree_insight(*, n_agents: int = 4, array_size: int = 128) -> MASInsight:
    """A 'prefer/preserve topology tree' insight, mirroring the fake minister.

    ``affected_skills`` carries the classify_topology skill id (``cf_budget_tree``)
    which is the only structured carrier of the topology name, and
    ``operation_recommendations`` carries a ``preserve`` action plus the
    condition bucket. This is the shape the deterministic insight report emits.
    """
    return MASInsight(
        insight_id="tree_tradeoff",
        title="tree tradeoff should stay evidence-backed",
        insight_type="tradeoff",
        claim_status="observed",
        summary="Tree reduction is the budget-first CF policy for this bucket.",
        evidence_refs=["run:a", "run:b"],
        metric_snapshot={"rmse": 0.2},
        affected_skills=["cf_budget_tree"],
        recommended_actions=["merge evidence into planner skill"],
        operation_recommendations=[
            {
                "action_type": "preserve",
                "target": "condition_trigger",
                "instruction": "Apply tree only inside the recorded bucket.",
                "conditions": {
                    "topology_name": "tree",
                    "agent_bucket": f"agents_{n_agents}",
                    "array_size_bucket": f"arrays_{array_size}",
                },
            }
        ],
        condition_buckets=_condition_buckets(n_agents=n_agents, array_size=array_size),
        confidence=0.65,
        falsification_test="Run additional seeds and compare regret.",
    )


def _report(insights: list[MASInsight]) -> InsightReport:
    return InsightReport(
        report_id="insight_report_test",
        experiment_id="test",
        key_insights=insights,
    )


def test_default_unchanged():
    """Default insight_report_to_patches(report) emits the same patch as today."""
    insight = _prefer_tree_insight()
    report = _report([insight])

    patches = insight_report_to_patches(report)

    assert len(patches) == 1
    patch = patches[0]
    assert patch.patch_id == "insight_tree_tradeoff"
    assert patch.action == "merge"
    assert patch.target_skill_id == "cf_budget_tree"
    assert patch.evidence_refs == ["run:a", "run:b"]
    assert "design_insights" in patch.update
    assert patch.update["design_insights"][0]["claim_status"] == "observed"
    # require_verified defaults to False and must equal the positional call.
    assert insight_report_to_patches(report, require_verified=False) == patches


def test_contradicted_insight_rejected():
    """T is preferred but held-out shows T has the WORST loss => rejected, no patch."""
    insight = _prefer_tree_insight(n_agents=4, array_size=128)
    report = _report([insight])
    held_out_rows = [
        # Same condition bucket. tree is the worst (highest RMSE) of three.
        {"topology_name": "tree", "n_agents": 4, "array_size": 128, "mean_rmse": 0.9},
        {"topology_name": "star", "n_agents": 4, "array_size": 128, "mean_rmse": 0.2},
        {"topology_name": "mesh_star", "n_agents": 4, "array_size": 128, "mean_rmse": 0.1},
    ]

    falsified = falsify_insights(report, held_out_rows)

    (checked,) = falsified.key_insights
    assert checked.claim_status == "rejected"
    # Default path still emits (back-compat); require_verified gate drops it.
    assert insight_report_to_patches(falsified) == []  # rejected skipped already
    assert insight_report_to_patches(falsified, require_verified=True) == []


def test_supported_insight_accepted():
    """T is preferred and held-out confirms T is best => observed, patch emitted."""
    insight = _prefer_tree_insight(n_agents=4, array_size=128)
    report = _report([insight])
    held_out_rows = [
        {"topology_name": "tree", "n_agents": 4, "array_size": 128, "mean_rmse": 0.1},
        {"topology_name": "star", "n_agents": 4, "array_size": 128, "mean_rmse": 0.5},
        {"topology_name": "mesh_star", "n_agents": 4, "array_size": 128, "mean_rmse": 0.9},
    ]

    falsified = falsify_insights(report, held_out_rows)

    (checked,) = falsified.key_insights
    assert checked.claim_status == "observed"
    patches = insight_report_to_patches(falsified, require_verified=True)
    assert len(patches) == 1
    assert patches[0].target_skill_id == "cf_budget_tree"


def test_unverifiable_stays_hypothesis():
    """Topology/condition absent from held-out => stays hypothesis, no patch."""
    insight = _prefer_tree_insight(n_agents=4, array_size=128)
    report = _report([insight])
    # Neither row references topology 'tree' (and the bucket differs), so the
    # claim cannot be checked.
    held_out_rows = [
        {"topology_name": "star", "n_agents": 8, "array_size": 1024, "mean_rmse": 0.2},
        {"topology_name": "mesh_star", "n_agents": 8, "array_size": 1024, "mean_rmse": 0.3},
    ]

    falsified = falsify_insights(report, held_out_rows)

    (checked,) = falsified.key_insights
    assert checked.claim_status == "hypothesis"
    assert insight_report_to_patches(falsified, require_verified=True) == []


def _write_tree_matrix_fixtures(tmp_path: Path, *, tree_is_worst: bool):
    """Write batch evidence + a multi-topology cross-seed summary for tree.

    Two topologies share one condition bucket (agents=4, array=128) so the
    median is discriminating. ``tree_is_worst`` flips tree's held-out RMSE so the
    same deterministic 'prefer tree' insight is either contradicted or supported.
    """
    evidence_path = tmp_path / "batch_evidence.jsonl"
    base_metrics = {
        "objective": "budget_first",
        "planner_policy": "fixed_topology",
        "array_size": 128,
        "merge_mode": "deterministic",
        "init_mode": "deterministic",
        "final_exact_match": False,
        "token_cost": 100,
    }
    records = [
        EvidenceRecord(
            evidence_id="run:tree:1",
            source_type="run",
            topology_name="tree",
            n_agents=4,
            seed=1,
            metrics={**base_metrics, "final_rmse": 0.9 if tree_is_worst else 0.1},
        ),
        EvidenceRecord(
            evidence_id="run:tree:2",
            source_type="run",
            topology_name="tree",
            n_agents=4,
            seed=2,
            metrics={**base_metrics, "final_rmse": 0.9 if tree_is_worst else 0.1},
        ),
    ]
    write_evidence_jsonl(records, evidence_path)
    tree_rmse = 0.9 if tree_is_worst else 0.1
    other_rmse = 0.1 if tree_is_worst else 0.9
    # The cross-seed condition key must match the evidence-record condition key
    # (objective/policy/topology/agents/array/merge_mode/init_mode), otherwise the
    # batch shard finds no evidence_refs and emits no insight.
    summary = {
        "conditions": [
            {
                "objective": "budget_first",
                "planner_policy": "fixed_topology",
                "topology_name": "tree",
                "n_agents": 4,
                "array_size": 128,
                "merge_mode": "deterministic",
                "init_mode": "deterministic",
                "run_count": 2,
                "mean_rmse": tree_rmse,
                "mean_token_cost": 100.0,
            },
            {
                "objective": "budget_first",
                "planner_policy": "fixed_topology",
                "topology_name": "mesh_star",
                "n_agents": 4,
                "array_size": 128,
                "merge_mode": "deterministic",
                "init_mode": "deterministic",
                "run_count": 2,
                "mean_rmse": other_rmse,
                "mean_token_cost": 120.0,
            },
        ]
    }
    summary_path = tmp_path / "cross_seed_metrics.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    trace_path = tmp_path / "cross_seed_trace_summary.json"
    trace_path.write_text('{"conditions": []}', encoding="utf-8")
    return evidence_path, summary_path, trace_path


def test_analyze_matrix_insights_falsify_suppresses_contradicted_patch(tmp_path):
    """End-to-end wiring: falsify_held_out=True drops a contradicted tree patch."""
    evidence_path, summary_path, trace_path = _write_tree_matrix_fixtures(
        tmp_path, tree_is_worst=True
    )

    def _run(*, falsify: bool, out: str):
        return analyze_matrix_insights(
            skill_dir=SKILL_DIR,
            evidence_file=evidence_path,
            summary_file=summary_path,
            trace_summary_file=trace_path,
            llm_provider="fake",
            model_name="fake",
            max_parallel_insight_shards=1,
            output_dir=tmp_path / out,
            falsify_held_out=falsify,
        )

    # Default path (no falsification) still emits a tree patch -- back-compat.
    baseline = _run(falsify=False, out="baseline")
    assert any(
        patch.target_skill_id == "cf_budget_tree"
        for patch in baseline.skill_update_recommendations
    )

    # With held-out falsification, the contradicted tree insight is rejected and
    # produces no accepted patch.
    falsified = _run(falsify=True, out="falsified")
    tree_insights = [
        insight
        for insight in falsified.key_insights
        if "cf_budget_tree" in insight.affected_skills
    ]
    assert tree_insights
    assert all(insight.claim_status == "rejected" for insight in tree_insights)
    assert not any(
        patch.target_skill_id == "cf_budget_tree"
        for patch in falsified.skill_update_recommendations
    )


def test_analyze_matrix_insights_falsify_keeps_supported_patch(tmp_path):
    """End-to-end wiring: a held-out-confirmed tree insight survives the gate."""
    evidence_path, summary_path, trace_path = _write_tree_matrix_fixtures(
        tmp_path, tree_is_worst=False
    )

    report = analyze_matrix_insights(
        skill_dir=SKILL_DIR,
        evidence_file=evidence_path,
        summary_file=summary_path,
        trace_summary_file=trace_path,
        llm_provider="fake",
        model_name="fake",
        max_parallel_insight_shards=1,
        output_dir=tmp_path / "insights",
        falsify_held_out=True,
    )

    tree_insights = [
        insight
        for insight in report.key_insights
        if "cf_budget_tree" in insight.affected_skills
    ]
    assert tree_insights
    assert any(insight.claim_status == "observed" for insight in tree_insights)
    assert any(
        patch.target_skill_id == "cf_budget_tree"
        for patch in report.skill_update_recommendations
    )


def test_avoid_insight_holds_when_topology_is_worst():
    """An 'avoid T' insight is verified iff T's loss >= median in its condition."""
    avoid = MASInsight(
        insight_id="mesh_star_risk",
        title="mesh_star has reusable risk boundary",
        insight_type="risk_pattern",
        claim_status="inferred",
        summary="Avoid mesh_star here; it inflates final-answer noise.",
        evidence_refs=["run:a", "run:b"],
        affected_skills=["cf_middle_ground_mesh_star"],
        operation_recommendations=[
            {
                "action_type": "avoid",
                "target": "skill_trigger",
                "instruction": "Keep mesh_star as a fallback, not a global rule.",
                "conditions": {"topology_name": "mesh_star"},
            }
        ],
        condition_buckets=_condition_buckets(n_agents=4, array_size=128),
        confidence=0.55,
    )
    report = _report([avoid])
    held_out_rows = [
        {"topology_name": "tree", "n_agents": 4, "array_size": 128, "mean_rmse": 0.1},
        {"topology_name": "star", "n_agents": 4, "array_size": 128, "mean_rmse": 0.2},
        {"topology_name": "mesh_star", "n_agents": 4, "array_size": 128, "mean_rmse": 0.9},
    ]

    falsified = falsify_insights(report, held_out_rows)

    (checked,) = falsified.key_insights
    assert checked.claim_status == "observed"
    patches = insight_report_to_patches(falsified, require_verified=True)
    assert len(patches) == 1


def test_unstructured_insight_marked_hypothesis_not_crash():
    """An insight with no extractable topology claim is marked hypothesis safely."""
    vague = MASInsight(
        insight_id="vague",
        title="use better communication",
        insight_type="design_principle",
        claim_status="inferred",
        summary="Improve coverage somehow.",
        evidence_refs=["run:a", "run:b"],
        affected_skills=[],  # no topology carrier
        operation_recommendations=[],
        condition_buckets=[],
        confidence=0.4,
    )
    report = _report([vague])
    held_out_rows = [
        {"topology_name": "tree", "n_agents": 4, "array_size": 128, "mean_rmse": 0.1},
    ]

    falsified = falsify_insights(report, held_out_rows)

    (checked,) = falsified.key_insights
    assert checked.claim_status == "hypothesis"
    assert insight_report_to_patches(falsified, require_verified=True) == []
