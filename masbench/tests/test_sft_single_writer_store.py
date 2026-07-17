from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.factor_bank_v2 import FactorBankV2
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
)
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgramLimits,
)
from masbench.sft_pilot.schema import (
    PILOT_USER_VERSION,
    AuthorizedPhaseBudgetV1,
    PilotArchivePayloadV1,
    PilotCapacityPolicyV1,
    PilotCapacityPreflightV1,
    PilotExecutionLeaseRequestV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
)
from masbench.sft_pilot.store import (
    EXPECTED_SCHEMA_DIGEST,
    PilotCapacityError,
    PilotIdempotenceConflict,
    PilotProtocolSealedError,
    PilotStoreError,
    PilotStateTransitionError,
    PilotStoreBusyError,
    PilotStoreIntegrityError,
    SingleWriterPilotStore,
    ZERO_SHA256,
    component_bundle_state_sha256,
)


KEY = b"single-writer-pilot-test-key-v1!!"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _protocol(**overrides: object) -> PilotProtocolV1:
    namespace = ExecutionNamespace(
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
        runtime_version="runner-v1",
        binder_version="phase-binder-v1",
        compiler_version="phase-compiler-v1",
    )
    values: dict[str, object] = {
        "protocol_id": "pilot-protocol-1",
        "method_arm": "sft_unified",
        "namespace": namespace,
        "source_manifest": PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("catalog"),
            source_policy_sha256=_sha("source-policy"),
        ),
        "source_authority_sha256": _sha("source-authority"),
        "dataset_split_policy_sha256": _sha("split-policy"),
        "candidate_pool_manifest_sha256": _sha("candidates"),
        "runner_config_sha256": _sha("runner-config"),
        "model_config_sha256": _sha("model-config"),
        "pair_manifest_sha256": _sha("pairs"),
        "genesis_state_sha256": _sha("genesis-state"),
        "authorized_logical_arms": tuple(
            _logical_arm(pair_id=pair_id)
            for pair_id in (
                "pair-1",
                "pair-owner-1",
                "pair-owner-2",
                "pair-owner-3",
                "pair-mixed",
            )
        )
        + (
            _logical_arm(
                pair_id="pair-final",
                split="FINAL_VAL",
                operation_kind="final_val",
            ),
        ),
        "phase_budgets": tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm="sft_unified",
                executions=8,
                call_slots=16,
                input_tokens=32_768,
                output_tokens=16_384,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        "capacity_policy": PilotCapacityPolicyV1(
            max_scientific_commits=16,
            max_execution_leases=16,
            max_call_receipts=32,
            max_call_slots_per_execution=4,
            max_input_tokens_per_call=3_072,
            max_output_tokens_per_call=1_024,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=4 * 1024 * 1024,
        ),
    }
    values.update(overrides)
    return PilotProtocolV1.model_validate(values)


def _preflight(**overrides: int) -> PilotCapacityPreflightV1:
    values = {
        "planned_scientific_commits": 8,
        "planned_execution_leases": 8,
        "planned_call_receipts": 16,
        "planned_max_calls_per_execution": 2,
        "planned_max_active_db_bytes": 8 * 1024 * 1024,
        "planned_archive_bytes": 32 * 1024,
        "planned_total_stored_scalar_bytes": 2 * 1024 * 1024,
        "planned_max_input_tokens_per_call": 3_072,
        "planned_max_output_tokens_per_call": 1_024,
        "quarantined_carriers_reserved": 1,
        "indeterminate_call_reserve": 1,
    }
    values.update(overrides)
    return PilotCapacityPreflightV1(**values)


def _open(tmp_path: Path, *, protocol: PilotProtocolV1 | None = None) -> SingleWriterPilotStore:
    return SingleWriterPilotStore.open(
        tmp_path / "pilot-state",
        protocol=_protocol() if protocol is None else protocol,
        hmac_key=KEY,
    )


def _component_envelopes(tmp_path: Path, *, label: str) -> tuple[bytes, bytes]:
    component_dir = tmp_path / f"components-{label}"
    component_dir.mkdir()
    phase_path = component_dir / "phase.json"
    factor_path = component_dir / "factor.json"
    phase_key = hashlib.sha256(f"phase-{label}".encode()).digest()
    factor_key = hashlib.sha256(f"factor-{label}".encode()).digest()
    registry = PhaseArtifactRegistry(
        registry_key=phase_key,
        manifest_verifier=lambda _manifest: False,
    )
    registry.save(phase_path)
    FactorBankV2(state_key=factor_key).save(factor_path)
    return phase_path.read_bytes(), factor_path.read_bytes()


def _advance_phase_component(tmp_path: Path, *, label: str) -> tuple[bytes, bytes]:
    """Create one real Phase-registry state change under the existing key."""

    component_dir = tmp_path / f"components-{label}"
    phase_path = component_dir / "phase.json"
    factor_path = component_dir / "factor.json"
    registry = PhaseArtifactRegistry.load(
        phase_path,
        registry_key=hashlib.sha256(f"phase-{label}".encode()).digest(),
        manifest_verifier=lambda _manifest: False,
    )
    registry.register_runtime_profile(
        namespace=ExecutionNamespace(
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
            runtime_version="component-test-runtime-v1",
            binder_version=PHASE_FACTOR_BINDER_VERSION,
            compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
        ),
        limits=PhaseProgramLimits(),
    )
    registry.save(phase_path)
    return phase_path.read_bytes(), factor_path.read_bytes()


