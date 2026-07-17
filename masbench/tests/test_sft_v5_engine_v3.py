"""Stage 3 closure tests: the exact engine accepts full-factor-v3 edges only
under a v3 protocol, replays the complete canonical bundle, and stays
image-loaded-only.

The store/journal machinery is shared with the leaf-v2 boundary tests — the
same verifier-only entry serves both binders, so the v2 suite continues to
pin the v2 behaviour while this file pins the v3 closure.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.factor_bank_v2 import FactorBankV2
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    SourceManifest,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    RegisteredPhaseFactorEdgeV3,
    make_phase_v3_binding_verifier,
    register_phase_materialization_v3,
)
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgramLimits,
)
from masbench.engine import (
    ExactRegisteredPhaseExecution,
    register_exact_phase_execution_result,
)
from masbench.sft_pilot.execution_attestation import PilotExecutionAttestor
from masbench.sft_pilot.schema import (
    AuthorizedPhaseBudgetV1,
    PilotCapacityPolicyV1,
    PilotCapacityPreflightV1,
    PilotProtocolV1,
    PilotSourceManifestV1,
)
from masbench.sft_pilot.store import SingleWriterPilotStore

import test_sft_execution_attestation as base


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _v3_namespace() -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_count",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=4,
        array_size_bucket="small",
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="exact-phase-runner-v1",
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
    )


def _v3_protocol() -> PilotProtocolV1:
    arms = base._arms()
    return PilotProtocolV1(
        protocol_id="execution-boundary-full-v3",
        method_arm="sft_unified",
        namespace=_v3_namespace(),
        source_manifest=PilotSourceManifestV1(
            split="TRAIN_UPDATE",
            source_catalog_sha256=_sha("source-catalog"),
            source_policy_sha256=_sha("source-policy"),
        ),
        source_authority_sha256=_sha("source-authority"),
        dataset_split_policy_sha256=_sha("split-policy"),
        candidate_pool_manifest_sha256=_sha("candidate-pool"),
        runner_config_sha256=_sha("runner-config"),
        model_config_sha256=_sha("model-config"),
        pair_manifest_sha256=base.canonical_sha256(arms),
        genesis_state_sha256=_sha("genesis"),
        authorized_logical_arms=arms,
        phase_budgets=tuple(
            AuthorizedPhaseBudgetV1(
                phase=phase,
                method_arm="sft_unified",
                executions=4,
                call_slots=4,
                input_tokens=4_000,
                output_tokens=800,
            )
            for phase in ("TRAIN_UPDATE", "PROBE", "FINAL_VAL")
        ),
        capacity_policy=PilotCapacityPolicyV1(
            max_scientific_commits=8,
            max_execution_leases=8,
            max_call_receipts=8,
            max_call_slots_per_execution=1,
            max_input_tokens_per_call=1_000,
            max_output_tokens_per_call=200,
            max_active_db_bytes=16 * 1024 * 1024,
            max_archive_bytes=64 * 1024,
            max_total_stored_scalar_bytes=4 * 1024 * 1024,
        ),
    )


def _v3_registry_edge(
    protocol: PilotProtocolV1,
    *,
    locator: str = "/phases/0/hub",
    generated_value: Any = 1,
) -> tuple[PhaseArtifactRegistry, RegisteredPhaseFactorEdgeV3]:
    manifest = SourceManifest(
        manifest_sha256=_sha("phase-source-manifest-v3"),
        split="TRAIN_UPDATE",
        source_catalog_sha256=protocol.source_manifest.source_catalog_sha256,
        policy_sha256=protocol.source_manifest.source_policy_sha256,
        producer_version="exact-phase-host-v3",
    )
    registry = PhaseArtifactRegistry(
        registry_key=base.REGISTRY_KEY,
        manifests=(manifest,),
        manifest_verifier=base._ExactManifestVerifier(manifest),
        branch_receipt_verifier=base._BranchVerifier(),
    )
    profile = registry.register_runtime_profile(
        namespace=protocol.namespace,
        limits=PhaseProgramLimits(),
    )
    ingress = registry.issue_ingress(manifest.manifest_sha256)
    source_artifact = registry.ingest_program(
        base._program(0), runtime_profile=profile, ingress=ingress
    )
    source_factor = registry.extract_factor(source_artifact, locator=locator)
    branch = registry.register_branch_receipt(
        branch="mutate",
        source_artifact=source_artifact,
        locator=locator,
        mutation_parent_factor=source_factor.factor,
        additional_input_root_commitments=(_sha("sanitized-train-input"),),
        producer_epoch="branch-host:execution-boundary",
        attestation_sha256=_sha("branch-attestation"),
    )
    seal = registry.seal_operation(branch_receipt=branch)
    generated = registry.register_generated_value(
        generated_value, operation_seal=seal, ingress=ingress
    )
    proof = registry.materialize(operation_seal=seal, target_factor=generated.factor)
    assert isinstance(proof, PhaseBindingProofHandle)
    bank = FactorBankV2(
        state_key=base.FACTOR_KEY,
        direct_binding_verifier=make_phase_v3_binding_verifier(registry),
    )
    edge = register_phase_materialization_v3(
        registry=registry, bank=bank, proof=proof
    )
    return registry, edge


@pytest.fixture
def v3_boundary(tmp_path: Path):
    protocol = _v3_protocol()
    registry, edge = _v3_registry_edge(protocol)
    store = SingleWriterPilotStore.open(
        tmp_path / "store", protocol=protocol, hmac_key=base.STORE_KEY
    )
    store.record_capacity_preflight(
        PilotCapacityPreflightV1(
            planned_scientific_commits=4,
            planned_execution_leases=4,
            planned_call_receipts=4,
            planned_max_calls_per_execution=1,
            planned_max_active_db_bytes=8 * 1024 * 1024,
            planned_archive_bytes=32 * 1024,
            planned_total_stored_scalar_bytes=2 * 1024 * 1024,
            planned_max_input_tokens_per_call=1_000,
            planned_max_output_tokens_per_call=200,
            quarantined_carriers_reserved=1,
            indeterminate_call_reserve=1,
        ),
        operation_id="capacity-preflight",
        request_sha256=_sha("capacity-preflight"),
    )
    arm = next(
        item
        for item in protocol.authorized_logical_arms
        if item.split == "TRAIN_UPDATE" and item.pair_arm == "source"
    )
    execution_key, call_keys = base._completed_store_execution(
        store, arm=arm, tag="train-v3"
    )
    snapshot = base._verified_pair_snapshot(
        tmp_path,
        protocol=protocol,
        registry=registry,
        edge=edge,
        pair_arm=arm,
        tag="train-v3",
    )
    yield protocol, registry, edge, store, arm, execution_key, call_keys, snapshot
    store.close()


def _register(
    v3_boundary,
    *,
    edge_override: Any = None,
    protocol_override: Any = None,
) -> ExactRegisteredPhaseExecution:
    protocol, registry, edge, store, arm, execution_key, call_keys, snapshot = (
        v3_boundary
    )
    return register_exact_phase_execution_result(
        protocol=protocol if protocol_override is None else protocol_override,
        logical_arm=arm,
        registry=registry,
        registered_edge=edge if edge_override is None else edge_override,
        store=store,
        logical_execution_key=execution_key,
        call_keys=call_keys,
        journal_snapshot=snapshot,
        engine_key=base.ENGINE_KEY,
    )


def test_v3_exact_execution_mints_capability_with_changed_factor_only(
    v3_boundary,
) -> None:
    protocol, registry, edge, *_rest = v3_boundary
    capability = _register(v3_boundary)
    attestor = PilotExecutionAttestor(protocol, engine_key=base.ENGINE_KEY)
    attestation = attestor.issue(capability)
    assert attestation.split == "TRAIN_UPDATE"
    assert attestation.pair_arm == "source"
    # Activation credit names exactly the changed source-side factor; the
    # unchanged background factors are never activated by a probe arm.
    assert attestation.activated_factor_revision_ids == (
        edge.transition.from_revision_id,
    )
    assert set(attestation.retrieved_factor_revision_ids) == {
        edge.transition.from_revision_id,
        edge.transition.to_revision_id,
    }
    assert (
        attestation.selected_artifact_sha256
        == attestation.loaded_artifact_sha256
        == edge.source_composition.artifact_sha256
    )
    assert attestation.composition_id == edge.source_composition.composition_id
    assert attestor.verify(attestation)


def test_v3_protocol_rejects_v2_edge_and_vice_versa(v3_boundary) -> None:
    v2_protocol = base._protocol()
    _v2_registry, v2_edge = base._registry_edge(v2_protocol)
    with pytest.raises(ValueError):
        _register(v3_boundary, edge_override=v2_edge)

    protocol, registry, edge, store, arm, execution_key, call_keys, snapshot = (
        v3_boundary
    )
    with pytest.raises(ValueError):
        register_exact_phase_execution_result(
            protocol=v2_protocol,
            logical_arm=arm,
            registry=registry,
            registered_edge=edge,
            store=store,
            logical_execution_key=execution_key,
            call_keys=call_keys,
            journal_snapshot=snapshot,
            engine_key=base.ENGINE_KEY,
        )


def test_v3_unknown_binder_fails_closed(v3_boundary) -> None:
    protocol = v3_boundary[0]
    alien_namespace = protocol.namespace.model_copy(
        update={"binder_version": "paper-binder-v1"}
    )
    alien_protocol = protocol.model_copy(update={"namespace": alien_namespace})
    with pytest.raises(ValueError, match="leaf-v2 or full-factor-v3 binder"):
        _register(v3_boundary, protocol_override=alien_protocol)


def test_v3_background_and_slot_tampers_fail_closed(v3_boundary) -> None:
    edge = v3_boundary[2]

    dropped = edge.model_dump(mode="python")
    dropped["source_scalar_factors"] = dropped["source_scalar_factors"][:-1]
    with pytest.raises(ValueError, match="canonical Phase bundle"):
        _register(
            v3_boundary,
            edge_override=RegisteredPhaseFactorEdgeV3.model_validate(dropped),
        )

    swapped = edge.model_dump(mode="python")
    swapped["source_scalar_factors"], swapped["target_scalar_factors"] = (
        swapped["target_scalar_factors"],
        swapped["source_scalar_factors"],
    )
    with pytest.raises(ValueError, match="canonical Phase bundle"):
        _register(
            v3_boundary,
            edge_override=RegisteredPhaseFactorEdgeV3.model_validate(swapped),
        )

    wrong_slot = edge.model_dump(mode="python")
    wrong_slot["transition"]["slot_id"] = wrong_slot["structural_factor"][
        "revision_id"
    ]
    with pytest.raises(ValueError, match="canonical Phase bundle"):
        _register(
            v3_boundary,
            edge_override=RegisteredPhaseFactorEdgeV3.model_validate(wrong_slot),
        )


def test_v3_step_activation_locus_fails_closed(tmp_path: Path) -> None:
    protocol = _v3_protocol()
    registry, edge = _v3_registry_edge(
        protocol,
        locator="/phases/0/instruction",
        generated_value="collect the evidence twice",
    )
    store = SingleWriterPilotStore.open(
        tmp_path / "store", protocol=protocol, hmac_key=base.STORE_KEY
    )
    try:
        store.record_capacity_preflight(
            PilotCapacityPreflightV1(
                planned_scientific_commits=4,
                planned_execution_leases=4,
                planned_call_receipts=4,
                planned_max_calls_per_execution=1,
                planned_max_active_db_bytes=8 * 1024 * 1024,
                planned_archive_bytes=32 * 1024,
                planned_total_stored_scalar_bytes=2 * 1024 * 1024,
                planned_max_input_tokens_per_call=1_000,
                planned_max_output_tokens_per_call=200,
                quarantined_carriers_reserved=1,
                indeterminate_call_reserve=1,
            ),
            operation_id="capacity-preflight",
            request_sha256=_sha("capacity-preflight"),
        )
        arm = next(
            item
            for item in protocol.authorized_logical_arms
            if item.split == "TRAIN_UPDATE" and item.pair_arm == "source"
        )
        execution_key, call_keys = base._completed_store_execution(
            store, arm=arm, tag="train-v3-step"
        )
        snapshot = base._verified_pair_snapshot(
            tmp_path,
            protocol=protocol,
            registry=registry,
            edge=edge,
            pair_arm=arm,
            tag="train-v3-step",
        )
        with pytest.raises(
            ValueError, match="step/submission activation capability"
        ):
            register_exact_phase_execution_result(
                protocol=protocol,
                logical_arm=arm,
                registry=registry,
                registered_edge=edge,
                store=store,
                logical_execution_key=execution_key,
                call_keys=call_keys,
                journal_snapshot=snapshot,
                engine_key=base.ENGINE_KEY,
            )
    finally:
        store.close()


def test_v3_cross_namespace_proof_fails_closed(v3_boundary) -> None:
    foreign_protocol = _v3_protocol().model_copy(
        update={"namespace": _v3_namespace().model_copy(update={"n_agents": 5})}
    )
    _foreign_registry, foreign_edge = _v3_registry_edge(foreign_protocol)
    with pytest.raises((ValueError, RuntimeError)):
        _register(v3_boundary, edge_override=foreign_edge)


def test_v3_capability_cannot_be_forged(v3_boundary) -> None:
    capability = _register(v3_boundary)
    body, sha = capability._export_for_attestation(
        protocol_sha256=v3_boundary[0].digest,
        engine_key=base.ENGINE_KEY,
    )
    with pytest.raises(ValueError, match="engine-owned"):
        ExactRegisteredPhaseExecution(body, sha, _token=object())
