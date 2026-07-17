from __future__ import annotations

import hashlib

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace, FactorBank
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    SourceManifest,
)
from exp_graph.mas.phase_factor_binding import (
    bind_registered_phase_materialization,
)
from exp_graph.mas.phase_program import PhaseProgram, PhaseProgramLimits


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _namespace() -> ExecutionNamespace:
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
        runtime_version="shadow-runtime-v2",
        binder_version=PHASE_FACTOR_BINDER_VERSION,
        compiler_version="1",
    )


def _program(instruction: str) -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": [
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": instruction,
                }
            ],
        }
    )


def _setup():
    manifest = SourceManifest(
        manifest_sha256=_h("train-manifest"),
        split="TRAIN_UPDATE",
        source_catalog_sha256=_h("catalog"),
        policy_sha256=_h("policy"),
        producer_version="test-host-v1",
    )
    registry = PhaseArtifactRegistry(
        registry_key=b"binding-registry-key" * 2,
        manifests=(manifest,),
        manifest_verifier=lambda candidate: candidate == manifest,
        branch_receipt_verifier=lambda _receipt: True,
    )
    namespace = _namespace()
    profile = registry.register_runtime_profile(
        namespace=namespace,
        limits=PhaseProgramLimits(),
    )
    ingress = registry.issue_ingress(manifest.manifest_sha256)
    return registry, namespace, profile, ingress


