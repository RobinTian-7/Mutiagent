"""Tests for the held-out validation gate on QueenBee skill evolution.

The gate implements the paper's "accept a skill update only if it improves a
held-out objective" rule. It must default OFF so all existing count-frequency
evolution behavior stays byte-identical, and only change anything when a caller
explicitly opts in with ``gate=True`` and supplies held-out ``validation_rows``.
"""

from __future__ import annotations

from exp_graph.mas.consolidation import consolidate_skill_updates
from exp_graph.mas.schemas import ObjectiveSpec, PlannerRequest, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.mas.validation import validation_objective


def _aggregate_row(
    *,
    topology: str,
    rmse: float,
    agents: int = 8,
    array_size: int = 256,
    messages: float = 10.0,
) -> dict:
    """One held-out aggregate row in the same shape ministers consume."""
    return {
        "Topology": topology,
        "Agents": agents,
        "ArraySize": array_size,
        "MergeMode": "deterministic",
        "InitMode": "deterministic",
        "Runs": 3,
        "MeanFinalRMSE": rmse,
        "StdFinalRMSE": 0.01,
        "MeanFinalNormalizedL1Error": rmse,
        "ExactMatchRate": 1.0 if rmse == 0.0 else 0.5,
        "MeanTotalSteps": 4,
        "MeanTotalMessages": messages,
        "MeanTotalModelCalls": 0,
        "MeanTokenCost": messages * 100,
        "MeanVoteTopRatio": 1.0,
    }


def _skill(skill_id: str, topology: str, *, rmse: float) -> SkillCard:
    """Selectable CF skill that advertises a topology with a given primary loss."""
    return SkillCard(
        skill_id=skill_id,
        objective="balanced",
        task_family="count_frequency",
        trigger={
            "task_family": "count_frequency",
            "min_agents": 1,
            "max_agents": 999,
        },
        organization_policy={
            "planner_mode": "topology_select",
            "topology_name": topology,
        },
        expected_tradeoff={
            "mean_rmse": rmse,
            "mean_token_cost": 1000.0,
            "mean_messages": 10.0,
        },
        tags=["mas", "emperor-skill", "count-frequency"],
    )


def _accuracy_request() -> PlannerRequest:
    return PlannerRequest(
        n_agents=8,
        array_size=256,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )


def test_gate_off_is_unconditional() -> None:
    """With gate=False (default) a patch is applied exactly as today."""
    bank = SkillBank([_skill("cf_budget_tree", "tree", rmse=0.16)])
    patch = SkillPatch(
        patch_id="merge_tree_run_1",
        action="merge",
        target_skill_id="cf_budget_tree",
        update={
            "risk_notes": [
                {"source": "test", "summary": "single run evidence should merge"}
            ]
        },
        lesson="merge one new run evidence record",
        confidence=0.8,
        source="test",
    )
    before_version = bank.get("cf_budget_tree").version

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[patch],
        evidence_records=[],
        batch_id="gate_off_batch",
    )

    skill = updated.get("cf_budget_tree")
    assert skill.version != before_version
    assert result.counts["merged"] == 1
    # Gate metadata must be absent when the gate is off.
    assert "gated_out" not in result.counts
    assert not any("validation gate" in warning for warning in result.warnings)


