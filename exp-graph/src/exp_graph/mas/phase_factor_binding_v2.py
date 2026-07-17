"""Canonical PhaseArtifactRegistry adapter for the SFT FactorBankV2.

The registry proof is the only authority.  This module deterministically
projects that proof into the complete Bank bundle and supplies the verifier
that FactorBankV2 calls both at registration and on every persisted-state
load.  Callers cannot choose logical IDs, background content, composition IDs,
branch labels, or artifact commitments.
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
    FactorContentHandle,
    NoOpMaterialization,
    PHASE_FACTOR_BINDER_VERSION,
    PhaseArtifactHandle,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    PhaseGenerationTerminalV1,
    PhaseMaterializationProofRecord,
    phase_materialization_event_sha256_v1,
)


PHASE_FACTOR_BANK_V2_VERIFIER_EPOCH = "facts-phase-v2:1"
_MISSING_GENERATED_VALUE = object()


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
class _CanonicalPhaseBundle:
    proof: PhaseMaterializationProofRecord
    background: _FactorTemplate
    source_factor: _FactorTemplate
    target_factor: _FactorTemplate
    source_composition: _CompositionTemplate
    target_composition: _CompositionTemplate
    changed_slot_id: str


class RegisteredPhaseFactorEdgeV2(BaseModel):
    """The immutable records installed for one registry-proved directed edge."""

    model_config = {"extra": "forbid", "frozen": True}

    proof: PhaseBindingProofHandle
    background_factor: FactorRevisionV2
    source_factor: FactorRevisionV2
    target_factor: FactorRevisionV2
    source_composition: CompositionRevisionV2
    target_composition: CompositionRevisionV2
    transition: DirectFactorTransitionV2


class AbortedPhaseProposalActionV2(BaseModel):
    """Typed terminal for an exact rejected Phase proof and Bank cleanup."""

    model_config = {"extra": "forbid", "frozen": True}

    action: ProposalActionV2
    phase_terminal_sha256: str


def _canonical_bundle(
    registry: PhaseArtifactRegistry,
    proof_handle: PhaseBindingProofHandle,
) -> _CanonicalPhaseBundle:
    proof = registry.verify_phase_materialization_proof(proof_handle).proof
    if proof.namespace.binder_version != PHASE_FACTOR_BINDER_VERSION:
        raise ValueError("leaf-v2 adapter rejects a non-v2 Phase profile")
    proof_action_id, _proof_action_intent_sha256 = _proof_action_binding(
        registry,
        proof,
    )
    action_bound = proof_action_id is not None
    source_artifact = registry.resolve_artifact(proof.source_artifact)
    target_artifact = registry.resolve_artifact(proof.target_artifact)
    source_content = registry.resolve_factor(proof.source_factor)
    target_content = registry.resolve_factor(proof.target_factor)
    locator = FactorLocator.model_validate(
        proof.descriptor.locator.model_dump(mode="python")
    )
    logical_factor_id = _opaque_id(
        "lf",
        {
            "namespace": proof.namespace.digest,
            "profile": proof.runtime_profile.handle_id,
            "locator": locator,
            "slot_schema": proof.descriptor.slot_schema_commitment,
        },
    )
    changed_slot_id = _opaque_id(
        "slot",
        {
            "profile": proof.runtime_profile.handle_id,
            "locator": locator.path,
            "slot_schema": proof.descriptor.slot_schema_commitment,
        },
    )
    background_revision_id = _opaque_id(
        "bg",
        {
            "namespace": proof.namespace.digest,
            "profile": proof.runtime_profile.handle_id,
            "slot": changed_slot_id,
            "masked": proof.masked_background_commitment,
        },
    )
    source_factor = _FactorTemplate(
        revision_id=proof.source_factor.handle_id,
        logical_factor_id=logical_factor_id,
        namespace=proof.namespace,
        carrier="phase_program",
        locator=locator,
        binding_status="proven_factorized",
        content_sha256=source_content.factor_content_commitment,
        parent_revision_id=None,
        origin_branch="migration",
        lineage_required=False,
    )
    target_factor = _FactorTemplate(
        revision_id=proof.target_factor.handle_id,
        logical_factor_id=logical_factor_id,
        namespace=proof.namespace,
        carrier="phase_program",
        locator=locator,
        binding_status="proven_factorized",
        content_sha256=target_content.factor_content_commitment,
        parent_revision_id=(
            source_factor.revision_id
            if action_bound and proof.branch == "mutate"
            else None
        ),
        origin_branch=(
            proof.branch
            if action_bound and proof.branch in {"mutate", "fresh"}
            else "migration"
        ),
        lineage_required=action_bound and proof.branch in {"mutate", "fresh"},
    )
    background = _FactorTemplate(
        revision_id=background_revision_id,
        logical_factor_id=_opaque_id(
            "lbg",
            {
                "namespace": proof.namespace.digest,
                "profile": proof.runtime_profile.handle_id,
                "slot": changed_slot_id,
            },
        ),
        namespace=proof.namespace,
        carrier="constraint",
        locator=FactorLocator(
            surface="atomic_artifact",
            path=f"/fixed_background/{changed_slot_id}",
            locator_version=PHASE_FACTOR_BINDER_VERSION,
        ),
        binding_status="locked_atomic",
        content_sha256=proof.masked_background_commitment,
        parent_revision_id=None,
        origin_branch="migration",
        lineage_required=True,
    )
    source_bindings = (
        SlotBinding(
            slot_id="fixed_background",
            factor_revision_id=background.revision_id,
        ),
        SlotBinding(
            slot_id=changed_slot_id,
            factor_revision_id=source_factor.revision_id,
        ),
    )
    target_bindings = (
        SlotBinding(
            slot_id="fixed_background",
            factor_revision_id=background.revision_id,
        ),
        SlotBinding(
            slot_id=changed_slot_id,
            factor_revision_id=target_factor.revision_id,
        ),
    )

    def composition_template(
        artifact: Any,
        bindings: tuple[SlotBinding, ...],
        *,
        is_target: bool,
    ) -> _CompositionTemplate:
        identity = {
            "namespace": proof.namespace.digest,
            "artifact": artifact.handle.handle_id,
            "execution_image": artifact.execution_image_commitment,
            "bindings": bindings,
        }
        metadata = {
            "artifact_revision_id": artifact.handle.handle_id,
            "execution_image_commitment": artifact.execution_image_commitment,
            "bindings": bindings,
        }
        return _CompositionTemplate(
            composition_id=_opaque_id("pc", identity),
            namespace=proof.namespace,
            artifact_revision_id=artifact.handle.handle_id,
            artifact_sha256=artifact.execution_image_commitment,
            bindings=bindings,
            canonical_metadata_bytes=len(_canonical_json(metadata).encode("utf-8")),
            artifact_bytes=len(_canonical_json(artifact.program).encode("utf-8")),
            parent_composition_id=(
                _opaque_id(
                    "pc",
                    {
                        "namespace": proof.namespace.digest,
                        "artifact": source_artifact.handle.handle_id,
                        "execution_image": (
                            source_artifact.execution_image_commitment
                        ),
                        "bindings": source_bindings,
                    },
                )
                if action_bound
                and is_target
                and proof.branch in {"mutate", "fresh"}
                else None
            ),
            origin_branch=(
                proof.branch
                if action_bound
                and is_target
                and proof.branch in {"mutate", "fresh"}
                else "migration"
            ),
            lineage_required=(
                action_bound
                and is_target
                and proof.branch in {"mutate", "fresh"}
            ),
        )

    return _CanonicalPhaseBundle(
        proof=proof,
        background=background,
        source_factor=source_factor,
        target_factor=target_factor,
        source_composition=composition_template(
            source_artifact,
            source_bindings,
            is_target=False,
        ),
        target_composition=composition_template(
            target_artifact,
            target_bindings,
            is_target=True,
        ),
        changed_slot_id=changed_slot_id,
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


def _canonical_repair_source_logical_ids(
    registry: PhaseArtifactRegistry,
    composition: CompositionRevisionV2,
) -> tuple[str, ...]:
    """Return registry-proved logical factors for one exact Bank composition.

    Registry artifact membership alone is not source authority.  A Bank row may
    otherwise reuse a real artifact handle/commitment while relabelling its
    execution namespace or replacing the canonical factor bindings.  Repair
    authority therefore requires all three layers to close simultaneously:

    * the artifact's authenticated runtime profile owns this exact namespace;
    * its handle and execution-image commitment equal the Bank artifact fields;
    * the complete Bank composition is a canonical source or target projected
      from a verified registry proof, including factor/background bindings and
      byte-accounting fields.

    The registry is mutable as generated actions commit, so this bounded scan is
    deliberately rebuilt from the current capacity-limited state instead of
    caching an index that would strand a newly admitted target.  Strict lineage
    comparison is safe here: a generated target is authorized by the proof that
    created it, even when a later proof also names it as a source.
    """

    state = registry.to_state()
    artifact_records = [
        item
        for item in state.artifacts
        if item.handle.handle_id == composition.artifact_revision_id
    ]
    if len(artifact_records) != 1:
        return ()
    try:
        artifact = registry.resolve_artifact(artifact_records[0].handle)
    except (ValueError, RuntimeError):
        return ()
    profile_records = [
        item for item in state.profiles if item.handle == artifact.runtime_profile
    ]
    if len(profile_records) != 1:
        return ()
    profile = profile_records[0]
    if not (
        artifact.handle.handle_id == composition.artifact_revision_id
        and artifact.execution_image_commitment == composition.artifact_sha256
        and profile.namespace == composition.namespace
    ):
        return ()

    logical_ids: set[str] = set()
    candidate_proofs = [
        item
        for item in state.proofs
        if item.runtime_profile == artifact.runtime_profile
        and (
            item.source_artifact == artifact.handle
            or item.target_artifact == artifact.handle
        )
    ]
    for proof_record in candidate_proofs:
        try:
            bundle = _canonical_bundle(registry, proof_record.handle)
        except (ValueError, RuntimeError):
            continue
        candidates = (
            (
                bundle.proof.source_artifact,
                bundle.proof.source_execution_image_commitment,
                bundle.source_composition,
                bundle.source_factor.logical_factor_id,
            ),
            (
                bundle.proof.target_artifact,
                bundle.proof.target_execution_image_commitment,
                bundle.target_composition,
                bundle.target_factor.logical_factor_id,
            ),
        )
        for handle, image_commitment, template, logical_factor_id in candidates:
            expected = template.build(created_seq=composition.created_seq).model_copy(
                update={"structural_state": composition.structural_state}
            )
            if (
                handle == artifact.handle
                and image_commitment == artifact.execution_image_commitment
                and bundle.proof.runtime_profile == artifact.runtime_profile
                and bundle.proof.namespace == profile.namespace
                and composition == expected
            ):
                logical_ids.add(logical_factor_id)
    return tuple(sorted(logical_ids))


def _proof_action_binding(
    registry: PhaseArtifactRegistry,
    proof: PhaseMaterializationProofRecord,
) -> tuple[str | None, str | None]:
    state = registry.to_state()
    seals = [item for item in state.seals if item.handle == proof.operation_seal]
    if len(seals) != 1:
        raise ValueError("Phase proof lacks one exact operation seal")
    receipts = [
        item
        for item in state.branch_receipts
        if item.handle == seals[0].branch_receipt
    ]
    if len(receipts) != 1:
        raise ValueError("Phase proof lacks one exact branch receipt")
    body = receipts[0].body
    return body.action_transaction_id, body.action_intent_sha256


def _action_phase_roots(
    action: ProposalActionV2,
    terminal: PhaseGenerationTerminalV1 | None,
) -> tuple[str, ...]:
    """Return the exact immutable plus post-START Phase input closure."""

    roots = set(action.exact_additional_input_root_commitments)
    if action.branch == "reuse":
        if terminal is not None:
            raise ValueError("reuse action cannot carry a generation terminal")
        return tuple(sorted(roots))
    request = action.generation_request
    lease = action.generation_lease
    if request is None or lease is None or lease.started_seq is None or terminal is None:
        raise ValueError("generated action lacks its request, lease, or terminal")
    roots.update({request.digest, lease.digest, terminal.digest})
    return tuple(sorted(roots))


def _generation_terminal_matches_action(
    action: ProposalActionV2,
    terminal: PhaseGenerationTerminalV1,
    *,
    require_bank_terminal: bool,
) -> bool:
    request = action.generation_request
    lease = action.generation_lease
    if request is None or lease is None or lease.started_seq is None:
        return False
    return bool(
        action.branch in {"mutate", "fresh"}
        and terminal.branch == action.branch
        and terminal.action_transaction_id == action.action_id
        and terminal.action_intent_sha256 == action.action_intent_sha256
        and terminal.generation_request_id == request.request_id
        and terminal.generation_request_sha256 == request.digest
        and terminal.generation_lease_id == lease.lease_id
        and terminal.generation_lease_sha256 == lease.digest
        and terminal.runner_lease_token_sha256
        == lease.runner_lease_token_sha256
        and terminal.fencing_generation == lease.fencing_generation
        and terminal.generation_lease_started_sequence == lease.started_seq
        and terminal.model_name == request.model_name
        and terminal.runtime_version == request.runtime_version
        and terminal.budget == request.budget
        and terminal.budget_sha256 == request.budget_sha256
        and (
            not require_bank_terminal
            or action.generation_terminal_sha256 == terminal.digest
        )
    )


def make_phase_v2_binding_verifier(
    registry: PhaseArtifactRegistry,
) -> Callable[..., bool]:
    """Return the complete canonical-bundle verifier required by FactorBankV2."""

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
            bundle = _canonical_bundle(registry, proof_record.handle)
            proof_action_id, proof_action_intent_sha256 = (
                _proof_action_binding(registry, bundle.proof)
            )
        except (ValueError, RuntimeError):
            return False
        proof = bundle.proof
        expected_fixed = _sha256(
            [("fixed_background", bundle.background.revision_id)]
        )
        return bool(
            transition.binding_proof_sha256 == proof.handle.proof_sha256
            and transition.binding_verifier_epoch == PHASE_FACTOR_BANK_V2_VERIFIER_EPOCH
            and transition.origin_branch == proof.branch
            and transition.proposal_action_id == proof_action_id
            and transition.proposal_action_intent_sha256
            == proof_action_intent_sha256
            and transition.namespace == proof.namespace
            and transition.source_composition_id == bundle.source_composition.composition_id
            and transition.target_composition_id == bundle.target_composition.composition_id
            and transition.slot_id == bundle.changed_slot_id
            and transition.from_revision_id == bundle.source_factor.revision_id
            and transition.to_revision_id == bundle.target_factor.revision_id
            and transition.fixed_background_sha256 == expected_fixed
            and transition.masked_background_sha256 == proof.masked_background_commitment
            and _factor_matches(bundle.source_factor, old)
            and _factor_matches(bundle.target_factor, new)
            and len(background) == 1
            and _factor_matches(bundle.background, background[0])
            and _composition_matches(bundle.source_composition, source)
            and _composition_matches(bundle.target_composition, target)
        )

    return verify


def _make_phase_proposal_action_terminal_verifier(
    registry: PhaseArtifactRegistry,
    *,
    expected_binder_version: str,
) -> Callable[
    [ProposalActionV2, DirectFactorTransitionV2, FactorBankStateV2],
    bool,
]:
    """Bind Bank finalization to one exact-version Phase action transaction.

    A structurally compatible, pre-existing Phase proof is insufficient.  The
    proof must descend from the unique branch receipt carrying this action's
    transaction id, intent digest, complete input-root closure, producer epoch,
    and host attestation.
    """

    def verify(
        action: ProposalActionV2,
        transition: DirectFactorTransitionV2,
        _state: FactorBankStateV2,
    ) -> bool:
        state = registry.to_state()
        proofs = [
            item
            for item in state.proofs
            if item.handle.handle_id == transition.binding_proof_id
            and item.handle.proof_sha256 == transition.binding_proof_sha256
        ]
        if len(proofs) != 1:
            return False
        proof = proofs[0]
        events = [
            item for item in state.events if item.handle == proof.event
        ]
        seals = [
            item for item in state.seals if item.handle == proof.operation_seal
        ]
        if len(events) != 1 or len(seals) != 1:
            return False
        event = events[0]
        seal = seals[0]
        receipts = [
            item
            for item in state.branch_receipts
            if item.handle == seal.branch_receipt
        ]
        if len(receipts) != 1:
            return False
        receipt = receipts[0]
        source_records = [
            item
            for item in state.artifacts
            if item.handle.handle_id == action.source_artifact_id
        ]
        if len(source_records) != 1:
            return False
        source = source_records[0]
        source_profiles = [
            item for item in state.profiles if item.handle == source.runtime_profile
        ]
        if len(source_profiles) != 1:
            return False
        source_namespace = source_profiles[0].namespace
        manifests = [
            item
            for item in state.manifests
            if item.manifest_sha256 == source.source_manifest_sha256
        ]
        if len(manifests) != 1:
            return False
        manifest = manifests[0]
        body = receipt.body
        terminal = body.generation_terminal
        try:
            action_roots = _action_phase_roots(action, terminal)
        except ValueError:
            return False
        expected_roots = tuple(
            sorted(
                {
                    manifest.source_catalog_sha256,
                    manifest.policy_sha256,
                    *action_roots,
                }
            )
        )
        source_factors = [
            item
            for item in state.factors
            if item.handle.handle_id == action.from_revision_id
        ]
        target_factors = [
            item
            for item in state.factors
            if item.handle.handle_id == action.resolved_to_revision_id
        ]
        if len(source_factors) != 1 or len(target_factors) != 1:
            return False
        branch_matches = (
            body.retrieved_target_factor is not None
            and body.retrieved_target_factor.handle_id
            == action.selected_target_revision_id
            and body.mutation_parent_factor is None
            and body.generation_terminal is None
            if action.branch == "reuse"
            else (
                body.retrieved_target_factor is None
                and body.mutation_parent_factor is not None
                and body.mutation_parent_factor.handle_id == action.from_revision_id
                and terminal is not None
                and _generation_terminal_matches_action(
                    action,
                    terminal,
                    require_bank_terminal=True,
                )
                if action.branch == "mutate"
                else (
                    body.retrieved_target_factor is None
                    and body.mutation_parent_factor is None
                    and terminal is not None
                    and _generation_terminal_matches_action(
                        action,
                        terminal,
                        require_bank_terminal=True,
                    )
                )
            )
        )
        transaction_receipts = [
            item
            for item in state.branch_receipts
            if item.body.action_transaction_id == action.action_id
        ]
        return bool(
            len(transaction_receipts) == 1
            and transaction_receipts[0].handle == receipt.handle
            and proof.branch == action.branch
            and event.status == "verified_delta"
            and event.operation_seal == seal.handle
            and proof.operation_seal == seal.handle
            and seal.branch == action.branch
            and body.branch == action.branch
            and body.action_transaction_id == action.action_id
            and body.action_intent_sha256 == action.action_intent_sha256
            and body.source_artifact.handle_id == action.source_artifact_id
            and body.runtime_profile == source.runtime_profile
            and body.descriptor.locator.path == action.locator_path
            and body.dependency_factor_ids == action.dependency_factor_ids
            and branch_matches
            and body.input_root_commitments == expected_roots
            and body.producer_epoch == action.producer_epoch
            and body.attestation_sha256 == action.attestation_sha256
            and source_namespace.binder_version == expected_binder_version
            and proof.namespace.binder_version == expected_binder_version
            and transition.namespace.binder_version == expected_binder_version
            and source_namespace.digest == action.namespace_digest
            and proof.namespace.digest == action.namespace_digest
            and proof.source_artifact.handle_id == action.source_artifact_id
            and proof.source_factor.handle_id == action.from_revision_id
            and proof.target_factor.handle_id == action.resolved_to_revision_id
            and proof.descriptor.locator.path == action.locator_path
            and source_factors[0].factor_content_commitment
            == action.from_content_sha256
            and target_factors[0].factor_content_commitment
            == action.resolved_target_content_sha256
            and transition.proposal_action_id == action.action_id
            and transition.proposal_action_intent_sha256
            == action.action_intent_sha256
            and transition.origin_branch == action.branch
            and transition.namespace.digest == action.namespace_digest
            and transition.source_composition_id == action.source_composition_id
            and transition.slot_id == action.slot_id
            and transition.from_revision_id == action.from_revision_id
            and transition.to_revision_id == action.resolved_to_revision_id
        )

    return verify


def make_phase_v2_proposal_action_terminal_verifier(
    registry: PhaseArtifactRegistry,
) -> Callable[
    [ProposalActionV2, DirectFactorTransitionV2, FactorBankStateV2],
    bool,
]:
    """Return the terminal verifier for explicit leaf-v2 namespaces only."""

    return _make_phase_proposal_action_terminal_verifier(
        registry,
        expected_binder_version=PHASE_FACTOR_BINDER_VERSION,
    )


def make_phase_v2_repair_opportunity_verifier(
    registry: PhaseArtifactRegistry,
    *,
    supported_branches: tuple[Literal["reuse", "mutate", "fresh"], ...] = (
        "reuse",
        "mutate",
        "fresh",
    ),
) -> Callable[
    [RepairOpportunityV2, FailureObservationV2, CompositionRevisionV2],
    bool,
]:
    """Authorize branches only for an exact registry-proved Phase composition.

    This verifier is the pre-generation source-authority boundary.  It joins the
    failure and opportunity to a complete canonical proof bundle before a branch
    can allocate model budget; later reconciliation rejection is intentionally
    not used as a substitute for this check.
    """

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
        canonical_logical_ids = _canonical_repair_source_logical_ids(
            registry,
            composition,
        )
        return bool(
            composition.namespace.payload_format == "phase_program_skill_v1"
            and composition.carrier == "phase_program"
            and bool(canonical_logical_ids)
            and opportunity.source_composition_id == composition.composition_id
            and opportunity.namespace_digest == composition.namespace.digest
            and failure.composition_id == composition.composition_id
            and failure.artifact_sha256 == composition.artifact_sha256
            and opportunity.host_allowed_locator_ids == canonical_logical_ids
            and opportunity.feasible_branches
            == tuple(
                branch
                for branch in supported_branches
                if branch in opportunity.feasible_branches
            )
            and bool(opportunity.host_allowed_locator_ids)
        )

    return verify


def make_phase_v2_arm_receipt_verifier(
    registry: PhaseArtifactRegistry,
    *,
    trusted_runner_verifier: Callable[
        [ArmReceiptV2, PhaseMaterializationProofRecord], bool
    ],
) -> Callable[[ArmReceiptV2, ProbePlanV2, Any], bool]:
    """Bind a runner-authenticated receipt to the exact registry proof arm.

    The registry proof only states what *would* constitute activation.  It is
    never accepted as evidence that execution happened.  The supplied host
    verifier must authenticate the concrete trace/root receipt; deterministic
    joins below then prevent that authority from being replayed onto another
    artifact, arm, block, profile, or factor.
    """

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
            bundle = _canonical_bundle(registry, proof_record.handle)
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
        joins = (
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
        if not all(joins):
            return False
        try:
            return bool(trusted_runner_verifier(receipt, proof))
        except Exception:
            return False

    return verify


def make_registered_phase_arm_receipt_v2(
    *,
    registry: PhaseArtifactRegistry,
    registered: RegisteredPhaseFactorEdgeV2,
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
    """Build the Bank receipt from registry-owned IDs, never caller aliases."""

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


def register_phase_materialization_v2(
    *,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    proof: PhaseBindingProofHandle,
) -> RegisteredPhaseFactorEdgeV2:
    """Atomically project and register one registry proof into the SFT Bank.

    The Bank's bundle boundary rolls back all newly projected rows if the final
    canonical verifier rejects.  No efficacy evidence is created by this
    structural registration.
    """

    bundle = _canonical_bundle(registry, proof)
    action_id, action_intent_sha256 = _proof_action_binding(
        registry,
        bundle.proof,
    )
    existing_edges = [
        item
        for item in bank.direct_transitions.values()
        if item.binding_proof_id == bundle.proof.handle.handle_id
    ]
    if existing_edges:
        if len(existing_edges) != 1:
            raise ValueError("one Phase proof owns multiple FactorBank edges")
        transition = existing_edges[0]
        background = bank.factors.get(bundle.background.revision_id)
        source_factor = bank.factors.get(bundle.source_factor.revision_id)
        target_factor = bank.factors.get(bundle.target_factor.revision_id)
        source = bank.compositions.get(bundle.source_composition.composition_id)
        target = bank.compositions.get(bundle.target_composition.composition_id)
        if any(
            item is None
            for item in (
                background,
                source_factor,
                target_factor,
                source,
                target,
            )
        ):
            raise ValueError("persisted Phase edge lost its canonical bundle")
        assert background is not None
        assert source_factor is not None and target_factor is not None
        assert source is not None and target is not None
        if not (
            _factor_matches(bundle.background, background)
            and _factor_matches(bundle.source_factor, source_factor)
            and _factor_matches(bundle.target_factor, target_factor)
            and _composition_matches(bundle.source_composition, source)
            and _composition_matches(bundle.target_composition, target)
            and transition.namespace == bundle.proof.namespace
            and transition.source_composition_id == source.composition_id
            and transition.target_composition_id == target.composition_id
            and transition.slot_id == bundle.changed_slot_id
            and transition.from_revision_id == source_factor.revision_id
            and transition.to_revision_id == target_factor.revision_id
            and transition.masked_background_sha256
            == bundle.proof.masked_background_commitment
            and transition.binding_proof_sha256
            == bundle.proof.handle.proof_sha256
            and transition.binding_verifier_epoch
            == PHASE_FACTOR_BANK_V2_VERIFIER_EPOCH
            and transition.origin_branch == bundle.proof.branch
            and transition.proposal_action_id == action_id
            and transition.proposal_action_intent_sha256
            == action_intent_sha256
        ):
            raise ValueError("persisted Phase edge differs from its canonical proof")
        return RegisteredPhaseFactorEdgeV2(
            proof=bundle.proof.handle,
            background_factor=background,
            source_factor=source_factor,
            target_factor=target_factor,
            source_composition=source,
            target_composition=target,
            transition=transition,
        )
    next_seq = bank.to_state().event_seq
    new_factors: list[FactorRevisionV2] = []
    for template in (
        bundle.background,
        bundle.source_factor,
        bundle.target_factor,
    ):
        existing = bank.factors.get(template.revision_id)
        if existing is not None:
            if not _factor_matches(template, existing):
                raise ValueError("existing FactorBank factor differs from registry projection")
            continue
        next_seq += 1
        new_factors.append(template.build(created_seq=next_seq))
    new_compositions: list[CompositionRevisionV2] = []
    for template in (bundle.source_composition, bundle.target_composition):
        existing = bank.compositions.get(template.composition_id)
        if existing is not None:
            if not _composition_matches(template, existing):
                raise ValueError(
                    "existing FactorBank composition differs from registry projection"
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
            "binding_verifier_epoch": PHASE_FACTOR_BANK_V2_VERIFIER_EPOCH,
            "origin_branch": bundle.proof.branch,
            "proposal_action_id": action_id,
            "proposal_action_intent_sha256": action_intent_sha256,
        },
    )
    background = bank.factors[bundle.background.revision_id]
    source_factor = bank.factors[bundle.source_factor.revision_id]
    target_factor = bank.factors[bundle.target_factor.revision_id]
    source = bank.compositions[bundle.source_composition.composition_id]
    target = bank.compositions[bundle.target_composition.composition_id]
    return RegisteredPhaseFactorEdgeV2(
        proof=bundle.proof.handle,
        background_factor=background,
        source_factor=source_factor,
        target_factor=target_factor,
        source_composition=source,
        target_composition=target,
        transition=transition,
    )


def _reconcile_phase_proposal_action_versioned(
    *,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    expected_binder_version: str,
    register_materialization: Callable[..., Any],
    action_id: str,
    generation_terminal: PhaseGenerationTerminalV1 | None = None,
    generated_value: Any = _MISSING_GENERATED_VALUE,
    ingress: Any | None = None,
    noop_abort_receipt: ProposalActionAbortReceiptV2 | None = None,
    terminal_abort_receipt: ProposalActionAbortReceiptV2 | None = None,
) -> Any:
    """Recoverably execute one exact-version Phase proposal action.

    The order is fixed: Phase ``COMMIT_ONCE`` → idempotent structural edge
    projection → Bank finalize.  Crashing after either of the first two steps
    is safe because an exact retry returns the same Phase terminal and the same
    edge.  Generated actions must already own their persisted Bank lease and a
    closed Phase terminal; this adapter performs no model call.  A Phase no-op
    or exact terminal rejection is fenced only by its typed Bank abort receipt.
    Exceptions are not translated into scientific outcomes.
    """

    action = next(
        (
            item
            for item in bank.to_state().proposal_actions
            if item.action_id == action_id
        ),
        None,
    )
    if action is None:
        raise ValueError("proposal action does not exist")
    if action.state == "aborted":
        raise ValueError("aborted proposal action is fenced from Phase execution")
    if noop_abort_receipt is not None and terminal_abort_receipt is not None:
        raise ValueError("one reconciliation cannot carry two abort terminals")
    source_record = next(
        (
            item
            for item in registry.to_state().artifacts
            if item.handle.handle_id == action.source_artifact_id
        ),
        None,
    )
    if source_record is None:
        raise ValueError("proposal action Phase source handle is missing")
    source_profiles = [
        item
        for item in registry.to_state().profiles
        if item.handle == source_record.runtime_profile
    ]
    if len(source_profiles) != 1:
        raise ValueError("proposal action Phase runtime profile is missing")
    source_namespace = source_profiles[0].namespace
    if not (
        source_namespace.binder_version == expected_binder_version
        and source_namespace.digest == action.namespace_digest
        and source_record.handle.handle_id == action.source_artifact_id
    ):
        raise ValueError("proposal action crosses its exact Phase binder/namespace")
    dependency_id = (
        action.selected_target_revision_id
        if action.branch == "reuse"
        else action.from_revision_id
        if action.branch == "mutate"
        else None
    )
    dependency_record = next(
        (
            item
            for item in registry.to_state().factors
            if item.handle.handle_id == dependency_id
        ),
        None,
    )
    if dependency_id is not None and dependency_record is None:
        raise ValueError("proposal action Phase dependency handle is missing")
    if action.branch == "reuse":
        if action.state not in {"prepared", "committed"}:
            raise ValueError("reuse action is not in its exact Phase state")
        if any(item is not None for item in (generation_terminal, ingress)) or (
            generated_value is not _MISSING_GENERATED_VALUE
        ):
            raise ValueError("reuse action cannot carry generation inputs")
        assert dependency_record is not None
        if dependency_record.factor_content_commitment != (
            action.selected_target_content_sha256
        ):
            raise ValueError("reuse target content differs from Phase registry")
    else:
        if action.state not in {"executing", "committed"}:
            raise ValueError("generated action lacks its persisted START lease")
        if (
            generation_terminal is None
            or generated_value is _MISSING_GENERATED_VALUE
            or ingress is None
        ):
            raise ValueError(
                "generated action requires its terminal, scalar, and ingress"
            )
        if not _generation_terminal_matches_action(
            action,
            generation_terminal,
            require_bank_terminal=action.state == "committed",
        ):
            raise ValueError("generation terminal differs from its Bank action")
        request = action.generation_request
        assert request is not None
        if not (
            request.source_manifest_sha256
            == source_record.source_manifest_sha256
            and request.namespace_digest == source_namespace.digest
        ):
            raise ValueError("generation request crosses its Phase source authority")
    action_roots = _action_phase_roots(action, generation_terminal)
    materialize_kwargs: dict[str, Any] = {
        "action_transaction_id": action.action_id,
        "action_intent_sha256": action.action_intent_sha256,
        "branch": action.branch,
        "source_artifact": PhaseArtifactHandle.model_validate(
            source_record.handle.model_dump(mode="python")
        ),
        "locator": action.locator_path,
        "dependency_factor": (
            FactorContentHandle.model_validate(
                dependency_record.handle.model_dump(mode="python")
            )
            if dependency_record is not None
            else None
        ),
        "exact_additional_input_root_commitments": action_roots,
        "producer_epoch": action.producer_epoch,
        "attestation_sha256": action.attestation_sha256,
    }
    if action.branch in {"mutate", "fresh"}:
        materialize_kwargs.update(
            {
                "generation_terminal": generation_terminal,
                "generated_value": generated_value,
                "ingress": ingress,
            }
        )
    result = registry.materialize_action_idempotent(
        **materialize_kwargs,
    )
    if isinstance(result, NoOpMaterialization):
        if terminal_abort_receipt is not None:
            raise ValueError("a Phase no-op cannot carry a rejection cleanup")
        terminal = registry.resolve_event(result.event)
        terminal_sha256 = phase_materialization_event_sha256_v1(terminal)
        if noop_abort_receipt is not None:
            if not (
                noop_abort_receipt.action_id == action.action_id
                and noop_abort_receipt.reason == "phase_noop"
                and noop_abort_receipt.phase_terminal_sha256 == terminal_sha256
            ):
                raise ValueError("proposal no-op abort does not join its Phase terminal")
            bank.abort_proposal_action(action.action_id, noop_abort_receipt)
        return result
    registered = register_materialization(
        registry=registry,
        bank=bank,
        proof=result,
    )
    if noop_abort_receipt is not None:
        raise ValueError("a verified Phase delta cannot carry a no-op abort")
    if terminal_abort_receipt is not None:
        expected_reason = (
            "phase_rejected"
            if action.branch == "reuse"
            else "generation_terminal_rejected"
        )
        if not (
            terminal_abort_receipt.action_id == action.action_id
            and terminal_abort_receipt.reason == expected_reason
            and terminal_abort_receipt.phase_terminal_sha256
            == result.proof_sha256
        ):
            raise ValueError(
                "proposal rejection cleanup does not join its Phase terminal"
            )
        aborted = bank.abort_proposal_action(
            action.action_id,
            terminal_abort_receipt,
        )
        return AbortedPhaseProposalActionV2(
            action=aborted,
            phase_terminal_sha256=result.proof_sha256,
        )
    bank.finalize_proposal_action(
        action.action_id,
        transition_id=registered.transition.transition_id,
        phase_terminal_sha256=result.proof_sha256,
        generation_terminal_sha256=(
            generation_terminal.digest
            if generation_terminal is not None
            else None
        ),
        resolved_to_revision_id=(
            registered.target_factor.revision_id
            if action.branch in {"mutate", "fresh"}
            else None
        ),
        resolved_target_content_sha256=(
            registered.target_factor.content_sha256
            if action.branch in {"mutate", "fresh"}
            else None
        ),
    )
    return registered.model_copy(
        update={
            "transition": bank.direct_transitions[
                registered.transition.transition_id
            ]
        }
    )


def reconcile_phase_proposal_action_v2(
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
    RegisteredPhaseFactorEdgeV2
    | NoOpMaterialization
    | AbortedPhaseProposalActionV2
):
    """Execute one proposal under the explicit leaf-v2 representation."""

    return _reconcile_phase_proposal_action_versioned(
        registry=registry,
        bank=bank,
        expected_binder_version=PHASE_FACTOR_BINDER_VERSION,
        register_materialization=register_phase_materialization_v2,
        action_id=action_id,
        generation_terminal=generation_terminal,
        generated_value=generated_value,
        ingress=ingress,
        noop_abort_receipt=noop_abort_receipt,
        terminal_abort_receipt=terminal_abort_receipt,
    )


def reconcile_phase_reuse_proposal_action_v1(
    *,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    action_id: str,
    noop_abort_receipt: ProposalActionAbortReceiptV2 | None = None,
) -> RegisteredPhaseFactorEdgeV2 | NoOpMaterialization:
    """Compatibility wrapper for the former reuse-only adapter surface."""

    result = reconcile_phase_proposal_action_v2(
        registry=registry,
        bank=bank,
        action_id=action_id,
        noop_abort_receipt=noop_abort_receipt,
    )
    if isinstance(result, AbortedPhaseProposalActionV2):
        raise RuntimeError("reuse compatibility path returned a rejection cleanup")
    return result


__all__ = [
    "AbortedPhaseProposalActionV2",
    "PHASE_FACTOR_BANK_V2_VERIFIER_EPOCH",
    "RegisteredPhaseFactorEdgeV2",
    "make_phase_v2_arm_receipt_verifier",
    "make_phase_v2_binding_verifier",
    "make_phase_v2_proposal_action_terminal_verifier",
    "make_phase_v2_repair_opportunity_verifier",
    "make_registered_phase_arm_receipt_v2",
    "reconcile_phase_proposal_action_v2",
    "reconcile_phase_reuse_proposal_action_v1",
    "register_phase_materialization_v2",
]