def _mutate(registry, profile, ingress, source_artifact, target: str, ordinal: int):
    source_factor = registry.extract_factor(
        source_artifact,
        locator="/phases/0/instruction",
    )
    branch_receipt = registry.register_branch_receipt(
        branch="mutate",
        source_artifact=source_artifact,
        locator="/phases/0/instruction",
        mutation_parent_factor=source_factor.factor,
        additional_input_root_commitments=(_h(f"input-root:{ordinal}"),),
        producer_epoch="branch-host:binding-v1",
        attestation_sha256=_h(f"branch-attestation:{ordinal}"),
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    generated = registry.register_generated_value(
        target,
        operation_seal=seal,
        ingress=ingress,
    )
    proof = registry.materialize(
        operation_seal=seal,
        target_factor=generated.factor,
    )
    assert isinstance(proof, PhaseBindingProofHandle)
    return source_factor, generated, proof


def _add_pair(bank: FactorBank, pair) -> None:
    for factor in (
        pair.background_factor,
        pair.source_factor,
        pair.target_factor,
    ):
        if factor.revision_id not in bank.factors:
            bank.add_factor(factor)
    for composition in (pair.source_composition, pair.target_composition):
        if composition.composition_id not in bank.compositions:
            bank.add_composition(composition)


def test_registry_proof_maps_to_one_runnable_direct_transition() -> None:
    registry, _namespace_value, profile, ingress = _setup()
    source_artifact = registry.ingest_program(
        _program("collect"),
        runtime_profile=profile,
        ingress=ingress,
    )
    _source, _target, proof = _mutate(
        registry, profile, ingress, source_artifact, "collect-and-dedupe", 1
    )
    pair = bind_registered_phase_materialization(registry, proof)

    assert pair.source_factor.origin_branch == "migration"
    assert pair.target_factor.origin_branch == "migration"
    assert pair.source_factor.parent_revision_id is None
    assert pair.target_factor.parent_revision_id is None
    assert pair.origin_branch == "mutate"
    assert (
        pair.source_composition.binding_map["fixed_background"]
        == pair.target_composition.binding_map["fixed_background"]
    )
    assert pair.source_composition.artifact_sha256 != (
        pair.target_composition.artifact_sha256
    )

    bank = FactorBank(binding_verifier=registry.factor_bank_binding_verifier)
    _add_pair(bank, pair)
    transition = bank.register_transition(
        source_composition_id=pair.source_composition.composition_id,
        target_composition_id=pair.target_composition.composition_id,
        slot_id=pair.changed_slot_id,
        binding_proof_id=pair.proof.handle_id,
        binding_proof_sha256=pair.proof.proof_sha256,
        masked_background_sha256=pair.masked_background_sha256,
        origin_branch=pair.origin_branch,
    )

    assert transition.from_revision_id == pair.source_factor.revision_id
    assert transition.to_revision_id == pair.target_factor.revision_id
    assert transition.origin_branch == "mutate"
    reloaded = FactorBank(
        state=bank.to_state(),
        binding_verifier=registry.factor_bank_binding_verifier,
    )
    assert reloaded.scientific_state_sha256 == bank.scientific_state_sha256


def test_adapter_and_scientific_bank_contain_no_raw_program_or_scalar() -> None:
    registry, _namespace_value, profile, ingress = _setup()
    source_artifact = registry.ingest_program(
        _program("collect"), runtime_profile=profile, ingress=ingress
    )
    _source, _target, proof = _mutate(
        registry, profile, ingress, source_artifact, "collect-and-dedupe", 1
    )
    pair = bind_registered_phase_materialization(registry, proof)
    bank = FactorBank(binding_verifier=registry.factor_bank_binding_verifier)
    _add_pair(bank, pair)

    serialized = str(
        {
            "pair": pair.model_dump(mode="json"),
            "bank": bank.to_state().model_dump(mode="json"),
        }
    )
    assert "collect" not in serialized
    assert "dedupe" not in serialized
    assert "TRAIN_UPDATE" not in serialized


def test_a_to_b_to_c_uses_the_same_b_factor_content() -> None:
    registry, _namespace_value, profile, ingress = _setup()
    artifact_a = registry.ingest_program(
        _program("A"), runtime_profile=profile, ingress=ingress
    )
    _a, b, proof_ab = _mutate(registry, profile, ingress, artifact_a, "B", 1)
    pair_ab = bind_registered_phase_materialization(registry, proof_ab)
    artifact_b = registry.resolve_proof(proof_ab).target_artifact
    b_again, _c, proof_bc = _mutate(
        registry, profile, ingress, artifact_b, "C", 2
    )
    pair_bc = bind_registered_phase_materialization(registry, proof_bc)

    assert b.factor == b_again.factor
    assert pair_ab.target_factor == pair_bc.source_factor
    assert pair_ab.target_factor.revision_id == b.factor.handle_id


def test_binding_verifier_rejects_wrong_branch_or_background() -> None:
    registry, _namespace_value, profile, ingress = _setup()
    artifact = registry.ingest_program(
        _program("A"), runtime_profile=profile, ingress=ingress
    )
    _a, _b, proof = _mutate(registry, profile, ingress, artifact, "B", 1)
    pair = bind_registered_phase_materialization(registry, proof)
    bank = FactorBank(binding_verifier=registry.factor_bank_binding_verifier)
    _add_pair(bank, pair)

    with pytest.raises(ValueError, match="rejected"):
        bank.register_transition(
            source_composition_id=pair.source_composition.composition_id,
            target_composition_id=pair.target_composition.composition_id,
            slot_id=pair.changed_slot_id,
            binding_proof_id=pair.proof.handle_id,
            binding_proof_sha256=pair.proof.proof_sha256,
            masked_background_sha256=pair.masked_background_sha256,
            origin_branch="fresh",
        )
    with pytest.raises(ValueError, match="rejected"):
        bank.register_transition(
            source_composition_id=pair.source_composition.composition_id,
            target_composition_id=pair.target_composition.composition_id,
            slot_id=pair.changed_slot_id,
            binding_proof_id=pair.proof.handle_id,
            binding_proof_sha256=pair.proof.proof_sha256,
            masked_background_sha256=_h("wrong-background"),
            origin_branch=pair.origin_branch,
        )


def test_shape_valid_caller_proof_is_not_registry_authority() -> None:
    registry, _namespace_value, profile, ingress = _setup()
    artifact = registry.ingest_program(
        _program("A"), runtime_profile=profile, ingress=ingress
    )
    _a, _b, proof = _mutate(registry, profile, ingress, artifact, "B", 1)
    forged = proof.model_copy(update={"record_mac": "0" * 64})

    with pytest.raises(ValueError, match="not registered"):
        bind_registered_phase_materialization(registry, forged)