def test_gate_rejects_regressing_patch() -> None:
    """A patch that makes the planner pick a worse topology is rejected."""
    # tree is currently best (lowest loss) and the planner selects it.
    bank = SkillBank(
        [
            _skill("cf_budget_tree", "tree", rmse=0.05),
            _skill("cf_accuracy_peer_star", "one_peer_exponential_dag_star", rmse=0.40),
        ]
    )
    # Held-out evidence: tree is the good choice; peer_star is much worse.
    validation_rows = [
        _aggregate_row(topology="tree", rmse=0.05),
        _aggregate_row(topology="one_peer_exponential_dag_star", rmse=0.40),
    ]
    # Sanity: before the patch, the planner picks tree -> J_val is the tree loss.
    assert validation_objective(
        bank, validation_rows, objective_name="accuracy_first"
    ) == 0.05

    # Patch degrades tree so the planner would instead pick peer_star (worse).
    patch = SkillPatch(
        patch_id="regress_tree",
        action="merge",
        target_skill_id="cf_budget_tree",
        update={"expected_tradeoff": {"mean_rmse": 0.90}},
        lesson="inflate tree loss so peer_star wins selection",
        confidence=0.8,
        source="test",
    )
    before = bank.get("cf_budget_tree").model_dump()
    before_peer = bank.get("cf_accuracy_peer_star").model_dump()

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[patch],
        evidence_records=[],
        batch_id="reject_batch",
        validation_rows=validation_rows,
        gate=True,
    )

    # The real bank is untouched on rejection.
    assert updated is bank
    assert updated.get("cf_budget_tree").model_dump() == before
    assert updated.get("cf_accuracy_peer_star").model_dump() == before_peer
    # Rejection is surfaced in the EvolutionResult.
    assert result.counts.get("gated_out", 0) >= 1
    assert result.counts.get("merged", 0) == 0
    assert any("validation gate" in warning.lower() for warning in result.warnings)
    assert result.gate_accepted is False
    assert result.gate_j_after > result.gate_j_before


def test_gate_accepts_improving_patch() -> None:
    """A patch that makes the planner pick a better topology is accepted."""
    # peer_star is currently best, but held-out evidence says peer_star is bad
    # and tree is good -> the current selection is suboptimal on held-out data.
    bank = SkillBank(
        [
            _skill("cf_budget_tree", "tree", rmse=0.50),
            _skill("cf_accuracy_peer_star", "one_peer_exponential_dag_star", rmse=0.05),
        ]
    )
    validation_rows = [
        _aggregate_row(topology="tree", rmse=0.05),
        _aggregate_row(topology="one_peer_exponential_dag_star", rmse=0.40),
    ]
    # Before: planner picks peer_star (lowest advertised loss) -> J_val = 0.40.
    assert validation_objective(
        bank, validation_rows, objective_name="accuracy_first"
    ) == 0.40

    # Patch improves tree's advertised loss so the planner switches to tree,
    # which is the genuinely better choice on held-out evidence.
    patch = SkillPatch(
        patch_id="improve_tree",
        action="merge",
        target_skill_id="cf_budget_tree",
        update={"expected_tradeoff": {"mean_rmse": 0.01}},
        lesson="tree is actually the best choice",
        confidence=0.8,
        source="test",
    )

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[patch],
        evidence_records=[],
        batch_id="accept_batch",
        validation_rows=validation_rows,
        gate=True,
    )

    # Accepted -> the real bank reflects the merge.
    assert updated is bank
    assert result.counts.get("merged", 0) == 1
    assert result.counts.get("gated_out", 0) == 0
    assert result.gate_accepted is True
    assert result.gate_j_after < result.gate_j_before
    # After acceptance the planner now selects tree on held-out data.
    assert validation_objective(
        updated, validation_rows, objective_name="accuracy_first"
    ) == 0.05


def test_validation_objective_penalizes_unmeasured_topology() -> None:
    """Selecting a topology with no held-out row incurs the penalty."""
    # The bank's only selectable skill advertises a topology absent from the rows.
    bank = SkillBank([_skill("cf_phantom", "mesh_star", rmse=0.01)])
    validation_rows = [
        _aggregate_row(topology="tree", rmse=0.10),
        _aggregate_row(topology="one_peer_exponential_dag_star", rmse=0.40),
    ]
    # max loss seen in the condition is 0.40, so penalty = 0.40 + 1.0 = 1.40.
    assert validation_objective(
        bank, validation_rows, objective_name="accuracy_first"
    ) == 1.40


def test_validation_objective_empty_rows_is_noop() -> None:
    """Empty validation_rows make the objective a no-op (returns 0.0)."""
    bank = SkillBank([_skill("cf_budget_tree", "tree", rmse=0.16)])
    assert validation_objective(bank, []) == 0.0
