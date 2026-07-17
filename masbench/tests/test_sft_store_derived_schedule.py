from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from masbench.sft_pilot.manifests import (
    PilotCallScheduleEntryV1,
    PilotExecutionScheduleEntryV1,
    PilotExecutionScheduleV1,
)
from masbench.sft_pilot.components import build_empty_component_envelopes
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
    PilotCapacityError,
    PilotIdempotenceConflict,
    PilotStateTransitionError,
    PilotStoreIntegrityError,
    SingleWriterPilotStore,
    component_bundle_state_sha256,
)


KEY = b"store-derived-schedule-test-key-v1"


def _h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _arm(index: int) -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id=f"pair-{index}",
        pair_arm="control",
        case_commitment_sha256=_h(f"case-{index}"),
        unit_commitment=f"unit-{index}",
        split="TRAIN_UPDATE",
        operation_kind="proposal_generation",
        execution_ordinal=index,
    )


def _call(block: int, slot: int) -> PilotCallScheduleEntryV1:
    return PilotCallScheduleEntryV1(
        call_slot=slot,
        input_tokens_reserved=512 + slot,
        output_tokens_reserved=128 + slot,
        request_envelope_sha256=_h(f"request:{block}:{slot}"),
        request_renderer_sha256=_h("renderer-v1"),
        prompt_template_sha256=_h(f"template:{block}:{slot}"),
        json_mode=(slot % 2 == 0),
        artifact_role="proposal_generation",
    )


def _schedule() -> PilotExecutionScheduleV1:
    return PilotExecutionScheduleV1(
        entries=(
            PilotExecutionScheduleEntryV1(
                logical_arm=_arm(0),
                physical_block_ordinal=0,
                calls=(_call(0, 0), _call(0, 1)),
            ),
            PilotExecutionScheduleEntryV1(
                logical_arm=_arm(1),
                physical_block_ordinal=1,
                calls=(_call(1, 0),),
            ),
        )
    )


def _protocol(schedule: PilotExecutionScheduleV1) -> PilotProtocolV1:
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
        binder_version="binder-v1",
        compiler_version="compiler-v1",
    )
    return PilotProtocolV1(
        protocol_id="scheduled-protocol",
        method_arm="sft_unified",
        namespace=namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_h("cases"),
            source_policy_sha256=_h("source-policy"),
        ),
        source_authority_sha256=_h("source-authority"),
        dataset_split_policy_sha256=_h("split-policy"),
        candidate_pool_manifest_sha256=_h("candidates"),
        runner_config_sha256=_h("runner"),
        model_config_sha256=_h("model"),
        pair_manifest_sha256=_h("pairs"),
        genesis_state_sha256=_h("genesis"),
        execution_schedule_sha256=schedule.digest,
        store_derived_schedule_required=True,
        authorized_logical_arms=tuple(item.logical_arm for item in schedule.entries),
        phase_budgets=(
            AuthorizedPhaseBudgetV1(
                phase="TRAIN_UPDATE",
                method_arm="sft_unified",
                executions=2,
                call_slots=3,
                input_tokens=2_000,
                output_tokens=500,
            ),
            AuthorizedPhaseBudgetV1(
                phase="PROBE",
                method_arm="sft_unified",
                executions=0,
                call_slots=0,
                input_tokens=0,
                output_tokens=0,
            ),
            AuthorizedPhaseBudgetV1(
                phase="FINAL_VAL",
                method_arm="sft_unified",
                executions=0,
                call_slots=0,
                input_tokens=0,
                output_tokens=0,
            ),
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=2,
            max_execution_leases=2,
            max_call_receipts=3,
            max_call_slots_per_execution=2,
            max_input_tokens_per_call=513,
            max_output_tokens_per_call=129,
            max_active_db_bytes=4 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=512 * 1024,
        ),
    )


def _preflight() -> PilotCapacityPreflightV1:
    return PilotCapacityPreflightV1(
        planned_scientific_commits=0,
        planned_execution_leases=2,
        planned_call_receipts=3,
        planned_component_checkpoints=0,
        planned_max_calls_per_execution=2,
        planned_max_active_db_bytes=4 * 1024 * 1024,
        planned_archive_bytes=64 * 1024,
        planned_total_stored_scalar_bytes=512 * 1024,
        planned_max_input_tokens_per_call=513,
        planned_max_output_tokens_per_call=129,
        quarantined_carriers_reserved=0,
        indeterminate_call_reserve=1,
    )


