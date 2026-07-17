from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.phase_artifact_registry import PHASE_FULL_FACTOR_BINDER_VERSION
from exp_graph.mas.phase_program import PHASE_PROGRAM_COMPILER_VERSION
from masbench.sft_pilot.components import build_empty_component_envelopes
from masbench.sft_pilot.provision import provision_pilot_store
from masbench.sft_pilot.structural_anchor import (
    StructuralAnchorPlanV1,
    build_structural_anchor_v1,
)
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotCapacityPreflightV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
)
from masbench.sft_pilot.store import (
    PilotIdempotenceConflict,
    component_bundle_state_sha256,
)


STORE_KEY = hashlib.sha256(b"provision-store-key").digest()
PHASE_KEY = hashlib.sha256(b"provision-phase-key").digest()
FACTOR_KEY = hashlib.sha256(b"provision-factor-key").digest()
SOURCE_AUTHORITY_KEY = hashlib.sha256(
    b"provision-source-authority-key"
).digest()


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _arm() -> PilotLogicalArmCoordinatesV1:
    return PilotLogicalArmCoordinatesV1(
        pair_id="pair-provision",
        pair_arm="control",
        case_commitment_sha256=_h("case-provision"),
        unit_commitment="unit-provision",
        split="TRAIN_UPDATE",
        operation_kind="proposal_generation",
        execution_ordinal=0,
    )


def _protocol(
    genesis: str,
    *,
    source_authority_sha256: str | None = None,
    checkpoint_saga: bool = False,
) -> PilotProtocolV1:
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
        runtime_version="pilot-runtime-v1",
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )
    return PilotProtocolV1(
        protocol_id="pilot-provision-v1",
        method_arm="sft_unified",
        namespace=namespace,
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_h("catalog"),
            source_policy_sha256=_h("source-policy"),
        ),
        source_authority_sha256=(
            _h("source-authority")
            if source_authority_sha256 is None
            else source_authority_sha256
        ),
        dataset_split_policy_sha256=_h("split-policy"),
        candidate_pool_manifest_sha256=_h("candidates"),
        runner_config_sha256=_h("runner"),
        model_config_sha256=_h("model"),
        pair_manifest_sha256=_h("pairs"),
        genesis_state_sha256=genesis,
        component_bundle_required=True,
        component_checkpoint_saga_required=checkpoint_saga,
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
            max_scientific_commits=2,
            max_execution_leases=2,
            max_call_receipts=2,
            max_call_slots_per_execution=1,
            max_input_tokens_per_call=3_072,
            max_output_tokens_per_call=1_024,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=8 * 1024 * 1024,
        ),
    )


def _preflight() -> PilotCapacityPreflightV1:
    return PilotCapacityPreflightV1(
        planned_scientific_commits=1,
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
    )


def _inputs(tmp_path: Path):
    component_dir = tmp_path / "component-source"
    phase_bytes, factor_bytes = build_empty_component_envelopes(
        component_dir,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
        manifest_verifier=lambda _manifest: False,
    )
    genesis = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    return phase_bytes, factor_bytes, _protocol(genesis)


