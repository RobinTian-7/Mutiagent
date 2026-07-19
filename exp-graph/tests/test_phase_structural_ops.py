from __future__ import annotations

import hashlib

import pytest

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.factor_bank_v2 import FactorBankV2
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    SourceManifest,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    PHASE_FULL_FACTOR_SKELETON_SLOT_ID,
    make_phase_v3_binding_verifier,
)
from exp_graph.mas.phase_program import PhaseProgram, PhaseProgramLimits
from exp_graph.mas.phase_structural_ops import (
    PHASE_WHOLE_OPERATION_VERIFIER_EPOCH,
    StructuralNoOpError,
    apply_structural_operation,
    make_phase_whole_operation_verifier,
    parse_structural_operation,
    prove_structural_operation,
    register_phase_whole_materialization_v1,
    verify_structural_operation_proof,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _program(*, phases=None) -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": phases
            or [
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": "gather",
                },
                {
                    "kind": "broadcast",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": "broadcast",
                },
            ],
        }
    )


_PAIRWISE = {
    "kind": "pairwise_exchange",
    "pattern": "rotating",
    "max_rounds": 2,
    "stop_when": "fixed_rounds",
}


class Fixture:
    def __init__(self) -> None:
        self.manifest = SourceManifest(
            manifest_sha256=_h("structural-ops-manifest"),
            split="TRAIN_UPDATE",
            source_catalog_sha256=_h("structural-ops-catalog"),
            policy_sha256=_h("structural-ops-policy"),
            producer_version="structural-ops-test-host",
        )
        self.registry = PhaseArtifactRegistry(
            registry_key=b"structural-ops-registry-key-x" * 2,
            manifests=(self.manifest,),
            manifest_verifier=lambda candidate: candidate == self.manifest,
            branch_receipt_verifier=lambda _body: True,
        )
        self.namespace = ExecutionNamespace(
            task_family="synthetic_full_phase",
            objective="balanced",
            information_goal="sink",
            planner_mode="program_generate",
            payload_format="phase_program_skill_v1",
            worker_contract="not_applicable",
            n_agents=4,
            array_size_bucket="small",
            budget_level="normal",
            model_name="gpt-4o-mini",
            runtime_version="full-phase-runtime-v3",
            binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
            compiler_version="1",
        )
        self.profile = self.registry.register_runtime_profile(
            namespace=self.namespace,
            limits=PhaseProgramLimits(),
        )
        self.ingress = self.registry.issue_ingress(self.manifest.manifest_sha256)
        self.proofs: dict[str, object] = {}
        self.bank = FactorBankV2(
            state_key=b"structural-ops-bank-key-value" * 2,
            direct_binding_verifier=make_phase_v3_binding_verifier(self.registry),
            whole_operation_verifier=make_phase_whole_operation_verifier(
                self.registry,
                self.proofs.get,
            ),
        )

    def ingest(self, program: PhaseProgram | None = None):
        return self.registry.ingest_program(
            program or _program(),
            runtime_profile=self.profile,
            ingress=self.ingress,
        )

    def prove(self, source, operation, *, branch="mutate"):
        proof = prove_structural_operation(
            self.registry,
            source_artifact=source,
            operation=operation,
            origin_branch=branch,
            ingress=self.ingress,
        )
        self.proofs[proof.receipt_sha256] = proof
        return proof


def test_apply_operations_reshape_the_container() -> None:
    program = _program()
    inserted = apply_structural_operation(
        program,
        {"op_kind": "insert_phase", "index": 1, "phase": _PAIRWISE},
    )
    assert [item.kind for item in inserted.phases] == [
        "gather",
        "pairwise_exchange",
        "broadcast",
    ]
    assert inserted.information_goal == program.information_goal

    moved = apply_structural_operation(
        inserted,
        {"op_kind": "move_phase", "index": 1, "to_index": 0},
    )
    assert [item.kind for item in moved.phases] == [
        "pairwise_exchange",
        "gather",
        "broadcast",
    ]

    deleted = apply_structural_operation(
        inserted,
        {"op_kind": "delete_phase", "index": 1},
    )
    assert deleted == program

    fresh = apply_structural_operation(
        program,
        {
            "op_kind": "fresh_skeleton",
            "phases": [
                _PAIRWISE,
                {"kind": "consensus", "pattern": "all_to_all", "max_rounds": 1},
            ],
        },
    )
    assert [item.kind for item in fresh.phases] == [
        "pairwise_exchange",
        "consensus",
    ]

    with pytest.raises(ValueError, match="beyond the phase container"):
        apply_structural_operation(
            program,
            {"op_kind": "delete_phase", "index": 5},
        )
    with pytest.raises(StructuralNoOpError):
        apply_structural_operation(
            program,
            {"op_kind": "move_phase", "index": 1, "to_index": 1},
        )