def _request(
    protocol: PilotProtocolV1,
    entry: PilotExecutionScheduleEntryV1,
    *,
    key: str,
    **changes: object,
) -> PilotExecutionLeaseRequestV1:
    values: dict[str, object] = {
        "logical_execution_key": key,
        "operation_kind": entry.logical_arm.operation_kind,
        "request_sha256": entry.execution_request_sha256,
        "namespace_sha256": protocol.namespace.digest,
        "split": entry.logical_arm.split,
        "unit_commitment": entry.logical_arm.unit_commitment,
        "action_id": f"action-{key}",
        "call_slots_reserved": len(entry.calls),
        "input_tokens_reserved": entry.input_tokens_reserved,
        "output_tokens_reserved": entry.output_tokens_reserved,
    }
    values.update(changes)
    return PilotExecutionLeaseRequestV1.model_validate(values)


def _record_preflight(store: SingleWriterPilotStore) -> None:
    store.record_capacity_preflight(
        _preflight(),
        operation_id="preflight",
        request_sha256=_h("preflight"),
    )


def _reserve_call(
    store: SingleWriterPilotStore,
    entry: PilotExecutionScheduleEntryV1,
    slot: int,
    *,
    execution: str,
    call_key: str,
    **changes: object,
):
    call = entry.calls[slot]
    values: dict[str, object] = {
        "operation_id": f"reserve-{call_key}",
        "operation_request_sha256": _h(f"reserve:{call_key}"),
        "call_key": call_key,
        "logical_execution_key": execution,
        "call_slot": slot,
        "call_request_sha256": call.request_envelope_sha256,
        "input_tokens_reserved": call.input_tokens_reserved,
        "output_tokens_reserved": call.output_tokens_reserved,
        "request_renderer_sha256": call.request_renderer_sha256,
        "prompt_template_sha256": call.prompt_template_sha256,
        "json_mode": call.json_mode,
        "artifact_role": call.artifact_role,
    }
    values.update(changes)
    return store.reserve_call(**values)


def _complete_call(store: SingleWriterPilotStore, call_key: str, request: str) -> None:
    authorization = store.start_call(
        call_key,
        operation_id=f"start-{call_key}",
        operation_request_sha256=_h(f"start:{call_key}"),
        call_request_sha256=request,
    )
    assert authorization.may_invoke_sdk
    store.complete_call(
        call_key,
        operation_id=f"complete-{call_key}",
        operation_request_sha256=_h(f"complete:{call_key}"),
        call_request_sha256=request,
        output_envelope_sha256=_h(f"output:{call_key}"),
        provider_usage_known=True,
        input_tokens_used=10,
        output_tokens_used=5,
    )


def test_required_schedule_open_is_exact_authenticated_and_reopen_closed(
    tmp_path: Path,
) -> None:
    schedule = _schedule()
    protocol = _protocol(schedule)
    state = tmp_path / "state"
    with pytest.raises(PilotStoreIntegrityError, match="requires its exact"):
        SingleWriterPilotStore.open(state, protocol=protocol, hmac_key=KEY)

    substitute = schedule.model_copy(
        update={
            "entries": (
                schedule.entries[0].model_copy(
                    update={"physical_block_ordinal": 1}
                ),
                schedule.entries[1].model_copy(
                    update={"physical_block_ordinal": 0}
                ),
            )
        }
    )
    with pytest.raises(PilotStoreIntegrityError, match="does not close"):
        SingleWriterPilotStore.open(
            state,
            protocol=protocol,
            hmac_key=KEY,
            execution_schedule=substitute,
        )

    with SingleWriterPilotStore.open(
        state,
        protocol=protocol,
        hmac_key=KEY,
        execution_schedule=schedule,
    ) as store:
        row = store._connection.execute(  # noqa: SLF001 - physical audit
            "SELECT schedule_sha256, schedule_hmac_sha256 FROM execution_schedule"
        ).fetchone()
        assert tuple(row)[0] == schedule.digest
        assert len(tuple(row)[1]) == 64
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._connection.execute(  # noqa: SLF001 - trigger audit
                "UPDATE execution_schedule SET schedule_sha256=?",
                (_h("tampered"),),
            )

    with SingleWriterPilotStore.open(
        state,
        protocol=protocol,
        hmac_key=KEY,
        execution_schedule=schedule,
    ):
        pass

    changed_schedule = PilotExecutionScheduleV1(
        entries=(
            schedule.entries[0].model_copy(
                update={
                    "calls": (
                        schedule.entries[0].calls[0].model_copy(
                            update={"request_envelope_sha256": _h("changed-request")}
                        ),
                        schedule.entries[0].calls[1],
                    )
                }
            ),
            schedule.entries[1],
        )
    )
    changed_protocol = protocol.model_copy(
        update={"execution_schedule_sha256": changed_schedule.digest}
    )
    with pytest.raises(PilotStoreIntegrityError, match="another protocol"):
        SingleWriterPilotStore.open(
            state,
            protocol=changed_protocol,
            hmac_key=KEY,
            execution_schedule=changed_schedule,
        )

    legacy_protocol = protocol.model_copy(
        update={
            "execution_schedule_sha256": None,
            "store_derived_schedule_required": False,
        }
    )
    with pytest.raises(PilotStoreIntegrityError, match="another protocol"):
        SingleWriterPilotStore.open(
            state,
            protocol=legacy_protocol,
            hmac_key=KEY,
        )


