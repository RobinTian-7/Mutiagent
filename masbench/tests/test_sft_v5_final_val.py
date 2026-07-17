"""Stage 8 closure tests: the FINAL_VAL whole-snapshot gate.

A candidate assessment reaches deployment only through the strict dense gate
over frozen, read-only FINAL_VAL executions; accept swaps the whole snapshot,
reject keeps the incumbent, and no FINAL_VAL fact can flow back into TRAIN
evidence.
"""

from __future__ import annotations

import hashlib

import pytest

from exp_graph.mas.factor_bank import DenseOutcome
from masbench.sft_pilot.final_val import (
    FinalValCaseSample,
    frozen_final_val_arms,
    run_final_val_gate,
)
from masbench.sft_pilot.scientific_runner import (
    reserve_scheduled_execution,
    skip_settled_probe_blocks,
)

from sft_v5_fixtures import V5ProbeHarness, benefit_pair


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _metrics(v: float, c: float) -> DenseOutcome:
    return DenseOutcome(V=v, K=v, U=v, P=v, S=v, stage_score=v, C=c, D=2.0)


def _samples(v: float, c: float) -> tuple[FinalValCaseSample, ...]:
    return tuple(
        FinalValCaseSample(
            case_id=case_id,
            seed=0,
            metrics=_metrics(v, c),
        )
        for case_id in ("case-vva", "case-vvb")
    )


@pytest.fixture
def candidate_harness(tmp_path):
    harness = V5ProbeHarness(tmp_path)
    edge = harness.commit_mutate_edge(tag="gate")
    action_id = next(
        item.action_id
        for item in harness.bank.to_state().proposal_actions
        if item.state == "committed"
    )
    plan = harness.seal_plan_for(edge.transition)
    for ordinal in range(4):
        source, target = benefit_pair()
        harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="gate",
            source=source,
            target=target,
        )
    assert harness.bank.assessments[plan.plan_id].label == "candidate"
    # The plan settled before its reserve units: skip their frozen blocks
    # honestly so the linear physical order reaches the FINAL_VAL blocks.
    skipped = skip_settled_probe_blocks(
        harness.store,
        schedule=harness.experiment.seal.execution_schedule,
        ordinals=(4, 5),
        action_id=action_id,
    )
    assert len(skipped) == 4
    yield harness, edge, plan
    harness.close()


def _final_val_executor(harness):
    def execute(arm, role):
        key = f"final-val-{role}"
        reserve_scheduled_execution(
            harness.store,
            schedule=harness.experiment.seal.execution_schedule,
            logical_arm=arm,
            logical_execution_key=key,
        )
        harness._complete_probe_store_execution(
            arm=arm,
            key=key,
            tag=f"final-val-{role}",
            recovery_root=harness.loaded.snapshot.recovery_root_sha256,
        )

    return execute


def test_gate_accept_swaps_whole_snapshot_and_promotes(candidate_harness) -> None:
    harness, edge, plan = candidate_harness
    train_state_before = {
        "transitions": harness.bank.to_state().direct_transitions,
        "assessment": harness.bank.assessments[plan.plan_id].digest,
    }
    outcome, promoted = run_final_val_gate(
        loaded=harness.loaded,
        coordinator=harness.coordinator,
        store=harness.store,
        schedule=harness.experiment.seal.execution_schedule,
        authority=harness.authority,
        protocol=harness.experiment.protocol,
        incumbent_samples=_samples(0.5, 25.0),
        candidate_samples=_samples(0.7, 9.0),
        owner_logical_execution_key="v5-generation-owner-gate",
        execute_final_val_arm=_final_val_executor(harness),
    )
    harness.loaded = promoted
    assert outcome.accepted
    assert outcome.strict_result["reason"] == "quality_improvement"
    assert (
        outcome.active_snapshot_id_after != outcome.active_snapshot_id_before
    )
    # Promotion advanced the scientific component generation.
    assert promoted.snapshot.metadata.generation == 1
    # FINAL_VAL updated no TRAIN evidence: transitions and the settled
    # assessment digest are unchanged.
    assert (
        harness.bank.to_state().direct_transitions
        == train_state_before["transitions"]
    )
    assert (
        harness.bank.assessments[plan.plan_id].digest
        == train_state_before["assessment"]
    )
    # Crash/restart after promotion restores the promoted generation.
    harness.reopen()
    assert harness.loaded.snapshot.origin == "scientific_bundle"
    assert harness.store.latest_component_bundle().metadata.generation == 1