def _record_preflight(store: SingleWriterPilotStore) -> None:
    store.record_capacity_preflight(
        _preflight(),
        operation_id="op-preflight",
        request_sha256=_sha("preflight-request"),
    )


def _lease(
    protocol: PilotProtocolV1,
    *,
    execution: str = "execution-1",
    request: str = "call-request-1",
    slots: int = 1,
) -> PilotExecutionLeaseRequestV1:
    return PilotExecutionLeaseRequestV1(
        logical_execution_key=execution,
        operation_kind="proposal_generation",
        request_sha256=_sha(request),
        namespace_sha256=protocol.namespace.digest,
        split="TRAIN_UPDATE",
        unit_commitment="unit-1",
        action_id="action-1",
        call_slots_reserved=slots,
        input_tokens_reserved=3_072 * slots,
        output_tokens_reserved=1_024 * slots,
    )


def _logical_arm(
    *,
    pair_id: str = "pair-1",
    execution_ordinal: int = 0,
    split: str = "TRAIN_UPDATE",
    operation_kind: str = "proposal_generation",
) -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id=pair_id,
        pair_arm="control",
        case_commitment_sha256=_sha("case-1"),
        unit_commitment="unit-1",
        split=split,  # type: ignore[arg-type]
        operation_kind=operation_kind,  # type: ignore[arg-type]
        execution_ordinal=execution_ordinal,
    )


def _reserve_execution_and_call(
    store: SingleWriterPilotStore,
    *,
    execution: str = "execution-1",
    call_key: str = "call-1",
    request: str = "call-request-1",
    logical_arm: PilotLogicalArmCoordinatesV1 | None = None,
) -> str:
    call_request_sha = _sha(request)
    store.reserve_execution(
        _lease(store.protocol, execution=execution, request=request),
        logical_arm=_logical_arm() if logical_arm is None else logical_arm,
        operation_id=f"op-reserve-{execution}",
        operation_request_sha256=_sha(f"reserve-{execution}"),
    )
    store.reserve_call(
        operation_id=f"op-reserve-{call_key}",
        operation_request_sha256=_sha(f"reserve-{call_key}"),
        call_key=call_key,
        logical_execution_key=execution,
        call_slot=0,
        call_request_sha256=call_request_sha,
        input_tokens_reserved=3_072,
        output_tokens_reserved=1_024,
    )
    return call_request_sha


def _complete_owner_execution(
    store: SingleWriterPilotStore,
    *,
    execution: str,
    call_key: str,
    pair_id: str,
    request: str,
) -> None:
    call_request = _reserve_execution_and_call(
        store,
        execution=execution,
        call_key=call_key,
        request=request,
        logical_arm=_logical_arm(pair_id=pair_id),
    )
    authorization = store.start_call(
        call_key,
        operation_id=f"op-start-{call_key}",
        operation_request_sha256=_sha(f"start-{call_key}"),
        call_request_sha256=call_request,
    )
    assert authorization.may_invoke_sdk
    store.complete_call(
        call_key,
        operation_id=f"op-complete-{call_key}",
        operation_request_sha256=_sha(f"complete-{call_key}"),
        call_request_sha256=call_request,
        output_envelope_sha256=_sha(f"output-{call_key}"),
        provider_usage_known=True,
        input_tokens_used=12,
        output_tokens_used=3,
    )
    store.complete_execution(
        execution,
        operation_id=f"op-complete-{execution}",
        operation_request_sha256=_sha(f"complete-{execution}"),
    )


def test_protocol_is_closed_single_namespace_and_no_retry() -> None:
    protocol = _protocol()
    assert protocol.model_name == "gpt-4o-mini"
    assert protocol.sdk_max_retries == 0
    assert protocol.application_max_retries == 0
    assert protocol.input_admission_policy == "utf8_bytes_plus_fixed_allowance_v1"
    assert protocol.input_envelope_token_allowance == 256
    assert protocol.namespace.information_goal == "sink"
    assert protocol.digest == protocol.digest

    payload = protocol.model_dump(mode="python")
    payload["sdk_max_retries"] = 1
    with pytest.raises(ValidationError):
        PilotProtocolV1.model_validate(payload)

    payload = protocol.model_dump(mode="python")
    payload["input_envelope_token_allowance"] = 255
    with pytest.raises(ValidationError):
        PilotProtocolV1.model_validate(payload)

    payload = protocol.model_dump(mode="python")
    payload["raw_prompt"] = "hidden"
    with pytest.raises(ValidationError):
        PilotProtocolV1.model_validate(payload)

    with pytest.raises(ValidationError, match="PUBLIC.*TRAIN_UPDATE"):
        PilotSourceManifestV1(
            split="TEST",  # type: ignore[arg-type]
            source_catalog_sha256=_sha("catalog"),
            source_policy_sha256=_sha("policy"),
        )


