from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

from exp_graph.mas.factor_bank import ExecutionUsage
from exp_graph.mas.factor_bank_v2 import (
    make_arm_receipt_v2,
    make_assignment_receipt_v2,
    make_pair_execution_receipt_v2,
)
from exp_graph.mas.phase_program import PhaseProgramLimits
from masbench.sft_pilot.components import (
    PilotComponentCoordinator,
    build_empty_component_envelopes,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotCapacityPreflightV1,
    PilotExecutionLeaseRequestV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
)
from masbench.sft_pilot.store import (
    PilotStateTransitionError,
    PilotStoreError,
    PilotStoreIntegrityError,
    SingleWriterPilotStore,
    component_bundle_state_sha256,
)


STORE_KEY = hashlib.sha256(b"checkpoint-saga-store-v2").digest()
PHASE_KEY = hashlib.sha256(b"checkpoint-saga-phase-v2").digest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _load_factor_fixture_module():
    """Reuse the canonical Factor API fixture without importing production tests."""

    path = Path(__file__).parents[2] / "exp-graph/tests/test_factor_bank_v2.py"
    spec = importlib.util.spec_from_file_location(
        "_sft_checkpoint_factor_fixture", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FACTOR_FIXTURE = _load_factor_fixture_module()
FACTOR_KEY = b"factor-bank-v2-test-key" * 2


def _arm(
    *,
    pair_id: str,
    pair_arm: str,
    operation_kind: str,
    ordinal: int,
) -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id=pair_id,
        pair_arm=pair_arm,
        case_commitment_sha256=_sha(f"case:{pair_id}"),
        unit_commitment=f"unit-{pair_id}",
        split="TRAIN_UPDATE",
        operation_kind=operation_kind,
        execution_ordinal=ordinal,
    )


PROPOSAL_ARM = _arm(
    pair_id="proposal",
    pair_arm="control",
    operation_kind="proposal_generation",
    ordinal=6,
)
PROPOSAL_ALIAS_ARM = _arm(
    pair_id="proposal-alias",
    pair_arm="control",
    operation_kind="proposal_generation",
    ordinal=7,
)
PROBE_ARMS = tuple(
    _arm(
        pair_id=f"pair-{ordinal}",
        pair_arm=pair_arm,
        operation_kind=f"{pair_arm}_probe",
        ordinal=ordinal,
    )
    for ordinal in range(6)
    for pair_arm in ("source", "target")
)


def _protocol(fixture, genesis_sha256: str) -> PilotProtocolV1:
    return PilotProtocolV1(
        protocol_id="checkpoint-semantics-v2",
        method_arm="sft_unified",
        namespace=fixture.namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("catalog"),
            source_policy_sha256=_sha("source-policy"),
        ),
        source_authority_sha256=_sha("source-authority"),
        dataset_split_policy_sha256=_sha("split-policy"),
        candidate_pool_manifest_sha256=_sha("candidate-pool"),
        runner_config_sha256=_sha("runner"),
        model_config_sha256=_sha("model"),
        pair_manifest_sha256=_sha("pairs"),
        genesis_state_sha256=genesis_sha256,
        component_bundle_required=True,
        component_checkpoint_saga_required=True,
        authorized_logical_arms=(
            PROPOSAL_ARM,
            PROPOSAL_ALIAS_ARM,
            *PROBE_ARMS,
        ),
        phase_budgets=(
            AuthorizedPhaseBudgetV1(
                phase="TRAIN_UPDATE",
                method_arm="sft_unified",
                executions=8,
                call_slots=8,
                input_tokens=32_768,
                output_tokens=8_192,
            ),
            AuthorizedPhaseBudgetV1(
                phase="PROBE",
                method_arm="sft_unified",
                executions=12,
                call_slots=12,
                input_tokens=49_152,
                output_tokens=12_288,
            ),
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=4,
            max_execution_leases=24,
            max_call_receipts=24,
            max_component_checkpoints=32,
            max_call_slots_per_execution=1,
            max_input_tokens_per_call=4_096,
            max_output_tokens_per_call=1_024,
            max_active_db_bytes=64 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=32 * 1024 * 1024,
        ),
    )