def test_store_derives_execution_call_caps_roles_and_physical_order(
    tmp_path: Path,
) -> None:
    schedule = _schedule()
    protocol = _protocol(schedule)
    with SingleWriterPilotStore.open(
        tmp_path / "state",
        protocol=protocol,
        hmac_key=KEY,
        execution_schedule=schedule,
    ) as store:
        with pytest.raises(PilotCapacityError, match="exact schedule"):
            store.record_capacity_preflight(
                _preflight().model_copy(update={"planned_call_receipts": 2}),
                operation_id="wrong-preflight",
                request_sha256=_h("wrong-preflight"),
            )
        _record_preflight(store)
        first, second = schedule.entries
        with pytest.raises(PilotStateTransitionError, match="physical block order"):
            store.reserve_execution(
                _request(protocol, second, key="execution-2"),
                logical_arm=second.logical_arm,
                operation_id="reserve-execution-2-early",
                operation_request_sha256=_h("reserve-execution-2-early"),
            )
        execution_mismatches = (
            ("request_sha256", _h("wrong-request")),
            ("operation_kind", "control_execution"),
            ("split", "FINAL_VAL"),
            ("unit_commitment", "wrong-unit"),
            ("call_slots_reserved", 1),
            ("input_tokens_reserved", first.input_tokens_reserved + 1),
            ("output_tokens_reserved", first.output_tokens_reserved + 1),
        )
        for field, wrong in execution_mismatches:
            with pytest.raises(
                PilotStoreIntegrityError, match="schedule row|do not close"
            ):
                store.reserve_execution(
                    _request(
                        protocol,
                        first,
                        key=f"wrong-{field}",
                        **{field: wrong},
                    ),
                    logical_arm=first.logical_arm,
                    operation_id=f"reserve-wrong-{field}",
                    operation_request_sha256=_h(f"reserve-wrong-{field}"),
                )
        lease = store.reserve_execution(
            _request(protocol, first, key="execution-1"),
            logical_arm=first.logical_arm,
            operation_id="reserve-execution-1",
            operation_request_sha256=_h("reserve-execution-1"),
        )
        assert lease.request_sha256 == first.execution_request_sha256
        assert lease.physical_block_ordinal == 0

        with pytest.raises(PilotStateTransitionError, match="contiguous"):
            _reserve_call(
                store,
                first,
                1,
                execution="execution-1",
                call_key="call-1-early",
            )
        for field, wrong in (
            ("call_request_sha256", _h("wrong-request")),
            ("input_tokens_reserved", 1),
            ("output_tokens_reserved", 1),
            ("request_renderer_sha256", _h("wrong-renderer")),
            ("prompt_template_sha256", _h("wrong-template")),
            ("json_mode", False),
            ("artifact_role", "target_artifact"),
        ):
            with pytest.raises(PilotStoreIntegrityError, match="schedule slot"):
                _reserve_call(
                    store,
                    first,
                    0,
                    execution="execution-1",
                    call_key=f"bad-{field}",
                    **{field: wrong},
                )

        receipt0 = _reserve_call(
            store, first, 0, execution="execution-1", call_key="call-1-0"
        )
        assert receipt0.scheduled_call_sha256 == first.calls[0].digest
        _complete_call(store, "call-1-0", first.calls[0].request_envelope_sha256)
        _reserve_call(store, first, 1, execution="execution-1", call_key="call-1-1")
        _complete_call(store, "call-1-1", first.calls[1].request_envelope_sha256)
        store.complete_execution(
            "execution-1",
            operation_id="complete-execution-1",
            operation_request_sha256=_h("complete-execution-1"),
        )

        lease2 = store.reserve_execution(
            _request(protocol, second, key="execution-2"),
            logical_arm=second.logical_arm,
            operation_id="reserve-execution-2",
            operation_request_sha256=_h("reserve-execution-2"),
        )
        assert lease2.physical_block_ordinal == 1