def test_open_fixes_pragmas_schema_digest_modes_and_stable_lock(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        assert store.protocol_status == "active"
        assert store.schema_digest == EXPECTED_SCHEMA_DIGEST
        assert (store.state_dir.stat().st_mode & 0o777) == 0o700
        assert (store.database_path.stat().st_mode & 0o777) == 0o600
        assert (store.lock_path.stat().st_mode & 0o777) == 0o600
        connection = sqlite3.connect(store.database_path)
        try:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA application_id").fetchone()[0] != 0
            assert (
                connection.execute("PRAGMA user_version").fetchone()[0]
                == PILOT_USER_VERSION
            )
        finally:
            connection.close()

        with pytest.raises(PilotStoreBusyError):
            _open(tmp_path)
        with pytest.raises(sqlite3.IntegrityError, match="identity is frozen"):
            store._connection.execute(  # noqa: SLF001 - physical trigger audit
                "UPDATE protocol SET protocol_json='{}' WHERE only_id=1"
            )


def test_stable_lock_inode_replacement_is_detected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    replacement = store.state_dir / "replacement.lock"
    replacement.write_bytes(b"replacement")
    os.chmod(replacement, 0o600)
    os.replace(replacement, store.lock_path)
    try:
        with pytest.raises(PilotStoreIntegrityError, match="lock identity"):
            _open(tmp_path)
        with pytest.raises(PilotStoreIntegrityError, match="replaced"):
            _record_preflight(store)
    finally:
        store.close()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork/flock")
def test_fork_child_close_cannot_unlock_parent_writer(tmp_path: Path) -> None:
    store = _open(tmp_path)
    pid = os.fork()
    if pid == 0:  # pragma: no branch - child exits immediately
        try:
            store.close()
        except PilotStoreError:
            os._exit(0)
        os._exit(2)
    _, status = os.waitpid(pid, 0)
    try:
        assert os.waitstatus_to_exitcode(status) == 0
        with pytest.raises(PilotStoreBusyError):
            _open(tmp_path)
        _record_preflight(store)
        assert store.protocol_status == "active"
    finally:
        store.close()


def test_preflight_is_required_bounded_and_operation_idempotent(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        with pytest.raises(PilotCapacityError, match="preflight"):
            store.reserve_execution(
                _lease(store.protocol),
                logical_arm=_logical_arm(),
                operation_id="op-reserve-before-preflight",
                operation_request_sha256=_sha("reserve-before-preflight"),
            )
        with pytest.raises(PilotCapacityError, match="call receipts"):
            store.record_capacity_preflight(
                _preflight(planned_call_receipts=33),
                operation_id="op-bad-preflight",
                request_sha256=_sha("bad-preflight"),
            )

        expected = _preflight()
        first = store.record_capacity_preflight(
            expected,
            operation_id="op-preflight",
            request_sha256=_sha("preflight-request"),
        )
        second = store.record_capacity_preflight(
            expected,
            operation_id="op-preflight",
            request_sha256=_sha("preflight-request"),
        )
        assert first == second
        with pytest.raises(PilotIdempotenceConflict):
            store.record_capacity_preflight(
                expected,
                operation_id="op-preflight",
                request_sha256=_sha("changed-preflight-request"),
            )


def test_start_call_requires_every_earlier_slot_completed(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        store.reserve_execution(
            _lease(store.protocol, slots=2),
            logical_arm=_logical_arm(),
            operation_id="op-reserve-sequential-authority",
            operation_request_sha256=_sha("reserve-sequential-authority"),
        )
        store.reserve_call(
            operation_id="op-reserve-sequential-call-0",
            operation_request_sha256=_sha("reserve-sequential-call-0"),
            call_key="sequential-call-0",
            logical_execution_key="execution-1",
            call_slot=0,
            call_request_sha256=_sha("sequential-request-0"),
            input_tokens_reserved=3_072,
            output_tokens_reserved=1_024,
        )
        with pytest.raises(PilotStateTransitionError, match="earlier slots"):
            store.reserve_call(
                operation_id="op-reserve-sequential-call-1-early",
                operation_request_sha256=_sha("reserve-sequential-call-1-early"),
                call_key="sequential-call-1",
                logical_execution_key="execution-1",
                call_slot=1,
                call_request_sha256=_sha("sequential-request-1"),
                input_tokens_reserved=3_072,
                output_tokens_reserved=1_024,
            )
        with pytest.raises(PilotStateTransitionError, match="unknown call"):
            store.get_call("sequential-call-1")


def test_start_call_enforces_one_global_inflight_request(tmp_path: Path) -> None:
    protocol = _protocol(
        authorized_logical_arms=(
            _logical_arm(pair_id="pair-owner-1"),
            _logical_arm(pair_id="pair-owner-2"),
        )
    )
    with _open(tmp_path, protocol=protocol) as store:
        _record_preflight(store)
        for ordinal, pair_id in enumerate(("pair-owner-1", "pair-owner-2"), start=1):
            execution = f"parallel-execution-{ordinal}"
            call_key = f"parallel-call-{ordinal}"
            request = f"parallel-request-{ordinal}"
            store.reserve_execution(
                _lease(
                    protocol,
                    execution=execution,
                    request=request,
                ),
                logical_arm=_logical_arm(pair_id=pair_id),
                operation_id=f"op-reserve-{execution}",
                operation_request_sha256=_sha(f"reserve-{execution}"),
            )
            store.reserve_call(
                operation_id=f"op-reserve-{call_key}",
                operation_request_sha256=_sha(f"reserve-{call_key}"),
                call_key=call_key,
                logical_execution_key=execution,
                call_slot=0,
                call_request_sha256=_sha(request),
                input_tokens_reserved=3_072,
                output_tokens_reserved=1_024,
            )
        assert store.start_call(
            "parallel-call-1",
            operation_id="op-start-parallel-call-1",
            operation_request_sha256=_sha("start-parallel-call-1"),
            call_request_sha256=_sha("parallel-request-1"),
        ).may_invoke_sdk
        with pytest.raises(PilotStateTransitionError, match="in flight"):
            store.start_call(
                "parallel-call-2",
                operation_id="op-start-parallel-call-2",
                operation_request_sha256=_sha("start-parallel-call-2"),
                call_request_sha256=_sha("parallel-request-2"),
            )
        assert store._connection.execute(
            "SELECT COUNT(*) FROM call_receipt WHERE state='request_started'"
        ).fetchone()[0] == 1


def test_logical_arm_is_globally_unique_not_generation_scoped(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        first = _lease(store.protocol)
        reserved = store.reserve_execution(
            first,
            logical_arm=_logical_arm(),
            operation_id="op-reserve-execution-1",
            operation_request_sha256=_sha("reserve-execution-1"),
        )
        assert reserved.logical_arm_key == _logical_arm().derive_logical_arm_key(
            store.protocol
        )
        assert store.reserve_execution(
            first,
            logical_arm=_logical_arm(),
            operation_id="op-reserve-execution-1",
            operation_request_sha256=_sha("reserve-execution-1"),
        ) == reserved

        generation_alias = _lease(
            store.protocol,
            execution="execution-generation-2",
        )
        with pytest.raises(PilotIdempotenceConflict, match="permanently consumed"):
            store.reserve_execution(
                generation_alias,
                logical_arm=_logical_arm(),
                operation_id="op-reserve-generation-2",
                operation_request_sha256=_sha("reserve-generation-2"),
            )
        with pytest.raises(PilotStoreIntegrityError, match="absent"):
            store.reserve_execution(
                _lease(store.protocol, execution="execution-unmanifested"),
                logical_arm=_logical_arm(pair_id="pair-not-frozen"),
                operation_id="op-reserve-unmanifested",
                operation_request_sha256=_sha("reserve-unmanifested"),
            )


def test_call_reserve_start_complete_and_exact_operation_retry(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        call_request = _reserve_execution_and_call(store)

        started = store.start_call(
            "call-1",
            operation_id="op-start-call-1",
            operation_request_sha256=_sha("start-call-1"),
            call_request_sha256=call_request,
        )
        assert started.disposition == "newly_authorized"
        assert started.may_invoke_sdk
        assert started.receipt.state == "request_started"
        retry = store.start_call(
            "call-1",
            operation_id="op-start-call-1",
            operation_request_sha256=_sha("start-call-1"),
            call_request_sha256=call_request,
        )
        assert retry.disposition == "already_started"
        assert not retry.may_invoke_sdk
        completed = store.complete_call(
            "call-1",
            operation_id="op-complete-call-1",
            operation_request_sha256=_sha("complete-call-1"),
            call_request_sha256=call_request,
            output_envelope_sha256=_sha("ephemeral-output"),
            provider_usage_known=True,
            input_tokens_used=301,
            output_tokens_used=97,
        )
        assert completed.state == "completed"
        assert completed.conservative_charged_tokens == 398
        assert store.complete_call(
            "call-1",
            operation_id="op-complete-call-1",
            operation_request_sha256=_sha("complete-call-1"),
            call_request_sha256=call_request,
            output_envelope_sha256=_sha("ephemeral-output"),
            provider_usage_known=True,
            input_tokens_used=301,
            output_tokens_used=97,
        ) == completed

        execution = store.complete_execution(
            "execution-1",
            operation_id="op-complete-execution-1",
            operation_request_sha256=_sha("complete-execution-1"),
        )
        assert execution.state == "completed"


def test_completion_requires_authoritative_usage_and_token_bounds(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        call_request = _reserve_execution_and_call(store)
        store.start_call(
            "call-1",
            operation_id="op-start-call-1",
            operation_request_sha256=_sha("start-call-1"),
            call_request_sha256=call_request,
        )
        with pytest.raises(PilotStateTransitionError, match="provider-authoritative"):
            store.complete_call(
                "call-1",
                operation_id="op-complete-no-usage",
                operation_request_sha256=_sha("complete-no-usage"),
                call_request_sha256=call_request,
                output_envelope_sha256=_sha("output"),
                provider_usage_known=False,
                input_tokens_used=10,
                output_tokens_used=10,
            )
        with pytest.raises(PilotCapacityError, match="output usage"):
            store.complete_call(
                "call-1",
                operation_id="op-complete-over-budget",
                operation_request_sha256=_sha("complete-over-budget"),
                call_request_sha256=call_request,
                output_envelope_sha256=_sha("output"),
                provider_usage_known=True,
                input_tokens_used=10,
                output_tokens_used=1_025,
            )
        assert store.get_call("call-1").state == "request_started"


def test_mixed_completed_and_prestart_failure_terminalizes_indeterminate(
    tmp_path: Path,
) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        request = _lease(store.protocol, execution="execution-mixed", slots=2)
        store.reserve_execution(
            request,
            logical_arm=_logical_arm(pair_id="pair-mixed"),
            operation_id="op-reserve-execution-mixed",
            operation_request_sha256=_sha("reserve-execution-mixed"),
        )
        store.reserve_call(
            operation_id="op-reserve-mixed-call-0",
            operation_request_sha256=_sha("reserve-mixed-call-0"),
            call_key="mixed-call-0",
            logical_execution_key="execution-mixed",
            call_slot=0,
            call_request_sha256=_sha("mixed-call-request-0"),
            input_tokens_reserved=3_072,
            output_tokens_reserved=1_024,
        )
        authorization = store.start_call(
            "mixed-call-0",
            operation_id="op-start-mixed-call-0",
            operation_request_sha256=_sha("start-mixed-call-0"),
            call_request_sha256=_sha("mixed-call-request-0"),
        )
        assert authorization.may_invoke_sdk
        store.complete_call(
            "mixed-call-0",
            operation_id="op-complete-mixed-call-0",
            operation_request_sha256=_sha("complete-mixed-call-0"),
            call_request_sha256=_sha("mixed-call-request-0"),
            output_envelope_sha256=_sha("mixed-output-0"),
            provider_usage_known=True,
            input_tokens_used=10,
            output_tokens_used=5,
        )
        store.reserve_call(
            operation_id="op-reserve-mixed-call-1",
            operation_request_sha256=_sha("reserve-mixed-call-1"),
            call_key="mixed-call-1",
            logical_execution_key="execution-mixed",
            call_slot=1,
            call_request_sha256=_sha("mixed-call-request-1"),
            input_tokens_reserved=3_072,
            output_tokens_reserved=1_024,
        )
        store.fail_call_before_start(
            "mixed-call-1",
            operation_id="op-fail-mixed-call-1",
            operation_request_sha256=_sha("fail-mixed-call-1"),
        )
        assert store.get_execution("execution-mixed").state == "indeterminate"


def test_final_val_execution_cannot_own_scientific_update(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        base = _lease(store.protocol, execution="execution-final")
        request = PilotExecutionLeaseRequestV1(
            **{
                **base.model_dump(mode="python"),
                "operation_kind": "final_val",
                "split": "FINAL_VAL",
            }
        )
        store.reserve_execution(
            request,
            logical_arm=_logical_arm(
                pair_id="pair-final",
                split="FINAL_VAL",
                operation_kind="final_val",
            ),
            operation_id="op-reserve-execution-final",
            operation_request_sha256=_sha("reserve-execution-final"),
        )
        store.reserve_call(
            operation_id="op-reserve-final-call",
            operation_request_sha256=_sha("reserve-final-call"),
            call_key="final-call",
            logical_execution_key="execution-final",
            call_slot=0,
            call_request_sha256=_sha("final-call-request"),
            input_tokens_reserved=3_072,
            output_tokens_reserved=1_024,
        )
        store.start_call(
            "final-call",
            operation_id="op-start-final-call",
            operation_request_sha256=_sha("start-final-call"),
            call_request_sha256=_sha("final-call-request"),
        )
        store.complete_call(
            "final-call",
            operation_id="op-complete-final-call",
            operation_request_sha256=_sha("complete-final-call"),
            call_request_sha256=_sha("final-call-request"),
            output_envelope_sha256=_sha("final-output"),
            provider_usage_known=True,
            input_tokens_used=10,
            output_tokens_used=5,
        )
        store.complete_execution(
            "execution-final",
            operation_id="op-complete-execution-final",
            operation_request_sha256=_sha("complete-execution-final"),
        )
        with pytest.raises(PilotStoreIntegrityError, match="TRAIN_UPDATE"):
            store.append_scientific_commit(
                operation_id="scientific-final-forbidden",
                owner_logical_execution_key="execution-final",
                request_sha256=_sha("scientific-final-forbidden"),
                before_state_sha256=store.protocol.genesis_state_sha256,
                after_state_sha256=_sha("forbidden-state"),
            )


def test_reopen_consumes_started_arm_as_permanent_indeterminate(tmp_path: Path) -> None:
    state_dir = tmp_path / "pilot-state"
    store = _open(tmp_path)
    _record_preflight(store)
    call_request = _reserve_execution_and_call(store)
    store.start_call(
        "call-1",
        operation_id="op-start-call-1",
        operation_request_sha256=_sha("start-call-1"),
        call_request_sha256=call_request,
    )
    store.close()

    with SingleWriterPilotStore.open(
        state_dir, protocol=_protocol(), hmac_key=KEY
    ) as reopened:
        assert reopened.recovered_indeterminate_count == 1
        assert reopened.get_call("call-1").state == "indeterminate"
        assert reopened.get_call("call-1").conservative_charged_tokens == 4_096
        assert reopened.get_execution("execution-1").state == "indeterminate"
        with pytest.raises(PilotIdempotenceConflict, match="permanently consumed"):
            reopened.reserve_execution(
                _lease(
                    reopened.protocol,
                    execution="execution-after-reopen",
                ),
                logical_arm=_logical_arm(),
                operation_id="op-reserve-after-reopen",
                operation_request_sha256=_sha("reserve-after-reopen"),
            )


def test_scientific_commits_are_chained_hmaced_and_idempotent(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        _complete_owner_execution(
            store,
            execution="execution-owner-1",
            call_key="call-owner-1",
            pair_id="pair-owner-1",
            request="owner-request-1",
        )
        first = store.append_scientific_commit(
            operation_id="scientific-1",
            owner_logical_execution_key="execution-owner-1",
            request_sha256=_sha("scientific-request-1"),
            before_state_sha256=store.protocol.genesis_state_sha256,
            after_state_sha256=_sha("state-1"),
        )
        assert first.previous_commit_sha256 == ZERO_SHA256
        assert store.append_scientific_commit(
            operation_id="scientific-1",
            owner_logical_execution_key="execution-owner-1",
            request_sha256=_sha("scientific-request-1"),
            before_state_sha256=store.protocol.genesis_state_sha256,
            after_state_sha256=_sha("state-1"),
        ) == first
        _complete_owner_execution(
            store,
            execution="execution-owner-2",
            call_key="call-owner-2",
            pair_id="pair-owner-2",
            request="owner-request-2",
        )
        second = store.append_scientific_commit(
            operation_id="scientific-2",
            owner_logical_execution_key="execution-owner-2",
            request_sha256=_sha("scientific-request-2"),
            before_state_sha256=_sha("state-1"),
            after_state_sha256=_sha("state-2"),
        )
        assert second.previous_commit_sha256 == first.commit_sha256
        assert store.commit_head_sha256 == second.commit_sha256
        _complete_owner_execution(
            store,
            execution="execution-owner-3",
            call_key="call-owner-3",
            pair_id="pair-owner-3",
            request="owner-request-3",
        )
        with pytest.raises(PilotStoreIntegrityError, match="does not continue"):
            store.append_scientific_commit(
                operation_id="scientific-gap",
                owner_logical_execution_key="execution-owner-3",
                request_sha256=_sha("scientific-gap"),
                before_state_sha256=_sha("wrong-state"),
                after_state_sha256=_sha("state-3"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._connection.execute(  # noqa: SLF001 - physical trigger audit
                "UPDATE scientific_commit SET after_state_sha256=? WHERE commit_ordinal=1",
                (_sha("tampered"),),
            )


def test_reopen_rejects_commit_tamper_even_if_sqlite_is_well_formed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _record_preflight(store)
    _complete_owner_execution(
        store,
        execution="execution-owner-1",
        call_key="call-owner-1",
        pair_id="pair-owner-1",
        request="owner-request-1",
    )
    store.append_scientific_commit(
        operation_id="scientific-1",
        owner_logical_execution_key="execution-owner-1",
        request_sha256=_sha("scientific-request-1"),
        before_state_sha256=store.protocol.genesis_state_sha256,
        after_state_sha256=_sha("state-1"),
    )
    database = store.database_path
    store.close()

    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TRIGGER scientific_commit_no_update")
        connection.execute(
            "UPDATE scientific_commit SET commit_hmac_sha256=? WHERE commit_ordinal=1",
            (_sha("forged-hmac"),),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(PilotStoreIntegrityError):
        SingleWriterPilotStore.open(
            tmp_path / "pilot-state", protocol=_protocol(), hmac_key=KEY
        )


def test_terminal_seal_requires_quiescence_and_freezes_all_writers(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        _reserve_execution_and_call(store)
        empty_head_payload = PilotArchivePayloadV1(
            archive_id="archive-1",
            protocol_sha256=store.protocol.digest,
            terminal_generation=0,
            terminal_state_sha256=store.protocol.genesis_state_sha256,
            commit_chain_head_sha256=ZERO_SHA256,
            budget_ledger_root_sha256=store.budget_ledger_root_sha256,
            operation_ledger_root_sha256=store.operation_ledger_root_sha256,
            pair_manifest_sha256=store.protocol.pair_manifest_sha256,
            disposition_counts=(("reserved", 1),),
        )
        with pytest.raises(PilotStateTransitionError, match="nonterminal"):
            store.seal_terminal_archive(
                empty_head_payload,
                operation_id="op-seal-too-early",
                operation_request_sha256=_sha("seal-too-early"),
            )
        store.fail_call_before_start(
            "call-1",
            operation_id="op-fail-call-1",
            operation_request_sha256=_sha("fail-call-1"),
        )
        empty_head_payload = PilotArchivePayloadV1(
            archive_id="archive-1",
            protocol_sha256=store.protocol.digest,
            terminal_generation=0,
            terminal_state_sha256=store.protocol.genesis_state_sha256,
            commit_chain_head_sha256=ZERO_SHA256,
            budget_ledger_root_sha256=store.budget_ledger_root_sha256,
            operation_ledger_root_sha256=store.operation_ledger_root_sha256,
            pair_manifest_sha256=store.protocol.pair_manifest_sha256,
            disposition_counts=(("failed_before_start", 1),),
        )
        forged_budget_payload = empty_head_payload.model_copy(
            update={"budget_ledger_root_sha256": _sha("forged-budget-root")}
        )
        with pytest.raises(PilotStoreIntegrityError, match="budget root"):
            store.seal_terminal_archive(
                forged_budget_payload,
                operation_id="op-seal-forged-budget",
                operation_request_sha256=_sha("seal-forged-budget"),
            )
        epoch = store.seal_terminal_archive(
            empty_head_payload,
            operation_id="op-seal",
            operation_request_sha256=_sha("seal"),
        )
        assert epoch.payload.archive_id == "archive-1"
        assert store.protocol_status == "sealed"
        assert store.seal_terminal_archive(
            empty_head_payload,
            operation_id="op-seal",
            operation_request_sha256=_sha("seal"),
        ) == epoch
        with pytest.raises(PilotProtocolSealedError):
            store.append_scientific_commit(
                operation_id="scientific-after-seal",
                owner_logical_execution_key="execution-1",
                request_sha256=_sha("after-seal"),
                before_state_sha256=store.protocol.genesis_state_sha256,
                after_state_sha256=_sha("state-1"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._connection.execute(  # noqa: SLF001 - physical trigger audit
                "DELETE FROM archive_epoch WHERE archive_id='archive-1'"
            )

    with _open(tmp_path) as reopened:
        assert reopened.protocol_status == "sealed"


def test_protocol_and_schema_mismatch_fail_closed_on_reopen(tmp_path: Path) -> None:
    store = _open(tmp_path)
    store.close()

    other = _protocol(protocol_id="pilot-protocol-2")
    with pytest.raises(PilotStoreIntegrityError, match="another protocol"):
        _open(tmp_path, protocol=other)

    database = tmp_path / "pilot-state" / "pilot.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE injected_schema(value TEXT)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(PilotStoreIntegrityError, match="schema digest"):
        _open(tmp_path)


def test_database_contains_commitments_not_raw_model_content(tmp_path: Path) -> None:
    with _open(tmp_path) as store:
        _record_preflight(store)
        call_request = _reserve_execution_and_call(store)
        store.start_call(
            "call-1",
            operation_id="op-start-call-1",
            operation_request_sha256=_sha("start-call-1"),
            call_request_sha256=call_request,
        )
        store.complete_call(
            "call-1",
            operation_id="op-complete-call-1",
            operation_request_sha256=_sha("complete-call-1"),
            call_request_sha256=call_request,
            output_envelope_sha256=_sha("secret ephemeral model text"),
            provider_usage_known=True,
            input_tokens_used=12,
            output_tokens_used=3,
        )
        values = [
            str(value)
            for table in (
                "protocol",
                "capacity_preflight",
                "operation_receipt",
                "execution_lease",
                "call_receipt",
            )
            for row in store._connection.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608, SLF001
            for value in row
            if value is not None
        ]
        assert "secret ephemeral model text" not in "\n".join(values)


def test_component_bundle_is_default_off_and_rejects_private_carriers(
    tmp_path: Path,
) -> None:
    phase_bytes, factor_bytes = _component_envelopes(tmp_path, label="safe")
    assert _protocol().component_bundle_required is False
    with _open(tmp_path) as store:
        with pytest.raises(PilotStateTransitionError, match="does not authorize"):
            store.record_genesis_component_bundle(
                operation_id="component-genesis",
                request_sha256=_sha("component-genesis"),
                phase_registry_envelope_bytes=phase_bytes,
                factor_bank_envelope_bytes=factor_bytes,
            )

    private_phase = json.loads(phase_bytes)
    private_phase["state"]["private_prompt"] = "hidden"
    private_phase_bytes = (
        json.dumps(
            private_phase,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    with pytest.raises(ValueError, match="forbidden|raw/private"):
        component_bundle_state_sha256(
            phase_registry_envelope_bytes=private_phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )


def test_component_bundle_genesis_atomic_commit_and_exact_recovery(
    tmp_path: Path,
) -> None:
    phase_bytes, factor_bytes = _component_envelopes(tmp_path, label="primary")
    next_phase_bytes, next_factor_bytes = _advance_phase_component(
        tmp_path, label="primary"
    )
    genesis_sha = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    protocol = _protocol(
        component_bundle_required=True,
        genesis_state_sha256=genesis_sha,
    )
    state_dir = tmp_path / "pilot-state"
    with _open(tmp_path, protocol=protocol) as store:
        with pytest.raises(PilotStateTransitionError, match="genesis"):
            store.latest_component_bundle()
        with pytest.raises(PilotStateTransitionError, match="explicit genesis"):
            _record_preflight(store)
        genesis = store.record_genesis_component_bundle(
            operation_id="component-genesis",
            request_sha256=_sha("component-genesis"),
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )
        assert genesis.metadata.generation == 0
        assert genesis.metadata.bundle_sha256 == genesis_sha
        assert store.record_genesis_component_bundle(
            operation_id="component-genesis",
            request_sha256=_sha("component-genesis"),
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        ) == genesis
        _record_preflight(store)
        _complete_owner_execution(
            store,
            execution="execution-owner-1",
            call_key="call-owner-1",
            pair_id="pair-owner-1",
            request="owner-request-1",
        )
        with pytest.raises(PilotStateTransitionError, match="hash-only"):
            store.append_scientific_commit(
                operation_id="hash-only-forbidden",
                owner_logical_execution_key="execution-owner-1",
                request_sha256=_sha("hash-only-forbidden"),
                before_state_sha256=genesis_sha,
                after_state_sha256=_sha("unbacked-state"),
            )
        commit, generation_one = store.append_component_scientific_commit(
            operation_id="component-scientific-1",
            owner_logical_execution_key="execution-owner-1",
            request_sha256=_sha("component-scientific-1"),
            before_state_sha256=genesis_sha,
            phase_registry_envelope_bytes=next_phase_bytes,
            factor_bank_envelope_bytes=next_factor_bytes,
        )
        assert commit.commit_ordinal == 1
        assert commit.after_state_sha256 == generation_one.metadata.bundle_sha256
        assert generation_one.metadata.previous_bundle_sha256 == genesis_sha
        assert generation_one.metadata.scientific_commit_ordinal == 1
        assert store.latest_component_bundle() == generation_one
        assert store.append_component_scientific_commit(
            operation_id="component-scientific-1",
            owner_logical_execution_key="execution-owner-1",
            request_sha256=_sha("component-scientific-1"),
            before_state_sha256=genesis_sha,
            phase_registry_envelope_bytes=next_phase_bytes,
            factor_bank_envelope_bytes=next_factor_bytes,
        ) == (commit, generation_one)
        assert store._connection.execute(  # noqa: SLF001 - physical join audit
            "SELECT COUNT(*) FROM component_bundle"
        ).fetchone()[0] == 2

    with SingleWriterPilotStore.open(
        state_dir,
        protocol=protocol,
        hmac_key=KEY,
    ) as reopened:
        recovered = reopened.latest_component_bundle()
        assert recovered.metadata.generation == 1
        assert recovered.phase_registry_envelope_bytes == next_phase_bytes
        assert recovered.factor_bank_envelope_bytes == next_factor_bytes
        restored_phase_path = tmp_path / "restored-phase.json"
        restored_factor_path = tmp_path / "restored-factor.json"
        restored_phase_path.write_bytes(recovered.phase_registry_envelope_bytes)
        restored_factor_path.write_bytes(recovered.factor_bank_envelope_bytes)
        restored_registry = PhaseArtifactRegistry.load(
            restored_phase_path,
            registry_key=hashlib.sha256(b"phase-primary").digest(),
            manifest_verifier=lambda _manifest: False,
        )
        restored_bank = FactorBankV2.load(
            restored_factor_path,
            state_key=hashlib.sha256(b"factor-primary").digest(),
        )
        assert restored_registry.to_state().schema_version.startswith(
            "phase-artifact-registry-"
        )
        assert restored_bank.to_state().schema_version.startswith(
            "sft_factor_transition_"
        )


def test_component_bundle_invalid_append_rolls_back_both_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phase_bytes, factor_bytes = _component_envelopes(tmp_path, label="rollback")
    next_phase_bytes, next_factor_bytes = _advance_phase_component(
        tmp_path, label="rollback"
    )
    genesis_sha = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    protocol = _protocol(
        component_bundle_required=True,
        genesis_state_sha256=genesis_sha,
    )
    with _open(tmp_path, protocol=protocol) as store:
        store.record_genesis_component_bundle(
            operation_id="component-genesis",
            request_sha256=_sha("component-genesis"),
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )
        _record_preflight(store)
        _complete_owner_execution(
            store,
            execution="execution-owner-1",
            call_key="call-owner-1",
            pair_id="pair-owner-1",
            request="owner-request-1",
        )
        def fail_component_insert(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected component insert failure")

        monkeypatch.setattr(
            SingleWriterPilotStore,
            "_insert_component_bundle",
            staticmethod(fail_component_insert),
        )
        with pytest.raises(RuntimeError, match="injected component insert failure"):
            store.append_component_scientific_commit(
                operation_id="component-scientific-invalid",
                owner_logical_execution_key="execution-owner-1",
                request_sha256=_sha("component-scientific-invalid"),
                before_state_sha256=genesis_sha,
                phase_registry_envelope_bytes=next_phase_bytes,
                factor_bank_envelope_bytes=next_factor_bytes,
            )
        assert store.commit_head_sha256 == ZERO_SHA256
        assert store.latest_component_bundle().metadata.generation == 0
        assert store._connection.execute(  # noqa: SLF001 - atomicity audit
            "SELECT COUNT(*) FROM scientific_commit"
        ).fetchone()[0] == 0
        assert store._connection.execute(  # noqa: SLF001 - atomicity audit
            "SELECT COUNT(*) FROM operation_receipt "
            "WHERE operation_id='component-scientific-invalid'"
        ).fetchone()[0] == 0


def test_reopen_rejects_component_blob_discontinuity(tmp_path: Path) -> None:
    phase_bytes, factor_bytes = _component_envelopes(tmp_path, label="original")
    alternate_phase, _ = _component_envelopes(tmp_path, label="alternate")
    genesis_sha = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    protocol = _protocol(
        component_bundle_required=True,
        genesis_state_sha256=genesis_sha,
    )
    store = _open(tmp_path, protocol=protocol)
    store.record_genesis_component_bundle(
        operation_id="component-genesis",
        request_sha256=_sha("component-genesis"),
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    database = store.database_path
    store.close()

    connection = sqlite3.connect(database)
    try:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='trigger' AND name='component_bundle_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER component_bundle_no_update")
        connection.execute(
            "UPDATE component_bundle SET phase_registry_envelope=? WHERE generation=0",
            (alternate_phase,),
        )
        connection.execute(trigger_sql)
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(PilotStoreIntegrityError, match="component bundle"):
        SingleWriterPilotStore.open(
            tmp_path / "pilot-state",
            protocol=protocol,
            hmac_key=KEY,
        )


def test_component_genesis_closes_terminal_archive_without_scientific_updates(
    tmp_path: Path,
) -> None:
    phase_bytes, factor_bytes = _component_envelopes(tmp_path, label="terminal")
    genesis_sha = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    protocol = _protocol(
        component_bundle_required=True,
        genesis_state_sha256=genesis_sha,
    )
    with _open(tmp_path, protocol=protocol) as store:
        store.record_genesis_component_bundle(
            operation_id="component-genesis",
            request_sha256=_sha("component-genesis"),
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )
        _record_preflight(store)
        payload = PilotArchivePayloadV1(
            archive_id="component-archive",
            protocol_sha256=protocol.digest,
            terminal_generation=0,
            terminal_state_sha256=genesis_sha,
            commit_chain_head_sha256=ZERO_SHA256,
            budget_ledger_root_sha256=store.budget_ledger_root_sha256,
            operation_ledger_root_sha256=store.operation_ledger_root_sha256,
            pair_manifest_sha256=protocol.pair_manifest_sha256,
            disposition_counts=(),
        )
        store.seal_terminal_archive(
            payload,
            operation_id="component-seal",
            operation_request_sha256=_sha("component-seal"),
        )
        assert store.protocol_status == "sealed"
        assert store.latest_component_bundle().metadata.bundle_sha256 == genesis_sha
    with _open(tmp_path, protocol=protocol) as reopened:
        assert reopened.protocol_status == "sealed"
        assert reopened.latest_component_bundle().metadata.bundle_sha256 == genesis_sha