def _capabilities(_registry):
    return FACTOR_FIXTURE._trusted_bank_capabilities()


def _coordinator(store: SingleWriterPilotStore) -> PilotComponentCoordinator:
    return PilotComponentCoordinator(
        store=store,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
        manifest_verifier=lambda _manifest: False,
        factor_capabilities_factory=_capabilities,
    )


def _open_initialized(tmp_path: Path):
    fixture = FACTOR_FIXTURE.Fixture()
    state_dir = tmp_path / "checkpoint-state"
    phase_bytes, _empty_factor_bytes = build_empty_component_envelopes(
        state_dir,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
        manifest_verifier=lambda _manifest: False,
        factor_capabilities_factory=_capabilities,
    )
    fixture_factor_path = state_dir / "semantic-genesis.factor.json"
    fixture.bank.save(fixture_factor_path)
    factor_bytes = fixture_factor_path.read_bytes()
    protocol = _protocol(
        fixture,
        component_bundle_state_sha256(
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        ),
    )
    store = SingleWriterPilotStore.open(
        state_dir,
        protocol=protocol,
        hmac_key=STORE_KEY,
    )
    store.record_genesis_component_bundle(
        operation_id="checkpoint-genesis",
        request_sha256=_sha("checkpoint-genesis"),
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    store.record_capacity_preflight(
        PilotCapacityPreflightV1(
            planned_scientific_commits=2,
            planned_execution_leases=16,
            planned_call_receipts=16,
            planned_component_checkpoints=16,
            planned_max_calls_per_execution=1,
            planned_max_active_db_bytes=48 * 1024 * 1024,
            planned_archive_bytes=32 * 1024,
            planned_total_stored_scalar_bytes=24 * 1024 * 1024,
            planned_max_input_tokens_per_call=4_096,
            planned_max_output_tokens_per_call=1_024,
            quarantined_carriers_reserved=1,
            indeterminate_call_reserve=1,
        ),
        operation_id="checkpoint-preflight",
        request_sha256=_sha("checkpoint-preflight"),
    )
    return fixture, store, _coordinator(store), protocol


def _reopen(store, protocol):
    state_dir = store.state_dir
    store.close()
    reopened = SingleWriterPilotStore.open(
        state_dir,
        protocol=protocol,
        hmac_key=STORE_KEY,
    )
    return reopened, _coordinator(reopened)


def _reserve_execution(store, *, key: str, arm, action_id: str) -> None:
    store.reserve_execution(
        PilotExecutionLeaseRequestV1(
            logical_execution_key=key,
            operation_kind=arm.operation_kind,
            request_sha256=_sha(f"request:{key}"),
            namespace_sha256=store.protocol.namespace.digest,
            split="TRAIN_UPDATE",
            unit_commitment=arm.unit_commitment,
            action_id=action_id,
            call_slots_reserved=1,
            input_tokens_reserved=4_096,
            output_tokens_reserved=1_024,
        ),
        logical_arm=arm,
        operation_id=f"reserve-{key}",
        operation_request_sha256=_sha(f"reserve:{key}"),
    )


def _run_call(
    store,
    *,
    execution: str,
    call_key: str,
    recovery_root: str,
    complete: bool = True,
) -> None:
    request_sha = _sha(f"call-request:{call_key}")
    store.reserve_call(
        operation_id=f"reserve-{call_key}",
        operation_request_sha256=_sha(f"reserve:{call_key}"),
        call_key=call_key,
        logical_execution_key=execution,
        call_slot=0,
        call_request_sha256=request_sha,
        input_tokens_reserved=4_096,
        output_tokens_reserved=1_024,
        expected_component_recovery_root_sha256=recovery_root,
    )
    authorization = store.start_call(
        call_key,
        operation_id=f"start-{call_key}",
        operation_request_sha256=_sha(f"start:{call_key}"),
        call_request_sha256=request_sha,
        expected_component_recovery_root_sha256=recovery_root,
    )
    assert authorization.may_invoke_sdk
    if not complete:
        return
    store.complete_call(
        call_key,
        operation_id=f"complete-{call_key}",
        operation_request_sha256=_sha(f"complete:{call_key}"),
        call_request_sha256=request_sha,
        output_envelope_sha256=_sha(f"output:{call_key}"),
        provider_usage_known=True,
        input_tokens_used=32,
        output_tokens_used=8,
    )
    store.complete_execution(
        execution,
        operation_id=f"complete-{execution}",
        operation_request_sha256=_sha(f"complete:{execution}"),
    )


def _checkpoint(coordinator, loaded, ordinal: int):
    return coordinator.checkpoint_loaded(
        loaded,
        operation_id=f"checkpoint-{ordinal}",
        operation_request_sha256=_sha(f"checkpoint:{ordinal}"),
    )


def _complete_attempt(fixture, attempt, transition, source, target, tag: str):
    source_root = _sha(f"root:{tag}:source")
    target_root = _sha(f"root:{tag}:target")
    if attempt.assignment.arm_order == "AB":
        source_started, source_finished = 1, 2
        target_started, target_finished = 3, 4
    else:
        target_started, target_finished = 1, 2
        source_started, source_finished = 3, 4
    pair = make_pair_execution_receipt_v2(
        attempt=attempt,
        source_root_id=source_root,
        target_root_id=target_root,
        source_started_seq=source_started,
        source_finished_seq=source_finished,
        target_started_seq=target_started,
        target_finished_seq=target_finished,
        verifier_epoch="pair-runner:checkpoint",
        attestation_sha256=_sha(f"pair-attestation:{tag}"),
    )
    usage = ExecutionUsage(
        messages=4,
        model_calls=2,
        input_tokens=1_000,
        output_tokens=200,
        wall_time_ms=2_000,
        cost_microusd=2_000,
    )

    def receipt(arm: str):
        return make_arm_receipt_v2(
            plan=fixture.plan,
            attempt=attempt,
            composition=source if arm == "source" else target,
            transition=transition,
            arm=arm,
            root_id=source_root if arm == "source" else target_root,
            paired_arm_root_id=target_root if arm == "source" else source_root,
            pair_execution_receipt=pair,
            runtime_profile_id="runtime-profile:checkpoint",
            materialization_event_id="materialization:checkpoint",
            activation_trace_root=_sha(f"activation:{tag}:{arm}"),
            usage=usage,
            execution_class="completed",
            outcome=(
                FACTOR_FIXTURE._outcome(0.50, V=0.50)
                if arm == "source"
                else FACTOR_FIXTURE._outcome(0.60, V=0.60, C=9.0)
            ),
            producer_epoch="receipt-producer:checkpoint",
            attestation_sha256=_sha(f"receipt-attestation:{tag}:{arm}"),
        )

    return fixture.bank.commit_attempt(
        attempt.attempt_id,
        receipt("source"),
        receipt("target"),
        pair,
    )


def _build_until_probe_terminal(
    fixture,
    store,
    coordinator,
    *,
    complete_proposal: bool = True,
):
    loaded = coordinator.restore_recovery_head()
    fixture.bank = loaded.bank
    *_prefix, prepared = FACTOR_FIXTURE._prepare_generated_action(
        fixture, "mutate", "checkpoint"
    )
    _reserve_execution(
        store,
        key="proposal-owner",
        arm=PROPOSAL_ARM,
        action_id=prepared.action_id,
    )
    loaded = _checkpoint(coordinator, loaded, 1)
    assert loaded.snapshot.checkpoint.checkpoint_kind == "action_prepared"

    fixture.bank = loaded.bank
    executing = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        FACTOR_FIXTURE._generation_lease(prepared, "checkpoint"),
    )
    loaded = _checkpoint(coordinator, loaded, 2)
    assert loaded.snapshot.checkpoint.checkpoint_kind == (
        "generation_start_authorized"
    )
    _run_call(
        store,
        execution="proposal-owner",
        call_key="proposal-call",
        recovery_root=loaded.snapshot.recovery_root_sha256,
        complete=complete_proposal,
    )

    fixture.bank = loaded.bank
    generated, target = FACTOR_FIXTURE._uninstalled_generated_carrier(
        fixture, "mutate", "checkpoint"
    )
    proof_sha = _sha("generated-proof:checkpoint")
    transition = FACTOR_FIXTURE._register_action_bundle(
        fixture,
        action=executing,
        branch="mutate",
        tag="checkpoint",
        generated=generated,
        target=target,
        proof_sha256=proof_sha,
    )
    fixture.bank.finalize_proposal_action(
        executing.action_id,
        transition_id=transition.transition_id,
        phase_terminal_sha256=proof_sha,
        generation_terminal_sha256=_sha("generation-terminal:checkpoint"),
        resolved_to_revision_id=generated.revision_id,
        resolved_target_content_sha256=generated.content_sha256,
    )
    fixture.plan = fixture.bank.seal_probe_plan(
        transition_id=transition.transition_id,
        owner_kind="direct_factor",
        epoch_id="epoch:checkpoint",
        unit_commitments=tuple(_sha(f"checkpoint-unit-{i}") for i in range(6)),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_sha("checkpoint-assignment-manifest"),
        runner_version="runner:checkpoint",
        budget=FACTOR_FIXTURE._budget(),
    )
    fixture.transition = transition
    fixture.source = fixture.source
    fixture.target = target

    checkpoint_ordinal = 3
    for ordinal in range(4):
        assignment = make_assignment_receipt_v2(
            plan=fixture.plan,
            ordinal=ordinal,
            origin_pool_sha256=_sha("origin-pool:checkpoint"),
            producer_epoch="assignment-producer:checkpoint",
            attestation_sha256=_sha(f"assignment:{ordinal}"),
        )
        attempt = fixture.bank.open_next_attempt(
            fixture.plan.plan_id,
            assignment,
            FACTOR_FIXTURE._runner_lease(
                fixture.plan, assignment, f"checkpoint-{ordinal}"
            ),
        )
        for pair_arm in ("source", "target"):
            arm = next(
                item
                for item in PROBE_ARMS
                if item.execution_ordinal == ordinal and item.pair_arm == pair_arm
            )
            _reserve_execution(
                store,
                key=f"probe-{ordinal}-{pair_arm}",
                arm=arm,
                action_id=prepared.action_id,
            )
        loaded = _checkpoint(coordinator, loaded, checkpoint_ordinal)
        checkpoint_ordinal += 1
        assert loaded.snapshot.checkpoint.checkpoint_kind == "probe_attempt_open"
        root = loaded.snapshot.recovery_root_sha256
        order = (
            ("source", "target")
            if attempt.assignment.arm_order == "AB"
            else ("target", "source")
        )
        for pair_arm in order:
            _run_call(
                store,
                execution=f"probe-{ordinal}-{pair_arm}",
                call_key=f"probe-call-{ordinal}-{pair_arm}",
                recovery_root=root,
            )
        fixture.bank = loaded.bank
        _complete_attempt(
            fixture,
            attempt,
            transition,
            fixture.source,
            target,
            f"attempt-{ordinal}",
        )
        loaded = _checkpoint(coordinator, loaded, checkpoint_ordinal)
        checkpoint_ordinal += 1
        assert loaded.snapshot.checkpoint.checkpoint_kind == "probe_terminal"
        fixture.bank = loaded.bank
    return loaded, checkpoint_ordinal, prepared