def test_started_scheduled_slot_reopens_indeterminate_without_alias(
    tmp_path: Path,
) -> None:
    schedule = _schedule()
    protocol = _protocol(schedule)
    state = tmp_path / "state"
    store = SingleWriterPilotStore.open(
        state,
        protocol=protocol,
        hmac_key=KEY,
        execution_schedule=schedule,
    )
    _record_preflight(store)
    first = schedule.entries[0]
    store.reserve_execution(
        _request(protocol, first, key="execution-1"),
        logical_arm=first.logical_arm,
        operation_id="reserve-execution-1",
        operation_request_sha256=_h("reserve-execution-1"),
    )
    _reserve_call(store, first, 0, execution="execution-1", call_key="call-1")
    authorization = store.start_call(
        "call-1",
        operation_id="start-call-1",
        operation_request_sha256=_h("start-call-1"),
        call_request_sha256=first.calls[0].request_envelope_sha256,
    )
    assert authorization.may_invoke_sdk
    store.close()

    with SingleWriterPilotStore.open(
        state,
        protocol=protocol,
        hmac_key=KEY,
        execution_schedule=schedule,
    ) as reopened:
        assert reopened.recovered_indeterminate_count == 1
        assert reopened.get_call("call-1").state == "indeterminate"
        assert reopened.get_execution("execution-1").state == "indeterminate"
        with pytest.raises(PilotIdempotenceConflict, match="permanently consumed"):
            reopened.reserve_execution(
                _request(protocol, first, key="execution-alias"),
                logical_arm=first.logical_arm,
                operation_id="reserve-execution-alias",
                operation_request_sha256=_h("reserve-execution-alias"),
            )
        second = schedule.entries[1]
        reopened.reserve_execution(
            _request(protocol, second, key="execution-2"),
            logical_arm=second.logical_arm,
            operation_id="reserve-execution-2",
            operation_request_sha256=_h("reserve-execution-2"),
        )
        with pytest.raises(PilotStoreIntegrityError, match="schedule slot"):
            _reserve_call(
                reopened,
                second,
                0,
                execution="execution-2",
                call_key="moved-request",
                call_request_sha256=first.calls[0].request_envelope_sha256,
            )
        persisted = reopened._connection.execute(  # noqa: SLF001 - privacy audit
            "SELECT protocol_json FROM protocol UNION ALL "
            "SELECT schedule_json FROM execution_schedule"
        ).fetchall()
        lowered = " ".join(str(row[0]).casefold() for row in persisted)
        for forbidden in (
            "ground_truth",
            "expected_output",
            "raw_prompt",
            "raw_response",
            "answer_key",
        ):
            assert forbidden not in lowered


def test_schedule_slot_and_semantic_checkpoint_are_conjunctive(
    tmp_path: Path,
) -> None:
    schedule = _schedule()
    component_dir = tmp_path / "components"
    phase_bytes, factor_bytes = build_empty_component_envelopes(
        component_dir,
        phase_registry_key=b"scheduled-phase-registry-key-v1!!",
        factor_bank_key=b"scheduled-factor-bank-key-v1!!!!!",
        manifest_verifier=lambda _manifest: False,
    )
    protocol = _protocol(schedule).model_copy(
        update={
            "component_bundle_required": True,
            "component_checkpoint_saga_required": True,
            "genesis_state_sha256": component_bundle_state_sha256(
                phase_registry_envelope_bytes=phase_bytes,
                factor_bank_envelope_bytes=factor_bytes,
            ),
        }
    )
    with SingleWriterPilotStore.open(
        tmp_path / "state",
        protocol=protocol,
        hmac_key=KEY,
        execution_schedule=schedule,
    ) as store:
        store.record_genesis_component_bundle(
            operation_id="genesis",
            request_sha256=_h("genesis"),
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )
        _record_preflight(store)
        first = schedule.entries[0]
        store.reserve_execution(
            _request(protocol, first, key="execution-1"),
            logical_arm=first.logical_arm,
            operation_id="reserve-execution-1",
            operation_request_sha256=_h("reserve-execution-1"),
        )
        with pytest.raises(PilotStoreIntegrityError, match="schedule slot"):
            _reserve_call(
                store,
                first,
                0,
                execution="execution-1",
                call_key="wrong-request",
                call_request_sha256=_h("wrong-request"),
            )
        with pytest.raises(PilotStateTransitionError, match="open checkpoint"):
            _reserve_call(
                store,
                first,
                0,
                execution="execution-1",
                call_key="exact-without-checkpoint",
                expected_component_recovery_root_sha256=(
                    store.latest_component_recovery_snapshot().recovery_root_sha256
                ),
            )
