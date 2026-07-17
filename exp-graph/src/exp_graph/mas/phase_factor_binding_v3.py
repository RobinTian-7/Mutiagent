"""Canonical full-factor PhaseProgram adapter for ``FactorBankV2``.

Unlike the legacy leaf-v2 projection, a composition in this adapter contains
every mutable typed Phase scalar plus one locked structural-skeleton factor.
Consequently the identity of an artifact's composition is independent of the
locus selected by a later one-factor proof.  The FactorBank's exact active
composition gate remains unchanged; this module repairs the representation
instead of introducing an artifact-hash alias.

The registry proof remains the only transition authority.  Callers provide a
proof handle, never a list of fields or factors.  Before registration the
registry atomically extracts its own complete canonical factor domain, and
the verifier reconstructs that domain again on every Bank load.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel

from exp_graph.mas.factor_bank import (
    DenseOutcome,
    ExecutionUsage,
    FactorLocator,
    SlotBinding,
)
from exp_graph.mas.factor_bank_v2 import (
    ArmReceiptV2,
    CompositionRevisionV2,
    DirectFactorTransitionV2,
    FactorBankV2,
    FactorBankStateV2,
    FactorRevisionV2,
    FailureObservationV2,
    PairExecutionReceiptV2,
    ProbeAttemptV3,
    ProbePlanV2,
    ProposalActionAbortReceiptV2,
    ProposalActionV2,
    RepairOpportunityV2,
    make_arm_receipt_v2,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    FactorContentHandle,
    NoOpMaterialization,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    PhaseGenerationTerminalV1,
    PhaseMaterializationProofRecord,
    PhaseProgramArtifactRecord,
    PhaseRuntimeProfileRecord,
    _descriptor,
    _leaf_differences,
    _pointer,
    _read_pointer,
    phase_mutable_factor_paths_v3,
)
from exp_graph.mas.phase_factor_binding_v2 import (
    AbortedPhaseProposalActionV2,
    _MISSING_GENERATED_VALUE,
    _make_phase_proposal_action_terminal_verifier,
    _proof_action_binding,
    _reconcile_phase_proposal_action_versioned,
)


PHASE_FACTOR_BANK_V3_VERIFIER_EPOCH = "facts-phase-full-v3:1"
PHASE_FULL_FACTOR_SKELETON_VERSION = "phase-structural-skeleton-v3"
PHASE_FULL_FACTOR_SKELETON_SLOT_ID = "phase_structural_skeleton"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _opaque_id(prefix: str, value: Any) -> str:
    return f"{prefix}:{_sha256(value)[:24]}"


@dataclass(frozen=True)
class _FactorTemplate:
    revision_id: str
    logical_factor_id: str
    namespace: Any
    carrier: str
    locator: FactorLocator
    binding_status: str
    content_sha256: str
    parent_revision_id: str | None
    origin_branch: str
    lineage_required: bool

    def build(self, *, created_seq: int) -> FactorRevisionV2:
        return FactorRevisionV2(
            revision_id=self.revision_id,
            logical_factor_id=self.logical_factor_id,
            namespace=self.namespace,
            carrier=self.carrier,
            locator=self.locator,
            binding_status=self.binding_status,
            content_sha256=self.content_sha256,
            parent_revision_id=self.parent_revision_id,
            origin_branch=self.origin_branch,
            insight_ids=(),
            failure_hypothesis_ids=(),
            structural_state="live",
            created_seq=created_seq,
        )


@dataclass(frozen=True)
class _CompositionTemplate:
    composition_id: str
    namespace: Any
    artifact_revision_id: str
    artifact_sha256: str
    bindings: tuple[SlotBinding, ...]
    canonical_metadata_bytes: int
    artifact_bytes: int
    parent_composition_id: str | None
    origin_branch: str
    lineage_required: bool

    def build(self, *, created_seq: int) -> CompositionRevisionV2:
        return CompositionRevisionV2(
            composition_id=self.composition_id,
            namespace=self.namespace,
            carrier="phase_program",
            artifact_revision_id=self.artifact_revision_id,
            artifact_sha256=self.artifact_sha256,
            bindings=self.bindings,
            origin_branch=self.origin_branch,
            parent_composition_id=self.parent_composition_id,
            structural_state="live",
            canonical_metadata_bytes=self.canonical_metadata_bytes,
            artifact_bytes=self.artifact_bytes,
            prompt_summary_tokens=0,
            created_seq=created_seq,
        )


@dataclass(frozen=True)
class _CanonicalFullPhaseBundle:
    proof: PhaseMaterializationProofRecord
    structural_factor: _FactorTemplate
    source_scalar_factors: tuple[_FactorTemplate, ...]
    target_scalar_factors: tuple[_FactorTemplate, ...]
    source_factor: _FactorTemplate
    target_factor: _FactorTemplate
    source_composition: _CompositionTemplate
    target_composition: _CompositionTemplate
    changed_slot_id: str

    @property
    def all_factor_templates(self) -> tuple[_FactorTemplate, ...]:
        by_id: dict[str, _FactorTemplate] = {}
        for item in (
            self.structural_factor,
            *self.source_scalar_factors,
            *self.target_scalar_factors,
        ):
            previous = by_id.get(item.revision_id)
            if previous is not None and previous != item:
                raise ValueError("one full Phase factor id has conflicting templates")
            by_id[item.revision_id] = item
        return tuple(by_id[key] for key in sorted(by_id))


class RegisteredPhaseFactorEdgeV3(BaseModel):
    """Immutable full-factor rows installed for one registry-proved edge."""

    model_config = {"extra": "forbid", "frozen": True}

    proof: PhaseBindingProofHandle
    structural_factor: FactorRevisionV2
    source_scalar_factors: tuple[FactorRevisionV2, ...]
    target_scalar_factors: tuple[FactorRevisionV2, ...]
    source_factor: FactorRevisionV2
    target_factor: FactorRevisionV2
    source_composition: CompositionRevisionV2
    target_composition: CompositionRevisionV2
    transition: DirectFactorTransitionV2


def _typed_equal(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _profile_for_artifact(
    registry: PhaseArtifactRegistry,
    artifact: PhaseProgramArtifactRecord,
) -> PhaseRuntimeProfileRecord:
    matches = [
        item
        for item in registry.to_state().profiles
        if item.handle == artifact.runtime_profile
    ]
    if len(matches) != 1:
        raise ValueError("Phase artifact lacks one exact runtime profile")
    profile = matches[0]
    if profile.binder_version != PHASE_FULL_FACTOR_BINDER_VERSION:
        raise ValueError("full-v3 adapter rejects a non-v3 Phase profile")
    return profile


def _registry_factors_for_artifact(
    registry: PhaseArtifactRegistry,
    *,
    artifact: PhaseProgramArtifactRecord,
    profile: PhaseRuntimeProfileRecord,
    paths: tuple[str, ...],
) -> tuple[Any, ...]:
    """Resolve one full map with one bounded state index, not L full scans."""

    state = registry.to_state()
    value_by_id = {item.handle.handle_id: item for item in state.values}
    factors_by_path: dict[str, list[Any]] = {}
    for item in state.factors:
        if item.runtime_profile != profile.handle:
            continue
        factors_by_path.setdefault(item.descriptor.locator.path, []).append(item)
    raw = artifact.program.model_dump(mode="json")
    resolved = []
    for path in paths:
        descriptor = _descriptor(artifact.program, profile, path)
        expected_value = _read_pointer(raw, path)
        candidates = []
        for item in factors_by_path.get(path, ()):
            value = value_by_id.get(item.value.handle_id)
            if (
                item.descriptor == descriptor
                and value is not None
                and _typed_equal(value.value, expected_value)
            ):
                candidates.append(item)
        if len(candidates) != 1:
            raise ValueError("full Phase locus lacks one exact registry factor")
        resolved.append(registry.resolve_factor(candidates[0].handle))
    return tuple(resolved)


def _structural_skeleton(
    artifact: PhaseProgramArtifactRecord,
    profile: PhaseRuntimeProfileRecord,
    paths: tuple[str, ...],
) -> dict[str, Any]:
    program = artifact.program
    phase_shapes = []
    for index, phase in enumerate(program.phases):
        prefix = f"/phases/{index}/"
        mutable_fields = tuple(
            path.removeprefix(prefix)
            for path in paths
            if path.startswith(prefix)
        )
        phase_shapes.append(
            {
                "index": index,
                "kind": phase.kind,
                "mutable_fields": mutable_fields,
            }
        )
    return {
        "skeleton_version": PHASE_FULL_FACTOR_SKELETON_VERSION,
        "profile_id": profile.handle.handle_id,
        "program_format": program.format,
        "information_goal": program.information_goal,
        "state_retention": program.state_retention,
        "allow_no_send": program.allow_no_send,
        "submit_when": program.submit_when,
        "phase_container": tuple(phase_shapes),
        "canonical_mutable_paths": paths,
    }


def _scalar_template(
    *,
    proof: PhaseMaterializationProofRecord,
    profile: PhaseRuntimeProfileRecord,
    factor: Any,
    is_changed_target: bool,
    source_changed_revision_id: str,
    action_bound: bool,
) -> tuple[str, _FactorTemplate]:
    descriptor = factor.descriptor
    locator = FactorLocator.model_validate(descriptor.locator.model_dump(mode="python"))
    logical_id = _opaque_id(
        "lf",
        {
            "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
            "namespace": proof.namespace.digest,
            "profile": profile.handle.handle_id,
            "locator": locator,
            "slot_schema": descriptor.slot_schema_commitment,
        },
    )
    slot_id = _opaque_id(
        "slot",
        {
            "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
            "profile": profile.handle.handle_id,
            "locator": locator.path,
            "slot_schema": descriptor.slot_schema_commitment,
        },
    )
    lineage_required = bool(
        is_changed_target
        and action_bound
        and proof.branch in {"mutate", "fresh"}
    )
    return slot_id, _FactorTemplate(
        revision_id=factor.handle.handle_id,
        logical_factor_id=logical_id,
        namespace=proof.namespace,
        carrier="phase_program",
        locator=locator,
        binding_status="proven_factorized",
        content_sha256=factor.factor_content_commitment,
        parent_revision_id=(
            source_changed_revision_id
            if is_changed_target and action_bound and proof.branch == "mutate"
            else None
        ),
        origin_branch=(
            proof.branch
            if is_changed_target
            and action_bound
            and proof.branch in {"mutate", "fresh"}
            else "migration"
        ),
        lineage_required=lineage_required,
    )


def _factor_matches(template: _FactorTemplate, record: FactorRevisionV2) -> bool:
    expected = template.build(created_seq=record.created_seq).model_copy(
        update={"structural_state": record.structural_state}
    )
    if not template.lineage_required:
        expected = expected.model_copy(
            update={
                "parent_revision_id": record.parent_revision_id,
                "origin_branch": record.origin_branch,
            }
        )
    return record == expected


def _composition_matches(
    template: _CompositionTemplate,
    record: CompositionRevisionV2,
) -> bool:
    expected = template.build(created_seq=record.created_seq).model_copy(
        update={"structural_state": record.structural_state}
    )
    if not template.lineage_required:
        expected = expected.model_copy(
            update={
                "parent_composition_id": record.parent_composition_id,
                "origin_branch": record.origin_branch,
            }
        )
    return record == expected


def _canonical_bundle_v3(
    registry: PhaseArtifactRegistry,
    proof_handle: PhaseBindingProofHandle,
) -> _CanonicalFullPhaseBundle:
    proof = registry.verify_phase_materialization_proof(proof_handle).proof
    if proof.namespace.binder_version != PHASE_FULL_FACTOR_BINDER_VERSION:
        raise ValueError("full-v3 adapter rejects a non-v3 Phase proof")
    action_id, _action_intent = _proof_action_binding(registry, proof)
    action_bound = action_id is not None
    source_artifact = registry.resolve_artifact(proof.source_artifact)
    target_artifact = registry.resolve_artifact(proof.target_artifact)
    source_profile = _profile_for_artifact(registry, source_artifact)
    target_profile = _profile_for_artifact(registry, target_artifact)
    if source_profile != target_profile or proof.runtime_profile != source_profile.handle:
        raise ValueError("full Phase proof crosses its exact runtime profile")

    source_raw = source_artifact.program.model_dump(mode="json")
    target_raw = target_artifact.program.model_dump(mode="json")
    differences = _leaf_differences(source_raw, target_raw)
    expected_path = proof.descriptor.locator.path
    if len(differences) != 1 or _pointer(differences[0][0]) != expected_path:
        raise ValueError("full Phase proof is not exactly one scalar-leaf delta")
    source_paths = phase_mutable_factor_paths_v3(source_artifact.program)
    target_paths = phase_mutable_factor_paths_v3(target_artifact.program)
    if source_paths != target_paths or expected_path not in source_paths:
        raise ValueError("full Phase delta changes its canonical scalar domain")

    source_records = _registry_factors_for_artifact(
        registry,
        artifact=source_artifact,
        profile=source_profile,
        paths=source_paths,
    )
    target_records = _registry_factors_for_artifact(
        registry,
        artifact=target_artifact,
        profile=target_profile,
        paths=target_paths,
    )
    record_by_source_path = dict(zip(source_paths, source_records))
    record_by_target_path = dict(zip(target_paths, target_records))
    if record_by_source_path[expected_path].handle != proof.source_factor:
        raise ValueError("full Phase source factor differs from the proof locus")
    if record_by_target_path[expected_path].handle != proof.target_factor:
        raise ValueError("full Phase target factor differs from the proof locus")

    source_templates: list[_FactorTemplate] = []
    target_templates: list[_FactorTemplate] = []
    source_bindings: list[SlotBinding] = []
    target_bindings: list[SlotBinding] = []
    changed_slot_id: str | None = None
    source_changed_revision_id = proof.source_factor.handle_id
    for path, source_record, target_record in zip(
        source_paths,
        source_records,
        target_records,
    ):
        source_slot, source_template = _scalar_template(
            proof=proof,
            profile=source_profile,
            factor=source_record,
            is_changed_target=False,
            source_changed_revision_id=source_changed_revision_id,
            action_bound=action_bound,
        )
        target_slot, target_template = _scalar_template(
            proof=proof,
            profile=source_profile,
            factor=target_record,
            is_changed_target=path == expected_path,
            source_changed_revision_id=source_changed_revision_id,
            action_bound=action_bound,
        )
        if source_slot != target_slot:
            raise ValueError("full Phase source and target slots differ")
        if path != expected_path and source_template != target_template:
            raise ValueError("full Phase proof changed an unselected factor")
        if path == expected_path:
            if source_template.revision_id == target_template.revision_id:
                raise ValueError("full Phase selected factor did not change")
            changed_slot_id = source_slot
        source_templates.append(source_template)
        target_templates.append(target_template)
        source_bindings.append(
            SlotBinding(
                slot_id=source_slot,
                factor_revision_id=source_template.revision_id,
            )
        )
        target_bindings.append(
            SlotBinding(
                slot_id=target_slot,
                factor_revision_id=target_template.revision_id,
            )
        )
    if changed_slot_id is None:
        raise RuntimeError("full Phase bundle lost its changed slot")

    source_skeleton = _structural_skeleton(source_artifact, source_profile, source_paths)
    target_skeleton = _structural_skeleton(target_artifact, target_profile, target_paths)
    if source_skeleton != target_skeleton:
        raise ValueError("full Phase transition changed its locked structure")
    skeleton_sha256 = _sha256(source_skeleton)
    structural_factor = _FactorTemplate(
        revision_id=_opaque_id(
            "psk",
            {
                "namespace": proof.namespace.digest,
                "profile": source_profile.handle.handle_id,
                "skeleton": skeleton_sha256,
            },
        ),
        logical_factor_id=_opaque_id(
            "lsk",
            {
                "namespace": proof.namespace.digest,
                "profile": source_profile.handle.handle_id,
                "version": PHASE_FULL_FACTOR_SKELETON_VERSION,
            },
        ),
        namespace=proof.namespace,
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
    source_bindings.append(
        SlotBinding(
            slot_id=PHASE_FULL_FACTOR_SKELETON_SLOT_ID,
            factor_revision_id=structural_factor.revision_id,
        )
    )
    target_bindings.append(
        SlotBinding(
            slot_id=PHASE_FULL_FACTOR_SKELETON_SLOT_ID,
            factor_revision_id=structural_factor.revision_id,
        )
    )
    canonical_source_bindings = tuple(sorted(source_bindings, key=lambda item: item.slot_id))
    canonical_target_bindings = tuple(sorted(target_bindings, key=lambda item: item.slot_id))

    def composition_template(
        artifact: PhaseProgramArtifactRecord,
        bindings: tuple[SlotBinding, ...],
        *,
        is_target: bool,
    ) -> _CompositionTemplate:
        identity = {
            "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
            "namespace": proof.namespace.digest,
            "artifact": artifact.handle.handle_id,
            "execution_image": artifact.execution_image_commitment,
            "bindings": bindings,
        }
        metadata = {
            "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
            "artifact_revision_id": artifact.handle.handle_id,
            "execution_image_commitment": artifact.execution_image_commitment,
            "bindings": bindings,
        }
        source_identity = {
            "binder": PHASE_FULL_FACTOR_BINDER_VERSION,
            "namespace": proof.namespace.digest,
            "artifact": source_artifact.handle.handle_id,
            "execution_image": source_artifact.execution_image_commitment,
            "bindings": canonical_source_bindings,
        }
        lineage_required = bool(
            action_bound and is_target and proof.branch in {"mutate", "fresh"}
        )
        return _CompositionTemplate(
            composition_id=_opaque_id("pc", identity),
            namespace=proof.namespace,
            artifact_revision_id=artifact.handle.handle_id,
            artifact_sha256=artifact.execution_image_commitment,
            bindings=bindings,
            canonical_metadata_bytes=len(_canonical_json(metadata).encode("utf-8")),
            artifact_bytes=len(_canonical_json(artifact.program).encode("utf-8")),
            parent_composition_id=(
                _opaque_id("pc", source_identity) if lineage_required else None
            ),
            origin_branch=(proof.branch if lineage_required else "migration"),
            lineage_required=lineage_required,
        )

    source_composition = composition_template(
        source_artifact,
        canonical_source_bindings,
        is_target=False,
    )
    target_composition = composition_template(
        target_artifact,
        canonical_target_bindings,
        is_target=True,
    )
    source_index = source_paths.index(expected_path)
    return _CanonicalFullPhaseBundle(
        proof=proof,
        structural_factor=structural_factor,
        source_scalar_factors=tuple(source_templates),
        target_scalar_factors=tuple(target_templates),
        source_factor=source_templates[source_index],
        target_factor=target_templates[source_index],
        source_composition=source_composition,
        target_composition=target_composition,
        changed_slot_id=changed_slot_id,
    )


def make_phase_v3_binding_verifier(
    registry: PhaseArtifactRegistry,
) -> Callable[..., bool]:
    """Return the exact complete-composition verifier for full-v3 rows."""

    def verify(
        transition: DirectFactorTransitionV2,
        source: CompositionRevisionV2,
        target: CompositionRevisionV2,
        old: FactorRevisionV2,
        new: FactorRevisionV2,
        background: tuple[FactorRevisionV2, ...],
    ) -> bool:
        proof_record = next(
            (
                item
                for item in registry.to_state().proofs
                if item.handle.handle_id == transition.binding_proof_id
            ),
            None,
        )
        if proof_record is None:
            return False
        try:
            bundle = _canonical_bundle_v3(registry, proof_record.handle)
            action_id, action_intent = _proof_action_binding(registry, bundle.proof)
        except (ValueError, RuntimeError):
            return False
        expected_background = {
            item.factor_revision_id
            for item in bundle.source_composition.bindings
            if item.slot_id != bundle.changed_slot_id
        }
        actual_background = {item.revision_id for item in background}
        expected_fixed = _sha256(
            [
                (item.slot_id, item.factor_revision_id)
                for item in bundle.source_composition.bindings
                if item.slot_id != bundle.changed_slot_id
            ]
        )
        template_by_id = {
            item.revision_id: item for item in bundle.all_factor_templates
        }
        return bool(
            transition.binding_proof_sha256 == bundle.proof.handle.proof_sha256
            and transition.binding_verifier_epoch == PHASE_FACTOR_BANK_V3_VERIFIER_EPOCH
            and transition.origin_branch == bundle.proof.branch
            and transition.proposal_action_id == action_id
            and transition.proposal_action_intent_sha256 == action_intent
            and transition.namespace == bundle.proof.namespace
            and transition.source_composition_id == bundle.source_composition.composition_id
            and transition.target_composition_id == bundle.target_composition.composition_id
            and transition.slot_id == bundle.changed_slot_id
            and transition.from_revision_id == bundle.source_factor.revision_id
            and transition.to_revision_id == bundle.target_factor.revision_id
            and transition.fixed_background_sha256 == expected_fixed
            and transition.masked_background_sha256
            == bundle.proof.masked_background_commitment
            and _factor_matches(bundle.source_factor, old)
            and _factor_matches(bundle.target_factor, new)
            and len(background) == len(expected_background)
            and actual_background == expected_background
            and all(
                revision_id in template_by_id
                and _factor_matches(template_by_id[revision_id], record)
                for revision_id, record in (
                    (item.revision_id, item) for item in background
                )
            )
            and _composition_matches(bundle.source_composition, source)
            and _composition_matches(bundle.target_composition, target)
        )

    return verify


def _canonical_repair_source_logical_ids_v3(
    registry: PhaseArtifactRegistry,
    composition: CompositionRevisionV2,
) -> tuple[str, ...]:
    state = registry.to_state()
    candidates = [
        item
        for item in state.proofs
        if item.namespace.digest == composition.namespace.digest
        and (
            item.source_artifact.handle_id == composition.artifact_revision_id
            or item.target_artifact is not None
            and item.target_artifact.handle_id == composition.artifact_revision_id
        )
    ]
    logical_ids: set[str] = set()
    for proof in candidates:
        try:
            bundle = _canonical_bundle_v3(registry, proof.handle)
        except (ValueError, RuntimeError):
            continue
        for template, factors in (
            (bundle.source_composition, bundle.source_scalar_factors),
            (bundle.target_composition, bundle.target_scalar_factors),
        ):
            expected = template.build(created_seq=composition.created_seq).model_copy(
                update={"structural_state": composition.structural_state}
            )
            if composition == expected:
                logical_ids.update(item.logical_factor_id for item in factors)
    return tuple(sorted(logical_ids))


def make_phase_v3_repair_opportunity_verifier(
    registry: PhaseArtifactRegistry,
    *,
    supported_branches: tuple[Literal["reuse", "mutate", "fresh"], ...] = (
        "reuse",
        "mutate",
        "fresh",
    ),
) -> Callable[[RepairOpportunityV2, FailureObservationV2, CompositionRevisionV2], bool]:
    canonical = ("reuse", "mutate", "fresh")
    if supported_branches != tuple(
        branch for branch in canonical if branch in supported_branches
    ) or not supported_branches:
        raise ValueError("supported Phase branches must be a canonical non-empty subset")

    def verify(
        opportunity: RepairOpportunityV2,
        failure: FailureObservationV2,
        composition: CompositionRevisionV2,
    ) -> bool:
        logical_ids = _canonical_repair_source_logical_ids_v3(
            registry,
            composition,
        )
        return bool(
            composition.namespace.binder_version == PHASE_FULL_FACTOR_BINDER_VERSION
            and composition.namespace.payload_format == "phase_program_skill_v1"
            and composition.carrier == "phase_program"
            and bool(logical_ids)
            and opportunity.source_composition_id == composition.composition_id
            and opportunity.namespace_digest == composition.namespace.digest
            and failure.composition_id == composition.composition_id
            and failure.artifact_sha256 == composition.artifact_sha256
            and opportunity.host_allowed_locator_ids == logical_ids
            and opportunity.feasible_branches
            == tuple(
                branch
                for branch in supported_branches
                if branch in opportunity.feasible_branches
            )
        )

    return verify


def make_phase_v3_arm_receipt_verifier(
    registry: PhaseArtifactRegistry,
    *,
    trusted_runner_verifier: Callable[
        [ArmReceiptV2, PhaseMaterializationProofRecord], bool
    ],
) -> Callable[[ArmReceiptV2, ProbePlanV2, Any], bool]:
    """Join runner evidence to a full-v3 proof and its changed factor only."""

    if not callable(trusted_runner_verifier):
        raise TypeError("trusted_runner_verifier must be a host capability")

    def verify(receipt: ArmReceiptV2, plan: ProbePlanV2, assignment: Any) -> bool:
        proof_record = next(
            (
                item
                for item in registry.to_state().proofs
                if item.handle.handle_id == receipt.binding_proof_id
            ),
            None,
        )
        if proof_record is None:
            return False
        try:
            bundle = _canonical_bundle_v3(registry, proof_record.handle)
        except (ValueError, RuntimeError):
            return False
        proof = bundle.proof
        template = (
            bundle.source_composition
            if receipt.arm == "source"
            else bundle.target_composition
        )
        activated = (
            bundle.source_factor.revision_id
            if receipt.arm == "source"
            else bundle.target_factor.revision_id
        )
        expected_position = (
            0
            if (
                (assignment.arm_order == "AB" and receipt.arm == "source")
                or (assignment.arm_order == "BA" and receipt.arm == "target")
            )
            else 1
        )
        artifact = (
            registry.resolve_artifact(proof.source_artifact)
            if receipt.arm == "source"
            else registry.resolve_artifact(proof.target_artifact)
        )
        if not all(
            (
                plan.owner_kind == "direct_factor",
                plan.binding_or_operation_proof_sha256 == proof.handle.proof_sha256,
                plan.namespace_digest == proof.namespace.digest,
                receipt.composition_id == template.composition_id,
                receipt.runtime_profile_id == proof.runtime_profile.handle_id,
                receipt.materialization_event_id == proof.event.handle_id,
                receipt.binding_proof_id == proof.handle.handle_id,
                receipt.observed_arm_order == assignment.arm_order,
                receipt.arm_position == expected_position,
                receipt.assigned_artifact_sha256 == artifact.execution_image_commitment,
                receipt.materialized_artifact_sha256 == artifact.execution_image_commitment,
                receipt.selected_artifact_sha256 == artifact.execution_image_commitment,
                receipt.loaded_artifact_sha256 == artifact.execution_image_commitment,
                receipt.activated_direct_factor_revision_ids == (activated,),
            )
        ):
            return False
        try:
            return bool(trusted_runner_verifier(receipt, proof))
        except Exception:
            return False

    return verify


def make_registered_phase_arm_receipt_v3(
    *,
    registry: PhaseArtifactRegistry,
    registered: RegisteredPhaseFactorEdgeV3,
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
    proof = registry.resolve_proof(registered.proof)
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
        runtime_profile_id=proof.runtime_profile.handle_id,
        materialization_event_id=proof.event.handle_id,
        activation_trace_root=activation_trace_root,
        usage=usage,
        execution_class=execution_class,
        outcome=outcome,
        producer_epoch=producer_epoch,
        attestation_sha256=attestation_sha256,
        safe_failure_code=safe_failure_code,
        failed_stage_rank=failed_stage_rank,
    )


def _registered_edge(
    bank: FactorBankV2,
    bundle: _CanonicalFullPhaseBundle,
    transition: DirectFactorTransitionV2,
) -> RegisteredPhaseFactorEdgeV3:
    source_factors = tuple(
        bank.factors[item.revision_id] for item in bundle.source_scalar_factors
    )
    target_factors = tuple(
        bank.factors[item.revision_id] for item in bundle.target_scalar_factors
    )
    return RegisteredPhaseFactorEdgeV3(
        proof=bundle.proof.handle,
        structural_factor=bank.factors[bundle.structural_factor.revision_id],
        source_scalar_factors=source_factors,
        target_scalar_factors=target_factors,
        source_factor=bank.factors[bundle.source_factor.revision_id],
        target_factor=bank.factors[bundle.target_factor.revision_id],
        source_composition=bank.compositions[
            bundle.source_composition.composition_id
        ],
        target_composition=bank.compositions[
            bundle.target_composition.composition_id
        ],
        transition=transition,
    )


def register_phase_materialization_v3(
    *,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    proof: PhaseBindingProofHandle,
) -> RegisteredPhaseFactorEdgeV3:
    """Atomically project one proof into a canonical full-factor Bank edge."""

    verified = registry.resolve_proof(proof)
    registry.extract_full_factorizations_v3(
        (verified.source_artifact, verified.target_artifact)
    )
    bundle = _canonical_bundle_v3(registry, proof)
    action_id, action_intent = _proof_action_binding(registry, bundle.proof)
    existing_edges = [
        item
        for item in bank.direct_transitions.values()
        if item.binding_proof_id == bundle.proof.handle.handle_id
    ]
    if existing_edges:
        if len(existing_edges) != 1:
            raise ValueError("one Phase proof owns multiple FactorBank edges")
        transition = existing_edges[0]
        if any(
            item.revision_id not in bank.factors
            for item in bundle.all_factor_templates
        ) or any(
            item.composition_id not in bank.compositions
            for item in (bundle.source_composition, bundle.target_composition)
        ):
            raise ValueError("persisted full Phase edge lost its canonical bundle")
        if not all(
            _factor_matches(item, bank.factors[item.revision_id])
            for item in bundle.all_factor_templates
        ) or not all(
            _composition_matches(item, bank.compositions[item.composition_id])
            for item in (bundle.source_composition, bundle.target_composition)
        ):
            raise ValueError("persisted full Phase rows differ from their proof")
        if not (
            transition.namespace == bundle.proof.namespace
            and transition.source_composition_id
            == bundle.source_composition.composition_id
            and transition.target_composition_id
            == bundle.target_composition.composition_id
            and transition.slot_id == bundle.changed_slot_id
            and transition.from_revision_id == bundle.source_factor.revision_id
            and transition.to_revision_id == bundle.target_factor.revision_id
            and transition.masked_background_sha256
            == bundle.proof.masked_background_commitment
            and transition.binding_proof_sha256
            == bundle.proof.handle.proof_sha256
            and transition.binding_verifier_epoch
            == PHASE_FACTOR_BANK_V3_VERIFIER_EPOCH
            and transition.origin_branch == bundle.proof.branch
            and transition.proposal_action_id == action_id
            and transition.proposal_action_intent_sha256 == action_intent
        ):
            raise ValueError("persisted full Phase edge differs from its proof")
        return _registered_edge(bank, bundle, transition)

    next_seq = bank.to_state().event_seq
    new_factors: list[FactorRevisionV2] = []
    for template in bundle.all_factor_templates:
        existing = bank.factors.get(template.revision_id)
        if existing is not None:
            if not _factor_matches(template, existing):
                raise ValueError("existing Bank factor differs from full Phase projection")
            continue
        next_seq += 1
        new_factors.append(template.build(created_seq=next_seq))
    new_compositions: list[CompositionRevisionV2] = []
    for template in (bundle.source_composition, bundle.target_composition):
        existing = bank.compositions.get(template.composition_id)
        if existing is not None:
            if not _composition_matches(template, existing):
                raise ValueError(
                    "existing Bank composition differs from full Phase projection"
                )
            continue
        next_seq += 1
        new_compositions.append(template.build(created_seq=next_seq))
    transition = bank.register_direct_bundle(
        factors=tuple(new_factors),
        compositions=tuple(new_compositions),
        transition_fields={
            "source_composition_id": bundle.source_composition.composition_id,
            "target_composition_id": bundle.target_composition.composition_id,
            "slot_id": bundle.changed_slot_id,
            "binding_proof_id": bundle.proof.handle.handle_id,
            "binding_proof_sha256": bundle.proof.handle.proof_sha256,
            "masked_background_sha256": bundle.proof.masked_background_commitment,
            "binding_verifier_epoch": PHASE_FACTOR_BANK_V3_VERIFIER_EPOCH,
            "origin_branch": bundle.proof.branch,
            "proposal_action_id": action_id,
            "proposal_action_intent_sha256": action_intent,
        },
    )
    return _registered_edge(bank, bundle, transition)


def make_phase_v3_proposal_action_terminal_verifier(
    registry: PhaseArtifactRegistry,
) -> Callable[
    [ProposalActionV2, DirectFactorTransitionV2, FactorBankStateV2],
    bool,
]:
    """Return the terminal verifier for explicit full-factor-v3 namespaces."""

    return _make_phase_proposal_action_terminal_verifier(
        registry,
        expected_binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
    )


def reconcile_phase_proposal_action_v3(
    *,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    action_id: str,
    generation_terminal: PhaseGenerationTerminalV1 | None = None,
    generated_value: Any = _MISSING_GENERATED_VALUE,
    ingress: Any | None = None,
    noop_abort_receipt: ProposalActionAbortReceiptV2 | None = None,
    terminal_abort_receipt: ProposalActionAbortReceiptV2 | None = None,
) -> (
    RegisteredPhaseFactorEdgeV3
    | NoOpMaterialization
    | AbortedPhaseProposalActionV2
):
    """Execute one action under the complete full-factor-v3 representation.

    The shared transaction choreography remains version-neutral, while this
    wrapper fixes both the admitted binder and the projection adapter.  A v2
    source can therefore never reach the v3 registrar (or vice versa).
    """

    return _reconcile_phase_proposal_action_versioned(
        registry=registry,
        bank=bank,
        expected_binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
        register_materialization=register_phase_materialization_v3,
        action_id=action_id,
        generation_terminal=generation_terminal,
        generated_value=generated_value,
        ingress=ingress,
        noop_abort_receipt=noop_abort_receipt,
        terminal_abort_receipt=terminal_abort_receipt,
    )


__all__ = [
    "PHASE_FACTOR_BANK_V3_VERIFIER_EPOCH",
    "PHASE_FULL_FACTOR_SKELETON_SLOT_ID",
    "PHASE_FULL_FACTOR_SKELETON_VERSION",
    "RegisteredPhaseFactorEdgeV3",
    "make_phase_v3_arm_receipt_verifier",
    "make_phase_v3_binding_verifier",
    "make_phase_v3_proposal_action_terminal_verifier",
    "make_phase_v3_repair_opportunity_verifier",
    "make_registered_phase_arm_receipt_v3",
    "reconcile_phase_proposal_action_v3",
    "register_phase_materialization_v3",
]