def test_real_factor_lifecycle_derives_kinds_reopens_and_promotes(tmp_path: Path):
    fixture, store, coordinator, protocol = _open_initialized(tmp_path)
    try:
        loaded, ordinal, _prepared = _build_until_probe_terminal(
            fixture, store, coordinator
        )
        fixture.bank = loaded.bank
        fixture.gate(accepted=True)
        loaded = _checkpoint(coordinator, loaded, ordinal)
        checkpoint = loaded.snapshot.checkpoint
        assert checkpoint is not None
        assert checkpoint.checkpoint_kind == "gate_terminal"
        assert checkpoint.semantic_witness.assessment_sha256 is not None
        assert checkpoint.semantic_witness.gate_receipt_sha256 is not None
        assert checkpoint.action_owner_logical_execution_key == "proposal-owner"
        store, coordinator = _reopen(store, protocol)
        recovered = coordinator.restore_recovery_head()
        assert recovered.snapshot == loaded.snapshot
        promoted = coordinator.promote_settled_checkpoint(
            recovered,
            operation_id="promote-checkpoint-action",
            owner_logical_execution_key="proposal-owner",
            request_sha256=_sha("promote-checkpoint-action"),
        )
        assert promoted.snapshot.metadata.generation == 1
    finally:
        store.close()


