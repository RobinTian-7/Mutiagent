"""FactorBank adapter for registry-verified PhaseProgram interventions.

The old prototype accepted two complete caller-provided programs plus caller
strings for artifact identity and TRAIN provenance.  That boundary was not a
proof.  The only public binding path now consumes a registry-backed proof
handle: the registry has already sealed the branch, materialized one typed
value, rebuilt both execution images, and verified provenance and identity.

This adapter contains no semantic judgement and no raw program/value.  It maps
one verified materialization to immutable FactorBank content records.  Branch
and lineage remain properties of the directed transition event, never of the
factor content identity, so B is the same factor in A->B and B->C.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from exp_graph.mas.factor_bank import (
    CompositionRevision,
    FactorLocator,
    FactorRevision,
    SlotBinding,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _opaque_id(prefix: str, value: Any) -> str:
    return f"{prefix}:{_sha256(value)[:24]}"


class PhaseFactorizedPair(BaseModel):
    """Bank-visible records for one registry-proved PhaseProgram edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proof: PhaseBindingProofHandle
    origin_branch: Literal["reuse", "mutate", "fresh"]
    background_factor: FactorRevision
    source_factor: FactorRevision
    target_factor: FactorRevision
    source_composition: CompositionRevision
    target_composition: CompositionRevision
    changed_slot_id: str
    masked_background_sha256: str


def bind_registered_phase_materialization(
    registry: PhaseArtifactRegistry,
    proof: PhaseBindingProofHandle,
) -> PhaseFactorizedPair:
    """Map one verified registry proof into content-only FactorBank records.

    No caller supplies programs, manifests, artifact IDs, locators, limits, or
    branch labels.  Every one of those joins is resolved from the proof and
    independently recomputed by ``verify_phase_materialization_proof``.
    """

    verified = registry.verify_phase_materialization_proof(proof)
    record = verified.proof
    source_artifact = registry.resolve_artifact(record.source_artifact)
    target_artifact = registry.resolve_artifact(record.target_artifact)
    source_content = registry.resolve_factor(record.source_factor)
    target_content = registry.resolve_factor(record.target_factor)

    locator = FactorLocator.model_validate(
        record.descriptor.locator.model_dump(mode="python")
    )
    logical_factor_id = _opaque_id(
        "lf",
        {
            "namespace": record.namespace.digest,
            "profile": record.runtime_profile.handle_id,
            "locator": locator,
            "slot_schema": record.descriptor.slot_schema_commitment,
        },
    )
    # Factor content is canonical and path-independent.  ``origin_branch`` and
    # parent fields are neutral here; the proof/transition event owns them.
    source_factor = FactorRevision(
        revision_id=record.source_factor.handle_id,
        logical_factor_id=logical_factor_id,
        namespace=record.namespace,
        carrier="phase_program",
        locator=locator,
        binding_status="proven_factorized",
        content_sha256=source_content.factor_content_commitment,
        origin_branch="migration",
    )
    target_factor = FactorRevision(
        revision_id=record.target_factor.handle_id,
        logical_factor_id=logical_factor_id,
        namespace=record.namespace,
        carrier="phase_program",
        locator=locator,
        binding_status="proven_factorized",
        content_sha256=target_content.factor_content_commitment,
        origin_branch="migration",
    )
    changed_slot_id = _opaque_id(
        "slot",
        {
            "profile": record.runtime_profile.handle_id,
            "locator": locator.path,
            "schema": record.descriptor.slot_schema_commitment,
        },
    )
    background_factor_id = _opaque_id(
        "bg",
        {
            "namespace": record.namespace.digest,
            "profile": record.runtime_profile.handle_id,
            "slot": changed_slot_id,
            "masked": record.masked_background_commitment,
        },
    )
    background_factor = FactorRevision(
        revision_id=background_factor_id,
        logical_factor_id=_opaque_id(
            "lbg",
            {
                "namespace": record.namespace.digest,
                "profile": record.runtime_profile.handle_id,
                "slot": changed_slot_id,
            },
        ),
        namespace=record.namespace,
        carrier="constraint",
        locator=FactorLocator(
            surface="atomic_artifact",
            path=f"/fixed_background/{changed_slot_id}",
            locator_version=PHASE_FACTOR_BINDER_VERSION,
        ),
        binding_status="locked_atomic",
        content_sha256=record.masked_background_commitment,
        origin_branch="migration",
    )
    source_bindings = (
        SlotBinding(
            slot_id="fixed_background",
            factor_revision_id=background_factor.revision_id,
        ),
        SlotBinding(
            slot_id=changed_slot_id,
            factor_revision_id=source_factor.revision_id,
        ),
    )
    target_bindings = (
        SlotBinding(
            slot_id="fixed_background",
            factor_revision_id=background_factor.revision_id,
        ),
        SlotBinding(
            slot_id=changed_slot_id,
            factor_revision_id=target_factor.revision_id,
        ),
    )
    source_composition_id = _opaque_id(
        "pc",
        {
            "namespace": record.namespace.digest,
            "artifact": source_artifact.handle.handle_id,
            "execution_image": source_artifact.execution_image_commitment,
            "bindings": source_bindings,
        },
    )
    target_composition_id = _opaque_id(
        "pc",
        {
            "namespace": record.namespace.digest,
            "artifact": target_artifact.handle.handle_id,
            "execution_image": target_artifact.execution_image_commitment,
            "bindings": target_bindings,
        },
    )
    source_composition = CompositionRevision(
        composition_id=source_composition_id,
        namespace=record.namespace,
        carrier="phase_program",
        artifact_revision_id=source_artifact.handle.handle_id,
        # Runtime receipts bind the actual loader execution image, not merely
        # the source-program digest.
        artifact_sha256=source_artifact.execution_image_commitment,
        bindings=source_bindings,
        origin_branch="migration",
    )
    target_composition = CompositionRevision(
        composition_id=target_composition_id,
        namespace=record.namespace,
        carrier="phase_program",
        artifact_revision_id=target_artifact.handle.handle_id,
        artifact_sha256=target_artifact.execution_image_commitment,
        bindings=target_bindings,
        origin_branch="migration",
    )
    return PhaseFactorizedPair(
        proof=record.handle,
        origin_branch=record.branch,
        background_factor=background_factor,
        source_factor=source_factor,
        target_factor=target_factor,
        source_composition=source_composition,
        target_composition=target_composition,
        changed_slot_id=changed_slot_id,
        masked_background_sha256=record.masked_background_commitment,
    )


__all__ = [
    "PHASE_FACTOR_BINDER_VERSION",
    "PhaseFactorizedPair",
    "bind_registered_phase_materialization",
]
