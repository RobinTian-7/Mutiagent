"""Typed structural operations over ``PhaseProgram`` and their whole edges.

The direct-factor channel (``phase_factor_binding_v3``) locks the structural
skeleton and proves exactly one scalar-leaf delta.  This module is the macro
channel: one typed structural operation (insert/delete/move/replace a phase,
or a fresh skeleton) turns a registered source artifact into a registered
target artifact, and the credit owner is one ``WholeCompositionTransitionV2``
— never the phases or scalars inside it.

Proof discipline: a ``PhaseStructuralOperationProofV1`` is content-complete
and replay-verified.  Every input is content-addressed registry state (both
artifacts, their compiled execution images, both skeleton projections), so
verification is deterministic re-derivation: apply the operation to the
source program, require byte-equality with the target program, and require
the recomputed receipt digest.  The FactorBank re-runs this verifier at
registration and during integrity audits via its trusted whole-operation
verifier hook, which is where enforcement lives.

Channel separation is enforced structurally: an operation whose source and
target project to the SAME skeleton is rejected here — single-scalar deltas
belong to the direct-factor channel where they earn exact per-factor credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, Field

from exp_graph.mas.factor_bank import (
    DenseOutcome,
    ExecutionNamespace,
    ExecutionUsage,
    FactorLocator,
    SlotBinding,
)
from exp_graph.mas.factor_bank_v2 import (
    ArmReceiptV2,
    CompositionRevisionV2,
    FactorBankV2,
    FactorRevisionV2,
    PairExecutionReceiptV2,
    ProbeAttemptV3,
    ProbePlanV2,
    WholeCompositionTransitionV2,
    make_arm_receipt_v2,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactHandle,
    PhaseArtifactRegistry,
    PhaseProgramArtifactRecord,
    phase_mutable_factor_paths_v3,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    PHASE_FULL_FACTOR_SKELETON_SLOT_ID,
    PHASE_FULL_FACTOR_SKELETON_VERSION,
    _canonical_json,
    _CompositionTemplate,
    _composition_matches,
    _factor_matches,
    _FactorTemplate,
    _opaque_id,
    _profile_for_artifact,
    _registry_factors_for_artifact,
    _scalar_template,
    _sha256,
    _structural_skeleton,
)
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgram,
    PhaseStatement,
)


STRUCTURAL_OPERATION_RECEIPT_VERSION = "phase-structural-operation-receipt-v1"
PHASE_WHOLE_OPERATION_VERIFIER_EPOCH = "facts-phase-whole-v1:1"


class StructuralNoOpError(ValueError):
    """The operation produced no new executable content (honest degenerate)."""


class _ClosedModel(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}


class InsertPhaseOpV1(_ClosedModel):
    op_kind: Literal["insert_phase"] = "insert_phase"
    index: int = Field(ge=0, le=12)
    phase: PhaseStatement


class DeletePhaseOpV1(_ClosedModel):
    op_kind: Literal["delete_phase"] = "delete_phase"
    index: int = Field(ge=0, le=11)


class MovePhaseOpV1(_ClosedModel):
    op_kind: Literal["move_phase"] = "move_phase"
    index: int = Field(ge=0, le=11)
    to_index: int = Field(ge=0, le=11)


class ReplacePhaseOpV1(_ClosedModel):
    op_kind: Literal["replace_phase"] = "replace_phase"
    index: int = Field(ge=0, le=11)
    phase: PhaseStatement


class FreshSkeletonOpV1(_ClosedModel):
    op_kind: Literal["fresh_skeleton"] = "fresh_skeleton"
    phases: tuple[PhaseStatement, ...] = Field(min_length=1, max_length=12)


StructuralOperationV1 = Annotated[
    Union[
        InsertPhaseOpV1,
        DeletePhaseOpV1,
        MovePhaseOpV1,
        ReplacePhaseOpV1,
        FreshSkeletonOpV1,
    ],
    Field(discriminator="op_kind"),
]


def parse_structural_operation(value: Any) -> Any:
    class _Holder(BaseModel):
        operation: StructuralOperationV1

    return _Holder.model_validate({"operation": value}).operation


def apply_structural_operation(
    program: PhaseProgram,
    operation: Any,
) -> PhaseProgram:
    """Deterministically apply one typed operation to a validated program.

    Program-level fields (goal, retention, submit rule, ...) are preserved
    verbatim; only the phase container changes.  The returned program is
    re-validated, so container bounds (1..12) and per-phase field laws hold.
    """

    operation = parse_structural_operation(
        operation.model_dump(mode="python")
        if isinstance(operation, BaseModel)
        else operation
    )
    phases = [item.model_dump(mode="python") for item in program.phases]
    if operation.op_kind == "insert_phase":
        if operation.index > len(phases):
            raise ValueError("insert_phase index is beyond the phase container")
        phases.insert(operation.index, operation.phase.model_dump(mode="python"))
    elif operation.op_kind == "delete_phase":
        if operation.index >= len(phases):
            raise ValueError("delete_phase index is beyond the phase container")
        phases.pop(operation.index)
    elif operation.op_kind == "move_phase":
        if operation.index >= len(phases) or operation.to_index >= len(phases):
            raise ValueError("move_phase index is beyond the phase container")
        if operation.index == operation.to_index:
            raise StructuralNoOpError("move_phase must change the phase order")
        moved = phases.pop(operation.index)
        phases.insert(operation.to_index, moved)
    elif operation.op_kind == "replace_phase":
        if operation.index >= len(phases):
            raise ValueError("replace_phase index is beyond the phase container")
        phases[operation.index] = operation.phase.model_dump(mode="python")
    elif operation.op_kind == "fresh_skeleton":
        phases = [item.model_dump(mode="python") for item in operation.phases]
    else:  # pragma: no cover - discriminator closes the union
        raise ValueError("unknown structural operation kind")
    payload = program.model_dump(mode="python")
    payload["phases"] = phases
    return PhaseProgram.model_validate(payload)


class PhaseStructuralOperationProofV1(_ClosedModel):
    """Content-complete, replay-verified record of one structural operation."""

    proof_id: str
    namespace: ExecutionNamespace
    runtime_profile_id: str
    source_artifact: PhaseArtifactHandle
    target_artifact: PhaseArtifactHandle
    operation: StructuralOperationV1
    origin_branch: Literal["mutate", "fresh"]
    source_skeleton_sha256: str
    target_skeleton_sha256: str
    source_image_commitment: str
    target_image_commitment: str
    binder_version: str
    compiler_version: str
    receipt_sha256: str


@dataclass(frozen=True)
class _ProofView:
    """Namespace/branch view for the shared scalar-template projector."""

    namespace: Any
    branch: str


def _receipt_payload(
    *,
    namespace: Any,
    runtime_profile_id: str,
    source_artifact_id: str,
    target_artifact_id: str,
    source_image_commitment: str,
    target_image_commitment: str,
    source_skeleton_sha256: str,
    target_skeleton_sha256: str,
    operation: Any,
    origin_branch: str,
) -> dict[str, Any]:
    return {
        "receipt_version": STRUCTURAL_OPERATION_RECEIPT_VERSION,
        "namespace": namespace.digest,
        "runtime_profile_id": runtime_profile_id,
        "source_artifact_id": source_artifact_id,
        "target_artifact_id": target_artifact_id,
        "source_image_commitment": source_image_commitment,
        "target_image_commitment": target_image_commitment,
        "source_skeleton_sha256": source_skeleton_sha256,
        "target_skeleton_sha256": target_skeleton_sha256,
        "operation": operation.model_dump(mode="json"),
        "origin_branch": origin_branch,
        "binder_version": PHASE_FULL_FACTOR_BINDER_VERSION,
        "compiler_version": PHASE_PROGRAM_COMPILER_VERSION,
    }


def _side_skeleton_sha256(
    artifact: PhaseProgramArtifactRecord,
    profile: Any,
) -> str:
    paths = phase_mutable_factor_paths_v3(artifact.program)
    return _sha256(_structural_skeleton(artifact, profile, paths))


def prove_structural_operation(
    registry: PhaseArtifactRegistry,
    *,
    source_artifact: PhaseArtifactHandle,
    operation: Any,
    origin_branch: Literal["mutate", "fresh"],
    ingress: Any,
) -> PhaseStructuralOperationProofV1:
    """Apply, compile-register, and receipt one structural operation.

    Raises ``StructuralNoOpError`` when the operation yields no new executable
    content: an unchanged program, an identical compiled execution image (the
    compiler elides rounds past coverage, so textual change is not enough),
    or an unchanged skeleton (that delta belongs to the direct channel).
    """

    operation = parse_structural_operation(
        operation.model_dump(mode="python")
        if isinstance(operation, BaseModel)
        else operation
    )
    source = registry.resolve_artifact(source_artifact)
    profile = _profile_for_artifact(registry, source)
    target_program = apply_structural_operation(source.program, operation)
    if target_program == source.program:
        raise StructuralNoOpError(
            "structural operation left the source program unchanged"
        )
    target_handle = registry.ingest_program(
        target_program,
        runtime_profile=source.runtime_profile,
        ingress=ingress,
    )
    target = registry.resolve_artifact(target_handle)
    if target.execution_image_commitment == source.execution_image_commitment:
        raise StructuralNoOpError(
            "structural operation compiled to the identical execution image"
        )
    source_skeleton_sha256 = _side_skeleton_sha256(source, profile)
    target_skeleton_sha256 = _side_skeleton_sha256(target, profile)
    if source_skeleton_sha256 == target_skeleton_sha256:
        raise StructuralNoOpError(
            "structural operation kept the locked skeleton; a single-scalar "
            "delta belongs to the direct-factor channel"
        )
    payload = _receipt_payload(
        namespace=profile.namespace,
        runtime_profile_id=profile.handle.handle_id,
        source_artifact_id=source.handle.handle_id,
        target_artifact_id=target.handle.handle_id,
        source_image_commitment=source.execution_image_commitment,
        target_image_commitment=target.execution_image_commitment,
        source_skeleton_sha256=source_skeleton_sha256,
        target_skeleton_sha256=target_skeleton_sha256,
        operation=operation,
        origin_branch=origin_branch,
    )
    return PhaseStructuralOperationProofV1(
        proof_id=_opaque_id("sop", payload),
        namespace=profile.namespace,
        runtime_profile_id=profile.handle.handle_id,
        source_artifact=source.handle,
        target_artifact=target.handle,
        operation=operation,
        origin_branch=origin_branch,
        source_skeleton_sha256=source_skeleton_sha256,
        target_skeleton_sha256=target_skeleton_sha256,
        source_image_commitment=source.execution_image_commitment,
        target_image_commitment=target.execution_image_commitment,
        binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        compiler_version=PHASE_PROGRAM_COMPILER_VERSION,
        receipt_sha256=_sha256(payload),
    )


def verify_structural_operation_proof(
    registry: PhaseArtifactRegistry,
    proof: PhaseStructuralOperationProofV1,
) -> bool:
    """Deterministically re-derive the proof; False on any divergence."""

    try:
        proof = PhaseStructuralOperationProofV1.model_validate(
            proof.model_dump(mode="python")
        )
        source = registry.resolve_artifact(proof.source_artifact)
        target = registry.resolve_artifact(proof.target_artifact)
        source_profile = _profile_for_artifact(registry, source)
        target_profile = _profile_for_artifact(registry, target)
        if source_profile != target_profile:
            return False
        if source_profile.handle.handle_id != proof.runtime_profile_id:
            return False
        if source_profile.namespace != proof.namespace:
            return False
        replayed = apply_structural_operation(source.program, proof.operation)
        if replayed != target.program:
            return False
        source_skeleton_sha256 = _side_skeleton_sha256(source, source_profile)
        target_skeleton_sha256 = _side_skeleton_sha256(target, target_profile)
        payload = _receipt_payload(
            namespace=source_profile.namespace,
            runtime_profile_id=source_profile.handle.handle_id,
            source_artifact_id=source.handle.handle_id,
            target_artifact_id=target.handle.handle_id,
            source_image_commitment=source.execution_image_commitment,
            target_image_commitment=target.execution_image_commitment,
            source_skeleton_sha256=source_skeleton_sha256,
            target_skeleton_sha256=target_skeleton_sha256,
            operation=proof.operation,
            origin_branch=proof.origin_branch,
        )
        return bool(
            proof.binder_version == PHASE_FULL_FACTOR_BINDER_VERSION
            and proof.compiler_version == PHASE_PROGRAM_COMPILER_VERSION
            and proof.source_skeleton_sha256 == source_skeleton_sha256
            and proof.target_skeleton_sha256 == target_skeleton_sha256
            and source_skeleton_sha256 != target_skeleton_sha256
            and proof.source_image_commitment
            == source.execution_image_commitment
            and proof.target_image_commitment
            == target.execution_image_commitment
            and proof.source_image_commitment != proof.target_image_commitment
            and proof.receipt_sha256 == _sha256(payload)
            and proof.proof_id == _opaque_id("sop", payload)
        )
    except Exception:
        return False


@dataclass(frozen=True)
class _CanonicalWholePhaseBundle:
    proof: PhaseStructuralOperationProofV1
    source_structural_factor: _FactorTemplate
    target_structural_factor: _FactorTemplate
    source_scalar_factors: tuple[_FactorTemplate, ...]
    target_scalar_factors: tuple[_FactorTemplate, ...]
    source_composition: _CompositionTemplate
    target_composition: _CompositionTemplate

    @property
    def all_factor_templates(self) -> tuple[_FactorTemplate, ...]:
        by_id: dict[str, _FactorTemplate] = {}
        for item in (
            self.source_structural_factor,
            self.target_structural_factor,
            *self.source_scalar_factors,
            *self.target_scalar_factors,
        ):
            previous = by_id.get(item.revision_id)
            if previous is not None and previous != item:
                raise ValueError(
                    "one whole Phase factor id has conflicting templates"
                )
            by_id[item.revision_id] = item
        return tuple(by_id[key] for key in sorted(by_id))


def _skeleton_factor_template(
    *,
    namespace: Any,
    profile: Any,
    skeleton_sha256: str,
) -> _FactorTemplate:
    return _FactorTemplate(
        revision_id=_opaque_id(
            "psk",
            {
                "namespace": namespace.digest,
                "profile": profile.handle.handle_id,
                "skeleton": skeleton_sha256,
            },
        ),
        logical_factor_id=_opaque_id(
            "lsk",
            {
                "namespace": namespace.digest,
                "profile": profile.handle.handle_id,
                "version": PHASE_FULL_FACTOR_SKELETON_VERSION,
            },
        ),
        namespace=namespace,
        carrier="constraint",
        locator=FactorLocator(
            surface="atomic_artifact",
            path="/structural_skeleton",
            locator_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        ),
        binding_status="locked_atomic",
        content_sha256=skeleton_sha256,
        parent_revision_id=None,
        origin_branch="migration",
        lineage_required=False,
    )


def _project_whole_side(
    registry: PhaseArtifactRegistry,
    *,
    artifact: PhaseProgramArtifactRecord,
    profile: Any,
    namespace: Any,
    origin_branch: str,
) -> tuple[tuple[_FactorTemplate, ...], _FactorTemplate, _CompositionTemplate]:
    """Project one artifact into whole-side rows: no lineage, no changed slot.

    Row identities (slot ids, factor revision ids, composition ids) reuse the
    exact direct-channel derivations, so a composition reached through both
    channels resolves to the same Bank rows instead of an alias.
    """

    paths = phase_mutable_factor_paths_v3(artifact.program)
    records = _registry_factors_for_artifact(
        registry,
        artifact=artifact,
        profile=profile,
        paths=paths,
    )
    view = _ProofView(namespace=namespace, branch=origin_branch)
    scalar_templates: list[_FactorTemplate] = []
    bindings: list[SlotBinding] = []
    for record in records:
        slot_id, template = _scalar_template(
            proof=view,
            profile=profile,
            factor=record,
            is_changed_target=False,
            source_changed_revision_id="",
            action_bound=False,
        )
        scalar_templates.append(template)
        bindings.append(
            SlotBinding(slot_id=slot_id, factor_revision_id=template.revision_id)
        )
    skeleton_sha256 = _sha256(_structural_skeleton(artifact, profile, paths))
    structural = _skeleton_factor_template(
        namespace=namespace,
        profile=profile,
        skeleton_sha256=skeleton_sha256,
    )
    bindings.append(
        SlotBinding(
            slot_id=PHASE_FULL_FACTOR_SKELETON_SLOT_ID,
            factor_revision_id=structural.revision_id,
        )
    )
    canonical_bindings = tuple(sorted(bindings, key=lambda item: item.slot_id))
    identity = {
        "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
        "namespace": namespace.digest,
        "artifact": artifact.handle.handle_id,
        "execution_image": artifact.execution_image_commitment,
        "bindings": canonical_bindings,
    }
    metadata = {
        "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
        "artifact_revision_id": artifact.handle.handle_id,
        "execution_image_commitment": artifact.execution_image_commitment,
        "bindings": canonical_bindings,
    }
    composition = _CompositionTemplate(
        composition_id=_opaque_id("pc", identity),
        namespace=namespace,
        artifact_revision_id=artifact.handle.handle_id,
        artifact_sha256=artifact.execution_image_commitment,
        bindings=canonical_bindings,
        canonical_metadata_bytes=len(_canonical_json(metadata).encode("utf-8")),
        artifact_bytes=len(_canonical_json(artifact.program).encode("utf-8")),
        parent_composition_id=None,
        origin_branch="migration",
        lineage_required=False,
    )
    return tuple(scalar_templates), structural, composition


def _canonical_whole_bundle(
    registry: PhaseArtifactRegistry,
    proof: PhaseStructuralOperationProofV1,
) -> _CanonicalWholePhaseBundle:
    if not verify_structural_operation_proof(registry, proof):
        raise ValueError(
            "structural operation proof failed deterministic replay"
        )
    source = registry.resolve_artifact(proof.source_artifact)
    target = registry.resolve_artifact(proof.target_artifact)
    profile = _profile_for_artifact(registry, source)
    source_scalars, source_structural, source_composition = _project_whole_side(
        registry,
        artifact=source,
        profile=profile,
        namespace=proof.namespace,
        origin_branch=proof.origin_branch,
    )
    target_scalars, target_structural, target_composition = _project_whole_side(
        registry,
        artifact=target,
        profile=profile,
        namespace=proof.namespace,
        origin_branch=proof.origin_branch,
    )
    return _CanonicalWholePhaseBundle(
        proof=proof,
        source_structural_factor=source_structural,
        target_structural_factor=target_structural,
        source_scalar_factors=source_scalars,
        target_scalar_factors=target_scalars,
        source_composition=source_composition,
        target_composition=target_composition,
    )


class RegisteredPhaseWholeCompositionEdgeV1(BaseModel):
    """Immutable whole-composition rows installed for one operation proof."""

    model_config = {"extra": "forbid", "frozen": True}

    proof: PhaseStructuralOperationProofV1
    source_structural_factor: FactorRevisionV2
    target_structural_factor: FactorRevisionV2
    source_scalar_factors: tuple[FactorRevisionV2, ...]
    target_scalar_factors: tuple[FactorRevisionV2, ...]
    source_composition: CompositionRevisionV2
    target_composition: CompositionRevisionV2
    transition: WholeCompositionTransitionV2


def _registered_whole_edge(
    bank: FactorBankV2,
    bundle: _CanonicalWholePhaseBundle,
    transition: WholeCompositionTransitionV2,
) -> RegisteredPhaseWholeCompositionEdgeV1:
    return RegisteredPhaseWholeCompositionEdgeV1(
        proof=bundle.proof,
        source_structural_factor=bank.factors[
            bundle.source_structural_factor.revision_id
        ],
        target_structural_factor=bank.factors[
            bundle.target_structural_factor.revision_id
        ],
        source_scalar_factors=tuple(
            bank.factors[item.revision_id]
            for item in bundle.source_scalar_factors
        ),
        target_scalar_factors=tuple(
            bank.factors[item.revision_id]
            for item in bundle.target_scalar_factors
        ),
        source_composition=bank.compositions[
            bundle.source_composition.composition_id
        ],
        target_composition=bank.compositions[
            bundle.target_composition.composition_id
        ],
        transition=transition,
    )


def _validate_persisted_bundle(
    bank: FactorBankV2,
    bundle: _CanonicalWholePhaseBundle,
) -> None:
    if any(
        item.revision_id not in bank.factors
        for item in bundle.all_factor_templates
    ) or any(
        item.composition_id not in bank.compositions
        for item in (bundle.source_composition, bundle.target_composition)
    ):
        raise ValueError("persisted whole Phase edge lost its canonical bundle")
    if not all(
        _factor_matches(item, bank.factors[item.revision_id])
        for item in bundle.all_factor_templates
    ) or not all(
        _composition_matches(item, bank.compositions[item.composition_id])
        for item in (bundle.source_composition, bundle.target_composition)
    ):
        raise ValueError("persisted whole Phase rows differ from their proof")


def register_phase_whole_materialization_v1(
    *,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    proof: PhaseStructuralOperationProofV1,
) -> RegisteredPhaseWholeCompositionEdgeV1:
    """Atomically project one operation proof into a whole Bank edge."""

    if not verify_structural_operation_proof(registry, proof):
        raise ValueError(
            "structural operation proof failed deterministic replay"
        )
    registry.extract_full_factorizations_v3(
        (proof.source_artifact, proof.target_artifact)
    )
    bundle = _canonical_whole_bundle(registry, proof)
    existing_edges = [
        item
        for item in bank.whole_transitions.values()
        if item.operation_receipt_sha256 == proof.receipt_sha256
    ]
    if existing_edges:
        if len(existing_edges) != 1:
            raise ValueError(
                "one structural operation owns multiple FactorBank edges"
            )
        transition = existing_edges[0]
        _validate_persisted_bundle(bank, bundle)
        if not (
            transition.namespace == proof.namespace
            and transition.source_composition_id
            == bundle.source_composition.composition_id
            and transition.target_composition_id
            == bundle.target_composition.composition_id
            and transition.source_artifact_sha256
            == proof.source_image_commitment
            and transition.target_artifact_sha256
            == proof.target_image_commitment
            and transition.operation_verifier_epoch
            == PHASE_WHOLE_OPERATION_VERIFIER_EPOCH
            and transition.origin_branch == proof.origin_branch
        ):
            raise ValueError("persisted whole Phase edge differs from its proof")
        return _registered_whole_edge(bank, bundle, transition)

    next_seq = bank.to_state().event_seq
    new_factors: list[FactorRevisionV2] = []
    for template in bundle.all_factor_templates:
        existing = bank.factors.get(template.revision_id)
        if existing is not None:
            if not _factor_matches(template, existing):
                raise ValueError(
                    "existing Bank factor differs from whole Phase projection"
                )
            continue
        next_seq += 1
        new_factors.append(template.build(created_seq=next_seq))
    new_compositions: list[CompositionRevisionV2] = []
    for template in (bundle.source_composition, bundle.target_composition):
        existing = bank.compositions.get(template.composition_id)
        if existing is not None:
            if not _composition_matches(template, existing):
                raise ValueError(
                    "existing Bank composition differs from whole Phase projection"
                )
            continue
        next_seq += 1
        new_compositions.append(template.build(created_seq=next_seq))
    transition = bank.register_whole_bundle(
        factors=tuple(new_factors),
        compositions=tuple(new_compositions),
        transition_fields={
            "source_composition_id": bundle.source_composition.composition_id,
            "target_composition_id": bundle.target_composition.composition_id,
            "operation_receipt_sha256": proof.receipt_sha256,
            "operation_verifier_epoch": PHASE_WHOLE_OPERATION_VERIFIER_EPOCH,
            "origin_branch": proof.origin_branch,
        },
    )
    return _registered_whole_edge(bank, bundle, transition)


def derive_whole_transition_identity(
    bundle: _CanonicalWholePhaseBundle,
) -> tuple[tuple[str, ...], str]:
    """Recompute changed slots and the transition id the Bank will mint.

    Mirrors ``FactorBankV2._register_whole_transition_impl`` exactly, so a
    verifier can join a receipt's ``binding_proof_id`` (= transition id for
    whole arms) to the operation proof without holding Bank state.
    """

    source_map = {
        item.slot_id: item.factor_revision_id
        for item in bundle.source_composition.bindings
    }
    target_map = {
        item.slot_id: item.factor_revision_id
        for item in bundle.target_composition.bindings
    }
    slots = sorted(set(source_map) | set(target_map))
    changed = tuple(
        slot for slot in slots if source_map.get(slot) != target_map.get(slot)
    )
    transition_id = _opaque_id(
        "wt",
        {
            "namespace": bundle.proof.namespace.digest,
            "source": bundle.source_composition.composition_id,
            "target": bundle.target_composition.composition_id,
            "changed": changed,
            "receipt": bundle.proof.receipt_sha256,
            "branch": bundle.proof.origin_branch,
        },
    )
    return changed, transition_id


def verify_registered_whole_edge(
    registry: PhaseArtifactRegistry,
    edge: RegisteredPhaseWholeCompositionEdgeV1,
) -> bool:
    """Replay one registered whole edge from its content-complete proof."""

    try:
        edge = RegisteredPhaseWholeCompositionEdgeV1.model_validate(
            edge.model_dump(mode="python")
        )
        bundle = _canonical_whole_bundle(registry, edge.proof)
    except (TypeError, ValueError, RuntimeError):
        return False
    changed, transition_id = derive_whole_transition_identity(bundle)
    transition = edge.transition
    template_by_id = {
        item.revision_id: item for item in bundle.all_factor_templates
    }
    rows = (
        edge.source_structural_factor,
        edge.target_structural_factor,
        *edge.source_scalar_factors,
        *edge.target_scalar_factors,
    )
    return bool(
        transition.transition_id == transition_id
        and transition.owner_kind == "whole_composition"
        and transition.namespace == edge.proof.namespace
        and transition.changed_slot_ids == changed
        and transition.source_composition_id
        == bundle.source_composition.composition_id
        and transition.target_composition_id
        == bundle.target_composition.composition_id
        and transition.source_artifact_sha256
        == edge.proof.source_image_commitment
        and transition.target_artifact_sha256
        == edge.proof.target_image_commitment
        and transition.operation_receipt_sha256 == edge.proof.receipt_sha256
        and transition.operation_verifier_epoch
        == PHASE_WHOLE_OPERATION_VERIFIER_EPOCH
        and transition.origin_branch == edge.proof.origin_branch
        and edge.source_structural_factor.revision_id
        == bundle.source_structural_factor.revision_id
        and edge.target_structural_factor.revision_id
        == bundle.target_structural_factor.revision_id
        and all(
            item.revision_id in template_by_id
            and _factor_matches(template_by_id[item.revision_id], item)
            for item in rows
        )
        and _composition_matches(
            bundle.source_composition, edge.source_composition
        )
        and _composition_matches(
            bundle.target_composition, edge.target_composition
        )
    )


def make_registered_phase_whole_arm_receipt_v1(
    *,
    registry: PhaseArtifactRegistry,
    registered: RegisteredPhaseWholeCompositionEdgeV1,
    plan: ProbePlanV2,
    attempt: ProbeAttemptV3,
    arm: Literal["source", "target"],
    root_id: str,
    paired_arm_root_id: str,
    pair_execution_receipt: PairExecutionReceiptV2,
    activation_trace_root: str,
    usage: ExecutionUsage,
    execution_class: Literal[
        "completed", "algorithm_failure", "infrastructure_failure", "harness_failure"
    ],
    outcome: DenseOutcome | None,
    producer_epoch: str,
    attestation_sha256: str,
    safe_failure_code: str | None = None,
    failed_stage_rank: int | None = None,
) -> ArmReceiptV2:
    """Whole-edge receipt codec; signature mirrors the direct v3 factory.

    ``make_arm_receipt_v2`` already derives the whole-arm law from the
    transition type: ``binding_proof_id`` becomes the transition id and the
    activated direct-factor set is empty.  The materialization event of a
    whole edge is the target artifact's registration.
    """

    del registry  # parity with the direct factory; the proof is content-complete
    composition = (
        registered.source_composition
        if arm == "source"
        else registered.target_composition
    )
    return make_arm_receipt_v2(
        plan=plan,
        attempt=attempt,
        composition=composition,
        transition=registered.transition,
        arm=arm,
        root_id=root_id,
        paired_arm_root_id=paired_arm_root_id,
        pair_execution_receipt=pair_execution_receipt,
        runtime_profile_id=registered.proof.runtime_profile_id,
        materialization_event_id=registered.proof.target_artifact.handle_id,
        activation_trace_root=activation_trace_root,
        usage=usage,
        execution_class=execution_class,
        outcome=outcome,
        producer_epoch=producer_epoch,
        attestation_sha256=attestation_sha256,
        safe_failure_code=safe_failure_code,
        failed_stage_rank=failed_stage_rank,
    )


def make_phase_whole_arm_receipt_verifier(
    registry: PhaseArtifactRegistry,
    proof_resolver: Callable[[str], PhaseStructuralOperationProofV1 | None],
    *,
    trusted_runner_verifier: Callable[[ArmReceiptV2, Any], bool],
) -> Callable[[ArmReceiptV2, ProbePlanV2, Any], bool]:
    """Join runner evidence to a whole operation proof; no factor is credited."""

    if not callable(trusted_runner_verifier):
        raise TypeError("trusted_runner_verifier must be a host capability")
    if not callable(proof_resolver):
        raise TypeError("proof_resolver must be a host capability")

    def verify(receipt: ArmReceiptV2, plan: ProbePlanV2, assignment: Any) -> bool:
        try:
            proof = proof_resolver(plan.binding_or_operation_proof_sha256)
            if proof is None:
                return False
            bundle = _canonical_whole_bundle(registry, proof)
        except (TypeError, ValueError, RuntimeError):
            return False
        _changed, transition_id = derive_whole_transition_identity(bundle)
        template = (
            bundle.source_composition
            if receipt.arm == "source"
            else bundle.target_composition
        )
        image = (
            proof.source_image_commitment
            if receipt.arm == "source"
            else proof.target_image_commitment
        )
        expected_position = (
            0
            if (
                (assignment.arm_order == "AB" and receipt.arm == "source")
                or (assignment.arm_order == "BA" and receipt.arm == "target")
            )
            else 1
        )
        if not all(
            (
                plan.owner_kind == "whole_composition",
                plan.binding_or_operation_proof_sha256 == proof.receipt_sha256,
                plan.namespace_digest == proof.namespace.digest,
                receipt.composition_id == template.composition_id,
                receipt.runtime_profile_id == proof.runtime_profile_id,
                receipt.materialization_event_id
                == proof.target_artifact.handle_id,
                receipt.binding_proof_id == transition_id,
                receipt.observed_arm_order == assignment.arm_order,
                receipt.arm_position == expected_position,
                receipt.assigned_artifact_sha256 == image,
                receipt.materialized_artifact_sha256 == image,
                receipt.selected_artifact_sha256 == image,
                receipt.loaded_artifact_sha256 == image,
                receipt.activated_direct_factor_revision_ids == (),
            )
        ):
            return False
        try:
            return bool(trusted_runner_verifier(receipt, proof))
        except Exception:
            return False

    return verify


def make_phase_whole_operation_verifier(
    registry: PhaseArtifactRegistry,
    proof_resolver: Callable[[str], PhaseStructuralOperationProofV1 | None],
) -> Callable[
    [WholeCompositionTransitionV2, CompositionRevisionV2, CompositionRevisionV2],
    bool,
]:
    """Return the Bank's trusted whole-operation verifier.

    ``proof_resolver`` maps an ``operation_receipt_sha256`` to its structural
    proof (the host persists proofs beside the Bank envelope).  Verification
    is full re-derivation: replay the operation, re-project both compositions,
    and require every transition field to match the recomputed bundle.
    """

    if not callable(proof_resolver):
        raise TypeError("proof_resolver must be a host capability")

    def verify(
        transition: WholeCompositionTransitionV2,
        source: CompositionRevisionV2,
        target: CompositionRevisionV2,
    ) -> bool:
        try:
            proof = proof_resolver(transition.operation_receipt_sha256)
            if proof is None:
                return False
            if proof.receipt_sha256 != transition.operation_receipt_sha256:
                return False
            bundle = _canonical_whole_bundle(registry, proof)
        except (TypeError, ValueError, RuntimeError):
            return False
        return bool(
            transition.operation_verifier_epoch
            == PHASE_WHOLE_OPERATION_VERIFIER_EPOCH
            and transition.origin_branch == proof.origin_branch
            and transition.namespace == proof.namespace
            and transition.source_composition_id
            == bundle.source_composition.composition_id
            and transition.target_composition_id
            == bundle.target_composition.composition_id
            and transition.source_artifact_sha256
            == proof.source_image_commitment
            and transition.target_artifact_sha256
            == proof.target_image_commitment
            and _composition_matches(bundle.source_composition, source)
            and _composition_matches(bundle.target_composition, target)
        )

    return verify


__all__ = [
    "PHASE_WHOLE_OPERATION_VERIFIER_EPOCH",
    "STRUCTURAL_OPERATION_RECEIPT_VERSION",
    "DeletePhaseOpV1",
    "FreshSkeletonOpV1",
    "InsertPhaseOpV1",
    "MovePhaseOpV1",
    "PhaseStructuralOperationProofV1",
    "RegisteredPhaseWholeCompositionEdgeV1",
    "ReplacePhaseOpV1",
    "StructuralNoOpError",
    "StructuralOperationV1",
    "apply_structural_operation",
    "derive_whole_transition_identity",
    "make_phase_whole_arm_receipt_verifier",
    "make_phase_whole_operation_verifier",
    "make_registered_phase_whole_arm_receipt_v1",
    "parse_structural_operation",
    "prove_structural_operation",
    "register_phase_whole_materialization_v1",
    "verify_registered_whole_edge",
    "verify_structural_operation_proof",
]