def test_phase_only_bytes_cannot_claim_any_checkpoint_kind(tmp_path: Path):
    _fixture, store, coordinator, _protocol_value = _open_initialized(tmp_path)
    try:
        loaded = coordinator.restore_recovery_head()
        loaded.registry.register_runtime_profile(
            namespace=store.protocol.namespace,
            limits=PhaseProgramLimits(max_steps=9, max_messages=33),
        )
        with pytest.raises(PilotStateTransitionError, match="Factor lifecycle"):
            coordinator.checkpoint_loaded(
                loaded,
                operation_id="phase-only",
                operation_request_sha256=_sha("phase-only"),
            )
        assert store.latest_component_recovery_snapshot().origin == (
            "scientific_bundle"
        )
    finally:
        store.close()


def test_two_proposal_owners_for_same_action_fail_closed(tmp_path: Path):
    fixture, store, coordinator, _protocol_value = _open_initialized(tmp_path)
    try:
        loaded = coordinator.restore_recovery_head()
        fixture.bank = loaded.bank
        *_prefix, action = FACTOR_FIXTURE._prepare_generated_action(
            fixture, "mutate", "owner-alias"
        )
        _reserve_execution(
            store,
            key="proposal-owner",
            arm=PROPOSAL_ARM,
            action_id=action.action_id,
        )
        _reserve_execution(
            store,
            key="proposal-alias",
            arm=PROPOSAL_ALIAS_ARM,
            action_id=action.action_id,
        )
        with pytest.raises(PilotStoreIntegrityError, match="one exact proposal owner"):
            coordinator.checkpoint_loaded(
                loaded,
                operation_id="owner-alias-checkpoint",
                operation_request_sha256=_sha("owner-alias-checkpoint"),
            )
        assert store.latest_component_recovery_snapshot().origin == (
            "scientific_bundle"
        )
    finally:
        store.close()


