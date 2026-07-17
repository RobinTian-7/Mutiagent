from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.phase_artifact_registry import PHASE_FACTOR_BINDER_VERSION
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgramLimits,
)
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
    PilotComponentBundleSnapshotV1,
)
from masbench.sft_pilot.store import (
    PilotStoreError,
    SingleWriterPilotStore,
    component_bundle_state_sha256,
)


STORE_KEY = b"component-coordinator-store-key-32bytes"
PHASE_KEY = hashlib.sha256(b"component-phase-key").digest()
FACTOR_KEY = hashlib.sha256(b"component-factor-key").digest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace() -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=2,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="pilot-runtime-v1",
        binder_version=PHASE_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _arm() -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id="pair-component",
        pair_arm="control",
        case_commitment_sha256=_sha("case-component"),
        unit_commitment="unit-component",
        split="TRAIN_UPDATE",
        operation_kind="proposal_generation",
        execution_ordinal=0,
    )


def _protocol(genesis_sha256: str) -> PilotProtocolV1:
    return PilotProtocolV1(
        protocol_id="component-coordinator-v1",
        method_arm="sft_unified",
        namespace=_namespace(),
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("catalog"),
            source_policy_sha256=_sha("source-policy"),
        ),
        source_authority_sha256=_sha("source-authority"),
        dataset_split_policy_sha256=_sha("split-policy"),
        candidate_pool_manifest_sha256=_sha("candidates"),
        runner_config_sha256=_sha("runner"),
        model_config_sha256=_sha("model"),
        pair_manifest_sha256=_sha("pairs"),
        genesis_state_sha256=genesis_sha256,
        component_bundle_required=True,
        authorized_logical_arms=(_arm(),),
        phase_budgets=tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm="sft_unified",
                executions=2,
                call_slots=2,
                input_tokens=4_096,
                output_tokens=2_048,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=4,
            max_execution_leases=4,
            max_call_receipts=4,
            max_call_slots_per_execution=2,
            max_input_tokens_per_call=3_072,
            max_output_tokens_per_call=1_024,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=8 * 1024 * 1024,
        ),
    )


def _preflight(store: SingleWriterPilotStore) -> None:
    store.record_capacity_preflight(
        PilotCapacityPreflightV1(
            planned_scientific_commits=2,
            planned_execution_leases=2,
            planned_call_receipts=2,
            planned_max_calls_per_execution=1,
            planned_max_active_db_bytes=8 * 1024 * 1024,
            planned_archive_bytes=32 * 1024,
            planned_total_stored_scalar_bytes=4 * 1024 * 1024,
            planned_max_input_tokens_per_call=3_072,
            planned_max_output_tokens_per_call=1_024,
            quarantined_carriers_reserved=1,
            indeterminate_call_reserve=1,
        ),
        operation_id="component-preflight",
        request_sha256=_sha("component-preflight"),
    )


def _complete_owner(store: SingleWriterPilotStore) -> None:
    call_request = _sha("component-call-request")
    store.reserve_execution(
        PilotExecutionLeaseRequestV1(
            logical_execution_key="execution-component",
            operation_kind="proposal_generation",
            request_sha256=_sha("execution-component"),
            namespace_sha256=store.protocol.namespace.digest,
            split="TRAIN_UPDATE",
            unit_commitment="unit-component",
            action_id="action-component",
            call_slots_reserved=1,
            input_tokens_reserved=3_072,
            output_tokens_reserved=1_024,
        ),
        logical_arm=_arm(),
        operation_id="reserve-execution-component",
        operation_request_sha256=_sha("reserve-execution-component"),
    )
    store.reserve_call(
        operation_id="reserve-call-component",
        operation_request_sha256=_sha("reserve-call-component"),
        call_key="call-component",
        logical_execution_key="execution-component",
        call_slot=0,
        call_request_sha256=call_request,
        input_tokens_reserved=3_072,
        output_tokens_reserved=1_024,
    )
    assert store.start_call(
        "call-component",
        operation_id="start-call-component",
        operation_request_sha256=_sha("start-call-component"),
        call_request_sha256=call_request,
    ).may_invoke_sdk
    store.complete_call(
        "call-component",
        operation_id="complete-call-component",
        operation_request_sha256=_sha("complete-call-component"),
        call_request_sha256=call_request,
        output_envelope_sha256=_sha("output-component"),
        provider_usage_known=True,
        input_tokens_used=12,
        output_tokens_used=3,
    )
    store.complete_execution(
        "execution-component",
        operation_id="complete-execution-component",
        operation_request_sha256=_sha("complete-execution-component"),
    )


