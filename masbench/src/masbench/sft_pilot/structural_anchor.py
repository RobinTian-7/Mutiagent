"""Non-empty generation-zero anchor for the default-off SFT pilot.

The scientific FactorBank cannot start from an empty carrier universe: there
would be no typed locus on which ``reuse|mutate|fresh`` can operate.  This
module provisions exactly one structural PhaseProgram edge and a source base
snapshot without manufacturing an execution, score, failure, or efficacy
claim.

The source program is deliberately code-defined and text-free.  Callers may
choose only the already-separated execution namespace, bounded compiler
limits, and two sanitized TRAIN_UPDATE commitments.  They cannot pass a raw
prompt, answer, TEST row, target scalar, or arbitrary receipt to a signing
method.  Domain-separated host HMACs authenticate the exact source manifest,
branch receipt, and base receipt; the public commitment to that authority is
safe to freeze before the later pilot protocol exists, avoiding a genesis
digest cycle.

``PhaseArtifactRegistry.seal_operation`` contains a cryptographic random
nonce.  Consequently a fresh reconstruction is intentionally *not* expected
to reproduce the same root.  One authoritative build must freeze the exact
native Phase and Factor envelopes; every subsequent use reloads those bytes
and verifies the frozen root.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.mas.factor_bank import ExecutionNamespace
from exp_graph.mas.factor_bank_v2 import (
    BaseSnapshotReceiptV2,
    FactorBankStateV2,
    FactorBankV2,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseArtifactRegistryState,
    PhaseBindingProofHandle,
    PhaseBranchReceiptBody,
    SourceManifest,
    phase_mutable_factor_paths_v3,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    RegisteredPhaseFactorEdgeV3,
    make_phase_v3_binding_verifier,
    register_phase_materialization_v3,
)
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    PhaseProgram,
    PhaseProgramLimits,
    compile_phase_program,
    phase_program_digest,
)


STRUCTURAL_ANCHOR_VERSION = "sft-structural-anchor-v2"
STRUCTURAL_ANCHOR_LOCATOR = "/phases/1/hub"
_BRANCH_PRODUCER_EPOCH = "sft-anchor-host:v2"
_BASE_VERIFIER_EPOCH = "sft-anchor-base:v2"
_PHASE_FILENAME = "phase_registry_anchor_v2.json"
_FACTOR_FILENAME = "factor_bank_anchor_v2.json"
_SHA256_ZERO = "0" * 64


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mac(key: bytes, domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\0" + _canonical_bytes(value)
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _require_key(value: bytes, name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 bytes")
    return bytes(value)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


# Per-base anchor law: source phase list, host target one-scalar diff, and the
# single mutable locus (path, field, scalar type, host target value, legal
# domain description).  The five user-directed bases are the phase-carrier
# equivalents of the named/paper propagation structures (see
# docs/sft_phase_v5/multi_base_design.md); "gather_broadcast" is the legacy
# default and stays byte-identical for existing anchors.
ANCHOR_BASE_STRUCTURES = (
    "gather_broadcast",
    "one_peer_exponential_dag",
    "static_exponential",
    "p2p",
    "broadcast",
    "sfs",
    "one_peer_instruction",
)

# Strategy-A instruction seeds: the source states the current implicit relay
# duty; the host target states the global-merge duty (validated by the
# strategy-C barrier A/B).  Both are answer-free process instructions.
ANCHOR_INSTRUCTION_SOURCE = (
    "Merge the incoming contributions losslessly with your own and keep "
    "relaying anything new."
)
ANCHOR_INSTRUCTION_TARGET = (
    "Combine every distinct per-agent contribution you have received into "
    "the task's single global answer: sum per-shard counts, take extrema "
    "over shard extrema, and merge partial maps or lists into one complete "
    "structure before answering."
)


def _base_phases(base: str) -> list[dict]:
    if base in ("gather_broadcast", "sfs"):
        return [
            {
                "kind": "gather",
                "hub": 0,
                "pattern": "tree",
                "instruction": None,
                "send_mode": "delta_or_no_send",
            },
            {
                "kind": "broadcast",
                "hub": 0,
                "pattern": "tree",
                "instruction": None,
                "send_mode": "delta_or_no_send",
            },
        ]
    if base == "one_peer_instruction":
        return [
            {
                "kind": "consensus",
                "pattern": "exponential",
                "max_rounds": 8,
                "stop_when": "all_agents_full_information",
                "instruction": ANCHOR_INSTRUCTION_SOURCE,
                "send_mode": "delta_or_no_send",
            }
        ]
    if base == "one_peer_exponential_dag":
        return [
            {
                "kind": "consensus",
                "pattern": "exponential",
                "max_rounds": 8,
                "stop_when": "all_agents_full_information",
                "instruction": None,
                "send_mode": "delta_or_no_send",
            }
        ]
    if base == "static_exponential":
        return [
            {
                "kind": "pairwise_exchange",
                "pattern": "exponential",
                "max_rounds": 3,
                "stop_when": "fixed_rounds",
                "instruction": None,
                "send_mode": "delta_or_no_send",
            }
        ]
    if base == "p2p":
        return [
            {
                "kind": "pairwise_exchange",
                "pattern": "rotating",
                "max_rounds": 4,
                "stop_when": "fixed_rounds",
                "instruction": None,
                "send_mode": "delta_or_no_send",
            }
        ]
    if base == "broadcast":
        return [
            {
                "kind": "consensus",
                "pattern": "all_to_all",
                "max_rounds": 2,
                "stop_when": "all_agents_full_information",
                "instruction": None,
                "send_mode": "delta_or_no_send",
            }
        ]
    raise ValueError(f"unknown anchor base structure {base!r}")


# Anchorize (S4) genesis-locus rule for override programs: flip phase 0's
# pattern to a kind-legal alternate.  Every alternate compiles to a different
# schedule at any n_agents >= 2, so the genesis target never aliases the
# source image.
_OVERRIDE_PATTERN_ALTERNATES: dict[str, dict[str, str]] = {
    "gather": {"star": "tree", "tree": "star"},
    "broadcast": {"star": "tree", "tree": "star"},
    "pairwise_exchange": {
        "ring": "bidirectional_ring",
        "bidirectional_ring": "ring",
        "rotating": "ring",
        "exponential": "rotating",
    },
    "consensus": {
        "all_to_all": "rotating",
        "rotating": "all_to_all",
        "exponential": "rotating",
    },
}

_ANCHOR_BASE_LOCI: dict[str, dict[str, object]] = {
    "gather_broadcast": {
        "locus": "/phases/1/hub",
        "field": "hub",
        "scalar_type": "int",
        "target_value": 1,
    },
    "one_peer_exponential_dag": {
        "locus": "/phases/0/pattern",
        "field": "pattern",
        "scalar_type": "string",
        "target_value": "rotating",
    },
    "static_exponential": {
        # The compiler elides rounds past full coverage, so values >= the
        # coverage point alias the source image; the movable direction is
        # fewer rounds (under-provisioned schedules).
        "locus": "/phases/0/max_rounds",
        "field": "max_rounds",
        "scalar_type": "int",
        "target_value": 2,
    },
    "p2p": {
        "locus": "/phases/0/pattern",
        "field": "pattern",
        "scalar_type": "string",
        "target_value": "ring",
    },
    "broadcast": {
        "locus": "/phases/0/pattern",
        "field": "pattern",
        "scalar_type": "string",
        "target_value": "rotating",
    },
    "one_peer_instruction": {
        "locus": "/phases/0/instruction",
        "field": "instruction",
        "scalar_type": "string",
        "target_value": ANCHOR_INSTRUCTION_TARGET,
    },
    "sfs": {
        # gather/broadcast pattern domain is exhausted by genesis (star|tree),
        # so sfs mutates WHICH agent hosts the shared store (the gather hub).
        "locus": "/phases/0/hub",
        "field": "hub",
        "scalar_type": "int",
        "target_value": 1,
    },
}


class StructuralAnchorPlanV1(_ClosedModel):
    """Closed, answer-free inputs from which the canonical anchor is derived."""

    plan_version: Literal[STRUCTURAL_ANCHOR_VERSION] = STRUCTURAL_ANCHOR_VERSION
    namespace: ExecutionNamespace
    limits: PhaseProgramLimits = Field(default_factory=PhaseProgramLimits)
    source_catalog_sha256: str
    source_policy_sha256: str
    base_structure: Literal[
        "gather_broadcast",
        "one_peer_exponential_dag",
        "static_exponential",
        "p2p",
        "broadcast",
        "sfs",
        "one_peer_instruction",
    ] = "gather_broadcast"
    # Chained-evolution overrides (strategy B): round k+1 anchors at round
    # k's accepted deployment by overriding the locus source value (and the
    # host genesis target, which must stay a different legal value).  None
    # keeps the base law byte-identical.
    source_value_override: int | str | None = None
    target_value_override: int | str | None = None
    # Anchorize (S4): a gate-accepted whole composition becomes the next
    # round's anchor by overriding the ENTIRE source program (a validated
    # PhaseProgram JSON dump).  The genesis direct edge still needs one
    # scalar locus; for override programs it follows a frozen deterministic
    # rule — flip phase 0's pattern to its kind-legal alternate (every phase
    # kind carries a pattern, and a pattern flip always changes the compiled
    # image, so the genesis target can never alias the source).
    source_program_override: dict | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> "StructuralAnchorPlanV1":
        for name in ("source_catalog_sha256", "source_policy_sha256"):
            value = str(getattr(self, name))
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        namespace = self.namespace
        if not (
            namespace.information_goal in {"sink", "all_agents"}
            and namespace.planner_mode == "program_generate"
            and namespace.payload_format == "phase_program_skill_v1"
            and namespace.worker_contract == "not_applicable"
            and namespace.model_name in ("gpt-4o-mini", "gpt-5-mini")
            and namespace.binder_version == PHASE_FULL_FACTOR_BINDER_VERSION
            and namespace.compiler_version == PHASE_PROGRAM_COMPILER_VERSION
        ):
            raise ValueError(
                "anchor namespace crosses information_goal/planner/payload/worker/model contract"
            )
        if namespace.n_agents < 2:
            raise ValueError("structural anchor requires at least two agents")
        if namespace.n_agents - 1 > min(16, self.limits.max_steps):
            raise ValueError("canonical anchor exceeds the frozen agent-count domain")
        # Registry profiles currently impose these tighter preliminary bounds.
        if self.limits.max_steps > 16:
            raise ValueError("anchor max_steps cannot exceed 16")
        if self.limits.max_messages > 128:
            raise ValueError("anchor max_messages cannot exceed 128")
        if self.limits.max_receiver_fan_in > 4:
            raise ValueError("anchor max_receiver_fan_in cannot exceed 4")
        compile_phase_program(
            self.source_program,
            n_agents=namespace.n_agents,
            limits=self.limits,
        )
        compile_phase_program(
            self.target_program,
            n_agents=namespace.n_agents,
            limits=self.limits,
        )
        return self

    @property
    def anchor_locus(self) -> str:
        if self.source_program_override is not None:
            return "/phases/0/pattern"
        return str(_ANCHOR_BASE_LOCI[self.base_structure]["locus"])

    @property
    def anchor_field_name(self) -> str:
        if self.source_program_override is not None:
            return "pattern"
        return str(_ANCHOR_BASE_LOCI[self.base_structure]["field"])

    @property
    def anchor_scalar_type(self) -> str:
        if self.source_program_override is not None:
            return "string"
        return str(_ANCHOR_BASE_LOCI[self.base_structure]["scalar_type"])

    @property
    def anchor_target_value(self):
        if self.target_value_override is not None:
            return self.target_value_override
        if self.source_program_override is not None:
            phase = self.source_program.phases[0]
            return _OVERRIDE_PATTERN_ALTERNATES[phase.kind][phase.pattern]
        return _ANCHOR_BASE_LOCI[self.base_structure]["target_value"]

    @property
    def source_program(self) -> PhaseProgram:
        """Return the sole, text-free generation-zero source carrier."""

        if self.source_program_override is not None:
            program = PhaseProgram.model_validate(self.source_program_override)
            if program.information_goal != self.namespace.information_goal:
                raise ValueError(
                    "anchor override program crosses the namespace goal"
                )
            return program
        phases = _base_phases(self.base_structure)
        if self.source_value_override is not None:
            phase_index = int(self.anchor_locus.split("/")[2])
            phases[phase_index][self.anchor_field_name] = (
                self.source_value_override
            )
        return PhaseProgram.model_validate(
            {
                "format": "phase_program_v1",
                "information_goal": self.namespace.information_goal,
                "selected_primary": 0,
                "state_retention": "keep",
                "allow_no_send": True,
                "submit_when": "coverage_complete",
                "phases": phases,
            }
        )

    @property
    def target_program(self) -> PhaseProgram:
        """Return the sole image-changing anchor target used by the host."""

        payload = self.source_program.model_dump(mode="python")
        phase_index = int(self.anchor_locus.split("/")[2])
        payload["phases"][phase_index][self.anchor_field_name] = (
            self.anchor_target_value
        )
        return PhaseProgram.model_validate(payload)

    @property
    def digest(self) -> str:
        return _sha256(self)


class StructuralZeroEvidenceV1(_ClosedModel):
    """The only legal scientific counters in a generation-zero anchor."""

    plans: Literal[0] = 0
    reservations: Literal[0] = 0
    attempts: Literal[0] = 0
    outcomes: Literal[0] = 0
    assessments: Literal[0] = 0
    gate_opportunities: Literal[0] = 0
    gate_receipts: Literal[0] = 0
    failures: Literal[0] = 0
    repair_opportunities: Literal[0] = 0
    proposal_actions: Literal[0] = 0
    positive_credit: Literal[0] = 0
    negative_credit: Literal[0] = 0


class StructuralAnchorBundleV1(_ClosedModel):
    """Public commitments needed to freeze and later re-open one anchor."""

    schema_version: Literal[STRUCTURAL_ANCHOR_VERSION] = STRUCTURAL_ANCHOR_VERSION
    anchor_plan_sha256: str
    source_authority_sha256: str
    source_manifest_sha256: str
    namespace_sha256: str
    locus: str = STRUCTURAL_ANCHOR_LOCATOR
    source_program_sha256: str
    target_program_sha256: str
    phase_registry_state_sha256: str
    factor_bank_state_sha256: str
    phase_registry_envelope_sha256: str
    factor_bank_envelope_sha256: str
    proof_id: str
    proof_sha256: str
    transition_id: str
    source_factor_revision_id: str
    target_factor_revision_id: str
    source_composition_id: str
    target_composition_id: str
    base_receipt_id: str
    base_snapshot_id: str
    zero_evidence: StructuralZeroEvidenceV1 = Field(
        default_factory=StructuralZeroEvidenceV1
    )
    root_policy: Literal["freeze_first_exact_native_envelopes"] = (
        "freeze_first_exact_native_envelopes"
    )
    exact_root_requires_one_time_freeze: Literal[True] = True
    anchor_root_sha256: str

    @model_validator(mode="after")
    def validate_bundle(self) -> "StructuralAnchorBundleV1":
        for name in (
            "anchor_plan_sha256",
            "source_authority_sha256",
            "source_manifest_sha256",
            "namespace_sha256",
            "source_program_sha256",
            "target_program_sha256",
            "phase_registry_state_sha256",
            "factor_bank_state_sha256",
            "phase_registry_envelope_sha256",
            "factor_bank_envelope_sha256",
            "proof_sha256",
            "anchor_root_sha256",
        ):
            value = str(getattr(self, name))
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        expected = _sha256(
            self.model_dump(mode="python", exclude={"anchor_root_sha256"})
        )
        if self.anchor_root_sha256 != expected:
            raise ValueError("structural anchor root is not reproducible")
        if self.source_program_sha256 == self.target_program_sha256:
            raise ValueError("structural anchor source and target programs must differ")
        return self


@dataclass(frozen=True)
class StructuralAnchorRuntimeV1:
    """Loaded native components plus their exact frozen recovery bytes."""

    bundle: StructuralAnchorBundleV1
    registry: PhaseArtifactRegistry
    bank: FactorBankV2
    phase_registry_path: Path
    factor_bank_path: Path
    phase_registry_envelope_bytes: bytes
    factor_bank_envelope_bytes: bytes


def _authority_commitment(source_authority_key: bytes) -> str:
    return hashlib.sha256(
        b"sft-structural-anchor-source-authority-v2\0" + source_authority_key
    ).hexdigest()


def _source_manifest(
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
) -> SourceManifest:
    source_authority_sha256 = _authority_commitment(source_authority_key)
    body = {
        "manifest_version": "sft-structural-anchor-source-manifest-v2",
        "anchor_plan_sha256": plan.digest,
        "source_authority_sha256": source_authority_sha256,
        "split": "TRAIN_UPDATE",
        "source_catalog_sha256": plan.source_catalog_sha256,
        "policy_sha256": plan.source_policy_sha256,
        "producer_version": STRUCTURAL_ANCHOR_VERSION,
    }
    return SourceManifest(
        manifest_sha256=_mac(
            source_authority_key,
            "sft-structural-anchor-source-manifest-v2",
            body,
        ),
        split="TRAIN_UPDATE",
        source_catalog_sha256=plan.source_catalog_sha256,
        policy_sha256=plan.source_policy_sha256,
        producer_version=STRUCTURAL_ANCHOR_VERSION,
    )


def _manifest_verifier(
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
) -> Callable[[SourceManifest], bool]:
    expected = _source_manifest(plan, source_authority_key)

    def verify(candidate: SourceManifest) -> bool:
        return bool(candidate == expected and candidate.split == "TRAIN_UPDATE")

    return verify


def _branch_attestation(
    body: PhaseBranchReceiptBody,
    source_authority_key: bytes,
) -> str:
    return _mac(
        source_authority_key,
        "sft-structural-anchor-branch-receipt-v2",
        body.model_dump(mode="python", exclude={"attestation_sha256"}),
    )


def _branch_verifier(
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
) -> Callable[[PhaseBranchReceiptBody], bool]:
    manifest = _source_manifest(plan, source_authority_key)
    required_roots = tuple(
        sorted(
            {
                plan.source_catalog_sha256,
                plan.source_policy_sha256,
                plan.digest,
                _authority_commitment(source_authority_key),
            }
        )
    )

    def verify(body: PhaseBranchReceiptBody) -> bool:
        return bool(
            body.branch == "mutate"
            and body.source_manifest_sha256 == manifest.manifest_sha256
            and body.runtime_profile.kind == "runtime_profile"
            and body.descriptor.locator.path == plan.anchor_locus
            and body.descriptor.field_name == plan.anchor_field_name
            and body.descriptor.activation_kind
            == (
                "phase_step_executed"
                if plan.anchor_field_name == "instruction"
                else "execution_image_load"
            )
            and body.mutation_parent_factor == body.source_factor
            and body.retrieved_target_factor is None
            and body.retrieved_target_attestation is None
            and body.dependency_factor_ids == (body.source_factor.handle_id,)
            and body.input_root_commitments == required_roots
            and body.action_transaction_id is None
            and body.action_intent_sha256 is None
            and body.generation_terminal is None
            and body.producer_epoch == _BRANCH_PRODUCER_EPOCH
            and hmac.compare_digest(
                body.attestation_sha256,
                _branch_attestation(body, source_authority_key),
            )
        )

    return verify


def _base_attestation(
    receipt: BaseSnapshotReceiptV2,
    source_authority_key: bytes,
) -> str:
    return _mac(
        source_authority_key,
        "sft-structural-anchor-base-receipt-v2",
        receipt.model_dump(mode="python", exclude={"attestation_sha256"}),
    )


def _base_verifier(
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
) -> Callable[[BaseSnapshotReceiptV2, FactorBankStateV2], bool]:
    def verify(receipt: BaseSnapshotReceiptV2, state: FactorBankStateV2) -> bool:
        sources = [
            edge
            for edge in state.direct_transitions
            if edge.source_composition_id == receipt.composition_id
        ]
        return bool(
            receipt.namespace_digest == plan.namespace.digest
            and receipt.runtime_version == plan.namespace.runtime_version
            and receipt.verifier_epoch == _BASE_VERIFIER_EPOCH
            and len(sources) == 1
            and sources[0].proposal_action_id is None
            and sources[0].proposal_action_intent_sha256 is None
            and sources[0].origin_branch == "mutate"
            and hmac.compare_digest(
                receipt.attestation_sha256,
                _base_attestation(receipt, source_authority_key),
            )
        )

    return verify


def _canonical_branch_body(
    *,
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
    source_artifact: Any,
    runtime_profile: Any,
    descriptor: Any,
    source_factor: Any,
    manifest: SourceManifest,
) -> PhaseBranchReceiptBody:
    input_roots = tuple(
        sorted(
            {
                manifest.source_catalog_sha256,
                manifest.policy_sha256,
                plan.digest,
                _authority_commitment(source_authority_key),
            }
        )
    )
    provenance_closure_sha256 = _sha256(
        {
            "source_manifest": manifest.manifest_sha256,
            "input_roots": input_roots,
            "bank_dependencies": (source_factor.handle_id,),
            "retrieved_target_attestation": None,
            "branch": "mutate",
            "source_artifact": source_artifact.handle_id,
            "descriptor": descriptor,
            "action_transaction_id": None,
            "action_intent_sha256": None,
            "generation_terminal_sha256": None,
        }
    )
    provisional = PhaseBranchReceiptBody(
        branch="mutate",
        source_artifact=source_artifact,
        runtime_profile=runtime_profile,
        descriptor=descriptor,
        source_factor=source_factor,
        mutation_parent_factor=source_factor,
        dependency_factor_ids=(source_factor.handle_id,),
        source_manifest_sha256=manifest.manifest_sha256,
        input_root_commitments=input_roots,
        provenance_closure_sha256=provenance_closure_sha256,
        producer_epoch=_BRANCH_PRODUCER_EPOCH,
        attestation_sha256=_SHA256_ZERO,
    )
    return provisional.model_copy(
        update={
            "attestation_sha256": _branch_attestation(
                provisional,
                source_authority_key,
            )
        }
    )


def _base_receipt(
    *,
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
    bank: FactorBankV2,
    edge: RegisteredPhaseFactorEdgeV3,
) -> BaseSnapshotReceiptV2:
    source = edge.source_composition
    binding_map_sha256 = _sha256(sorted(source.binding_map.items()))
    receipt_id = f"base:{_sha256({'plan': plan.digest, 'source': source.composition_id})[:24]}"
    provisional = BaseSnapshotReceiptV2(
        receipt_id=receipt_id,
        deployment_slot_id=bank.deployment_slot_id(source.namespace),
        namespace_digest=source.namespace.digest,
        composition_id=source.composition_id,
        loaded_artifact_sha256=source.artifact_sha256,
        binding_map_sha256=binding_map_sha256,
        runtime_version=source.namespace.runtime_version,
        verifier_epoch=_BASE_VERIFIER_EPOCH,
        attestation_sha256=_SHA256_ZERO,
        emitted_seq=bank.to_state().event_seq + 1,
    )
    return provisional.model_copy(
        update={
            "attestation_sha256": _base_attestation(
                provisional,
                source_authority_key,
            )
        }
    )


def _validate_zero_evidence_state(
    *,
    registry_state: PhaseArtifactRegistryState,
    bank_state: FactorBankStateV2,
    manifest: SourceManifest,
    edge: RegisteredPhaseFactorEdgeV3,
) -> None:
    if not (
        len(registry_state.manifests) == 1
        and registry_state.manifests[0] == manifest
        and manifest.split == "TRAIN_UPDATE"
        and len(registry_state.profiles) == 1
        and len(registry_state.artifacts) == 2
        and len(registry_state.values)
        == len(phase_mutable_factor_paths_v3(registry_state.artifacts[0].program)) + 1
        and len(registry_state.attestations)
        == 2 * len(phase_mutable_factor_paths_v3(registry_state.artifacts[0].program)) + 1
        and len(registry_state.factors)
        == len(phase_mutable_factor_paths_v3(registry_state.artifacts[0].program)) + 1
        and len(registry_state.branch_receipts) == 1
        and len(registry_state.seals) == 1
        and len(registry_state.events) == 1
        and registry_state.events[0].status == "verified_delta"
        and len(registry_state.proofs) == 1
    ):
        raise ValueError("Phase generation-zero anchor is not one exact structural proof")
    expected_paths = set(
        phase_mutable_factor_paths_v3(registry_state.artifacts[0].program)
    )
    descriptor_paths = {item.descriptor.locator.path for item in registry_state.factors}
    if descriptor_paths != expected_paths:
        raise ValueError("Phase generation-zero anchor lacks its complete locus domain")
    if not (
        len(bank_state.factors) == len(expected_paths) + 2
        and len(bank_state.compositions) == 2
        and len(bank_state.direct_transitions) == 1
        and not bank_state.whole_transitions
        and bank_state.direct_transitions[0] == edge.transition
        and edge.transition.proposal_action_id is None
        and edge.transition.proposal_action_intent_sha256 is None
        and len(bank_state.base_receipts) == 1
        and len(bank_state.deployment_snapshots) == 1
        and len(bank_state.deployment_heads) == 1
        and bank_state.deployment_snapshots[0].is_base_fallback
        and bank_state.deployment_heads[0].active_composition_id
        == edge.source_composition.composition_id
    ):
        raise ValueError("Factor generation-zero anchor is not one edge plus one base")
    forbidden_nonempty = {
        "plans": bank_state.plans,
        "reservations": bank_state.reservations,
        "attempts": bank_state.attempts,
        "assessments": bank_state.assessments,
        "gate_opportunities": bank_state.gate_opportunities,
        "gate_receipts": bank_state.gate_receipts,
        "rollback_triggers": bank_state.rollback_triggers,
        "rollback_records": bank_state.rollback_records,
        "failures": bank_state.failures,
        "repair_opportunities": bank_state.repair_opportunities,
        "branch_assignments": bank_state.branch_assignments,
        "proposal_decisions": bank_state.proposal_decisions,
        "proposal_lifetime_counters": bank_state.proposal_lifetime_counters,
        "proposal_actions": bank_state.proposal_actions,
        "proposal_carrier_reservations": bank_state.proposal_carrier_reservations,
        "proposal_carrier_admissions": bank_state.proposal_carrier_admissions,
        "exposures": bank_state.exposures,
        "used_roots": bank_state.used_roots,
        "used_receipts": bank_state.used_receipts,
        "used_edge_epochs": bank_state.used_edge_epochs,
        "used_unit_commitments": bank_state.used_unit_commitments,
        "tombstones": bank_state.tombstones,
        "portable_evidence_leaves": bank_state.portable_evidence_leaves,
        "checkpoints": bank_state.checkpoints,
    }
    populated = sorted(name for name, values in forbidden_nonempty.items() if values)
    if populated:
        raise ValueError(
            "generation-zero anchor contains scientific evidence/credit: "
            + ",".join(populated)
        )


def _bundle(
    *,
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
    manifest: SourceManifest,
    registry: PhaseArtifactRegistry,
    bank: FactorBankV2,
    edge: RegisteredPhaseFactorEdgeV3,
    phase_bytes: bytes,
    factor_bytes: bytes,
) -> StructuralAnchorBundleV1:
    proof = registry.resolve_proof(edge.proof)
    source_artifact = registry.resolve_artifact(proof.source_artifact)
    target_artifact = registry.resolve_artifact(proof.target_artifact)
    bank_state = bank.to_state()
    snapshot = bank_state.deployment_snapshots[0]
    body = {
        "schema_version": STRUCTURAL_ANCHOR_VERSION,
        "anchor_plan_sha256": plan.digest,
        "source_authority_sha256": _authority_commitment(source_authority_key),
        "source_manifest_sha256": manifest.manifest_sha256,
        "namespace_sha256": plan.namespace.digest,
        "locus": plan.anchor_locus,
        "source_program_sha256": phase_program_digest(source_artifact.program),
        "target_program_sha256": phase_program_digest(target_artifact.program),
        "phase_registry_state_sha256": registry.scientific_state_sha256,
        "factor_bank_state_sha256": bank.scientific_state_sha256,
        "phase_registry_envelope_sha256": _file_sha256(phase_bytes),
        "factor_bank_envelope_sha256": _file_sha256(factor_bytes),
        "proof_id": edge.proof.handle_id,
        "proof_sha256": edge.proof.proof_sha256,
        "transition_id": edge.transition.transition_id,
        "source_factor_revision_id": edge.source_factor.revision_id,
        "target_factor_revision_id": edge.target_factor.revision_id,
        "source_composition_id": edge.source_composition.composition_id,
        "target_composition_id": edge.target_composition.composition_id,
        "base_receipt_id": bank_state.base_receipts[0].receipt_id,
        "base_snapshot_id": snapshot.snapshot_id,
        "zero_evidence": StructuralZeroEvidenceV1(),
        "root_policy": "freeze_first_exact_native_envelopes",
        "exact_root_requires_one_time_freeze": True,
    }
    return StructuralAnchorBundleV1(
        **body,
        anchor_root_sha256=_sha256(body),
    )


def _fresh_root(value: str | Path) -> tuple[Path, Path, Path]:
    supplied = Path(value)
    if not supplied.is_absolute():
        raise ValueError("structural anchor root must be absolute")
    normalized = Path(os.path.abspath(os.fspath(supplied)))
    if normalized != supplied:
        raise ValueError("structural anchor root must not contain dot segments")
    for ancestor in (normalized, *normalized.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError("structural anchor root must not traverse a symlink")
    normalized.mkdir(mode=0o700, parents=True, exist_ok=True)
    normalized.chmod(0o700)
    phase_path = normalized / _PHASE_FILENAME
    factor_path = normalized / _FACTOR_FILENAME
    if phase_path.exists() or factor_path.exists():
        raise FileExistsError("structural anchor native envelope already exists")
    return normalized, phase_path, factor_path


def _existing_root(value: str | Path) -> tuple[Path, Path, Path]:
    supplied = Path(value)
    if not supplied.is_absolute():
        raise ValueError("structural anchor root must be absolute")
    normalized = Path(os.path.abspath(os.fspath(supplied)))
    if normalized != supplied:
        raise ValueError("structural anchor root must not contain dot segments")
    for ancestor in (normalized, *normalized.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError("structural anchor root must not traverse a symlink")
    phase_path = normalized / _PHASE_FILENAME
    factor_path = normalized / _FACTOR_FILENAME
    if phase_path.is_symlink() or factor_path.is_symlink():
        raise ValueError("structural anchor envelope must not be a symlink")
    return normalized, phase_path, factor_path


def build_structural_anchor_v1(
    root: str | Path,
    *,
    plan: StructuralAnchorPlanV1,
    source_authority_key: bytes,
    phase_registry_key: bytes,
    factor_bank_key: bytes,
) -> StructuralAnchorRuntimeV1:
    """Build one structural-only anchor and freeze its native envelopes once."""

    plan = StructuralAnchorPlanV1.model_validate(plan.model_dump(mode="python"))
    source_authority_key = _require_key(
        source_authority_key,
        "source_authority_key",
    )
    phase_registry_key = _require_key(phase_registry_key, "phase_registry_key")
    factor_bank_key = _require_key(factor_bank_key, "factor_bank_key")
    _, phase_path, factor_path = _fresh_root(root)

    manifest = _source_manifest(plan, source_authority_key)
    registry = PhaseArtifactRegistry(
        registry_key=phase_registry_key,
        manifests=(manifest,),
        manifest_verifier=_manifest_verifier(plan, source_authority_key),
        branch_receipt_verifier=_branch_verifier(plan, source_authority_key),
    )
    profile = registry.register_runtime_profile(
        namespace=plan.namespace,
        limits=plan.limits,
    )
    ingress = registry.issue_ingress(manifest.manifest_sha256)
    source = registry.ingest_program(
        plan.source_program,
        runtime_profile=profile,
        ingress=ingress,
    )
    extracted = registry.extract_factor(
        source,
        locator=plan.anchor_locus,
    )
    branch_body = _canonical_branch_body(
        plan=plan,
        source_authority_key=source_authority_key,
        source_artifact=source,
        runtime_profile=profile,
        descriptor=extracted.descriptor,
        source_factor=extracted.factor,
        manifest=manifest,
    )
    branch_receipt = registry.register_branch_receipt(
        branch="mutate",
        source_artifact=source,
        locator=plan.anchor_locus,
        mutation_parent_factor=extracted.factor,
        additional_input_root_commitments=(
            plan.digest,
            _authority_commitment(source_authority_key),
        ),
        producer_epoch=_BRANCH_PRODUCER_EPOCH,
        attestation_sha256=branch_body.attestation_sha256,
    )
    seal = registry.seal_operation(branch_receipt=branch_receipt)
    generated = registry.register_generated_value(
        plan.anchor_target_value,
        operation_seal=seal,
        ingress=ingress,
    )
    proof = registry.materialize(
        operation_seal=seal,
        target_factor=generated.factor,
    )
    if not isinstance(proof, PhaseBindingProofHandle):
        raise RuntimeError("canonical structural anchor unexpectedly materialized a no-op")
    proof_record = registry.resolve_proof(proof)
    target_artifact = registry.resolve_artifact(proof_record.target_artifact)
    if target_artifact.program != plan.target_program:
        raise RuntimeError("canonical structural anchor target differs from its plan")

    bank = FactorBankV2(
        state_key=factor_bank_key,
        direct_binding_verifier=make_phase_v3_binding_verifier(registry),
        base_snapshot_verifier=_base_verifier(plan, source_authority_key),
    )
    edge = register_phase_materialization_v3(
        registry=registry,
        bank=bank,
        proof=proof,
    )
    base_receipt = _base_receipt(
        plan=plan,
        source_authority_key=source_authority_key,
        bank=bank,
        edge=edge,
    )
    bank.register_base_snapshot(base_receipt)
    _validate_zero_evidence_state(
        registry_state=registry.to_state(),
        bank_state=bank.to_state(),
        manifest=manifest,
        edge=edge,
    )

    registry.save(phase_path)
    bank.save(factor_path)
    phase_bytes = phase_path.read_bytes()
    factor_bytes = factor_path.read_bytes()
    bundle = _bundle(
        plan=plan,
        source_authority_key=source_authority_key,
        manifest=manifest,
        registry=registry,
        bank=bank,
        edge=edge,
        phase_bytes=phase_bytes,
        factor_bytes=factor_bytes,
    )
    return StructuralAnchorRuntimeV1(
        bundle=bundle,
        registry=registry,
        bank=bank,
        phase_registry_path=phase_path,
        factor_bank_path=factor_path,
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )


def load_structural_anchor_v1(
    root: str | Path,
    *,
    plan: StructuralAnchorPlanV1,
    expected_bundle: StructuralAnchorBundleV1,
    source_authority_key: bytes,
    phase_registry_key: bytes,
    factor_bank_key: bytes,
) -> StructuralAnchorRuntimeV1:
    """Native-reload exact frozen envelopes and rederive every public root."""

    plan = StructuralAnchorPlanV1.model_validate(plan.model_dump(mode="python"))
    expected_bundle = StructuralAnchorBundleV1.model_validate(
        expected_bundle.model_dump(mode="python")
    )
    source_authority_key = _require_key(
        source_authority_key,
        "source_authority_key",
    )
    phase_registry_key = _require_key(phase_registry_key, "phase_registry_key")
    factor_bank_key = _require_key(factor_bank_key, "factor_bank_key")
    _, phase_path, factor_path = _existing_root(root)
    phase_bytes = phase_path.read_bytes()
    factor_bytes = factor_path.read_bytes()
    if not hmac.compare_digest(
        _file_sha256(phase_bytes),
        expected_bundle.phase_registry_envelope_sha256,
    ) or not hmac.compare_digest(
        _file_sha256(factor_bytes),
        expected_bundle.factor_bank_envelope_sha256,
    ):
        raise ValueError("structural anchor exact envelope digest mismatch")

    manifest = _source_manifest(plan, source_authority_key)
    registry = PhaseArtifactRegistry.load(
        phase_path,
        registry_key=phase_registry_key,
        manifest_verifier=_manifest_verifier(plan, source_authority_key),
        branch_receipt_verifier=_branch_verifier(plan, source_authority_key),
    )
    bank = FactorBankV2.load(
        factor_path,
        state_key=factor_bank_key,
        direct_binding_verifier=make_phase_v3_binding_verifier(registry),
        base_snapshot_verifier=_base_verifier(plan, source_authority_key),
    )
    proof_records = registry.to_state().proofs
    if len(proof_records) != 1:
        raise ValueError("frozen structural anchor lost its unique Phase proof")
    edge = register_phase_materialization_v3(
        registry=registry,
        bank=bank,
        proof=proof_records[0].handle,
    )
    _validate_zero_evidence_state(
        registry_state=registry.to_state(),
        bank_state=bank.to_state(),
        manifest=manifest,
        edge=edge,
    )
    actual_bundle = _bundle(
        plan=plan,
        source_authority_key=source_authority_key,
        manifest=manifest,
        registry=registry,
        bank=bank,
        edge=edge,
        phase_bytes=phase_bytes,
        factor_bytes=factor_bytes,
    )
    if actual_bundle != expected_bundle:
        raise ValueError("native-reloaded structural anchor differs from its frozen bundle")
    return StructuralAnchorRuntimeV1(
        bundle=actual_bundle,
        registry=registry,
        bank=bank,
        phase_registry_path=phase_path,
        factor_bank_path=factor_path,
        phase_registry_envelope_bytes=phase_bytes,
        factor_bank_envelope_bytes=factor_bytes,
    )


__all__ = [
    "STRUCTURAL_ANCHOR_LOCATOR",
    "STRUCTURAL_ANCHOR_VERSION",
    "StructuralAnchorBundleV1",
    "StructuralAnchorPlanV1",
    "StructuralAnchorRuntimeV1",
    "StructuralZeroEvidenceV1",
    "build_structural_anchor_v1",
    "load_structural_anchor_v1",
]