def test_prove_verify_and_tamper_rejection() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    proof = fixture.prove(
        source,
        {"op_kind": "insert_phase", "index": 1, "phase": _PAIRWISE},
    )
    assert verify_structural_operation_proof(fixture.registry, proof)
    assert proof.source_skeleton_sha256 != proof.target_skeleton_sha256

    tampered = proof.model_copy(update={"origin_branch": "fresh"})
    assert not verify_structural_operation_proof(fixture.registry, tampered)
    swapped = proof.model_copy(
        update={
            "source_artifact": proof.target_artifact,
            "target_artifact": proof.source_artifact,
        }
    )
    assert not verify_structural_operation_proof(fixture.registry, swapped)


def test_noop_and_channel_guards() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    with pytest.raises(StructuralNoOpError, match="unchanged"):
        fixture.prove(
            source,
            {
                "op_kind": "replace_phase",
                "index": 0,
                "phase": {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": "gather",
                },
            },
        )
    with pytest.raises(StructuralNoOpError, match="direct-factor channel"):
        fixture.prove(
            source,
            {
                "op_kind": "replace_phase",
                "index": 0,
                "phase": {
                    "kind": "gather",
                    "hub": 1,
                    "pattern": "tree",
                    "instruction": "gather",
                },
            },
        )


def test_register_whole_edge_is_atomic_and_idempotent() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    proof = fixture.prove(
        source,
        {"op_kind": "insert_phase", "index": 1, "phase": _PAIRWISE},
    )
    edge = register_phase_whole_materialization_v1(
        registry=fixture.registry,
        bank=fixture.bank,
        proof=proof,
    )
    transition = edge.transition
    assert transition.owner_kind == "whole_composition"
    assert transition.operation_verifier_epoch == (
        PHASE_WHOLE_OPERATION_VERIFIER_EPOCH
    )
    assert transition.transition_id in fixture.bank.whole_transitions
    assert PHASE_FULL_FACTOR_SKELETON_SLOT_ID in transition.changed_slot_ids
    assert transition.source_artifact_sha256 != transition.target_artifact_sha256
    assert (
        edge.source_structural_factor.revision_id
        != edge.target_structural_factor.revision_id
    )
    assert edge.source_composition.composition_id in fixture.bank.compositions
    assert edge.target_composition.composition_id in fixture.bank.compositions

    replay = register_phase_whole_materialization_v1(
        registry=fixture.registry,
        bank=fixture.bank,
        proof=proof,
    )
    assert replay == edge


def test_register_rejects_unresolvable_receipt() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    proof = fixture.prove(
        source,
        {"op_kind": "insert_phase", "index": 1, "phase": _PAIRWISE},
    )
    fixture.proofs.clear()
    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="whole-operation verifier rejected"):
        register_phase_whole_materialization_v1(
            registry=fixture.registry,
            bank=fixture.bank,
            proof=proof,
        )
    assert fixture.bank.to_state() == before


def test_fresh_skeleton_round_trip() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    operation = parse_structural_operation(
        {
            "op_kind": "fresh_skeleton",
            "phases": [
                _PAIRWISE,
                {"kind": "consensus", "pattern": "all_to_all", "max_rounds": 1},
            ],
        }
    )
    proof = fixture.prove(source, operation, branch="fresh")
    edge = register_phase_whole_materialization_v1(
        registry=fixture.registry,
        bank=fixture.bank,
        proof=proof,
    )
    assert edge.transition.origin_branch == "fresh"
    target_program = fixture.registry.resolve_artifact(
        proof.target_artifact
    ).program
    assert [item.kind for item in target_program.phases] == [
        "pairwise_exchange",
        "consensus",
    ]