def _open_initialized(tmp_path: Path) -> tuple[SingleWriterPilotStore, PilotComponentCoordinator]:
    state_dir = tmp_path / "state"
    phase_bytes, factor_bytes = build_empty_component_envelopes(
        state_dir,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
        manifest_verifier=lambda _manifest: False,
    )
    genesis = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    store = SingleWriterPilotStore.open(
        state_dir,
        protocol=_protocol(genesis),
        hmac_key=STORE_KEY,
    )
    store.record_genesis_component_bundle(
        operation_id="component-genesis",
        request_sha256=_sha("component-genesis"),
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    coordinator = PilotComponentCoordinator(
        store=store,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
        manifest_verifier=lambda _manifest: False,
    )
    return store, coordinator


def test_restore_discards_working_file_drift(tmp_path: Path) -> None:
    store, coordinator = _open_initialized(tmp_path)
    try:
        first = coordinator.restore_latest()
        coordinator.phase_path.write_text("not an envelope", encoding="utf-8")
        coordinator.factor_path.write_text("not an envelope", encoding="utf-8")
        restored = coordinator.restore_latest()
        assert restored.snapshot == first.snapshot
        assert coordinator.phase_path.read_bytes() == (
            first.snapshot.phase_registry_envelope_bytes
        )
        assert coordinator.factor_path.read_bytes() == (
            first.snapshot.factor_bank_envelope_bytes
        )
    finally:
        store.close()


def test_component_mutation_commits_and_reopens_exact_generation(tmp_path: Path) -> None:
    store, coordinator = _open_initialized(tmp_path)
    protocol = store.protocol
    try:
        _preflight(store)
        _complete_owner(store)
        loaded = coordinator.restore_latest()
        loaded.registry.register_runtime_profile(
            namespace=protocol.namespace,
            limits=PhaseProgramLimits(
                max_steps=8,
                max_messages=32,
                max_receiver_fan_in=2,
            ),
        )
        committed = coordinator.commit_loaded(
            loaded,
            operation_id="component-scientific-one",
            owner_logical_execution_key="execution-component",
            request_sha256=_sha("component-scientific-one"),
        )
        assert committed.snapshot.metadata.generation == 1
        assert len(committed.registry.to_state().profiles) == 1
        state_dir = store.state_dir
    finally:
        store.close()

    with SingleWriterPilotStore.open(
        state_dir,
        protocol=protocol,
        hmac_key=STORE_KEY,
    ) as reopened:
        restored = PilotComponentCoordinator(
            store=reopened,
            phase_registry_key=PHASE_KEY,
            factor_bank_key=FACTOR_KEY,
            manifest_verifier=lambda _manifest: False,
        ).restore_latest()
        assert restored.snapshot.metadata.generation == 1
        assert len(restored.registry.to_state().profiles) == 1


def test_failed_component_commit_restores_prior_working_bytes(tmp_path: Path) -> None:
    store, coordinator = _open_initialized(tmp_path)
    try:
        original = coordinator.restore_latest().snapshot
        loaded = coordinator.restore_latest()
        loaded.registry.register_runtime_profile(
            namespace=store.protocol.namespace,
            limits=PhaseProgramLimits(max_steps=4, max_messages=16),
        )
        # No preflight/completed owner: SQLite publication must fail and the
        # sidecars must immediately return to the committed generation.
        with pytest.raises(PilotStoreError):
            coordinator.commit_loaded(
                loaded,
                operation_id="component-invalid-owner",
                owner_logical_execution_key="missing-owner",
                request_sha256=_sha("component-invalid-owner"),
            )
        assert coordinator.phase_path.read_bytes() == (
            original.phase_registry_envelope_bytes
        )
        assert coordinator.factor_path.read_bytes() == (
            original.factor_bank_envelope_bytes
        )
    finally:
        store.close()


def test_store_rejects_same_bytes_as_a_new_component_generation(tmp_path: Path) -> None:
    store, coordinator = _open_initialized(tmp_path)
    try:
        _preflight(store)
        _complete_owner(store)
        current = coordinator.restore_latest().snapshot
        with pytest.raises(PilotStoreError, match="must change"):
            store.append_component_scientific_commit(
                operation_id="component-same-bytes",
                owner_logical_execution_key="execution-component",
                request_sha256=_sha("component-same-bytes"),
                before_state_sha256=current.metadata.bundle_sha256,
                phase_registry_envelope_bytes=current.phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=current.factor_bank_envelope_bytes,
            )
        assert store.latest_component_bundle() == current
    finally:
        store.close()


def test_recovery_validation_rejects_legacy_adjacent_same_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, coordinator = _open_initialized(tmp_path)
    try:
        _preflight(store)
        _complete_owner(store)
        genesis = coordinator.restore_latest().snapshot
        loaded = coordinator.restore_latest()
        loaded.registry.register_runtime_profile(
            namespace=store.protocol.namespace,
            limits=PhaseProgramLimits(max_steps=8, max_messages=32),
        )
        committed = coordinator.commit_loaded(
            loaded,
            operation_id="component-real-change",
            owner_logical_execution_key="execution-component",
            request_sha256=_sha("component-real-change"),
        )
        assert committed.snapshot.metadata.generation == 1
        legacy_metadata = store._component_bundle_metadata(  # noqa: SLF001
            generation=1,
            scientific_commit_ordinal=1,
            phase_registry_envelope_bytes=genesis.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=genesis.factor_bank_envelope_bytes,
            previous_bundle_sha256=genesis.metadata.bundle_sha256,
        )
        legacy = PilotComponentBundleSnapshotV1(
            metadata=legacy_metadata,
            phase_registry_envelope_bytes=genesis.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=genesis.factor_bank_envelope_bytes,
        )
        native_loader = store._component_snapshot_from_row  # noqa: SLF001

        def legacy_loader(row):
            if int(row["generation"]) == 1:
                return legacy
            return native_loader(row)

        monkeypatch.setattr(store, "_component_snapshot_from_row", legacy_loader)
        with pytest.raises(PilotStoreError, match="repeat exact state bytes"):
            store._verify_component_bundles()  # noqa: SLF001
    finally:
        store.close()
