"""Stage 7 closure tests: the multi-round TRAIN update loop.

Round 1: bootstrap opportunity -> mutate action (one frozen call) -> probe ->
harmful terminal -> harm-repair opportunity + capacity archive pass.
Round 2: driven from the Bank's pending repair opportunity (never a hidden
caller queue) -> reuse action with zero generation calls.
Round 3: a further mutate attempt is rejected by the frozen TRAIN budget
before any model call can start.  Crash/restart between rounds restores
exact roots, and every scheduler counter is read back from Bank state.
"""

from __future__ import annotations

import hashlib

import pytest

from exp_graph.mas.factor_bank_v2 import FailureObservationV2
from exp_graph.mas.phase_factor_binding_v3 import (
    RegisteredPhaseFactorEdgeV3,
    reconcile_phase_proposal_action_v3,
)
from masbench.sft_pilot.scientific_runner import (
    branch_assignment_counts,
    pending_repair_opportunities,
    reserve_scheduled_execution,
)
from masbench.sft_pilot.store import PilotCapacityError, PilotStoreError

from sft_v5_fixtures import ArmPlan, V5ProbeHarness, benefit_pair


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def harness(tmp_path):
    built = V5ProbeHarness(tmp_path)
    yield built
    built.close()


def test_two_rounds_with_repair_reuse_and_capacity_preflight(harness) -> None:
    # ---- Round 1: bootstrap -> mutate -> probe -> harmful terminal.
    assert pending_repair_opportunities(harness.bank) == ()
    edge = harness.commit_mutate_edge(tag="round1")
    assert isinstance(edge, RegisteredPhaseFactorEdgeV3)
    action_id = next(
        item.action_id
        for item in harness.bank.to_state().proposal_actions
        if item.state == "committed"
    )
    plan = harness.seal_plan_for(edge.transition)
    harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=0,
        tag="round1",
        source=ArmPlan(v=0.6, c=9.0),
        target=ArmPlan(
            terminal="algorithm_failure",
            v=0.0,
            c=30.0,
            safe_failure_code="algorithm_failure",
            failed_stage_rank=1,
        ),
    )
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.label == "harmful"

    # ---- Crash/restart at the settled probe boundary restores exact roots.
    before = harness.bank.scientific_state_sha256
    harness.reopen()
    assert harness.bank.scientific_state_sha256 == before
    # Re-project the generated edge over the restored components (replay of
    # the same registry proof returns the identical registered edge).
    from exp_graph.mas.phase_factor_binding_v3 import (
        register_phase_materialization_v3,
    )

    generated_proof = harness.registry.to_state().proofs[-1]
    edge = register_phase_materialization_v3(
        registry=harness.registry,
        bank=harness.bank,
        proof=generated_proof.handle,
    )
    counts_before = branch_assignment_counts(harness.bank)
    assert counts_before["mutate"] == 1
    assert counts_before["reuse"] == 0

    # The harmful edge produces a repair opportunity on its target cell; the
    # mutation context only ever carries the safe failure code.  (Durable
    # chaining of the NEXT action requires the gate settlement/promotion
    # cycle — the saga is gate-delimited by design — so round 2 continues in
    # the live session here.)
    harm_observation = FailureObservationV2(
        failure_id="failure:v5:round1-harm",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=edge.target_composition.composition_id,
        transition_id=edge.transition.transition_id,
        artifact_sha256=edge.target_composition.artifact_sha256,
        created_seq=harness.bank.to_state().event_seq + 1,
    )
    repair = harness.bank.record_failure(
        harm_observation, feasible_branches=("reuse",)
    )
    assert repair is not None
    assert repair.source_kind == "algorithm_failure"

    # Capacity/archive pass: an unauthorized attestation can never evict —
    # the authority's archive verifier fails closed on the harmful victim.
    with pytest.raises(ValueError, match="archive verifier rejected"):
        harness.bank.archive_for_capacity(
            harness.experiment.protocol.namespace,
            archive_attestation_sha256=_sha("round1-archive"),
        )

    queue = pending_repair_opportunities(harness.bank)
    assert [item.opportunity_id for item in queue] == [repair.opportunity_id]

    # ---- Round 2: the pending opportunity drives a zero-call reuse action.
    budget_root_before = harness.store.budget_ledger_root_sha256
    _e, _o, _obs, _prop, context, action = harness.prepare_action_from(
        edge,
        queue[0],
        harm_observation,
        expected_branch="reuse",
        source_factor=edge.target_factor,
        source_composition=edge.target_composition,
    )
    assert context is None
    assert action.generation_request is None
    harness.branch_authority.authorize_action(action)
    reconcile_phase_proposal_action_v3(
        registry=harness.registry,
        bank=harness.bank,
        action_id=action.action_id,
    )
    assert harness.store.budget_ledger_root_sha256 == budget_root_before
    assert pending_repair_opportunities(harness.bank) == ()
    counts_after = branch_assignment_counts(harness.bank)
    assert counts_after["reuse"] == 1
    assert counts_after["mutate"] == 1

    # ---- Round 3: another mutate cannot even reserve a generation
    # execution — the frozen TRAIN budget rejects before any model call.
    generation_arm = next(
        item
        for item in harness.experiment.protocol.authorized_logical_arms
        if item.operation_kind == "proposal_generation"
    )
    with pytest.raises((PilotCapacityError, PilotStoreError)):
        reserve_scheduled_execution(
            harness.store,
            schedule=harness.experiment.seal.execution_schedule,
            logical_arm=generation_arm,
            logical_execution_key="v5-generation-owner-round3",
            action_id=action.action_id,
        )


def test_scheduler_owns_no_hidden_state_across_reopen(harness) -> None:
    edge = harness.anchor_edge()
    observation = FailureObservationV2(
        failure_id="failure:v5:queue",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=edge.source_composition.composition_id,
        artifact_sha256=edge.source_composition.artifact_sha256,
        created_seq=harness.bank.to_state().event_seq + 1,
    )
    opportunity = harness.bank.record_failure(
        observation, feasible_branches=("reuse",)
    )
    assert opportunity is not None
    # The queue derives purely from Bank state and survives reopen without
    # any caller-side memory. (The un-checkpointed tail is deliberately
    # discarded by recovery: the queue must re-derive from the restored
    # component head, not from in-process state.)
    queue_before = pending_repair_opportunities(harness.bank)
    assert [item.opportunity_id for item in queue_before] == [
        opportunity.opportunity_id
    ]
    harness.reopen()
    restored_queue = pending_repair_opportunities(harness.bank)
    assert restored_queue == ()  # failure was never checkpointed
    assert branch_assignment_counts(harness.bank) == {
        "reuse": 0,
        "mutate": 0,
        "fresh": 0,
    }