def test_settled_assessment_without_gate_receipt_cannot_settle(tmp_path: Path):
    fixture, store, coordinator, _protocol_value = _open_initialized(tmp_path)
    try:
        loaded, ordinal, _prepared = _build_until_probe_terminal(
            fixture, store, coordinator
        )
        assessment = next(
            item
            for item in loaded.bank.to_state().assessments
            if item.plan_id == fixture.plan.plan_id
        )
        assert assessment.settled and assessment.label == "candidate"
        loaded.registry.register_runtime_profile(
            namespace=store.protocol.namespace,
            limits=PhaseProgramLimits(max_steps=11, max_messages=35),
        )
        with pytest.raises(PilotStateTransitionError, match="Factor lifecycle"):
            _checkpoint(coordinator, loaded, ordinal)
        recovery = store.latest_component_recovery_snapshot()
        assert recovery.checkpoint is not None
        assert recovery.checkpoint.checkpoint_kind == "probe_terminal"
        assert not recovery.checkpoint.settled
    finally:
        store.close()


def test_pre_gate_inflight_cannot_become_promotable_after_crash(tmp_path: Path):
    fixture, store, coordinator, protocol = _open_initialized(tmp_path)
    loaded = coordinator.restore_recovery_head()
    fixture.bank = loaded.bank
    *_prefix, prepared = FACTOR_FIXTURE._prepare_generated_action(
        fixture, "mutate", "pregate-crash"
    )
    _reserve_execution(
        store,
        key="proposal-owner",
        arm=PROPOSAL_ARM,
        action_id=prepared.action_id,
    )
    loaded = _checkpoint(coordinator, loaded, 1)
    fixture.bank = loaded.bank
    fixture.bank.begin_proposal_generation(
        prepared.action_id,
        FACTOR_FIXTURE._generation_lease(prepared, "pregate-crash"),
    )
    loaded = _checkpoint(coordinator, loaded, 2)
    _run_call(
        store,
        execution="proposal-owner",
        call_key="proposal-call",
        recovery_root=loaded.snapshot.recovery_root_sha256,
        complete=False,
    )
    loaded.registry.register_runtime_profile(
        namespace=store.protocol.namespace,
        limits=PhaseProgramLimits(max_steps=10, max_messages=34),
    )
    with pytest.raises(PilotStateTransitionError, match="Factor lifecycle"):
        _checkpoint(coordinator, loaded, 3)
    generation_root = loaded.snapshot.recovery_root_sha256
    store, coordinator = _reopen(store, protocol)
    try:
        assert store.get_execution("proposal-owner").state == "indeterminate"
        recovered = coordinator.restore_recovery_head()
        assert recovered.snapshot.recovery_root_sha256 == generation_root
        assert recovered.snapshot.checkpoint is not None
        assert recovered.snapshot.checkpoint.checkpoint_kind == (
            "generation_start_authorized"
        )
        with pytest.raises(PilotStateTransitionError, match="settled recovery head"):
            coordinator.promote_settled_checkpoint(
                recovered,
                operation_id="post-crash-promotion",
                owner_logical_execution_key="proposal-owner",
                request_sha256=_sha("post-crash-promotion"),
            )
    finally:
        store.close()