def test_gate_reject_keeps_incumbent(candidate_harness) -> None:
    harness, edge, plan = candidate_harness
    outcome, promoted = run_final_val_gate(
        loaded=harness.loaded,
        coordinator=harness.coordinator,
        store=harness.store,
        schedule=harness.experiment.seal.execution_schedule,
        authority=harness.authority,
        protocol=harness.experiment.protocol,
        incumbent_samples=_samples(0.7, 9.0),
        candidate_samples=_samples(0.4, 30.0),
        owner_logical_execution_key="v5-generation-owner-gate",
        execute_final_val_arm=_final_val_executor(harness),
    )
    harness.loaded = promoted
    assert not outcome.accepted
    assert outcome.strict_result["reason"] == "quality_regression"
    assert (
        outcome.active_snapshot_id_after == outcome.active_snapshot_id_before
    )
    opportunity = next(
        item for item in harness.bank.to_state().gate_opportunities
    )
    assert opportunity.state == "rejected"
    # Gate rejection does not relabel the transition's TRAIN effect.
    assert harness.bank.assessments[plan.plan_id].label == "candidate"


def test_gate_requires_candidate_and_signed_receipt(candidate_harness) -> None:
    harness, edge, plan = candidate_harness
    incumbent_arm, candidate_arm = frozen_final_val_arms(
        harness.experiment.protocol
    )
    assert incumbent_arm.execution_ordinal < candidate_arm.execution_ordinal

    # Mismatched paired keys fail closed inside the strict predicate.
    with pytest.raises(ValueError, match="identical incumbent/candidate keys"):
        run_final_val_gate(
            loaded=harness.loaded,
            coordinator=harness.coordinator,
            store=harness.store,
            schedule=harness.experiment.seal.execution_schedule,
            authority=harness.authority,
            protocol=harness.experiment.protocol,
            incumbent_samples=_samples(0.5, 25.0),
            candidate_samples=(
                FinalValCaseSample(
                    case_id="case-foreign",
                    seed=0,
                    metrics=_metrics(0.7, 9.0),
                ),
            ),
            owner_logical_execution_key="v5-generation-owner-gate",
            execute_final_val_arm=_final_val_executor(harness),
        )

    # A gate receipt signed by a foreign authority key is rejected by the
    # Bank's installed gate verifier.
    from masbench.sft_pilot.factor_authority import SFTPilotFactorAuthority

    foreign = SFTPilotFactorAuthority(
        harness.experiment.protocol,
        pair_manifest=harness.experiment.seal.pair_manifest,
        attestation_key=hashlib.sha256(b"foreign-gate-key").digest(),
    )
    pending = next(
        item
        for item in harness.bank.to_state().gate_opportunities
        if item.state == "pending"
    )
    assessment = harness.bank.assessments[plan.plan_id]
    head = harness.bank.deployment_heads[pending.deployment_slot_id]
    incumbent = next(
        item
        for item in harness.bank.to_state().deployment_snapshots
        if item.snapshot_id == head.active_snapshot_id
    )
    from exp_graph.mas.factor_bank_v2 import GateReceiptV2
    from masbench.sft_pilot.schema import canonical_sha256

    forged = foreign.attest_gate(
        GateReceiptV2(
            decision_id="gd:forged",
            opportunity_id=pending.opportunity_id,
            deployment_slot_id=pending.deployment_slot_id,
            accepted=True,
            incumbent_snapshot_sha256=canonical_sha256(incumbent),
            candidate_snapshot_sha256=pending.candidate_snapshot_sha256,
            settled_assessment_sha256=assessment.digest,
            gate_config_sha256=_sha("forged-config"),
            aggregate_summary_sha256=canonical_sha256(
                assessment.strict_summary
            ),
            verifier_epoch=foreign.verifier_epoch,
            verification_attestation_sha256="0" * 64,
            emitted_seq=harness.bank.to_state().event_seq + 1,
        )
    )
    with pytest.raises(ValueError, match="gate verifier rejected"):
        harness.bank.apply_gate(forged)