def test_provision_is_exact_and_idempotent(tmp_path: Path) -> None:
    phase_bytes, factor_bytes, protocol = _inputs(tmp_path)
    state_dir = (tmp_path / "pilot-state").resolve()
    first = provision_pilot_store(
        state_dir,
        protocol=protocol,
        preflight=_preflight(),
        store_hmac_key=STORE_KEY,
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    second = provision_pilot_store(
        state_dir,
        protocol=protocol,
        preflight=_preflight(),
        store_hmac_key=STORE_KEY,
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )

    assert first == second
    assert first.protocol_sha256 == protocol.digest
    assert first.genesis_state_sha256 == protocol.genesis_state_sha256


def test_provision_rejects_changed_preflight_and_relative_path(tmp_path: Path) -> None:
    phase_bytes, factor_bytes, protocol = _inputs(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        provision_pilot_store(
            Path("relative-state"),
            protocol=protocol,
            preflight=_preflight(),
            store_hmac_key=STORE_KEY,
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )

    state_dir = (tmp_path / "pilot-state").resolve()
    provision_pilot_store(
        state_dir,
        protocol=protocol,
        preflight=_preflight(),
        store_hmac_key=STORE_KEY,
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )
    changed = _preflight().model_copy(
        update={"planned_archive_bytes": 32 * 1024 - 1}
    )
    with pytest.raises(PilotIdempotenceConflict):
        provision_pilot_store(
            state_dir,
            protocol=protocol,
            preflight=changed,
            store_hmac_key=STORE_KEY,
            phase_registry_envelope_bytes=phase_bytes,
            factor_bank_envelope_bytes=factor_bytes,
        )


def test_provision_rejects_component_bytes_outside_protocol(tmp_path: Path) -> None:
    phase_bytes, factor_bytes, protocol = _inputs(tmp_path)
    with pytest.raises(ValueError, match="envelope|frozen protocol genesis"):
        provision_pilot_store(
            (tmp_path / "pilot-state").resolve(),
            protocol=protocol,
            preflight=_preflight(),
            store_hmac_key=STORE_KEY,
            phase_registry_envelope_bytes=phase_bytes + b"x",
            factor_bank_envelope_bytes=factor_bytes,
        )


def test_checkpoint_saga_requires_exact_nonempty_structural_anchor(
    tmp_path: Path,
) -> None:
    plan = StructuralAnchorPlanV1(
        namespace=_protocol(_h("placeholder")).namespace,
        source_catalog_sha256=_h("catalog"),
        source_policy_sha256=_h("source-policy"),
    )
    anchor = build_structural_anchor_v1(
        (tmp_path / "anchor").resolve(),
        plan=plan,
        source_authority_key=SOURCE_AUTHORITY_KEY,
        phase_registry_key=PHASE_KEY,
        factor_bank_key=FACTOR_KEY,
    )
    genesis = component_bundle_state_sha256(
        phase_registry_envelope_bytes=anchor.phase_registry_envelope_bytes,
        factor_bank_envelope_bytes=anchor.factor_bank_envelope_bytes,
    )
    protocol = _protocol(
        genesis,
        source_authority_sha256=anchor.bundle.source_authority_sha256,
        checkpoint_saga=True,
    )
    state_dir = (tmp_path / "pilot-state-anchor").resolve()
    with pytest.raises(ValueError, match="non-empty structural anchor"):
        provision_pilot_store(
            state_dir,
            protocol=protocol,
            preflight=_preflight(),
            store_hmac_key=STORE_KEY,
            phase_registry_envelope_bytes=anchor.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=anchor.factor_bank_envelope_bytes,
        )

    receipt = provision_pilot_store(
        state_dir,
        protocol=protocol,
        preflight=_preflight(),
        store_hmac_key=STORE_KEY,
        phase_registry_envelope_bytes=anchor.phase_registry_envelope_bytes,
        factor_bank_envelope_bytes=anchor.factor_bank_envelope_bytes,
        structural_anchor=anchor.bundle,
        structural_anchor_plan=plan,
    )
    assert receipt.structural_anchor_root_sha256 == (
        anchor.bundle.anchor_root_sha256
    )

    non_saga = _protocol(
        genesis,
        source_authority_sha256=anchor.bundle.source_authority_sha256,
    )
    with pytest.raises(ValueError, match="only by a checkpoint-saga protocol"):
        provision_pilot_store(
            (tmp_path / "pilot-state-non-saga").resolve(),
            protocol=non_saga,
            preflight=_preflight(),
            store_hmac_key=STORE_KEY,
            phase_registry_envelope_bytes=anchor.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=anchor.factor_bank_envelope_bytes,
            structural_anchor=anchor.bundle,
            structural_anchor_plan=plan,
        )