def test_semantic_checkpoint_transaction_rolls_back_and_hmac_tamper_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture, store, coordinator, protocol = _open_initialized(tmp_path)
    loaded = coordinator.restore_recovery_head()
    fixture.bank = loaded.bank
    *_prefix, action = FACTOR_FIXTURE._prepare_generated_action(
        fixture, "mutate", "rollback"
    )
    _reserve_execution(
        store,
        key="proposal-owner",
        arm=PROPOSAL_ARM,
        action_id=action.action_id,
    )

    def reject_commit(_connection) -> None:
        raise PilotStoreError("injected checkpoint commit boundary")

    monkeypatch.setattr(store, "_enforce_live_capacity", reject_commit)
    with pytest.raises(PilotStoreError, match="injected checkpoint"):
        coordinator.checkpoint_loaded(
            loaded,
            operation_id="checkpoint-rollback",
            operation_request_sha256=_sha("checkpoint-rollback"),
        )
    assert store.latest_component_recovery_snapshot().origin == "scientific_bundle"
    monkeypatch.undo()
    loaded = coordinator.restore_recovery_head()
    fixture.bank = loaded.bank
    *_prefix, replayed_action = FACTOR_FIXTURE._prepare_generated_action(
        fixture, "mutate", "rollback"
    )
    assert replayed_action.action_id == action.action_id
    loaded = coordinator.checkpoint_loaded(
        loaded,
        operation_id="checkpoint-authenticated",
        operation_request_sha256=_sha("checkpoint-authenticated"),
    )
    database_path = store.database_path
    state_dir = store.state_dir
    store.close()
    connection = sqlite3.connect(database_path)
    try:
        trigger_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' "
                "AND name='component_checkpoint_no_update'"
            ).fetchone()[0]
        )
        connection.execute("DROP TRIGGER component_checkpoint_no_update")
        connection.execute(
            "UPDATE component_checkpoint SET semantic_witness_sha256=? "
            "WHERE checkpoint_ordinal=1",
            (_sha("forged-semantics"),),
        )
        connection.execute(trigger_sql)
        connection.commit()
    finally:
        connection.close()
    with pytest.raises((PilotStoreIntegrityError, ValueError)):
        SingleWriterPilotStore.open(
            state_dir,
            protocol=protocol,
            hmac_key=STORE_KEY,
        )
