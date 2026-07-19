"""Default-off Sealed Factor-Transition Bank (SFT-Bank) lifecycle.

The indivisible algorithmic object is a sealed, comparator-conditioned
transition.  The same object is the legal search move, the sole owner of paired
evidence, and the only route to a deployment opportunity.  Factor and complete
composition revisions carry structural storage state only; efficacy is never
copied onto reusable content.

This module intentionally lives beside the legacy research skeleton.  A v1
state cannot be causally upgraded because it lacks frozen assignment bodies,
complete execution receipts, recomputable assessments and deployment heads.
The v2 implementation is default-off and rejects legacy persistence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
import re
import fcntl
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.mas.factor_bank import (
    BindingStatus,
    DenseDelta,
    DenseOutcome,
    ExecutionBudget,
    ExecutionNamespace,
    ExecutionUsage,
    FactorCarrier,
    FactorLocator,
    SlotBinding,
    assert_bank_safe_public_value,
)
from exp_graph.mas.sft_proposal import (
    CandidateCounterWitnessV1,
    EdgeProposalPolicyV1,
    ExactFactorLocusV1,
    ExactProposalCellV1,
    LineageNicheV1,
    MAX_EXACT_JOIN_ID_CHARS,
    MAX_PROPOSAL_INPUT_BYTES,
    MAX_PROPOSAL_RECEIPT_BYTES,
    PortableBackgroundSignV1,
    PortableCandidateV1,
    ProposalCounterDeltaV1,
    ProposalCursorV1,
    ProposalRequestV1,
    ProposalReceiptV1,
    SFTProposalInputV1,
    proposal_counter_state_sha256,
    proposal_slate_fits_byte_bounds,
    replay_validate_proposal_receipt,
    select_exact_edge_proposal,
)


SFT_BANK_SCHEMA_VERSION = "sft_factor_transition_v14"
OwnerKind = Literal["direct_factor", "whole_composition"]
OriginBranch = Literal["reuse", "mutate", "fresh", "migration"]
ScientificBranch = Literal["reuse", "mutate", "fresh"]
ProposalActionState = Literal["prepared", "executing", "committed", "aborted"]
CarrierAdmissionState = Literal["staged", "admitted", "quarantined"]
StructuralState = Literal["live", "cold", "tombstone", "quarantine"]
AttemptState = Literal["open", "complete", "incomplete", "quarantine", "cancelled"]
Vote = Literal["benefit", "harm", "null"]
PortableEvidenceSign = Literal[
    "benefit", "harm", "null", "all_zero", "infrastructure"
]
AssessmentLabel = Literal[
    "registered",
    "probing",
    "candidate",
    "neutral",
    "harmful",
    "infrastructure_exhausted",
    "quarantine",
]
OpportunityState = Literal[
    "pending", "revoked", "consumed", "rejected", "capacity_rejected"
]
HeadState = Literal["active", "disabled"]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# Prepared actions already contain the full bounded generation request.  The
# only Bank-generated growth before carrier projection is one generation lease
# plus one admission; every identifier is capped at 128 characters and every
# digest at 64.  This deliberately conservative slab is checked at PREPARE so
# a caller cannot configure a profile that starts a model call but cannot even
# serialize its trusted successor records.
_GENERATED_OWNER_SUCCESSOR_OVERHEAD_BYTES = 16 * 1024
# Selector input and receipt each retain their independent 64-KiB contracts.
# A persisted decision repeats bounded exact-join identifiers and may also own
# one verified generation context, so it has a separate frozen slab instead of
# silently borrowing either selector bound.  The 32-KiB closure allowance is
# deliberately charged again by the aggregate 64-MiB proposal/action budget.
MAX_PROPOSAL_DECISION_BYTES = MAX_PROPOSAL_RECEIPT_BYTES + 32 * 1024


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
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


def _mac(key: bytes, domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\0" + _canonical_json(value).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _opaque_id(prefix: str, value: Any) -> str:
    return f"{prefix}:{_sha256(value)[:24]}"


_BRANCH_SELECTOR_POLICY_SHA256 = _sha256(
    {
        "name": "sft_namespace_deficit_branch_v1",
        "scope": "exact_execution_namespace",
        "branches": ("reuse", "mutate", "fresh"),
        "choice": "least_assigned_then_public_hash_max",
        "one_shot_per_repair_opportunity": True,
    }
)

_PROPOSAL_CONDITIONED_BRANCH_POLICY_SHA256 = _sha256(
    {
        "name": "sft_proposal_conditioned_namespace_deficit_v2",
        "scope": "exact_execution_namespace",
        "proposal_law": "sft_exact_edge_proposal_v5",
        "reuse_feasible_iff": "receipt_has_exact_safe_target",
        "choice": (
            "least_assigned_then_public_hash_max_of_alias_free_scheduler_decision"
        ),
        "one_shot_per_repair_opportunity": True,
    }
)

_PROPOSAL_CANDIDATE_SLATE_POLICY_SHA256 = _sha256(
    {
        "name": "sft_host_complete_candidate_slate_v4",
        "eligibility": (
            "live canonical content owner at exact namespace/logical factor/"
            "carrier/locator, with host-replayed carrier admission authority, "
            "not aliasing the canonical comparator, and at most 50 "
            "authoritative background signs"
        ),
        "exposure_identity": (
            "canonical comparator/target/lineage keys; exact revisions remain "
            "execution joins only"
        ),
        "max_candidates": 16,
        "max_proposal_input_bytes": MAX_PROPOSAL_INPUT_BYTES,
        "max_proposal_receipt_bytes": MAX_PROPOSAL_RECEIPT_BYTES,
        "exact_join_id_reservation_chars": MAX_EXACT_JOIN_ID_CHARS,
        "overflow": (
            "public canonical-cell/committed-lifetime-ordinal sha256 reservoir"
        ),
        "admission": (
            "canonical-rank greedy dual-byte dry-run with fixed worst-case exact "
            "join reservations plus actual rooted lifetime-counter witnesses; "
            "skip oversized candidates and continue"
        ),
        "selector_policy": EdgeProposalPolicyV1().digest,
    }
)


def _proposal_conditioned_branch_tiebreak_sha256(
    *,
    public_seed: int,
    proposal_scheduler_decision_sha256: str,
    branch: ScientificBranch,
) -> str:
    """Alias-free tie key; exact receipt/opportunity IDs are replay joins only."""

    _require_sha(
        proposal_scheduler_decision_sha256,
        "proposal_scheduler_decision_sha256",
    )
    return _sha256(
        {
            "seed": public_seed,
            "proposal_scheduler_decision": proposal_scheduler_decision_sha256,
            "branch": branch,
        }
    )


def _host_proposal_scheduler_decision_sha256(
    *,
    receipt: ProposalReceiptV1,
    candidate_universe_sha256: str,
    candidate_universe_count: int,
) -> str:
    """Bind the pure alias-free selector decision to the complete host universe."""

    _require_sha(candidate_universe_sha256, "candidate_universe_sha256")
    return _sha256(
        {
            "selector_scheduler_decision_sha256": (
                receipt.proposal_scheduler_decision_sha256
            ),
            "host_candidate_universe_sha256": candidate_universe_sha256,
            "host_candidate_universe_count": candidate_universe_count,
            "candidate_slate_scheduler_sha256": (
                receipt.candidate_slate_scheduler_sha256
            ),
            "selected_target_factor_key_sha256": (
                receipt.selected_target_factor_key_sha256
            ),
        }
    )


def _atomic_bank_update(method: Callable[..., Any]) -> Callable[..., Any]:
    """Publish one public Bank mutation only after validation and owned-file CAS."""

    @wraps(method)
    def wrapped(self: "FactorBankV2", *args: Any, **kwargs: Any) -> Any:
        # A shared depth counter is safe only while one OS thread owns the
        # instance.  The re-entrant lock preserves intentional nested Bank
        # mutations while giving every cross-thread call one linearization
        # point.  File CAS remains the separate cross-process fence.
        with self._mutation_lock:
            with self._atomic_update():
                return method(self, *args, **kwargs)

    return wrapped


def _linearized_bank_read(method: Callable[..., Any]) -> Callable[..., Any]:
    """Return one authoritative view outside any provisional write window."""

    @wraps(method)
    def wrapped(self: "FactorBankV2", *args: Any, **kwargs: Any) -> Any:
        # Mutations may publish several immutable candidate states inside one
        # outer transaction and then roll all of them back.  A public read must
        # share that transaction's linearization lock or another OS thread can
        # observe a candidate that never committed.
        with self._mutation_lock:
            return method(self, *args, **kwargs)

    return wrapped


def _require_id(value: str, name: str) -> None:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be an opaque identifier")


def _require_sha(value: str, name: str) -> None:
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def reject_private_or_oracle_values(self) -> "_ClosedModel":
        assert_bank_safe_public_value(self.model_dump(mode="python"))
        return self


class FactorRevisionV2(_ClosedModel):
    revision_id: str
    logical_factor_id: str
    namespace: ExecutionNamespace
    carrier: FactorCarrier
    locator: FactorLocator
    binding_status: BindingStatus
    content_sha256: str
    parent_revision_id: str | None = None
    origin_branch: OriginBranch = "migration"
    insight_ids: tuple[str, ...] = ()
    failure_hypothesis_ids: tuple[str, ...] = ()
    structural_state: StructuralState = "live"
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_factor(self) -> "FactorRevisionV2":
        for name in ("revision_id", "logical_factor_id"):
            _require_id(str(getattr(self, name)), name)
        _require_sha(self.content_sha256, "content_sha256")
        if self.parent_revision_id is not None:
            _require_id(self.parent_revision_id, "parent_revision_id")
        if self.binding_status == "locked_atomic" and self.locator.surface != "atomic_artifact":
            raise ValueError("locked_atomic factors require an atomic locator")
        if self.binding_status == "proven_factorized" and self.locator.surface == "atomic_artifact":
            raise ValueError("factorized content requires a host-owned non-atomic locator")
        return self


class CompositionRevisionV2(_ClosedModel):
    composition_id: str
    namespace: ExecutionNamespace
    carrier: Literal[
        "named_topology", "paper_transport", "graph", "phase_program", "python_source"
    ]
    artifact_revision_id: str
    artifact_sha256: str
    bindings: tuple[SlotBinding, ...]
    origin_branch: OriginBranch = "migration"
    parent_composition_id: str | None = None
    structural_state: StructuralState = "live"
    canonical_metadata_bytes: int = Field(default=0, ge=0)
    artifact_bytes: int = Field(default=0, ge=0)
    prompt_summary_tokens: int = Field(default=0, ge=0)
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_composition(self) -> "CompositionRevisionV2":
        _require_id(self.composition_id, "composition_id")
        _require_id(self.artifact_revision_id, "artifact_revision_id")
        _require_sha(self.artifact_sha256, "artifact_sha256")
        if self.parent_composition_id is not None:
            _require_id(self.parent_composition_id, "parent_composition_id")
        slots = [item.slot_id for item in self.bindings]
        if not slots or len(slots) != len(set(slots)):
            raise ValueError("composition bindings must contain unique slots")
        expected = {
            "named_topology_skill_v1": "named_topology",
            "paper_transport_skill_v1": "paper_transport",
            "graph_skill_v1": "graph",
            "phase_program_skill_v1": "phase_program",
            "python_skill_v1": "python_source",
        }[self.namespace.payload_format]
        if self.carrier != expected:
            raise ValueError("composition carrier crosses its payload namespace")
        return self

    @property
    def binding_map(self) -> dict[str, str]:
        return {item.slot_id: item.factor_revision_id for item in self.bindings}


class DirectFactorTransitionV2(_ClosedModel):
    owner_kind: Literal["direct_factor"] = "direct_factor"
    transition_id: str
    namespace: ExecutionNamespace
    source_composition_id: str
    target_composition_id: str
    slot_id: str
    from_revision_id: str
    to_revision_id: str
    fixed_background_sha256: str
    masked_background_sha256: str
    binding_proof_id: str
    binding_proof_sha256: str
    binding_verifier_epoch: str
    origin_branch: ScientificBranch
    proposal_action_id: str | None = None
    proposal_action_intent_sha256: str | None = None
    proposal_action_committed_seq: int | None = Field(default=None, ge=0)
    structural_state: StructuralState = "live"
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_direct_ids(self) -> "DirectFactorTransitionV2":
        for name in (
            "transition_id", "source_composition_id", "target_composition_id",
            "slot_id", "from_revision_id", "to_revision_id", "binding_proof_id",
            "binding_verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "fixed_background_sha256", "masked_background_sha256", "binding_proof_sha256"
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.from_revision_id == self.to_revision_id:
            raise ValueError("direct factor transition must change content")
        action_fields = (
            self.proposal_action_id,
            self.proposal_action_intent_sha256,
        )
        if any(item is None for item in action_fields) != all(
            item is None for item in action_fields
        ):
            raise ValueError("direct transition proposal action closure is partial")
        if self.proposal_action_id is None:
            if self.proposal_action_committed_seq is not None:
                raise ValueError("ordinary transition cannot claim action commit")
        else:
            _require_id(self.proposal_action_id, "proposal_action_id")
            assert self.proposal_action_intent_sha256 is not None
            _require_sha(
                self.proposal_action_intent_sha256,
                "proposal_action_intent_sha256",
            )
            if (
                self.proposal_action_committed_seq is not None
                and self.proposal_action_committed_seq <= self.created_seq
            ):
                raise ValueError("proposal action must commit after edge projection")
        return self


class WholeCompositionTransitionV2(_ClosedModel):
    owner_kind: Literal["whole_composition"] = "whole_composition"
    transition_id: str
    namespace: ExecutionNamespace
    source_composition_id: str
    target_composition_id: str
    changed_slot_ids: tuple[str, ...]
    source_artifact_sha256: str
    target_artifact_sha256: str
    operation_receipt_sha256: str
    operation_verifier_epoch: str
    origin_branch: ScientificBranch
    structural_state: StructuralState = "live"
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_whole_ids(self) -> "WholeCompositionTransitionV2":
        for name in (
            "transition_id", "source_composition_id", "target_composition_id",
            "operation_verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        if not self.changed_slot_ids or len(self.changed_slot_ids) != len(set(self.changed_slot_ids)):
            raise ValueError("whole-composition transition needs unique changed slots")
        for item in self.changed_slot_ids:
            _require_id(item, "changed_slot_id")
        for name in (
            "source_artifact_sha256", "target_artifact_sha256", "operation_receipt_sha256"
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.source_artifact_sha256 == self.target_artifact_sha256:
            raise ValueError("whole-composition transition requires distinct artifacts")
        return self


ScientificTransitionV2 = DirectFactorTransitionV2 | WholeCompositionTransitionV2


class AggregatePolicyV1(_ClosedModel):
    policy_name: Literal["factor_probe_aggregate_v1"] = "factor_probe_aggregate_v1"
    target_complete_blocks: Literal[4] = 4
    min_complete_blocks: Literal[2] = 2
    max_attempted_blocks: Literal[6] = 6
    max_open_attempts: Literal[1] = 1
    benefit_quorum_numerator: Literal[3] = 3
    benefit_quorum_denominator: Literal[4] = 4
    harm_quorum_numerator: Literal[1] = 1
    harm_quorum_denominator: Literal[2] = 2
    require_zero_harm_for_candidate: Literal[True] = True
    min_dense_delta: float = Field(default=0.01, ge=0, allow_inf_nan=False)
    partial_tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    numeric_tolerance: float = Field(default=1e-12, gt=0, allow_inf_nan=False)
    bootstrap_samples: int = Field(default=2000, ge=1, le=100_000)
    bootstrap_seed: int = 20260713
    strict_gate_config_sha256: str = Field(
        default_factory=lambda: _sha256("strict-dense-v2")
    )

    @model_validator(mode="after")
    def validate_policy(self) -> "AggregatePolicyV1":
        _require_sha(self.strict_gate_config_sha256, "strict_gate_config_sha256")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ProbeUnitV2(_ClosedModel):
    ordinal: int = Field(ge=0, le=5)
    role: Literal["primary", "reserve"]
    unit_commitment: str
    arm_order: Literal["AB", "BA"]

    @model_validator(mode="after")
    def validate_unit(self) -> "ProbeUnitV2":
        _require_sha(self.unit_commitment, "unit_commitment")
        return self


class ProbePlanV2(_ClosedModel):
    plan_id: str
    epoch_id: str
    owner_kind: OwnerKind
    transition_id: str
    canonical_scientific_edge_key_sha256: str
    canonical_background_sha256: str
    credit_owner_transition_id: str
    namespace_digest: str
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    source_snapshot_sha256: str
    target_snapshot_sha256: str
    source_artifact_sha256: str
    target_artifact_sha256: str
    fixed_background_sha256: str
    binding_or_operation_proof_sha256: str
    aggregate_policy: AggregatePolicyV1
    aggregate_policy_sha256: str
    units: tuple[ProbeUnitV2, ...]
    assignment_manifest_sha256: str
    runner_version: str
    model_name: str = Field(min_length=1, max_length=100)
    runtime_version: str
    budget: ExecutionBudget
    budget_sha256: str
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_plan(self) -> "ProbePlanV2":
        for name in (
            "plan_id", "epoch_id", "transition_id",
            "credit_owner_transition_id", "runner_version", "runtime_version",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "canonical_scientific_edge_key_sha256",
            "canonical_background_sha256", "namespace_digest",
            "source_snapshot_sha256", "target_snapshot_sha256",
            "source_artifact_sha256", "target_artifact_sha256", "fixed_background_sha256",
            "binding_or_operation_proof_sha256", "aggregate_policy_sha256",
            "assignment_manifest_sha256", "budget_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.aggregate_policy_sha256 != self.aggregate_policy.digest:
            raise ValueError("probe plan policy digest mismatch")
        if self.budget_sha256 != self.budget.digest:
            raise ValueError("probe plan budget digest mismatch")
        if len(self.units) != 6 or [item.ordinal for item in self.units] != list(range(6)):
            raise ValueError("probe plan must freeze ordinals 0..5")
        if [item.role for item in self.units] != [
            "primary", "primary", "primary", "primary", "reserve", "reserve"
        ]:
            raise ValueError("probe plan must freeze four primary and two reserve units")
        if len({item.unit_commitment for item in self.units}) != 6:
            raise ValueError("probe plan units must be unique")
        if sum(item.arm_order == "AB" for item in self.units[:4]) != 2:
            raise ValueError("primary arm order must be balanced 2/2")
        if sum(item.arm_order == "AB" for item in self.units) != 3:
            raise ValueError("full arm order must be balanced 3/3")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class AssignmentReceiptV2(_ClosedModel):
    assignment_receipt_id: str
    plan_id: str
    plan_sha256: str
    ordinal: int = Field(ge=0, le=5)
    unit_commitment: str
    arm_order: Literal["AB", "BA"]
    origin_pool_sha256: str
    assignment_manifest_sha256: str
    without_replacement_index: int = Field(ge=0)
    producer_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_assignment(self) -> "AssignmentReceiptV2":
        for name in ("assignment_receipt_id", "plan_id", "producer_epoch"):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "plan_sha256", "unit_commitment", "origin_pool_sha256",
            "assignment_manifest_sha256", "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self


class RunnerLeaseGrantV1(_ClosedModel):
    """Host-journal authority for exactly one generation-1 attempt."""

    lease_version: Literal["runner_lease_v1"] = "runner_lease_v1"
    lease_id: str
    attempt_id: str
    plan_id: str
    ordinal: int = Field(ge=0, le=5)
    assignment_receipt_sha256: str
    scheduled_arm_order: Literal["AB", "BA"]
    runner_session_id: str
    runner_lease_token_sha256: str
    fencing_generation: Literal[1] = 1
    journal_anchor_sha256: str
    verifier_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_lease(self) -> "RunnerLeaseGrantV1":
        for name in (
            "lease_id", "attempt_id", "plan_id", "runner_session_id",
            "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "assignment_receipt_sha256", "runner_lease_token_sha256",
            "journal_anchor_sha256", "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        body = self.model_dump(mode="python", exclude={"lease_id", "attestation_sha256"})
        if self.lease_id != _opaque_id("rl", body):
            raise ValueError("runner lease identity is not reproducible")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


def runner_schedule_commitment_v1(
    *,
    expected_open_attempt_sha256: str,
    assignment_receipt_sha256: str,
    plan_id: str,
    ordinal: int,
    scheduled_arm_order: Literal["AB", "BA"],
    runner_session_id: str,
    runner_lease_token_sha256: str,
    fencing_generation: int,
    journal_anchor_sha256: str,
    prestart_schedule_event_id: str,
    prestart_schedule_event_seq: int,
) -> str:
    return _sha256(
        {
            "domain": "sft-runner-schedule-v1",
            "expected_open_attempt_sha256": expected_open_attempt_sha256,
            "assignment_receipt_sha256": assignment_receipt_sha256,
            "plan_id": plan_id,
            "ordinal": ordinal,
            "scheduled_arm_order": scheduled_arm_order,
            "runner_session_id": runner_session_id,
            "runner_lease_token_sha256": runner_lease_token_sha256,
            "fencing_generation": fencing_generation,
            "journal_anchor_sha256": journal_anchor_sha256,
            "prestart_schedule_event_id": prestart_schedule_event_id,
            "prestart_schedule_event_seq": prestart_schedule_event_seq,
        }
    )


def pair_event_root_v1(
    *,
    journal_anchor_sha256: str,
    schedule_commitment_sha256: str,
    observed_arm_order: Literal["AB", "BA"],
    source_root_id: str,
    target_root_id: str,
    source_started_event_id: str,
    source_started_seq: int,
    source_finished_event_id: str,
    source_finished_seq: int,
    target_started_event_id: str,
    target_started_seq: int,
    target_finished_event_id: str,
    target_finished_seq: int,
    terminal_event_id: str,
    terminal_event_seq: int,
    runner_lease_token_sha256: str,
    fencing_generation: int,
) -> str:
    chain = _sha256(
        {
            "domain": "sft-pair-event-v1",
            "previous": journal_anchor_sha256,
            "schedule": schedule_commitment_sha256,
        }
    )
    events = (
        (
            "source", source_root_id, source_started_event_id,
            source_started_seq, source_finished_event_id, source_finished_seq,
        ),
        (
            "target", target_root_id, target_started_event_id,
            target_started_seq, target_finished_event_id, target_finished_seq,
        ),
    )
    if observed_arm_order == "BA":
        events = (events[1], events[0])
    for arm, root_id, start_id, start_seq, finish_id, finish_seq in events:
        for event_kind, event_id, event_seq in (
            ("start", start_id, start_seq), ("finish", finish_id, finish_seq)
        ):
            chain = _sha256(
                {
                    "domain": "sft-pair-event-v1",
                    "previous": chain,
                    "event_kind": event_kind,
                    "event_id": event_id,
                    "event_seq": event_seq,
                    "arm": arm,
                    "root_id": root_id,
                }
            )
    return _sha256(
        {
            "domain": "sft-pair-event-v1",
            "previous": chain,
            "event_kind": "pair_complete",
            "event_id": terminal_event_id,
            "event_seq": terminal_event_seq,
            "runner_lease_token_sha256": runner_lease_token_sha256,
            "fencing_generation": fencing_generation,
        }
    )


class PairExecutionReceiptV2(_ClosedModel):
    """Reproducible generation-1 pair terminal from the host journal."""

    receipt_version: Literal["pair_execution_v2"] = "pair_execution_v2"
    pair_receipt_id: str
    plan_id: str
    ordinal: int = Field(ge=0, le=5)
    assignment_receipt_sha256: str
    expected_open_attempt_sha256: str
    scheduled_arm_order: Literal["AB", "BA"]
    runner_lease_sha256: str
    runner_lease_token_sha256: str
    fencing_generation: Literal[1] = 1
    journal_anchor_sha256: str
    source_root_id: str
    target_root_id: str
    prestart_schedule_event_id: str
    prestart_schedule_event_seq: int = Field(ge=0)
    schedule_commitment_sha256: str
    source_started_event_id: str
    target_started_event_id: str
    source_finished_event_id: str
    target_finished_event_id: str
    source_started_seq: int = Field(ge=0)
    target_started_seq: int = Field(ge=0)
    source_finished_seq: int = Field(ge=0)
    target_finished_seq: int = Field(ge=0)
    terminal_event_id: str
    terminal_event_seq: int = Field(ge=0)
    observed_arm_order: Literal["AB", "BA"]
    runner_session_id: str
    runner_event_root_sha256: str
    verifier_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_pair_execution(self) -> "PairExecutionReceiptV2":
        for name in (
            "pair_receipt_id", "plan_id", "prestart_schedule_event_id",
            "source_started_event_id", "target_started_event_id",
            "source_finished_event_id", "target_finished_event_id",
            "terminal_event_id", "runner_session_id", "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "assignment_receipt_sha256", "expected_open_attempt_sha256",
            "runner_lease_sha256", "runner_lease_token_sha256",
            "journal_anchor_sha256", "schedule_commitment_sha256",
            "source_root_id", "target_root_id", "runner_event_root_sha256",
            "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.source_root_id == self.target_root_id:
            raise ValueError("paired execution requires distinct physical arm roots")
        if self.source_started_event_id == self.target_started_event_id:
            raise ValueError("paired execution requires distinct arm-start events")
        event_ids = (
            self.prestart_schedule_event_id,
            self.source_started_event_id,
            self.target_started_event_id,
            self.source_finished_event_id,
            self.target_finished_event_id,
            self.terminal_event_id,
        )
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("paired execution event ids must be unique")
        if self.source_started_seq == self.target_started_seq:
            raise ValueError("paired execution arm starts require a strict order")
        if not (
            self.source_started_seq < self.source_finished_seq
            and self.target_started_seq < self.target_finished_seq
        ):
            raise ValueError("paired execution arm spans are reversed")
        observed = (
            "AB" if self.source_started_seq < self.target_started_seq else "BA"
        )
        if self.observed_arm_order != observed:
            raise ValueError("observed arm order is not derived from runner events")
        nonoverlap = (
            self.source_finished_seq < self.target_started_seq
            if observed == "AB"
            else self.target_finished_seq < self.source_started_seq
        )
        if not nonoverlap:
            raise ValueError("paired execution arms overlap or violate physical order")
        event_seqs = (
            self.prestart_schedule_event_seq,
            self.source_started_seq,
            self.source_finished_seq,
            self.target_started_seq,
            self.target_finished_seq,
            self.terminal_event_seq,
        )
        if len(set(event_seqs)) != len(event_seqs):
            raise ValueError("paired execution event sequences must be unique")
        if self.prestart_schedule_event_seq >= min(
            self.source_started_seq, self.target_started_seq
        ) or self.terminal_event_seq <= max(
            self.source_finished_seq, self.target_finished_seq
        ):
            raise ValueError("paired terminal does not bound the exact arm journal")
        expected_schedule = runner_schedule_commitment_v1(
            expected_open_attempt_sha256=self.expected_open_attempt_sha256,
            assignment_receipt_sha256=self.assignment_receipt_sha256,
            plan_id=self.plan_id,
            ordinal=self.ordinal,
            scheduled_arm_order=self.scheduled_arm_order,
            runner_session_id=self.runner_session_id,
            runner_lease_token_sha256=self.runner_lease_token_sha256,
            fencing_generation=self.fencing_generation,
            journal_anchor_sha256=self.journal_anchor_sha256,
            prestart_schedule_event_id=self.prestart_schedule_event_id,
            prestart_schedule_event_seq=self.prestart_schedule_event_seq,
        )
        if self.schedule_commitment_sha256 != expected_schedule:
            raise ValueError("pair schedule commitment is not reproducible")
        expected_root = pair_event_root_v1(
            journal_anchor_sha256=self.journal_anchor_sha256,
            schedule_commitment_sha256=self.schedule_commitment_sha256,
            observed_arm_order=self.observed_arm_order,
            source_root_id=self.source_root_id,
            target_root_id=self.target_root_id,
            source_started_event_id=self.source_started_event_id,
            source_started_seq=self.source_started_seq,
            source_finished_event_id=self.source_finished_event_id,
            source_finished_seq=self.source_finished_seq,
            target_started_event_id=self.target_started_event_id,
            target_started_seq=self.target_started_seq,
            target_finished_event_id=self.target_finished_event_id,
            target_finished_seq=self.target_finished_seq,
            terminal_event_id=self.terminal_event_id,
            terminal_event_seq=self.terminal_event_seq,
            runner_lease_token_sha256=self.runner_lease_token_sha256,
            fencing_generation=self.fencing_generation,
        )
        if self.runner_event_root_sha256 != expected_root:
            raise ValueError("pair terminal event root is not reproducible")
        if self.runner_event_root_sha256 in {self.source_root_id, self.target_root_id}:
            raise ValueError("pair terminal root aliases a physical arm root")
        expected_id = _opaque_id(
            "px",
            {
                "attempt": self.expected_open_attempt_sha256,
                "runner_lease": self.runner_lease_sha256,
                "terminal_event_root": self.runner_event_root_sha256,
            },
        )
        if self.pair_receipt_id != expected_id:
            raise ValueError("pair receipt identity is not reproducible")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ArmReceiptV2(_ClosedModel):
    receipt_id: str
    plan_id: str
    ordinal: int = Field(ge=0, le=5)
    arm: Literal["source", "target"]
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    root_id: str
    observed_arm_order: Literal["AB", "BA"]
    arm_position: Literal[0, 1]
    paired_execution_root_sha256: str
    pair_execution_receipt_sha256: str
    assignment_receipt_sha256: str
    unit_commitment: str
    namespace_digest: str
    composition_id: str
    assigned_artifact_sha256: str
    materialized_artifact_sha256: str
    selected_artifact_sha256: str
    loaded_artifact_sha256: str
    loaded_binding_ids: tuple[str, ...]
    activated_direct_factor_revision_ids: tuple[str, ...]
    activation_trace_root: str
    runtime_profile_id: str
    materialization_event_id: str
    binding_proof_id: str
    model_name: str = Field(min_length=1, max_length=100)
    runtime_version: str
    budget_sha256: str
    usage: ExecutionUsage
    execution_class: Literal[
        "completed", "algorithm_failure", "infrastructure_failure", "harness_failure"
    ]
    outcome: DenseOutcome | None = None
    safe_failure_code: str | None = None
    failed_stage_rank: int | None = Field(default=None, ge=0)
    producer_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_receipt(self) -> "ArmReceiptV2":
        for name in (
            "receipt_id", "plan_id", "composition_id", "runtime_profile_id",
            "materialization_event_id", "binding_proof_id", "runtime_version", "producer_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "root_id", "assignment_receipt_sha256", "unit_commitment", "namespace_digest",
            "paired_execution_root_sha256",
            "pair_execution_receipt_sha256",
            "assigned_artifact_sha256", "materialized_artifact_sha256",
            "selected_artifact_sha256", "loaded_artifact_sha256", "activation_trace_root",
            "budget_sha256", "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        algorithmic = self.execution_class in {"completed", "algorithm_failure"}
        if (self.outcome is not None) != algorithmic:
            raise ValueError("only algorithmic receipts carry dense outcomes")
        if (self.safe_failure_code is not None) != (self.execution_class != "completed"):
            raise ValueError("non-completed receipts require a safe failure code")
        if (self.failed_stage_rank is not None) != (
            self.execution_class == "algorithm_failure"
        ):
            raise ValueError("only algorithm failures carry a failed stage rank")
        if self.safe_failure_code is not None:
            _require_id(self.safe_failure_code, "safe_failure_code")
        return self


class StartedArmJournalWitnessV2(_ClosedModel):
    arm: Literal["source", "target"]
    root_id: str
    start_event_id: str
    start_event_seq: int = Field(ge=0)
    finish_event_id: str | None = None
    finish_event_seq: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_witness(self) -> "StartedArmJournalWitnessV2":
        _require_sha(self.root_id, "root_id")
        _require_id(self.start_event_id, "start_event_id")
        if (self.finish_event_id is None) != (self.finish_event_seq is None):
            raise ValueError("arm finish event id and sequence must be paired")
        if self.finish_event_id is not None:
            _require_id(self.finish_event_id, "finish_event_id")
            if self.finish_event_id == self.start_event_id:
                raise ValueError("arm start and finish event ids must differ")
            assert self.finish_event_seq is not None
            if self.finish_event_seq <= self.start_event_seq:
                raise ValueError("arm finish must follow its start")
        return self


def cancellation_event_root_v3(
    *,
    journal_anchor_sha256: str,
    schedule_commitment_sha256: str,
    started_arm_roots: Sequence[StartedArmJournalWitnessV2],
    abort_event_id: str,
    abort_event_seq: int,
    cancel_kind: Literal["infrastructure", "harness"],
    safe_failure_code: str,
    terminate_scope: bool,
    runner_lease_token_sha256: str,
    fencing_generation: int,
    next_fencing_generation: int,
) -> str:
    chain = _sha256(
        {
            "domain": "sft-abort-event-v3",
            "previous": journal_anchor_sha256,
            "schedule": schedule_commitment_sha256,
        }
    )
    for witness in started_arm_roots:
        chain = _sha256(
            {
                "domain": "sft-abort-event-v3",
                "previous": chain,
                "start_event_id": witness.start_event_id,
                "start_event_seq": witness.start_event_seq,
                "arm": witness.arm,
                "root_id": witness.root_id,
            }
        )
        if witness.finish_event_id is not None:
            chain = _sha256(
                {
                    "domain": "sft-abort-event-v3",
                    "previous": chain,
                    "finish_event_id": witness.finish_event_id,
                    "finish_event_seq": witness.finish_event_seq,
                    "arm": witness.arm,
                    "root_id": witness.root_id,
                }
            )
    return _sha256(
        {
            "domain": "sft-abort-event-v3",
            "previous": chain,
            "abort_event_id": abort_event_id,
            "abort_event_seq": abort_event_seq,
            "cancel_kind": cancel_kind,
            "safe_failure_code": safe_failure_code,
            "terminate_scope": terminate_scope,
            "runner_lease_token_sha256": runner_lease_token_sha256,
            "fencing_generation": fencing_generation,
            "next_fencing_generation": next_fencing_generation,
        }
    )


class AttemptCancellationReceiptV3(_ClosedModel):
    """Authenticated zero/one/two-start generation-2 abort terminal."""

    receipt_version: Literal["attempt_cancellation_v3"] = "attempt_cancellation_v3"
    cancellation_id: str
    attempt_id: str
    plan_id: str
    ordinal: int = Field(ge=0, le=5)
    assignment_receipt_sha256: str
    expected_opened_seq: int = Field(ge=0)
    expected_open_attempt_sha256: str
    scheduled_arm_order: Literal["AB", "BA"]
    runner_lease_sha256: str
    runner_session_id: str
    runner_lease_token_sha256: str
    fencing_generation: Literal[1] = 1
    next_fencing_generation: Literal[2] = 2
    journal_anchor_sha256: str
    prestart_schedule_event_id: str
    prestart_schedule_event_seq: int = Field(ge=0)
    schedule_commitment_sha256: str
    started_arm_roots: tuple[StartedArmJournalWitnessV2, ...] = Field(
        default=(), max_length=2
    )
    abort_event_id: str
    abort_event_seq: int = Field(ge=0)
    runner_event_root_sha256: str
    cancel_kind: Literal["infrastructure", "harness"]
    safe_failure_code: str
    terminate_scope: bool = False
    verifier_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_cancellation(self) -> "AttemptCancellationReceiptV3":
        for name in (
            "cancellation_id", "attempt_id", "plan_id", "safe_failure_code",
            "runner_session_id", "prestart_schedule_event_id",
            "abort_event_id", "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "assignment_receipt_sha256", "expected_open_attempt_sha256",
            "runner_lease_sha256", "runner_lease_token_sha256",
            "journal_anchor_sha256", "schedule_commitment_sha256",
            "runner_event_root_sha256", "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.next_fencing_generation != self.fencing_generation + 1:
            raise ValueError("cancellation fencing generation must advance once")
        expected_prefix = (
            ("source", "target")
            if self.scheduled_arm_order == "AB"
            else ("target", "source")
        )[: len(self.started_arm_roots)]
        if tuple(item.arm for item in self.started_arm_roots) != expected_prefix:
            raise ValueError("cancellation witnesses are not the scheduled arm prefix")
        if self.started_arm_roots and not self.terminate_scope:
            raise ValueError("any started-arm cancellation must terminate its scope")
        if len(self.started_arm_roots) == 2:
            first, second = self.started_arm_roots
            if first.finish_event_seq is None:
                raise ValueError("two-start cancellation requires first-arm finish")
            if first.finish_event_seq >= second.start_event_seq:
                raise ValueError("second arm starts before the first arm finishes")
        roots = [item.root_id for item in self.started_arm_roots]
        if len(roots) != len(set(roots)):
            raise ValueError("cancellation physical roots must be distinct")
        event_ids = [
            self.prestart_schedule_event_id,
            *(
                event_id
                for item in self.started_arm_roots
                for event_id in (item.start_event_id, item.finish_event_id)
                if event_id is not None
            ),
            self.abort_event_id,
        ]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("cancellation journal event ids must be unique")
        event_seqs = [
            self.prestart_schedule_event_seq,
            *(
                event_seq
                for item in self.started_arm_roots
                for event_seq in (item.start_event_seq, item.finish_event_seq)
                if event_seq is not None
            ),
            self.abort_event_seq,
        ]
        if event_seqs != sorted(set(event_seqs)):
            raise ValueError("cancellation journal events require strict order")
        expected_schedule = runner_schedule_commitment_v1(
            expected_open_attempt_sha256=self.expected_open_attempt_sha256,
            assignment_receipt_sha256=self.assignment_receipt_sha256,
            plan_id=self.plan_id,
            ordinal=self.ordinal,
            scheduled_arm_order=self.scheduled_arm_order,
            runner_session_id=self.runner_session_id,
            runner_lease_token_sha256=self.runner_lease_token_sha256,
            fencing_generation=self.fencing_generation,
            journal_anchor_sha256=self.journal_anchor_sha256,
            prestart_schedule_event_id=self.prestart_schedule_event_id,
            prestart_schedule_event_seq=self.prestart_schedule_event_seq,
        )
        if self.schedule_commitment_sha256 != expected_schedule:
            raise ValueError("cancellation schedule commitment is not reproducible")
        expected_event_root = cancellation_event_root_v3(
            journal_anchor_sha256=self.journal_anchor_sha256,
            schedule_commitment_sha256=self.schedule_commitment_sha256,
            started_arm_roots=self.started_arm_roots,
            abort_event_id=self.abort_event_id,
            abort_event_seq=self.abort_event_seq,
            cancel_kind=self.cancel_kind,
            safe_failure_code=self.safe_failure_code,
            terminate_scope=self.terminate_scope,
            runner_lease_token_sha256=self.runner_lease_token_sha256,
            fencing_generation=self.fencing_generation,
            next_fencing_generation=self.next_fencing_generation,
        )
        if self.runner_event_root_sha256 != expected_event_root:
            raise ValueError("cancellation terminal event root is not reproducible")
        if self.runner_event_root_sha256 in {
            item.root_id for item in self.started_arm_roots
        }:
            raise ValueError("runner terminal root aliases a physical arm root")
        expected_id = _opaque_id(
            "ac",
            {
                "attempt": self.expected_open_attempt_sha256,
                "runner_lease": self.runner_lease_sha256,
                "terminal_event_root": self.runner_event_root_sha256,
            },
        )
        if self.cancellation_id != expected_id:
            raise ValueError("cancellation identity is not reproducible")
        return self


class ProbeAttemptV3(_ClosedModel):
    attempt_id: str
    plan_id: str
    ordinal: int = Field(ge=0, le=5)
    state: AttemptState
    assignment: AssignmentReceiptV2
    runner_lease: RunnerLeaseGrantV1
    pair_execution_receipt: PairExecutionReceiptV2 | None = None
    source_receipt: ArmReceiptV2 | None = None
    target_receipt: ArmReceiptV2 | None = None
    presented_root_ids: tuple[str, ...] = ()
    presented_receipt_ids: tuple[str, ...] = ()
    disposition_reason: str | None = None
    cancellation_receipt: AttemptCancellationReceiptV3 | None = None
    opened_seq: int = Field(ge=0)
    settled_seq: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_attempt(self) -> "ProbeAttemptV3":
        for name in ("attempt_id", "plan_id"):
            _require_id(str(getattr(self, name)), name)
        if not (
            self.runner_lease.attempt_id == self.attempt_id
            and self.runner_lease.plan_id == self.plan_id
            and self.runner_lease.ordinal == self.ordinal
            and self.runner_lease.assignment_receipt_sha256 == _sha256(self.assignment)
            and self.runner_lease.scheduled_arm_order == self.assignment.arm_order
            and self.runner_lease.fencing_generation == 1
        ):
            raise ValueError("attempt does not exactly own its generation-1 runner lease")
        if self.state == "open":
            if (
                self.source_receipt is not None
                or self.target_receipt is not None
                or self.pair_execution_receipt is not None
                or self.cancellation_receipt is not None
                or self.presented_root_ids
                or self.presented_receipt_ids
                or self.disposition_reason is not None
                or self.settled_seq is not None
            ):
                raise ValueError("open attempt cannot contain settled evidence")
        elif self.state in {"complete", "incomplete"}:
            if (
                self.source_receipt is None
                or self.target_receipt is None
                or self.pair_execution_receipt is None
                or self.cancellation_receipt is not None
                or self.settled_seq is None
            ):
                raise ValueError("settled attempt requires both execution receipts")
            if len(self.presented_root_ids) != 3 or len(self.presented_receipt_ids) != 3:
                raise ValueError(
                    "settled attempt must preserve two arm roots, one pair root, and three receipts"
                )
        elif self.state == "quarantine":
            if (
                self.disposition_reason is None
                or self.cancellation_receipt is not None
                or self.settled_seq is None
            ):
                raise ValueError("quarantine attempt requires a reason and settlement")
        else:
            cancellation = self.cancellation_receipt
            if (
                cancellation is None
                or self.source_receipt is not None
                or self.target_receipt is not None
                or self.pair_execution_receipt is not None
                or self.settled_seq is None
            ):
                raise ValueError("cancelled attempt requires only its trusted receipt")
            expected_roots = (
                *(item.root_id for item in cancellation.started_arm_roots),
                cancellation.runner_event_root_sha256,
            )
            if self.presented_root_ids != expected_roots:
                raise ValueError("cancelled attempt omits its exact journal roots")
            if self.presented_receipt_ids != (cancellation.cancellation_id,):
                raise ValueError("cancelled attempt omits its cancellation identity")
            if self.disposition_reason != cancellation.safe_failure_code:
                raise ValueError("cancelled attempt reason does not join its receipt")
        if self.settled_seq is not None and self.settled_seq <= self.opened_seq:
            raise ValueError("attempt settlement must follow its Bank-owned open sequence")
        if self.disposition_reason is not None:
            _require_id(self.disposition_reason, "disposition_reason")
        for value in (*self.presented_root_ids,):
            _require_sha(value, "presented_root_id")
        for value in self.presented_receipt_ids:
            _require_id(value, "presented_receipt_id")
        return self


class StrictDenseSummaryV2(_ClosedModel):
    n_samples: int = Field(ge=0, le=6)
    accepted: bool
    hard_checks_pass: bool
    reason: Literal[
        "no_paired_validation_samples", "quality_regression", "quality_improvement",
        "equal_quality_lower_cost", "no_change",
    ]
    algorithm_failure_rate_before: float = Field(ge=0, le=1, allow_inf_nan=False)
    algorithm_failure_rate_after: float = Field(ge=0, le=1, allow_inf_nan=False)
    mean_before: DenseOutcome | None
    mean_after: DenseOutcome | None
    min_K_before: float = Field(ge=0, le=1, allow_inf_nan=False)
    min_K_after: float = Field(ge=0, le=1, allow_inf_nan=False)
    mean_stage_delta: float = Field(allow_inf_nan=False)
    stage_bootstrap_ci_low: float = Field(allow_inf_nan=False)
    stage_bootstrap_ci_high: float = Field(allow_inf_nan=False)
    quality_improved: bool
    quality_equal: bool
    cost_tiebreak: bool


class EdgeAssessmentV2(_ClosedModel):
    assessment_id: str
    plan_id: str
    transition_id: str
    label: AssessmentLabel
    settled: bool
    n_attempted: int = Field(ge=0, le=6)
    n_open: int = Field(ge=0, le=1)
    n_complete: int = Field(ge=0, le=6)
    n_complete_ab: int = Field(ge=0, le=3)
    n_complete_ba: int = Field(ge=0, le=3)
    counterbalanced: bool
    n_benefit: int = Field(ge=0, le=6)
    n_harm: int = Field(ge=0, le=6)
    n_null: int = Field(ge=0, le=6)
    complete_attempt_ids: tuple[str, ...]
    incomplete_attempt_ids: tuple[str, ...]
    quarantine_attempt_ids: tuple[str, ...]
    cancelled_attempt_ids: tuple[str, ...]
    vote_by_attempt: tuple[tuple[str, Vote], ...]
    aggregate_dense_delta: DenseDelta
    source_algorithm_failure_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    target_algorithm_failure_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    strict_summary: StrictDenseSummaryV2
    all_zero_stream: bool
    catastrophic_harm: bool
    aggregate_policy_sha256: str
    evidence_root_sha256: str
    revision_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_assessment(self) -> "EdgeAssessmentV2":
        for name in ("assessment_id", "plan_id", "transition_id"):
            _require_id(str(getattr(self, name)), name)
        _require_sha(self.aggregate_policy_sha256, "aggregate_policy_sha256")
        _require_sha(self.evidence_root_sha256, "evidence_root_sha256")
        if self.n_complete != self.n_benefit + self.n_harm + self.n_null:
            raise ValueError("assessment vote counts do not cover complete attempts")
        if self.n_complete != self.n_complete_ab + self.n_complete_ba:
            raise ValueError("assessment arm-order counts do not cover complete attempts")
        if self.counterbalanced != (
            self.n_complete >= 2 and self.n_complete_ab == self.n_complete_ba
        ):
            raise ValueError("assessment counterbalance flag is not reproducible")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


def _portable_sign_for_assessment(
    assessment: EdgeAssessmentV2,
) -> PortableEvidenceSign | None:
    """Project one settled scientific assessment to the selector's sign alphabet."""

    if not assessment.settled:
        return None
    if assessment.label == "harmful" or assessment.catastrophic_harm:
        return "harm"
    if assessment.label == "candidate":
        return "benefit"
    if assessment.label == "neutral":
        return "all_zero" if assessment.all_zero_stream else "null"
    if assessment.label == "infrastructure_exhausted":
        return "infrastructure"
    return None


def _zero_delta() -> DenseDelta:
    return DenseDelta(V=0, K=0, U=0, P=0, S=0, stage_score=0, C=0, D=0)


def _mean_outcome(values: Sequence[DenseOutcome]) -> DenseOutcome | None:
    if not values:
        return None
    return DenseOutcome(
        **{
            name: sum(float(getattr(item, name)) for item in values) / len(values)
            for name in ("V", "K", "U", "P", "S", "stage_score", "C", "D")
        }
    )


def classify_attempt_vote(attempt: ProbeAttemptV3, policy: AggregatePolicyV1) -> Vote:
    if attempt.state != "complete":
        raise ValueError("only complete attempts receive scientific votes")
    assert attempt.source_receipt is not None and attempt.target_receipt is not None
    source = attempt.source_receipt
    target = attempt.target_receipt
    assert source.outcome is not None and target.outcome is not None
    if source.execution_class == target.execution_class == "algorithm_failure":
        return "null"
    if target.execution_class == "algorithm_failure" and source.execution_class == "completed":
        return "harm"
    delta = target.outcome.subtract(source.outcome)
    quality_names = ("V", "K", "U", "P", "S")
    all_zero = all(
        abs(float(getattr(source.outcome, name))) <= policy.numeric_tolerance
        and abs(float(getattr(target.outcome, name))) <= policy.numeric_tolerance
        for name in (*quality_names, "stage_score")
    )
    if all_zero:
        return "null"
    if any(
        float(getattr(delta, name)) < -policy.partial_tolerance
        for name in quality_names
    ) or delta.stage_score < -policy.numeric_tolerance:
        return "harm"
    quality_gain = (
        delta.stage_score >= policy.min_dense_delta
        and any(float(getattr(delta, name)) >= policy.min_dense_delta for name in quality_names)
    )
    quality_equal = all(
        abs(float(getattr(delta, name))) <= policy.numeric_tolerance
        for name in quality_names
    )
    cost_tiebreak = bool(
        quality_equal
        and target.outcome.stage_score > 0
        and delta.C <= policy.numeric_tolerance
        and delta.D <= policy.numeric_tolerance
        and (delta.C < -policy.numeric_tolerance or delta.D < -policy.numeric_tolerance)
    )
    return "benefit" if quality_gain or cost_tiebreak else "null"


def _strict_summary(
    complete: Sequence[ProbeAttemptV3],
    policy: AggregatePolicyV1,
) -> StrictDenseSummaryV2:
    if not complete:
        return StrictDenseSummaryV2(
            n_samples=0,
            accepted=False,
            hard_checks_pass=False,
            reason="no_paired_validation_samples",
            algorithm_failure_rate_before=0,
            algorithm_failure_rate_after=0,
            mean_before=None,
            mean_after=None,
            min_K_before=0,
            min_K_after=0,
            mean_stage_delta=0,
            stage_bootstrap_ci_low=0,
            stage_bootstrap_ci_high=0,
            quality_improved=False,
            quality_equal=False,
            cost_tiebreak=False,
        )
    sources = [item.source_receipt for item in complete]
    targets = [item.target_receipt for item in complete]
    assert all(item is not None and item.outcome is not None for item in (*sources, *targets))
    source_outcomes = [item.outcome for item in sources if item and item.outcome]
    target_outcomes = [item.outcome for item in targets if item and item.outcome]
    before = _mean_outcome(source_outcomes)
    after = _mean_outcome(target_outcomes)
    assert before is not None and after is not None
    delta = after.subtract(before)
    quality_names = ("V", "K", "U", "P", "S")
    hard_checks = bool(
        all(float(getattr(delta, name)) >= -policy.partial_tolerance for name in quality_names)
        and sum(item.execution_class == "algorithm_failure" for item in targets)
        <= sum(item.execution_class == "algorithm_failure" for item in sources)
    )
    quality_improved = bool(
        delta.stage_score >= policy.min_dense_delta
        and any(float(getattr(delta, name)) >= policy.min_dense_delta for name in quality_names)
    )
    quality_equal = all(
        abs(float(getattr(delta, name))) <= policy.numeric_tolerance for name in quality_names
    )
    cost_tiebreak = bool(
        quality_equal
        and after.stage_score > 0
        and delta.C <= policy.numeric_tolerance
        and delta.D <= policy.numeric_tolerance
        and (delta.C < -policy.numeric_tolerance or delta.D < -policy.numeric_tolerance)
    )
    deltas = [
        target.outcome.stage_score - source.outcome.stage_score
        for source, target in zip(sources, targets)
        if source and target and source.outcome and target.outcome
    ]
    rng = random.Random(policy.bootstrap_seed)
    samples = []
    for _ in range(policy.bootstrap_samples):
        samples.append(sum(rng.choice(deltas) for _ in deltas) / len(deltas))
    samples.sort()
    low = samples[max(0, int(0.025 * len(samples)) - 1)]
    high = samples[min(len(samples) - 1, int(0.975 * len(samples)))]
    accepted = bool(hard_checks and (quality_improved or cost_tiebreak))
    if not hard_checks:
        reason = "quality_regression"
    elif quality_improved:
        reason = "quality_improvement"
    elif cost_tiebreak:
        reason = "equal_quality_lower_cost"
    else:
        reason = "no_change"
    return StrictDenseSummaryV2(
        n_samples=len(complete),
        accepted=accepted,
        hard_checks_pass=hard_checks,
        reason=reason,
        algorithm_failure_rate_before=sum(
            item.execution_class == "algorithm_failure" for item in sources
        ) / len(sources),
        algorithm_failure_rate_after=sum(
            item.execution_class == "algorithm_failure" for item in targets
        ) / len(targets),
        mean_before=before,
        mean_after=after,
        min_K_before=min(item.K for item in source_outcomes),
        min_K_after=min(item.K for item in target_outcomes),
        mean_stage_delta=delta.stage_score,
        stage_bootstrap_ci_low=low,
        stage_bootstrap_ci_high=high,
        quality_improved=quality_improved,
        quality_equal=quality_equal,
        cost_tiebreak=cost_tiebreak,
    )


def recompute_assessment(
    plan: ProbePlanV2,
    attempts: Sequence[ProbeAttemptV3],
    *,
    revision_seq: int,
) -> EdgeAssessmentV2:
    ordered = sorted(attempts, key=lambda item: (item.ordinal, item.attempt_id))
    if any(item.plan_id != plan.plan_id for item in ordered):
        raise ValueError("assessment attempts cross a probe plan")
    if [item.ordinal for item in ordered] != list(range(len(ordered))):
        raise ValueError("probe attempts must form an ordinal prefix")
    opened = [item for item in ordered if item.state == "open"]
    complete = [item for item in ordered if item.state == "complete"]
    incomplete = [item for item in ordered if item.state == "incomplete"]
    quarantined = [item for item in ordered if item.state == "quarantine"]
    cancelled = [item for item in ordered if item.state == "cancelled"]
    votes = [(item.attempt_id, classify_attempt_vote(item, plan.aggregate_policy)) for item in complete]
    n_benefit = sum(vote == "benefit" for _attempt, vote in votes)
    n_harm = sum(vote == "harm" for _attempt, vote in votes)
    n_null = sum(vote == "null" for _attempt, vote in votes)
    n_attempted = len([item for item in ordered if item.state != "open"])
    n_complete = len(complete)
    n_complete_ab = sum(
        item.source_receipt is not None
        and item.source_receipt.observed_arm_order == "AB"
        for item in complete
    )
    n_complete_ba = n_complete - n_complete_ab
    counterbalanced = bool(
        n_complete >= 2 and n_complete_ab == n_complete_ba
    )
    strict = _strict_summary(complete, plan.aggregate_policy)
    deltas = [
        item.target_receipt.outcome.subtract(item.source_receipt.outcome)
        for item in complete
        if item.source_receipt and item.target_receipt
        and item.source_receipt.outcome and item.target_receipt.outcome
    ]
    mean_delta = DenseDelta(
        **{
            name: (
                sum(float(getattr(item, name)) for item in deltas) / len(deltas)
                if deltas else 0.0
            )
            for name in ("V", "K", "U", "P", "S", "stage_score", "C", "D")
        }
    )
    all_zero_stream = bool(
        complete
        and all(
            item.source_receipt
            and item.target_receipt
            and item.source_receipt.outcome
            and item.target_receipt.outcome
            and all(
                abs(float(getattr(item.source_receipt.outcome, name)))
                <= plan.aggregate_policy.numeric_tolerance
                and abs(float(getattr(item.target_receipt.outcome, name)))
                <= plan.aggregate_policy.numeric_tolerance
                for name in ("V", "K", "U", "P", "S", "stage_score")
            )
            for item in complete
        )
    )
    catastrophic = bool(
        any(
            item.source_receipt
            and item.target_receipt
            and item.source_receipt.execution_class == "completed"
            and item.target_receipt.execution_class == "algorithm_failure"
            for item in complete
        )
    )
    has_partial_abort = any(
        item.cancellation_receipt is not None
        and bool(item.cancellation_receipt.started_arm_roots)
        for item in cancelled
    )
    has_terminal_cancellation = any(
        item.cancellation_receipt is not None
        and item.cancellation_receipt.terminate_scope
        for item in cancelled
    )
    benefit_needed = math.ceil(
        plan.aggregate_policy.benefit_quorum_numerator * n_complete
        / plan.aggregate_policy.benefit_quorum_denominator
    ) if n_complete else 1
    harm_needed = math.ceil(
        plan.aggregate_policy.harm_quorum_numerator * n_complete
        / plan.aggregate_policy.harm_quorum_denominator
    ) if n_complete else 1
    harm_terminal = bool(
        n_complete >= plan.aggregate_policy.min_complete_blocks
        and n_harm >= harm_needed
        and not strict.hard_checks_pass
    )
    settled = bool(
        quarantined
        or catastrophic
        or harm_terminal
        or has_terminal_cancellation
        or (
            n_complete >= plan.aggregate_policy.target_complete_blocks
            and counterbalanced
        )
        or n_attempted >= plan.aggregate_policy.max_attempted_blocks
    )
    if quarantined:
        label: AssessmentLabel = "quarantine"
        settled = True
    elif catastrophic or harm_terminal:
        label = "harmful"
    elif settled and (
        has_partial_abort
        or n_complete < plan.aggregate_policy.target_complete_blocks
        or (
            n_complete >= plan.aggregate_policy.target_complete_blocks
            and not counterbalanced
        )
    ):
        label = "infrastructure_exhausted"
    elif (
        n_complete >= plan.aggregate_policy.target_complete_blocks
        and n_benefit >= benefit_needed
        and n_harm == 0
        and strict.accepted
        and not all_zero_stream
        and counterbalanced
    ):
        label = "candidate"
    elif n_attempted or opened:
        label = "neutral" if n_complete else "probing"
    else:
        label = "registered"
    evidence_root = _sha256(
        [
            {
                "attempt": item.attempt_id,
                "ordinal": item.ordinal,
                "state": item.state,
                "assignment": item.assignment.attestation_sha256,
                "source": item.source_receipt.attestation_sha256 if item.source_receipt else None,
                "target": item.target_receipt.attestation_sha256 if item.target_receipt else None,
                "cancellation": (
                    item.cancellation_receipt.attestation_sha256
                    if item.cancellation_receipt else None
                ),
                "reason": item.disposition_reason,
            }
            for item in ordered
        ]
    )
    return EdgeAssessmentV2(
        assessment_id=_opaque_id("ea", plan.plan_id),
        plan_id=plan.plan_id,
        transition_id=plan.transition_id,
        label=label,
        settled=settled,
        n_attempted=n_attempted,
        n_open=len(opened),
        n_complete=n_complete,
        n_complete_ab=n_complete_ab,
        n_complete_ba=n_complete_ba,
        counterbalanced=counterbalanced,
        n_benefit=n_benefit,
        n_harm=n_harm,
        n_null=n_null,
        complete_attempt_ids=tuple(item.attempt_id for item in complete),
        incomplete_attempt_ids=tuple(item.attempt_id for item in incomplete),
        quarantine_attempt_ids=tuple(item.attempt_id for item in quarantined),
        cancelled_attempt_ids=tuple(item.attempt_id for item in cancelled),
        vote_by_attempt=tuple(votes),
        aggregate_dense_delta=mean_delta,
        source_algorithm_failure_rate=(
            sum(item.source_receipt.execution_class == "algorithm_failure" for item in complete if item.source_receipt)
            / n_complete if n_complete else 0
        ),
        target_algorithm_failure_rate=(
            sum(item.target_receipt.execution_class == "algorithm_failure" for item in complete if item.target_receipt)
            / n_complete if n_complete else 0
        ),
        strict_summary=strict,
        all_zero_stream=all_zero_stream,
        catastrophic_harm=catastrophic,
        aggregate_policy_sha256=plan.aggregate_policy_sha256,
        evidence_root_sha256=evidence_root,
        revision_seq=revision_seq,
    )


def next_allowed_ordinal(
    plan: ProbePlanV2,
    attempts: Sequence[ProbeAttemptV3],
    assessment: EdgeAssessmentV2,
) -> int | None:
    if assessment.settled or any(item.state == "open" for item in attempts):
        return None
    ordinal = len(attempts)
    if ordinal >= plan.aggregate_policy.max_attempted_blocks:
        return None
    if ordinal >= plan.aggregate_policy.target_complete_blocks and (
        assessment.n_complete >= plan.aggregate_policy.target_complete_blocks
        and assessment.counterbalanced
    ):
        return None
    return ordinal


class GateOpportunityV2(_ClosedModel):
    opportunity_id: str
    deployment_slot_id: str
    namespace_digest: str
    transition_id: str
    plan_id: str
    settled_assessment_sha256: str
    candidate_snapshot_sha256: str
    incumbent_snapshot_id: str
    created_seq: int = Field(ge=0)
    expiry_seq: int = Field(ge=0)
    state: OpportunityState = "pending"
    decision_id: str | None = None

    @model_validator(mode="after")
    def validate_opportunity(self) -> "GateOpportunityV2":
        for name in (
            "opportunity_id", "deployment_slot_id", "transition_id", "plan_id",
            "incumbent_snapshot_id",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "namespace_digest", "settled_assessment_sha256", "candidate_snapshot_sha256"
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.expiry_seq < self.created_seq:
            raise ValueError("gate opportunity expiry precedes creation")
        if (self.decision_id is None) != (self.state in {"pending", "revoked"}):
            raise ValueError("terminal gate opportunity must name its decision")
        return self


class GateReceiptV2(_ClosedModel):
    decision_id: str
    opportunity_id: str
    deployment_slot_id: str
    split: Literal["FINAL_VAL"] = "FINAL_VAL"
    accepted: bool
    incumbent_snapshot_sha256: str
    candidate_snapshot_sha256: str
    settled_assessment_sha256: str
    gate_config_sha256: str
    aggregate_summary_sha256: str
    verifier_epoch: str
    verification_attestation_sha256: str
    emitted_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_gate_receipt(self) -> "GateReceiptV2":
        for name in ("decision_id", "opportunity_id", "deployment_slot_id", "verifier_epoch"):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "incumbent_snapshot_sha256", "candidate_snapshot_sha256",
            "settled_assessment_sha256", "gate_config_sha256",
            "aggregate_summary_sha256", "verification_attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self


class BaseSnapshotReceiptV2(_ClosedModel):
    receipt_id: str
    deployment_slot_id: str
    namespace_digest: str
    composition_id: str
    loaded_artifact_sha256: str
    binding_map_sha256: str
    runtime_version: str
    verifier_epoch: str
    attestation_sha256: str
    emitted_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_base_receipt(self) -> "BaseSnapshotReceiptV2":
        for name in (
            "receipt_id", "deployment_slot_id", "composition_id", "runtime_version",
            "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "namespace_digest", "loaded_artifact_sha256", "binding_map_sha256",
            "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self


class DeploymentSnapshotV2(_ClosedModel):
    snapshot_id: str
    deployment_slot_id: str
    namespace_digest: str
    composition_id: str
    transition_id: str | None
    artifact_sha256: str
    binding_map_sha256: str
    accepted_gate_decision_id: str | None
    accepted_gate_receipt_sha256: str | None
    scientific_snapshot_sha256: str
    predecessor_snapshot_id: str | None
    is_base_fallback: bool = False
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "DeploymentSnapshotV2":
        for name in ("snapshot_id", "deployment_slot_id", "composition_id"):
            _require_id(str(getattr(self, name)), name)
        for optional in (
            self.transition_id, self.accepted_gate_decision_id, self.predecessor_snapshot_id
        ):
            if optional is not None:
                _require_id(optional, "snapshot reference")
        for name in (
            "namespace_digest", "artifact_sha256", "binding_map_sha256",
            "scientific_snapshot_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.accepted_gate_receipt_sha256 is not None:
            _require_sha(self.accepted_gate_receipt_sha256, "accepted_gate_receipt_sha256")
        gate_fields = (
            self.transition_id,
            self.accepted_gate_decision_id,
            self.accepted_gate_receipt_sha256,
        )
        if self.is_base_fallback:
            if any(item is not None for item in gate_fields):
                raise ValueError("base snapshot cannot claim a gate transition")
        elif any(item is None for item in gate_fields):
            raise ValueError("non-base snapshot requires a complete accepted gate chain")
        return self


class DeploymentHeadV2(_ClosedModel):
    deployment_slot_id: str
    namespace_digest: str
    active_snapshot_id: str | None
    active_composition_id: str | None
    active_transition_id: str | None
    accepted_gate_receipt_sha256: str | None
    active_snapshot_sha256: str | None
    predecessor_snapshot_id: str | None
    rollback_lease_expiry_seq: int | None = Field(default=None, ge=0)
    base_fallback_snapshot_id: str | None
    generation: int = Field(ge=0)
    state: HeadState
    updated_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_head(self) -> "DeploymentHeadV2":
        _require_id(self.deployment_slot_id, "deployment_slot_id")
        _require_sha(self.namespace_digest, "namespace_digest")
        if self.state == "active":
            for value in (self.active_snapshot_id, self.active_composition_id):
                if value is None:
                    raise ValueError("active head requires snapshot and composition")
                _require_id(value, "active head reference")
            if self.active_snapshot_sha256 is None:
                raise ValueError("active head requires a snapshot digest")
            _require_sha(self.active_snapshot_sha256, "active_snapshot_sha256")
        else:
            if any(
                item is not None
                for item in (
                    self.active_snapshot_id, self.active_composition_id,
                    self.active_transition_id, self.accepted_gate_receipt_sha256,
                    self.active_snapshot_sha256, self.predecessor_snapshot_id,
                    self.rollback_lease_expiry_seq,
                )
            ):
                raise ValueError("disabled head cannot retain an active deployment")
        for value in (
            self.active_transition_id, self.predecessor_snapshot_id,
            self.base_fallback_snapshot_id,
        ):
            if value is not None:
                _require_id(value, "deployment head reference")
        if self.accepted_gate_receipt_sha256 is not None:
            _require_sha(self.accepted_gate_receipt_sha256, "accepted_gate_receipt_sha256")
        return self


class RollbackTriggerV2(_ClosedModel):
    trigger_id: str
    kind: Literal["support_invalid", "train_monitor_harm", "loaded_integrity_mismatch"]
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    deployment_slot_id: str
    expected_head_generation: int = Field(ge=0)
    active_snapshot_id: str
    safe_failure_code: str
    evidence_or_support_sha256: str
    verifier_epoch: str
    attestation_sha256: str
    emitted_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_trigger(self) -> "RollbackTriggerV2":
        for name in (
            "trigger_id", "deployment_slot_id", "active_snapshot_id", "safe_failure_code",
            "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in ("evidence_or_support_sha256", "attestation_sha256"):
            _require_sha(str(getattr(self, name)), name)
        return self


class RollbackRecordV2(_ClosedModel):
    rollback_id: str
    trigger_id: str
    deployment_slot_id: str
    old_snapshot_id: str
    restored_snapshot_id: str | None
    old_generation: int = Field(ge=0)
    new_generation: int = Field(ge=1)
    disposition: Literal["restored_predecessor", "restored_base", "disabled"]
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_rollback(self) -> "RollbackRecordV2":
        for name in ("rollback_id", "trigger_id", "deployment_slot_id", "old_snapshot_id"):
            _require_id(str(getattr(self, name)), name)
        if self.restored_snapshot_id is not None:
            _require_id(self.restored_snapshot_id, "restored_snapshot_id")
        if self.new_generation != self.old_generation + 1:
            raise ValueError("rollback generation must increase exactly once")
        if (self.restored_snapshot_id is None) != (self.disposition == "disabled"):
            raise ValueError("rollback disposition does not match restored snapshot")
        return self


class CapacityPolicyV1(_ClosedModel):
    policy_name: Literal["sft_capacity_v1"] = "sft_capacity_v1"
    max_active_heads_per_namespace: int = Field(default=1, ge=1)
    max_pending_gate_per_namespace: int = Field(default=4, ge=1)
    max_live_plans_per_namespace: int = Field(default=4, ge=1)
    max_attempt_records: int = Field(default=24, ge=6)
    max_receipt_records: int = Field(default=96, ge=24)
    max_consumed_root_ids: int = Field(default=16_384, ge=18)
    max_consumed_receipt_ids: int = Field(default=8_192, ge=18)
    max_unit_commitments: int = Field(default=24_576, ge=6)
    max_infrastructure_epochs_per_edge: int = Field(default=3, ge=1, le=16)
    infrastructure_retry_lease_events: int = Field(default=64, ge=1)
    max_hot_compositions_per_namespace: int = Field(default=12, ge=1)
    max_hot_metadata_bytes: int = Field(default=4 * 1024 * 1024, ge=1024)
    max_hot_artifact_bytes_per_namespace: int = Field(
        default=64 * 1024 * 1024,
        ge=1024,
    )
    max_cold_metadata_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    max_prompt_summary_tokens_per_namespace: int = Field(default=4000, ge=0)
    unknown_structural_reserve: int = Field(default=4, ge=0)
    max_factor_records: int = Field(default=4096, ge=1)
    max_composition_records: int = Field(default=2048, ge=1)
    max_transition_records: int = Field(default=4096, ge=1)
    max_plan_records: int = Field(default=4096, ge=1)
    max_gate_receipts: int = Field(default=4096, ge=1)
    max_deployment_slots: int = Field(default=256, ge=1)
    max_recent_tombstones: int = Field(default=1024, ge=1)
    max_portable_evidence_leaves: int = Field(default=4096, ge=1)
    max_checkpoints: int = Field(default=64, ge=1)
    max_failures: int = Field(default=1024, ge=0)
    max_repair_opportunities: int = Field(default=1024, ge=0)
    max_branch_assignments: int = Field(default=1024, ge=0)
    max_proposal_decisions: int = Field(default=1024, ge=0)
    max_proposal_decision_bytes: Literal[98_304] = MAX_PROPOSAL_DECISION_BYTES
    max_proposal_lifetime_counters: int = Field(default=1024, ge=0)
    max_proposal_actions: int = Field(default=1024, ge=0)
    max_proposal_carrier_admissions: int = Field(default=1024, ge=0)
    max_generated_target_metadata_bytes: int = Field(
        default=64 * 1024,
        ge=1024,
    )
    max_generated_target_artifact_bytes: int = Field(
        default=4 * 1024 * 1024,
        ge=1024,
    )
    max_generated_target_prompt_summary_tokens: int = Field(
        default=512,
        ge=0,
    )
    max_generated_carrier_structural_bytes: int = Field(
        default=64 * 1024,
        ge=4096,
    )
    max_generated_transition_bytes: int = Field(default=8 * 1024, ge=2048)
    max_generated_admission_bytes: int = Field(default=8 * 1024, ge=2048)
    max_generated_owner_slab_bytes: int = Field(default=32 * 1024, ge=4096)
    max_active_generated_carrier_reservation_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=16 * 1024,
    )
    max_event_seq: int = Field(default=2**63 - 1, ge=1)
    max_proposal_action_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=64 * 1024,
    )
    max_exposures: int = Field(default=1024, ge=0)
    gate_opportunity_ttl_events: int = Field(default=64, ge=1)
    rollback_lease_events: int = Field(default=64, ge=1)

    @model_validator(mode="after")
    def validate_generated_carrier_bounds(self) -> "CapacityPolicyV1":
        if self.max_proposal_lifetime_counters > self.max_proposal_decisions:
            raise ValueError(
                "proposal lifetime-counter capacity exceeds decision capacity"
            )
        if self.max_generated_target_metadata_bytes > self.max_hot_metadata_bytes:
            raise ValueError(
                "generated target metadata bound exceeds hot metadata capacity"
            )
        if (
            self.max_generated_target_artifact_bytes
            > self.max_hot_artifact_bytes_per_namespace
        ):
            raise ValueError(
                "generated target artifact bound exceeds hot artifact capacity"
            )
        if (
            self.max_generated_target_prompt_summary_tokens
            > self.max_prompt_summary_tokens_per_namespace
        ):
            raise ValueError(
                "generated target prompt bound exceeds namespace token capacity"
            )
        one_reservation = (
            self.max_generated_carrier_structural_bytes
            + self.max_generated_target_metadata_bytes
            + self.max_generated_target_artifact_bytes
            + self.max_generated_transition_bytes
            + self.max_generated_admission_bytes
            + self.max_generated_owner_slab_bytes
        )
        if one_reservation > self.max_active_generated_carrier_reservation_bytes:
            raise ValueError(
                "one generated carrier closure exceeds reservation-byte capacity"
            )
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class PlanCapacityReservationV2(_ClosedModel):
    reservation_id: str
    plan_id: str
    namespace_digest: str
    reserved_attempt_slots: Literal[6] = 6
    reserved_receipt_slots: Literal[24] = 24
    reserved_consumed_root_slots: Literal[18] = 18
    reserved_consumed_receipt_slots: Literal[18] = 18
    state: Literal["active", "released"] = "active"
    created_seq: int = Field(ge=0)
    released_seq: int | None = Field(default=None, ge=0)


def _receipt_record_capacity_usage(
    attempts: Sequence[ProbeAttemptV3],
    active_plan_ids: Iterable[str],
) -> tuple[int, int]:
    """Return exact materialized and worst-case residual receipt records.

    Every attempt embeds one assignment record.  An existing open attempt may
    still materialize two arms plus one terminal; each not-yet-open ordinal may
    materialize assignment, two arms, and one terminal.  Cancellation creates
    safe slack but never a negative reservation.
    """

    active = set(active_plan_ids)
    materialized = sum(
        1
        + int(attempt.source_receipt is not None)
        + int(attempt.target_receipt is not None)
        + int(attempt.pair_execution_receipt is not None)
        + int(attempt.cancellation_receipt is not None)
        for attempt in attempts
    )
    residual = 0
    for plan_id in active:
        scoped = [item for item in attempts if item.plan_id == plan_id]
        residual += 3 * sum(item.state == "open" for item in scoped)
        residual += 4 * (6 - len(scoped))
    return materialized, residual


class NegativeTombstoneV2(_ClosedModel):
    tombstone_id: str
    subject_id: str
    namespace_digest: str
    portable_pair_sha256: str
    background_sha256: str
    disposition: Literal[
        "quarantine", "harmful", "rollback_revoked", "gate_rejected",
        "infrastructure_exhausted", "neutral", "expired_candidate", "unknown",
    ]
    artifact_sha256: str
    evidence_root_sha256: str
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_tombstone(self) -> "NegativeTombstoneV2":
        for name in ("tombstone_id", "subject_id"):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "namespace_digest", "portable_pair_sha256", "background_sha256",
            "artifact_sha256", "evidence_root_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self


class PortableEvidenceLeafV1(_ClosedModel):
    """Archive-stable selector evidence without transferable efficacy ownership.

    The leaf preserves only the exact transition/background sign needed to
    replay a historical proposal decision.  It is bound to the externally
    verified cold checkpoint and authenticated by the Bank state key; it does
    not make the archived transition deployable or copy utility to an alias.
    """

    leaf_version: Literal["sft-portable-evidence-leaf-v1"] = (
        "sft-portable-evidence-leaf-v1"
    )
    leaf_id: str
    transition_id: str
    namespace_digest: str
    portable_pair_sha256: str
    background_sha256: str
    sign: PortableEvidenceSign
    evidence_root_sha256: str
    source_assessment_sha256: str
    source_revision_seq: int = Field(ge=0)
    checkpoint_id: str
    checkpoint_merkle_root_sha256: str
    created_seq: int = Field(ge=0)
    bank_attestation_sha256: str

    @model_validator(mode="after")
    def validate_leaf(self) -> "PortableEvidenceLeafV1":
        for name in ("leaf_id", "transition_id", "checkpoint_id"):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "namespace_digest",
            "portable_pair_sha256",
            "background_sha256",
            "evidence_root_sha256",
            "source_assessment_sha256",
            "checkpoint_merkle_root_sha256",
            "bank_attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self

    @property
    def attestation_body(self) -> dict[str, Any]:
        return self.model_dump(
            mode="python",
            exclude={"leaf_id", "bank_attestation_sha256"},
        )


class ArchivedEpochManifestV1(_ClosedModel):
    """Exact bounded lifetime owner removed from the hot plan registry.

    A checkpoint keeps one manifest per archived plan.  The external archive
    root commits this complete body, while semantic replay joins its exact
    transition and canonical owner back to the retained structural graph.
    """

    manifest_version: Literal["sft-archived-epoch-manifest-v1"] = (
        "sft-archived-epoch-manifest-v1"
    )
    canonical_scientific_edge_key_sha256: str
    credit_owner_transition_id: str
    exact_transition_id: str
    plan_id: str
    epoch_id: str
    unit_commitments: tuple[str, ...]
    plan_sha256: str

    @model_validator(mode="after")
    def validate_manifest(self) -> "ArchivedEpochManifestV1":
        for name in (
            "credit_owner_transition_id",
            "exact_transition_id",
            "plan_id",
            "epoch_id",
        ):
            _require_id(str(getattr(self, name)), name)
        _require_sha(
            self.canonical_scientific_edge_key_sha256,
            "archived manifest scientific edge key",
        )
        _require_sha(self.plan_sha256, "archived manifest plan digest")
        if len(self.unit_commitments) != 6:
            raise ValueError("archived epoch manifest must bind exactly six units")
        if len(set(self.unit_commitments)) != 6:
            raise ValueError("archived epoch manifest units must be distinct")
        for unit_commitment in self.unit_commitments:
            _require_sha(unit_commitment, "archived manifest unit commitment")
        return self

    @property
    def identity_key(self) -> tuple[str, str, str]:
        return (
            self.canonical_scientific_edge_key_sha256,
            self.epoch_id,
            self.plan_id,
        )


class ColdCheckpointV2(_ClosedModel):
    checkpoint_id: str
    namespace_digest: str
    epoch_start_seq: int = Field(ge=0)
    epoch_end_seq: int = Field(ge=0)
    archive_records_sha256: str
    merkle_root_sha256: str
    record_count: int = Field(ge=1)
    subject_ids: tuple[str, ...]
    disposition_counts: tuple[tuple[str, int], ...]
    archived_epoch_manifests: tuple[ArchivedEpochManifestV1, ...] = ()
    capacity_policy_sha256: str
    archive_attestation_sha256: str
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_checkpoint(self) -> "ColdCheckpointV2":
        _require_id(self.checkpoint_id, "checkpoint_id")
        if self.epoch_end_seq < self.epoch_start_seq:
            raise ValueError("cold checkpoint epoch is reversed")
        if not self.subject_ids or len(self.subject_ids) != len(set(self.subject_ids)):
            raise ValueError("cold checkpoint needs unique archived subjects")
        for subject_id in self.subject_ids:
            _require_id(subject_id, "checkpoint subject_id")
        for name in (
            "namespace_digest",
            "archive_records_sha256",
            "merkle_root_sha256",
            "capacity_policy_sha256",
            "archive_attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.record_count != len(self.subject_ids):
            raise ValueError("checkpoint record count does not cover subjects")
        if sum(count for _label, count in self.disposition_counts) != len(
            self.subject_ids
        ):
            raise ValueError("checkpoint disposition counts do not cover subjects")
        manifest_keys = tuple(
            item.identity_key for item in self.archived_epoch_manifests
        )
        if manifest_keys != tuple(sorted(set(manifest_keys))):
            raise ValueError("checkpoint epoch manifests must be unique and sorted")
        if self.merkle_root_sha256 != _sha256(self.archive_root_body):
            raise ValueError("checkpoint root does not cover its exact manifest body")
        return self

    @property
    def archived_edge_epochs(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (
                    item.canonical_scientific_edge_key_sha256,
                    item.epoch_id,
                )
                for item in self.archived_epoch_manifests
            )
        )

    @property
    def archived_unit_commitments(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (
                    item.canonical_scientific_edge_key_sha256,
                    unit_commitment,
                )
                for item in self.archived_epoch_manifests
                for unit_commitment in item.unit_commitments
            )
        )

    @property
    def archive_root_body(self) -> dict[str, Any]:
        return {
            "namespace_digest": self.namespace_digest,
            "capacity_policy_sha256": self.capacity_policy_sha256,
            "archived_epoch_manifests": self.archived_epoch_manifests,
            "archive_records_sha256": self.archive_records_sha256,
        }


class FailureObservationV2(_ClosedModel):
    failure_id: str
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    failure_class: Literal["algorithm", "infrastructure", "harness"]
    failed_stage: str
    safe_failure_code: str
    composition_id: str
    transition_id: str | None = None
    artifact_sha256: str
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_failure(self) -> "FailureObservationV2":
        for name in ("failure_id", "failed_stage", "safe_failure_code", "composition_id"):
            _require_id(str(getattr(self, name)), name)
        if self.transition_id is not None:
            _require_id(self.transition_id, "transition_id")
        _require_sha(self.artifact_sha256, "artifact_sha256")
        return self


class RepairOpportunityV2(_ClosedModel):
    opportunity_id: str
    source_composition_id: str
    namespace_digest: str
    source_kind: Literal[
        "algorithm_failure", "neutral_edge", "gate_reject", "capacity_refresh"
    ]
    safe_failure_code: str
    failed_stage: str
    transition_id: str | None
    host_allowed_locator_ids: tuple[str, ...]
    feasible_branches: tuple[ScientificBranch, ...]
    public_seed: int
    created_seq: int = Field(ge=0)
    expiry_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_repair_opportunity(self) -> "RepairOpportunityV2":
        for name in (
            "opportunity_id", "source_composition_id", "safe_failure_code",
            "failed_stage",
        ):
            _require_id(str(getattr(self, name)), name)
        _require_sha(self.namespace_digest, "namespace_digest")
        if self.transition_id is not None:
            _require_id(self.transition_id, "transition_id")
        if self.host_allowed_locator_ids != tuple(
            sorted(set(self.host_allowed_locator_ids))
        ):
            raise ValueError("repair opportunity locator set must be canonical")
        for locator_id in self.host_allowed_locator_ids:
            _require_id(locator_id, "host_allowed_locator_id")
        if not self.feasible_branches or len(self.feasible_branches) != len(
            set(self.feasible_branches)
        ):
            raise ValueError("repair opportunity needs unique feasible branches")
        if self.expiry_seq < self.created_seq:
            raise ValueError("repair opportunity expiry precedes creation")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class BranchAssignmentV2(_ClosedModel):
    assignment_id: str
    repair_opportunity_id: str
    repair_opportunity_sha256: str
    namespace_digest: str
    source_composition_id: str
    branch: ScientificBranch
    assigned_counts_before: tuple[tuple[ScientificBranch, int], ...]
    selector_policy_sha256: str
    public_tiebreak_sha256: str
    proposal_decision_id: str | None = None
    proposal_decision_sha256: str | None = None
    effective_feasible_branches: tuple[ScientificBranch, ...] | None = None
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_branch_assignment(self) -> "BranchAssignmentV2":
        for name in (
            "assignment_id", "repair_opportunity_id", "source_composition_id",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "repair_opportunity_sha256", "namespace_digest",
            "selector_policy_sha256", "public_tiebreak_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        expected_order = ("reuse", "mutate", "fresh")
        if tuple(item[0] for item in self.assigned_counts_before) != expected_order:
            raise ValueError("branch counts must use the canonical branch order")
        if any(count < 0 for _branch, count in self.assigned_counts_before):
            raise ValueError("branch counts must be non-negative")
        proposal_fields = (
            self.proposal_decision_id,
            self.proposal_decision_sha256,
            self.effective_feasible_branches,
        )
        if any(item is None for item in proposal_fields) != all(
            item is None for item in proposal_fields
        ):
            raise ValueError("proposal-conditioned assignment closure is partial")
        if self.proposal_decision_id is not None:
            _require_id(self.proposal_decision_id, "proposal_decision_id")
            assert self.proposal_decision_sha256 is not None
            _require_sha(
                self.proposal_decision_sha256,
                "proposal_decision_sha256",
            )
            assert self.effective_feasible_branches is not None
            if not self.effective_feasible_branches or len(
                self.effective_feasible_branches
            ) != len(set(self.effective_feasible_branches)):
                raise ValueError(
                    "proposal-conditioned assignment needs unique feasible branches"
                )
        return self


class ProposalLifetimeCounterV1(_ClosedModel):
    """Capacity-bounded host state for the exact lifetime UNKNOWN rule."""

    counter_version: Literal["sft_proposal_lifetime_counter_v1"] = (
        "sft_proposal_lifetime_counter_v1"
    )
    cell_sha256: str
    target_factor_key_sha256: str
    unknown_selection_count: int = Field(ge=1)
    single_safe_unknown_selection_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counter(self) -> "ProposalLifetimeCounterV1":
        _require_sha(self.cell_sha256, "cell_sha256")
        _require_sha(
            self.target_factor_key_sha256,
            "target_factor_key_sha256",
        )
        if self.single_safe_unknown_selection_count > self.unknown_selection_count:
            raise ValueError("single-safe UNKNOWN count exceeds UNKNOWN count")
        return self

    @property
    def witness(self) -> CandidateCounterWitnessV1:
        return CandidateCounterWitnessV1(
            cell_sha256=self.cell_sha256,
            target_factor_key_sha256=self.target_factor_key_sha256,
            unknown_selection_count=self.unknown_selection_count,
            single_safe_unknown_selection_count=(
                self.single_safe_unknown_selection_count
            ),
        )


def _proposal_lifetime_counter_root(
    counters: Sequence[ProposalLifetimeCounterV1],
    *,
    cell_sha256: str,
) -> str:
    """Root only one exact cell so unrelated namespaces cannot perturb choice."""

    return proposal_counter_state_sha256(
        tuple(
            item.witness
            for item in counters
            if item.cell_sha256 == cell_sha256
        )
    )


def _apply_proposal_counter_delta(
    counters: Sequence[ProposalLifetimeCounterV1],
    delta: ProposalCounterDeltaV1 | None,
    *,
    max_rows: int,
) -> tuple[ProposalLifetimeCounterV1, ...]:
    """Apply one committed selector delta without an LLM or hidden eviction."""

    by_key = {
        (item.cell_sha256, item.target_factor_key_sha256): item
        for item in counters
    }
    if len(by_key) != len(counters):
        raise ValueError("proposal lifetime-counter table has duplicate keys")
    if delta is not None:
        key = (delta.cell_sha256, delta.target_factor_key_sha256)
        before = by_key.get(key)
        if before is None:
            if len(by_key) >= max_rows:
                raise RuntimeError("proposal lifetime-counter capacity is exhausted")
            unknown_before = single_before = 0
        else:
            unknown_before = before.unknown_selection_count
            single_before = before.single_safe_unknown_selection_count
        by_key[key] = ProposalLifetimeCounterV1(
            cell_sha256=delta.cell_sha256,
            target_factor_key_sha256=delta.target_factor_key_sha256,
            unknown_selection_count=(
                unknown_before + delta.unknown_selection_increment
            ),
            single_safe_unknown_selection_count=(
                single_before
                + delta.single_safe_unknown_selection_increment
            ),
        )
    return tuple(by_key[key] for key in sorted(by_key))


class ProposalDecisionV1(_ClosedModel):
    """Pure selector receipt admitted against one authoritative Bank snapshot.

    Input and receipt own independent 64-KiB selector bounds.  The host applies
    the separate frozen decision bound only after this complete shape exists,
    because repeated exact joins and an optional verified generation context
    are not part of either selector object.
    """

    decision_version: Literal["sft_proposal_decision_v3"] = (
        "sft_proposal_decision_v3"
    )
    decision_id: str
    repair_opportunity_id: str
    repair_opportunity_sha256: str
    proposal_receipt: ProposalReceiptV1
    proposal_receipt_sha256: str
    proposal_scheduler_decision_sha256: str
    proposal_counter_state_before_sha256: str
    proposal_counter_state_after_sha256: str
    committed_counter_delta: ProposalCounterDeltaV1 | None
    committed_counter_delta_sha256: str
    candidate_slate_policy_sha256: str
    candidate_universe_sha256: str
    candidate_universe_count: int = Field(ge=0, le=4096)
    candidate_slate_target_revision_ids: tuple[str, ...] = Field(max_length=16)
    candidate_slate_sha256: str
    candidate_slate_scheduler_sha256: str
    candidate_slate_attestation_sha256: str
    generation_context: ProposalGenerationContextV1 | None = None
    generation_context_sha256: str | None = None
    effective_feasible_branches: tuple[ScientificBranch, ...]
    selected_branch: ScientificBranch | None
    cursor_committed: bool
    created_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_decision(self) -> "ProposalDecisionV1":
        for name in ("decision_id", "repair_opportunity_id"):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "repair_opportunity_sha256",
            "proposal_receipt_sha256",
            "proposal_scheduler_decision_sha256",
            "proposal_counter_state_before_sha256",
            "proposal_counter_state_after_sha256",
            "committed_counter_delta_sha256",
            "candidate_slate_policy_sha256",
            "candidate_universe_sha256",
            "candidate_slate_sha256",
            "candidate_slate_scheduler_sha256",
            "candidate_slate_attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.proposal_receipt_sha256 != self.proposal_receipt.digest:
            raise ValueError("proposal decision receipt digest mismatch")
        if (
            self.proposal_counter_state_before_sha256
            != self.proposal_receipt.proposal_counter_state_before_sha256
        ):
            raise ValueError("proposal decision counter root crosses its receipt")
        if self.committed_counter_delta_sha256 != _sha256(
            self.committed_counter_delta
        ):
            raise ValueError("proposal decision counter delta digest mismatch")
        if self.proposal_scheduler_decision_sha256 != (
            _host_proposal_scheduler_decision_sha256(
                receipt=self.proposal_receipt,
                candidate_universe_sha256=self.candidate_universe_sha256,
                candidate_universe_count=self.candidate_universe_count,
            )
        ):
            raise ValueError("proposal scheduler decision digest mismatch")
        if (self.generation_context is None) != (
            self.generation_context_sha256 is None
        ):
            raise ValueError("proposal decision generation context is partial")
        if self.generation_context is not None:
            assert self.generation_context_sha256 is not None
            _require_sha(
                self.generation_context_sha256,
                "generation_context_sha256",
            )
            if self.generation_context_sha256 != self.generation_context.digest:
                raise ValueError("proposal decision generation context digest mismatch")
        expected_id = _opaque_id(
            "pd",
            {
                "opportunity": self.repair_opportunity_sha256,
                "proposal": self.proposal_receipt_sha256,
            },
        )
        if self.decision_id != expected_id:
            raise ValueError("proposal decision identity is not reproducible")
        expected_target_ids = tuple(
            item.candidate.target_revision_id
            for item in self.proposal_receipt.candidate_manifest
        )
        if (
            self.candidate_slate_policy_sha256
            != _PROPOSAL_CANDIDATE_SLATE_POLICY_SHA256
            or self.candidate_slate_target_revision_ids != expected_target_ids
            or self.candidate_slate_sha256
            != _sha256(
                tuple(
                    item.candidate
                    for item in self.proposal_receipt.candidate_manifest
                )
            )
            or self.candidate_slate_scheduler_sha256
            != self.proposal_receipt.candidate_slate_scheduler_sha256
            or self.candidate_universe_count
            < len(self.candidate_slate_target_revision_ids)
        ):
            raise ValueError("proposal decision candidate-slate closure is invalid")
        if len(self.effective_feasible_branches) != len(
            set(self.effective_feasible_branches)
        ):
            raise ValueError("proposal decision needs unique feasible branches")
        requires_generation_context = any(
            branch in {"mutate", "fresh"}
            for branch in self.effective_feasible_branches
        )
        if requires_generation_context != (self.generation_context is not None):
            raise ValueError(
                "generated feasible branches require one verified generation context"
            )
        if not self.effective_feasible_branches and not (
            self.selected_branch is None
            and self.proposal_receipt.selection_mode == "no_safe_reuse"
        ):
            raise ValueError("only a no-safe proposal may exhaust every branch")
        if self.selected_branch is not None and (
            self.selected_branch not in self.effective_feasible_branches
        ):
            raise ValueError("proposal decision branch is not feasible")
        expected_cursor_commit = (
            self.selected_branch == "reuse"
            or self.proposal_receipt.selection_mode == "no_safe_reuse"
        )
        if self.cursor_committed != expected_cursor_commit:
            raise ValueError("proposal decision cursor ownership is inconsistent")
        expected_delta = (
            self.proposal_receipt.projected_counter_delta
            if self.selected_branch == "reuse"
            else None
        )
        if self.committed_counter_delta != expected_delta:
            raise ValueError("proposal decision committed the wrong counter delta")
        if self.committed_counter_delta is None and (
            self.proposal_counter_state_after_sha256
            != self.proposal_counter_state_before_sha256
        ):
            raise ValueError("counter root changed without a committed delta")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)

    @property
    def slate_attestation_body(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "repair_opportunity_sha256": self.repair_opportunity_sha256,
            "proposal_receipt_sha256": self.proposal_receipt_sha256,
            "proposal_scheduler_decision_sha256": (
                self.proposal_scheduler_decision_sha256
            ),
            "proposal_counter_state_before_sha256": (
                self.proposal_counter_state_before_sha256
            ),
            "candidate_counter_witnesses_sha256": (
                self.proposal_receipt.candidate_counter_witnesses_sha256
            ),
            "candidate_slate_policy_sha256": self.candidate_slate_policy_sha256,
            "candidate_universe_sha256": self.candidate_universe_sha256,
            "candidate_universe_count": self.candidate_universe_count,
            "candidate_slate_target_revision_ids": (
                self.candidate_slate_target_revision_ids
            ),
            "candidate_slate_sha256": self.candidate_slate_sha256,
            "candidate_slate_scheduler_sha256": (
                self.candidate_slate_scheduler_sha256
            ),
            "generation_context_sha256": self.generation_context_sha256,
        }


def _proposal_decision_canonical_bytes(decision: ProposalDecisionV1) -> int:
    """Return the exact persisted size used by every decision-capacity Gate."""

    return len(_canonical_json(decision).encode("utf-8"))


def _assert_proposal_decision_byte_bound(
    decision: ProposalDecisionV1,
    *,
    max_bytes: int,
) -> None:
    """Fail closed on one exact decision before publication or full replay."""

    if max_bytes != MAX_PROPOSAL_DECISION_BYTES:
        raise ValueError("proposal decision byte capacity is not the frozen value")
    actual = _proposal_decision_canonical_bytes(decision)
    if actual > max_bytes:
        raise ValueError(
            "canonical proposal decision exceeds frozen "
            f"{max_bytes}-byte capacity"
        )


class ProposalGenerationContextV1(_ClosedModel):
    """Host-resolved TRAIN context admitted before branch selection."""

    context_version: Literal["sft_proposal_generation_context_v1"] = (
        "sft_proposal_generation_context_v1"
    )
    context_id: str
    proposal_receipt_sha256: str
    repair_opportunity_id: str
    repair_opportunity_sha256: str
    failure_observation_sha256: str
    namespace_digest: str
    source_composition_id: str
    source_artifact_id: str
    slot_id: str
    locator_path: str
    from_revision_id: str
    source_manifest_sha256: str
    train_update_source_catalog_sha256: str
    train_update_policy_sha256: str
    safe_failure_code: str
    failure_artifact_sha256: str
    generation_policy_sha256: str
    prompt_template_sha256: str
    scalar_output_schema_sha256: str
    model_name: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    runtime_version: str
    budget: ExecutionBudget
    budget_sha256: str
    verifier_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_context(self) -> "ProposalGenerationContextV1":
        for name in (
            "context_id", "repair_opportunity_id", "source_composition_id", "source_artifact_id",
            "slot_id", "from_revision_id", "safe_failure_code",
            "runtime_version", "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "proposal_receipt_sha256", "repair_opportunity_sha256",
            "failure_observation_sha256", "namespace_digest",
            "source_manifest_sha256", "train_update_source_catalog_sha256",
            "train_update_policy_sha256", "failure_artifact_sha256",
            "generation_policy_sha256", "prompt_template_sha256",
            "scalar_output_schema_sha256", "budget_sha256",
            "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.budget_sha256 != self.budget.digest:
            raise ValueError("generation context budget commitment is not reproducible")
        body = self.model_dump(mode="python", exclude={"context_id"})
        if self.context_id != _opaque_id("pgc", body):
            raise ValueError("generation context identity is not reproducible")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


# The decision shape is declared immediately before this context to keep the
# existing proposal schema grouping stable.  Resolve that one forward type now
# that the closed context model exists.
ProposalDecisionV1.model_rebuild()


class ProposalGenerationRequestV1(_ClosedModel):
    """One bounded scalar-generation request derived from a verified context."""

    request_version: Literal["sft_proposal_generation_request_v1"] = (
        "sft_proposal_generation_request_v1"
    )
    request_id: str
    action_id: str
    branch: Literal["mutate", "fresh"]
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    generation_context_sha256: str
    repair_opportunity_sha256: str
    failure_observation_sha256: str
    namespace_digest: str
    source_composition_id: str
    source_artifact_id: str
    slot_id: str
    locator_path: str
    from_revision_id: str
    dependency_factor_ids: tuple[str, ...]
    source_manifest_sha256: str
    train_update_source_catalog_sha256: str
    train_update_policy_sha256: str
    safe_failure_code: str
    failure_artifact_sha256: str
    generation_policy_sha256: str
    prompt_template_sha256: str
    scalar_output_schema_sha256: str
    model_name: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    runtime_version: str
    budget: ExecutionBudget
    budget_sha256: str

    @model_validator(mode="after")
    def validate_request(self) -> "ProposalGenerationRequestV1":
        for name in (
            "request_id", "action_id", "source_composition_id",
            "source_artifact_id", "slot_id", "from_revision_id",
            "safe_failure_code", "runtime_version",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "generation_context_sha256", "repair_opportunity_sha256",
            "failure_observation_sha256", "namespace_digest",
            "source_manifest_sha256", "train_update_source_catalog_sha256",
            "train_update_policy_sha256", "failure_artifact_sha256",
            "generation_policy_sha256", "prompt_template_sha256",
            "scalar_output_schema_sha256", "budget_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        for factor_id in self.dependency_factor_ids:
            _require_id(factor_id, "dependency_factor_id")
        expected_dependencies = (
            (self.from_revision_id,) if self.branch == "mutate" else ()
        )
        if self.dependency_factor_ids != expected_dependencies:
            raise ValueError("generation request branch dependency is not exact")
        if self.budget_sha256 != self.budget.digest:
            raise ValueError("generation request budget commitment is not reproducible")
        body = self.model_dump(mode="python", exclude={"request_id"})
        if self.request_id != _opaque_id("grq", body):
            raise ValueError("generation request identity is not reproducible")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ProposalGenerationLeaseV1(_ClosedModel):
    """Bank-started generation-1 authority; never a retry token."""

    lease_version: Literal["sft_proposal_generation_lease_v1"] = (
        "sft_proposal_generation_lease_v1"
    )
    lease_id: str
    action_id: str
    generation_request_sha256: str
    expected_prepared_action_sha256: str
    runner_session_id: str
    runner_lease_token_sha256: str
    fencing_generation: Literal[1] = 1
    journal_anchor_sha256: str
    verifier_epoch: str
    attestation_sha256: str
    started_seq: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_lease(self) -> "ProposalGenerationLeaseV1":
        for name in (
            "lease_id", "action_id", "runner_session_id", "verifier_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "generation_request_sha256", "expected_prepared_action_sha256",
            "runner_lease_token_sha256", "journal_anchor_sha256",
            "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        body = self.model_dump(mode="python", exclude={"lease_id", "started_seq"})
        if self.lease_id != _opaque_id("pgl", body):
            raise ValueError("proposal generation lease identity is not reproducible")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


def _proposal_action_intent_sha256(
    *,
    action_id: str,
    assignment_id: str,
    assignment_sha256: str,
    proposal_decision_id: str,
    proposal_decision_sha256: str,
    proposal_receipt_sha256: str,
    branch: ScientificBranch,
    namespace_digest: str,
    source_composition_id: str,
    source_artifact_id: str,
    slot_id: str,
    locator_path: str,
    from_revision_id: str,
    dependency_factor_ids: tuple[str, ...],
    selected_target_revision_id: str | None,
    selected_target_content_sha256: str | None,
    generation_context_sha256: str | None,
    generation_request_sha256: str | None,
    carrier_capacity_reservation_id: str | None,
    producer_epoch: str,
    attestation_sha256: str,
) -> str:
    """Digest the immutable Bank→carrier command without a self-hash cycle."""

    return _sha256(
        {
            "intent_version": "sft_proposal_action_intent_v2",
            "action_id": action_id,
            "assignment_id": assignment_id,
            "assignment_sha256": assignment_sha256,
            "proposal_decision_id": proposal_decision_id,
            "proposal_decision_sha256": proposal_decision_sha256,
            "proposal_receipt_sha256": proposal_receipt_sha256,
            "branch": branch,
            "namespace_digest": namespace_digest,
            "source_composition_id": source_composition_id,
            "source_artifact_id": source_artifact_id,
            "slot_id": slot_id,
            "locator_path": locator_path,
            "from_revision_id": from_revision_id,
            "dependency_factor_ids": dependency_factor_ids,
            "selected_target_revision_id": selected_target_revision_id,
            "selected_target_content_sha256": selected_target_content_sha256,
            "generation_context_sha256": generation_context_sha256,
            "generation_request_sha256": generation_request_sha256,
            "carrier_capacity_reservation_id": carrier_capacity_reservation_id,
            "producer_epoch": producer_epoch,
            "attestation_sha256": attestation_sha256,
        }
    )


class ProposalActionAbortReceiptV2(_ClosedModel):
    """Authenticated generation-2 fence over one exact action predecessor."""

    receipt_version: Literal["sft_proposal_action_abort_v2"] = (
        "sft_proposal_action_abort_v2"
    )
    abort_id: str
    action_id: str
    predecessor_state: Literal["prepared", "executing"]
    expected_action_sha256: str
    reason: Literal[
        "phase_noop", "phase_rejected", "lease_expired", "runner_fenced",
        "carrier_capacity", "generation_invalid_output",
        "generation_budget_exceeded", "generation_runner_crash",
        "generation_terminal_rejected",
    ]
    phase_terminal_sha256: str | None = None
    expected_fencing_generation: Literal[1] = 1
    next_fencing_generation: Literal[2] = 2
    safe_failure_code: str
    verifier_epoch: str
    attestation_sha256: str
    cleanup_transition_id: str | None = None
    cleanup_transition_sha256: str | None = None
    cleanup_action_intent_sha256: str | None = None
    cleanup_admission_id: str | None = None
    cleanup_admission_sha256: str | None = None
    emitted_seq: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_abort(self) -> "ProposalActionAbortReceiptV2":
        for name in ("abort_id", "action_id", "safe_failure_code", "verifier_epoch"):
            _require_id(str(getattr(self, name)), name)
        for name in ("expected_action_sha256", "attestation_sha256"):
            _require_sha(str(getattr(self, name)), name)
        if self.phase_terminal_sha256 is not None:
            _require_sha(self.phase_terminal_sha256, "phase_terminal_sha256")
        cleanup_values = (
            self.cleanup_transition_id,
            self.cleanup_transition_sha256,
            self.cleanup_action_intent_sha256,
            self.cleanup_admission_id,
            self.cleanup_admission_sha256,
        )
        if any(item is not None for item in cleanup_values) != all(
            item is not None for item in cleanup_values
        ):
            raise ValueError("proposal abort cleanup commitment must be all-or-none")
        if self.cleanup_transition_id is not None:
            _require_id(self.cleanup_transition_id, "cleanup_transition_id")
            assert self.cleanup_transition_sha256 is not None
            assert self.cleanup_action_intent_sha256 is not None
            assert self.cleanup_admission_id is not None
            assert self.cleanup_admission_sha256 is not None
            _require_sha(
                self.cleanup_transition_sha256,
                "cleanup_transition_sha256",
            )
            _require_sha(
                self.cleanup_action_intent_sha256,
                "cleanup_action_intent_sha256",
            )
            _require_id(self.cleanup_admission_id, "cleanup_admission_id")
            _require_sha(
                self.cleanup_admission_sha256,
                "cleanup_admission_sha256",
            )
            generated_cleanup = (
                self.predecessor_state == "executing"
                and self.reason.startswith("generation_")
            )
            reuse_cleanup = (
                self.predecessor_state == "prepared"
                and self.reason == "phase_rejected"
                and self.phase_terminal_sha256 is not None
            )
            if not (generated_cleanup or reuse_cleanup):
                raise ValueError(
                    "inert-edge cleanup requires an exact generated or reuse rejection"
                )
        if self.reason in {
            "phase_noop", "generation_terminal_rejected",
        } and self.phase_terminal_sha256 is None:
            raise ValueError(
                "Phase/generation terminal rejection requires its commitment"
            )
        if self.reason not in {
            "phase_noop", "phase_rejected", "generation_terminal_rejected",
        } and (
            self.phase_terminal_sha256 is not None
        ):
            raise ValueError("abort reason cannot carry a Phase terminal")
        body = self.model_dump(mode="python", exclude={"abort_id", "emitted_seq"})
        # Preserve the identity of ordinary v5 abort receipts serialized before
        # cleanup recovery existed.  New cleanup receipts commit all three
        # fields, while the all-None legacy shape hashes byte-for-byte as before.
        if self.cleanup_transition_id is None:
            body.pop("cleanup_transition_id")
            body.pop("cleanup_transition_sha256")
            body.pop("cleanup_action_intent_sha256")
            body.pop("cleanup_admission_id")
            body.pop("cleanup_admission_sha256")
        if self.abort_id != _opaque_id("pab", body):
            raise ValueError("proposal abort identity is not reproducible")
        return self


class ProposalActionV2(_ClosedModel):
    """One durable reuse/mutate/fresh assignment→carrier transaction."""

    action_version: Literal["sft_proposal_action_v2"] = "sft_proposal_action_v2"
    action_id: str
    assignment_id: str
    assignment_sha256: str
    proposal_decision_id: str
    proposal_decision_sha256: str
    proposal_receipt_sha256: str
    proposal_policy_sha256: str
    proposal_cursor_before_sha256: str
    proposal_candidate_manifest_sha256: str
    proposal_projected_history_sha256: str
    branch: ScientificBranch
    namespace_digest: str
    source_composition_id: str
    source_artifact_id: str
    slot_id: str
    locator_path: str
    from_revision_id: str
    from_content_sha256: str
    dependency_factor_ids: tuple[str, ...]
    selected_target_revision_id: str | None = None
    selected_target_content_sha256: str | None = None
    generation_context: ProposalGenerationContextV1 | None = None
    generation_request: ProposalGenerationRequestV1 | None = None
    carrier_capacity_reservation_id: str | None = None
    action_intent_sha256: str
    exact_additional_input_root_commitments: tuple[str, ...]
    state: ProposalActionState = "prepared"
    generation_lease: ProposalGenerationLeaseV1 | None = None
    generation_terminal_sha256: str | None = None
    resolved_to_revision_id: str | None = None
    resolved_target_content_sha256: str | None = None
    phase_terminal_sha256: str | None = None
    transition_id: str | None = None
    binding_proof_id: str | None = None
    abort_receipt: ProposalActionAbortReceiptV2 | None = None
    fencing_generation: Literal[1, 2] = 1
    producer_epoch: str
    attestation_sha256: str
    prepared_seq: int = Field(ge=0)
    updated_seq: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_action(self) -> "ProposalActionV2":
        for name in (
            "action_id", "assignment_id", "proposal_decision_id",
            "source_composition_id", "source_artifact_id", "slot_id",
            "from_revision_id", "producer_epoch",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "assignment_sha256", "proposal_decision_sha256",
            "proposal_receipt_sha256", "proposal_policy_sha256",
            "proposal_cursor_before_sha256",
            "proposal_candidate_manifest_sha256",
            "proposal_projected_history_sha256", "namespace_digest",
            "from_content_sha256", "action_intent_sha256", "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        for name in ("selected_target_revision_id", "resolved_to_revision_id"):
            value = getattr(self, name)
            if value is not None:
                _require_id(value, name)
        if self.carrier_capacity_reservation_id is not None:
            _require_id(
                self.carrier_capacity_reservation_id,
                "carrier_capacity_reservation_id",
            )
        for name in (
            "selected_target_content_sha256", "resolved_target_content_sha256",
            "generation_terminal_sha256", "phase_terminal_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_sha(value, name)
        if self.transition_id is not None:
            _require_id(self.transition_id, "transition_id")
        if self.binding_proof_id is not None:
            _require_id(self.binding_proof_id, "binding_proof_id")
        expected_action_id = _opaque_id(
            "ptx", {"assignment": self.assignment_sha256,
                    "proposal": self.proposal_receipt_sha256},
        )
        if self.action_id != expected_action_id:
            raise ValueError("proposal action identity is not reproducible")
        context_sha = self.generation_context.digest if self.generation_context else None
        request_sha = self.generation_request.digest if self.generation_request else None
        if self.branch == "reuse":
            if (
                self.selected_target_revision_id is None
                or self.selected_target_content_sha256 is None
                or self.generation_request is not None
                or self.carrier_capacity_reservation_id is not None
                or self.dependency_factor_ids != (self.selected_target_revision_id,)
            ):
                raise ValueError("reuse action target/dependency shape is not exact")
        elif self.branch == "mutate":
            if (
                self.selected_target_revision_id is not None
                or self.selected_target_content_sha256 is not None
                or self.generation_context is None
                or self.generation_request is None
                or self.carrier_capacity_reservation_id is None
                or self.dependency_factor_ids != (self.from_revision_id,)
            ):
                raise ValueError("mutate action requires only its exact source parent")
        elif (
            self.selected_target_revision_id is not None
            or self.selected_target_content_sha256 is not None
            or self.generation_context is None
            or self.generation_request is None
            or self.carrier_capacity_reservation_id is None
            or self.dependency_factor_ids
        ):
            raise ValueError("fresh action requires an empty Bank dependency")
        if self.generation_request is not None:
            request = self.generation_request
            context = self.generation_context
            assert context is not None
            if not (
                request.action_id == self.action_id
                and request.branch == self.branch
                and request.generation_context_sha256 == context.digest
                and request.repair_opportunity_sha256
                == context.repair_opportunity_sha256
                and request.failure_observation_sha256
                == context.failure_observation_sha256
                and request.namespace_digest == self.namespace_digest
                and request.source_composition_id == self.source_composition_id
                and request.source_artifact_id == self.source_artifact_id
                and request.slot_id == self.slot_id
                and request.locator_path == self.locator_path
                and request.from_revision_id == self.from_revision_id
                and request.dependency_factor_ids == self.dependency_factor_ids
                and request.source_manifest_sha256 == context.source_manifest_sha256
                and request.train_update_source_catalog_sha256
                == context.train_update_source_catalog_sha256
                and request.train_update_policy_sha256
                == context.train_update_policy_sha256
                and request.safe_failure_code == context.safe_failure_code
                and request.failure_artifact_sha256 == context.failure_artifact_sha256
                and request.generation_policy_sha256 == context.generation_policy_sha256
                and request.prompt_template_sha256 == context.prompt_template_sha256
                and request.scalar_output_schema_sha256
                == context.scalar_output_schema_sha256
                and request.model_name == context.model_name
                and request.runtime_version == context.runtime_version
                and request.budget == context.budget
                and request.budget_sha256 == context.budget_sha256
            ):
                raise ValueError("generation request differs from its verified context")
        expected_intent = _proposal_action_intent_sha256(
            action_id=self.action_id,
            assignment_id=self.assignment_id,
            assignment_sha256=self.assignment_sha256,
            proposal_decision_id=self.proposal_decision_id,
            proposal_decision_sha256=self.proposal_decision_sha256,
            proposal_receipt_sha256=self.proposal_receipt_sha256,
            branch=self.branch,
            namespace_digest=self.namespace_digest,
            source_composition_id=self.source_composition_id,
            source_artifact_id=self.source_artifact_id,
            slot_id=self.slot_id,
            locator_path=self.locator_path,
            from_revision_id=self.from_revision_id,
            dependency_factor_ids=self.dependency_factor_ids,
            selected_target_revision_id=self.selected_target_revision_id,
            selected_target_content_sha256=self.selected_target_content_sha256,
            generation_context_sha256=context_sha,
            generation_request_sha256=request_sha,
            carrier_capacity_reservation_id=(
                self.carrier_capacity_reservation_id
            ),
            producer_epoch=self.producer_epoch,
            attestation_sha256=self.attestation_sha256,
        )
        if self.action_intent_sha256 != expected_intent:
            raise ValueError("proposal action intent digest is not reproducible")
        expected_roots = {
            self.assignment_sha256, self.proposal_decision_sha256,
            self.proposal_receipt_sha256, self.proposal_policy_sha256,
            self.proposal_cursor_before_sha256,
            self.proposal_candidate_manifest_sha256,
            self.proposal_projected_history_sha256, self.action_intent_sha256,
        }
        if self.generation_context is not None:
            context = self.generation_context
            expected_roots.update({
                context.digest, context.source_manifest_sha256,
                context.repair_opportunity_sha256,
                context.failure_observation_sha256,
                context.train_update_source_catalog_sha256,
                context.train_update_policy_sha256,
                context.failure_artifact_sha256,
                context.generation_policy_sha256,
                context.prompt_template_sha256,
                context.scalar_output_schema_sha256,
                context.budget_sha256,
            })
        if self.generation_request is not None:
            expected_roots.add(self.generation_request.digest)
        roots = self.exact_additional_input_root_commitments
        if roots != tuple(sorted(expected_roots)):
            raise ValueError("proposal action input-root closure is not exact")
        if self.updated_seq < self.prepared_seq:
            raise ValueError("proposal action update predates prepare")
        terminal_fields = (
            self.generation_terminal_sha256, self.resolved_to_revision_id,
            self.resolved_target_content_sha256, self.phase_terminal_sha256,
            self.transition_id, self.binding_proof_id,
        )
        if self.state == "prepared":
            if (
                self.generation_lease is not None
                or any(item is not None for item in terminal_fields)
                or self.abort_receipt is not None
                or self.fencing_generation != 1
                or self.updated_seq != self.prepared_seq
            ):
                raise ValueError("prepared proposal action carries terminal state")
        elif self.state == "executing":
            if (
                self.branch == "reuse" or self.generation_lease is None
                or self.generation_lease.started_seq is None
                or any(item is not None for item in terminal_fields)
                or self.abort_receipt is not None
                or self.fencing_generation != 1
                or self.updated_seq != self.generation_lease.started_seq
                or self.updated_seq <= self.prepared_seq
            ):
                raise ValueError("executing proposal action lacks one exact lease")
        elif self.state == "committed":
            common_complete = all(
                item is not None
                for item in (
                    self.resolved_to_revision_id,
                    self.resolved_target_content_sha256,
                    self.phase_terminal_sha256,
                    self.transition_id,
                    self.binding_proof_id,
                )
            )
            branch_complete = (
                self.generation_lease is None
                and self.generation_terminal_sha256 is None
                and self.resolved_to_revision_id == self.selected_target_revision_id
                and self.resolved_target_content_sha256
                == self.selected_target_content_sha256
                if self.branch == "reuse"
                else (
                    self.generation_lease is not None
                    and self.generation_lease.started_seq is not None
                    and self.generation_terminal_sha256 is not None
                    and self.updated_seq > self.generation_lease.started_seq
                )
            )
            if (
                not common_complete or not branch_complete
                or self.abort_receipt is not None
                or self.fencing_generation != 1
                or self.updated_seq <= self.prepared_seq
            ):
                raise ValueError("committed proposal action lacks its exact terminal")
        else:
            if (
                self.abort_receipt is None
                or any(item is not None for item in terminal_fields)
                or self.fencing_generation != 2
                or self.abort_receipt.emitted_seq != self.updated_seq
                or self.abort_receipt.predecessor_state
                != ("executing" if self.generation_lease is not None else "prepared")
                or (
                    self.generation_lease is not None
                    and self.generation_lease.started_seq is not None
                    and self.updated_seq <= self.generation_lease.started_seq
                )
            ):
                raise ValueError("aborted proposal action lacks its authenticated fence")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)

    # Reuse-only v6 adapter compatibility.  These are projections, never
    # serialized v4 fields or a migration path.
    @property
    def to_revision_id(self) -> str | None:
        return self.resolved_to_revision_id or self.selected_target_revision_id

    @property
    def target_content_sha256(self) -> str | None:
        return (
            self.resolved_target_content_sha256
            or self.selected_target_content_sha256
        )


class ProposalCarrierAdmissionV1(_ClosedModel):
    """Eligibility lineage for the exact target of one action-owned edge.

    Structural rows may outlive a rejected action because they can be shared or
    needed for audit.  This record prevents mere storage from being mistaken
    for reuse authority: action-exclusive content is staged until the same
    edge/action terminal commits, then either admitted or quarantined.
    """

    admission_version: Literal["sft_proposal_carrier_admission_v2"] = (
        "sft_proposal_carrier_admission_v2"
    )
    admission_id: str
    action_id: str
    action_intent_sha256: str
    transition_id: str
    projected_transition_sha256: str
    namespace_digest: str
    source_composition_id: str
    target_composition_id: str
    target_composition_sha256: str
    target_composition_carrier_key_sha256: str
    target_factor_revision_id: str
    target_factor_sha256: str
    target_factor_carrier_key_sha256: str
    independent_authority_cutoff_seq: int = Field(ge=0)
    factor_independently_eligible_before: bool
    composition_independently_eligible_before: bool
    state: CarrierAdmissionState = "staged"
    created_seq: int = Field(ge=1)
    terminal_seq: int | None = Field(default=None, ge=1)
    terminal_sha256: str | None = None

    @model_validator(mode="after")
    def validate_admission(self) -> "ProposalCarrierAdmissionV1":
        for name in (
            "admission_id", "action_id", "transition_id",
            "source_composition_id", "target_composition_id",
            "target_factor_revision_id",
        ):
            _require_id(str(getattr(self, name)), name)
        for name in (
            "action_intent_sha256", "projected_transition_sha256",
            "namespace_digest", "target_composition_sha256",
            "target_composition_carrier_key_sha256",
            "target_factor_sha256", "target_factor_carrier_key_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.terminal_sha256 is not None:
            _require_sha(self.terminal_sha256, "terminal_sha256")
        identity = self.model_dump(
            mode="python",
            exclude={
                "admission_id", "state", "terminal_seq", "terminal_sha256",
            },
        )
        if self.admission_id != _opaque_id("pca", identity):
            raise ValueError("proposal carrier admission identity is not reproducible")
        if self.state == "staged":
            if self.terminal_seq is not None or self.terminal_sha256 is not None:
                raise ValueError("staged carrier admission carries a terminal")
        elif (
            self.terminal_seq is None
            or self.terminal_sha256 is None
            or self.terminal_seq <= self.created_seq
        ):
            raise ValueError("terminal carrier admission lacks its exact successor")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ProposalCarrierCapacityReservationV1(_ClosedModel):
    """Bank-owned worst-case closure capacity acquired before generation START."""

    reservation_version: Literal["sft_proposal_carrier_capacity_v1"] = (
        "sft_proposal_carrier_capacity_v1"
    )
    reservation_id: str
    action_id: str
    namespace_digest: str
    capacity_policy_sha256: str
    reserved_factor_records: Literal[1] = 1
    reserved_composition_records: Literal[1] = 1
    reserved_hot_composition_slots: Literal[1] = 1
    reserved_transition_records: Literal[1] = 1
    reserved_admission_records: Literal[1] = 1
    reserved_hot_metadata_bytes: int = Field(ge=1024)
    reserved_artifact_bytes: int = Field(ge=1024)
    reserved_prompt_summary_tokens: int = Field(ge=0)
    reserved_structural_bytes: int = Field(ge=4096)
    reserved_transition_bytes: int = Field(ge=2048)
    reserved_admission_bytes: int = Field(ge=2048)
    reserved_owner_slab_bytes: int = Field(ge=4096)
    state: Literal["reserved", "materialized", "consumed", "released"] = (
        "reserved"
    )
    created_seq: int = Field(ge=1)
    materialized_seq: int | None = Field(default=None, ge=1)
    released_seq: int | None = Field(default=None, ge=1)
    consumed_seq: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_carrier_capacity_reservation(
        self,
    ) -> "ProposalCarrierCapacityReservationV1":
        _require_id(self.reservation_id, "reservation_id")
        _require_id(self.action_id, "action_id")
        _require_sha(self.namespace_digest, "namespace_digest")
        _require_sha(self.capacity_policy_sha256, "capacity_policy_sha256")
        identity = self.model_dump(
            mode="python",
            exclude={
                "reservation_id",
                "state",
                "materialized_seq",
                "released_seq",
                "consumed_seq",
            },
        )
        if self.reservation_id != _opaque_id("pcr", identity):
            raise ValueError("proposal carrier reservation identity is not reproducible")
        if self.state == "reserved":
            if any(
                item is not None
                for item in (
                    self.materialized_seq,
                    self.released_seq,
                    self.consumed_seq,
                )
            ):
                raise ValueError("reserved carrier capacity has a later lifecycle event")
        elif self.state == "materialized":
            if (
                self.materialized_seq is None
                or self.materialized_seq <= self.created_seq
                or self.released_seq is not None
                or self.consumed_seq is not None
            ):
                raise ValueError("materialized carrier capacity lacks its exact event")
        elif self.state == "consumed":
            if (
                self.materialized_seq is None
                or self.consumed_seq is None
                or self.materialized_seq <= self.created_seq
                or self.consumed_seq <= self.materialized_seq
                or self.released_seq is not None
            ):
                raise ValueError("consumed carrier capacity lacks its exact closure")
        elif (
            self.released_seq is None
            or self.released_seq <= self.created_seq
            or self.materialized_seq is not None
            or self.consumed_seq is not None
        ):
            raise ValueError("released carrier capacity was not a pre-edge abort")
        return self

    @property
    def reserved_total_bytes(self) -> int:
        return (
            self.reserved_structural_bytes
            + self.reserved_hot_metadata_bytes
            + self.reserved_artifact_bytes
            + self.reserved_transition_bytes
            + self.reserved_admission_bytes
            + self.reserved_owner_slab_bytes
        )


class FactorBankStateV2(_ClosedModel):
    schema_version: Literal[SFT_BANK_SCHEMA_VERSION] = SFT_BANK_SCHEMA_VERSION
    event_seq: int = Field(default=0, ge=0)
    previous_state_sha256: str = Field(default_factory=lambda: "0" * 64)
    capacity_policy: CapacityPolicyV1 = Field(default_factory=CapacityPolicyV1)
    factors: tuple[FactorRevisionV2, ...] = ()
    compositions: tuple[CompositionRevisionV2, ...] = ()
    direct_transitions: tuple[DirectFactorTransitionV2, ...] = ()
    whole_transitions: tuple[WholeCompositionTransitionV2, ...] = ()
    plans: tuple[ProbePlanV2, ...] = ()
    reservations: tuple[PlanCapacityReservationV2, ...] = ()
    attempts: tuple[ProbeAttemptV3, ...] = ()
    assessments: tuple[EdgeAssessmentV2, ...] = ()
    gate_opportunities: tuple[GateOpportunityV2, ...] = ()
    gate_receipts: tuple[GateReceiptV2, ...] = ()
    base_receipts: tuple[BaseSnapshotReceiptV2, ...] = ()
    deployment_snapshots: tuple[DeploymentSnapshotV2, ...] = ()
    deployment_heads: tuple[DeploymentHeadV2, ...] = ()
    rollback_triggers: tuple[RollbackTriggerV2, ...] = ()
    rollback_records: tuple[RollbackRecordV2, ...] = ()
    failures: tuple[FailureObservationV2, ...] = ()
    repair_opportunities: tuple[RepairOpportunityV2, ...] = ()
    branch_assignments: tuple[BranchAssignmentV2, ...] = ()
    proposal_decisions: tuple[ProposalDecisionV1, ...] = ()
    proposal_lifetime_counters: tuple[ProposalLifetimeCounterV1, ...] = ()
    proposal_actions: tuple[ProposalActionV2, ...] = ()
    proposal_carrier_reservations: tuple[
        ProposalCarrierCapacityReservationV1, ...
    ] = ()
    proposal_carrier_admissions: tuple[ProposalCarrierAdmissionV1, ...] = ()
    exposures: tuple[tuple[str, int], ...] = ()
    used_roots: tuple[tuple[str, str], ...] = ()
    used_receipts: tuple[tuple[str, str], ...] = ()
    used_edge_epochs: tuple[tuple[str, str], ...] = ()
    used_unit_commitments: tuple[tuple[str, str], ...] = ()
    tombstones: tuple[NegativeTombstoneV2, ...] = ()
    portable_evidence_leaves: tuple[PortableEvidenceLeafV1, ...] = ()
    checkpoints: tuple[ColdCheckpointV2, ...] = ()

    @model_validator(mode="after")
    def validate_uniqueness(self) -> "FactorBankStateV2":
        _require_sha(self.previous_state_sha256, "previous_state_sha256")
        collections = (
            ("factor", [item.revision_id for item in self.factors]),
            ("composition", [item.composition_id for item in self.compositions]),
            ("direct transition", [item.transition_id for item in self.direct_transitions]),
            ("whole transition", [item.transition_id for item in self.whole_transitions]),
            ("plan", [item.plan_id for item in self.plans]),
            ("reservation", [item.reservation_id for item in self.reservations]),
            ("attempt", [item.attempt_id for item in self.attempts]),
            ("runner lease", [item.runner_lease.lease_id for item in self.attempts]),
            (
                "runner lease token",
                [item.runner_lease.runner_lease_token_sha256 for item in self.attempts],
            ),
            (
                "attempt cancellation",
                [
                    item.cancellation_receipt.cancellation_id
                    for item in self.attempts
                    if item.cancellation_receipt is not None
                ],
            ),
            (
                "pair execution receipt",
                [
                    item.pair_execution_receipt.pair_receipt_id
                    for item in self.attempts
                    if item.pair_execution_receipt is not None
                ],
            ),
            ("assessment", [item.assessment_id for item in self.assessments]),
            ("gate opportunity", [item.opportunity_id for item in self.gate_opportunities]),
            ("gate receipt", [item.decision_id for item in self.gate_receipts]),
            ("base receipt", [item.receipt_id for item in self.base_receipts]),
            ("snapshot", [item.snapshot_id for item in self.deployment_snapshots]),
            ("head", [item.deployment_slot_id for item in self.deployment_heads]),
            ("rollback trigger", [item.trigger_id for item in self.rollback_triggers]),
            ("rollback", [item.rollback_id for item in self.rollback_records]),
            ("failure", [item.failure_id for item in self.failures]),
            ("repair opportunity", [item.opportunity_id for item in self.repair_opportunities]),
            ("branch assignment", [item.assignment_id for item in self.branch_assignments]),
            ("proposal decision", [item.decision_id for item in self.proposal_decisions]),
            (
                "proposal lifetime counter",
                [
                    (item.cell_sha256, item.target_factor_key_sha256)
                    for item in self.proposal_lifetime_counters
                ],
            ),
            ("proposal action", [item.action_id for item in self.proposal_actions]),
            (
                "proposal carrier reservation",
                [item.reservation_id for item in self.proposal_carrier_reservations],
            ),
            (
                "proposal carrier reservation action",
                [item.action_id for item in self.proposal_carrier_reservations],
            ),
            (
                "proposal carrier admission",
                [item.admission_id for item in self.proposal_carrier_admissions],
            ),
            (
                "proposal carrier admission action",
                [item.action_id for item in self.proposal_carrier_admissions],
            ),
            (
                "proposal carrier admission transition",
                [item.transition_id for item in self.proposal_carrier_admissions],
            ),
            (
                "proposal generation request",
                [
                    item.generation_request.request_id
                    for item in self.proposal_actions
                    if item.generation_request is not None
                ],
            ),
            (
                "proposal generation request digest",
                [
                    item.generation_request.digest
                    for item in self.proposal_actions
                    if item.generation_request is not None
                ],
            ),
            (
                "proposal generation lease",
                [
                    item.generation_lease.lease_id
                    for item in self.proposal_actions
                    if item.generation_lease is not None
                ],
            ),
            (
                "proposal generation lease token",
                [
                    item.generation_lease.runner_lease_token_sha256
                    for item in self.proposal_actions
                    if item.generation_lease is not None
                ],
            ),
            (
                "proposal generation terminal",
                [
                    item.generation_terminal_sha256
                    for item in self.proposal_actions
                    if item.generation_terminal_sha256 is not None
                ],
            ),
            (
                "proposal action abort",
                [
                    item.abort_receipt.abort_id
                    for item in self.proposal_actions
                    if item.abort_receipt is not None
                ],
            ),
            (
                "proposal action cleanup transition",
                [
                    item.abort_receipt.cleanup_transition_id
                    for item in self.proposal_actions
                    if item.abort_receipt is not None
                    and item.abort_receipt.cleanup_transition_id is not None
                ],
            ),
            (
                "proposal action cleanup transition digest",
                [
                    item.abort_receipt.cleanup_transition_sha256
                    for item in self.proposal_actions
                    if item.abort_receipt is not None
                    and item.abort_receipt.cleanup_transition_sha256 is not None
                ],
            ),
            (
                "proposal action cleanup admission",
                [
                    item.abort_receipt.cleanup_admission_id
                    for item in self.proposal_actions
                    if item.abort_receipt is not None
                    and item.abort_receipt.cleanup_admission_id is not None
                ],
            ),
            (
                "proposal action cleanup admission digest",
                [
                    item.abort_receipt.cleanup_admission_sha256
                    for item in self.proposal_actions
                    if item.abort_receipt is not None
                    and item.abort_receipt.cleanup_admission_sha256 is not None
                ],
            ),
            ("tombstone", [item.tombstone_id for item in self.tombstones]),
            (
                "portable evidence leaf",
                [item.leaf_id for item in self.portable_evidence_leaves],
            ),
            ("checkpoint", [item.checkpoint_id for item in self.checkpoints]),
        )
        for label, identifiers in collections:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} identifier")
        counter_keys = tuple(
            (item.cell_sha256, item.target_factor_key_sha256)
            for item in self.proposal_lifetime_counters
        )
        if counter_keys != tuple(sorted(counter_keys)):
            raise ValueError("proposal lifetime counters must be key-sorted")
        roots = [item[0] for item in self.used_roots]
        receipts = [item[0] for item in self.used_receipts]
        if len(roots) != len(set(roots)) or len(receipts) != len(set(receipts)):
            raise ValueError("used root/receipt registries must be globally unique")
        if len(self.used_edge_epochs) != len(set(self.used_edge_epochs)):
            raise ValueError("used scientific edge/epoch pairs must be globally unique")
        for edge_key, epoch_id in self.used_edge_epochs:
            _require_sha(edge_key, "used epoch scientific edge key")
            _require_id(epoch_id, "used edge epoch_id")
        if len(self.used_unit_commitments) != len(set(self.used_unit_commitments)):
            raise ValueError("used edge/unit commitments must be globally unique")
        for edge_key, unit_commitment in self.used_unit_commitments:
            _require_sha(edge_key, "used unit scientific edge key")
            _require_sha(unit_commitment, "used unit commitment")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class StateEnvelopeV2(_ClosedModel):
    envelope_version: Literal["sft-state-envelope-v2"] = "sft-state-envelope-v2"
    state: FactorBankStateV2
    state_sha256: str
    state_hmac_sha256: str


class LegacyStateRejected(ValueError):
    """A v1 efficacy/deployment claim cannot be fabricated into v2 authority."""


class FactorBankV2:
    """Mutable TRAIN-side facade over one immutable, fully revalidated state."""

    def __init__(
        self,
        state: FactorBankStateV2 | None = None,
        *,
        state_key: bytes,
        direct_binding_verifier: Callable[
            [
                DirectFactorTransitionV2,
                CompositionRevisionV2,
                CompositionRevisionV2,
                FactorRevisionV2,
                FactorRevisionV2,
                tuple[FactorRevisionV2, ...],
            ],
            bool,
        ]
        | None = None,
        whole_operation_verifier: Callable[
            [WholeCompositionTransitionV2, CompositionRevisionV2, CompositionRevisionV2],
            bool,
        ]
        | None = None,
        plan_verifier: Callable[[ProbePlanV2], bool] | None = None,
        assignment_verifier: Callable[[AssignmentReceiptV2, ProbePlanV2], bool]
        | None = None,
        runner_lease_verifier: Callable[
            [RunnerLeaseGrantV1, AssignmentReceiptV2, ProbePlanV2], bool
        ]
        | None = None,
        arm_receipt_verifier: Callable[
            [ArmReceiptV2, ProbePlanV2, AssignmentReceiptV2], bool
        ]
        | None = None,
        pair_execution_receipt_verifier: Callable[
            [PairExecutionReceiptV2, ProbeAttemptV3, ProbePlanV2], bool
        ]
        | None = None,
        cancellation_verifier: Callable[
            [AttemptCancellationReceiptV3, ProbeAttemptV3, ProbePlanV2], bool
        ]
        | None = None,
        proposal_generation_context_verifier: Callable[
            [
                ProposalGenerationContextV1,
                RepairOpportunityV2,
                ProposalReceiptV1,
                CompositionRevisionV2,
                FactorRevisionV2,
                FactorBankStateV2,
            ],
            bool,
        ]
        | None = None,
        proposal_generation_lease_verifier: Callable[
            [ProposalGenerationLeaseV1, ProposalActionV2, FactorBankStateV2],
            bool,
        ]
        | None = None,
        proposal_abort_verifier: Callable[
            [ProposalActionAbortReceiptV2, ProposalActionV2, FactorBankStateV2],
            bool,
        ]
        | None = None,
        proposal_action_terminal_verifier: Callable[
            [ProposalActionV2, DirectFactorTransitionV2, FactorBankStateV2],
            bool,
        ]
        | None = None,
        repair_opportunity_verifier: Callable[
            [RepairOpportunityV2, FailureObservationV2, CompositionRevisionV2],
            bool,
        ]
        | None = None,
        gate_verifier: Callable[[GateReceiptV2, FactorBankStateV2], bool] | None = None,
        base_snapshot_verifier: Callable[
            [BaseSnapshotReceiptV2, FactorBankStateV2], bool
        ]
        | None = None,
        rollback_verifier: Callable[
            [RollbackTriggerV2, FactorBankStateV2], bool
        ]
        | None = None,
        archive_verifier: Callable[[str, str], bool] | None = None,
        capacity_policy: CapacityPolicyV1 | None = None,
    ) -> None:
        if not isinstance(state_key, bytes) or len(state_key) < 32:
            raise ValueError("state_key must contain at least 32 bytes")
        if state is not None and capacity_policy is not None:
            raise ValueError("persisted state owns its capacity policy")
        self._key = bytes(state_key)
        self._direct_binding_verifier = direct_binding_verifier
        self._whole_operation_verifier = whole_operation_verifier
        self._plan_verifier = plan_verifier
        self._assignment_verifier = assignment_verifier
        self._runner_lease_verifier = runner_lease_verifier
        self._arm_receipt_verifier = arm_receipt_verifier
        self._pair_execution_receipt_verifier = pair_execution_receipt_verifier
        self._cancellation_verifier = cancellation_verifier
        self._proposal_generation_context_verifier = (
            proposal_generation_context_verifier
        )
        self._proposal_generation_lease_verifier = (
            proposal_generation_lease_verifier
        )
        self._proposal_abort_verifier = proposal_abort_verifier
        self._proposal_action_terminal_verifier = (
            proposal_action_terminal_verifier
        )
        self._repair_opportunity_verifier = repair_opportunity_verifier
        self._gate_verifier = gate_verifier
        self._base_snapshot_verifier = base_snapshot_verifier
        self._rollback_verifier = rollback_verifier
        self._archive_verifier = archive_verifier
        self._persisted_path: Path | None = None
        self._persisted_envelope_sha256: str | None = None
        self._mutation_lock = threading.RLock()
        self._transaction_depth = 0
        candidate = state or FactorBankStateV2(
            capacity_policy=capacity_policy or CapacityPolicyV1()
        )
        candidate = FactorBankStateV2.model_validate(
            candidate.model_dump(mode="python")
        )
        self._validate_state(candidate)
        self._state = candidate

    @contextmanager
    def _atomic_update(self):
        outermost = self._transaction_depth == 0
        snapshot: tuple[Any, ...] | None = None
        if outermost:
            snapshot = (
                self._state,
                self._persisted_path,
                self._persisted_envelope_sha256,
            )
        self._transaction_depth += 1
        try:
            yield
            if outermost:
                self._validate_state(self._state)
                if self._persisted_path is not None:
                    self.save(self._persisted_path)
        except Exception:
            if outermost and snapshot is not None:
                (
                    self._state,
                    self._persisted_path,
                    self._persisted_envelope_sha256,
                ) = snapshot
            raise
        finally:
            self._transaction_depth -= 1

    @property
    @_linearized_bank_read
    def factors(self) -> dict[str, FactorRevisionV2]:
        return {item.revision_id: item for item in self._state.factors}

    @property
    @_linearized_bank_read
    def compositions(self) -> dict[str, CompositionRevisionV2]:
        return {item.composition_id: item for item in self._state.compositions}

    @property
    @_linearized_bank_read
    def direct_transitions(self) -> dict[str, DirectFactorTransitionV2]:
        return {item.transition_id: item for item in self._state.direct_transitions}

    @property
    @_linearized_bank_read
    def whole_transitions(self) -> dict[str, WholeCompositionTransitionV2]:
        return {item.transition_id: item for item in self._state.whole_transitions}

    @property
    @_linearized_bank_read
    def plans(self) -> dict[str, ProbePlanV2]:
        return {item.plan_id: item for item in self._state.plans}

    @property
    @_linearized_bank_read
    def attempts(self) -> dict[str, ProbeAttemptV3]:
        return {item.attempt_id: item for item in self._state.attempts}

    @property
    @_linearized_bank_read
    def assessments(self) -> dict[str, EdgeAssessmentV2]:
        return {item.plan_id: item for item in self._state.assessments}

    @property
    @_linearized_bank_read
    def gate_opportunities(self) -> dict[str, GateOpportunityV2]:
        return {item.opportunity_id: item for item in self._state.gate_opportunities}

    @property
    @_linearized_bank_read
    def deployment_heads(self) -> dict[str, DeploymentHeadV2]:
        return {item.deployment_slot_id: item for item in self._state.deployment_heads}

    @property
    @_linearized_bank_read
    def proposal_carrier_admissions(self) -> dict[str, ProposalCarrierAdmissionV1]:
        return {
            item.admission_id: item
            for item in self._state.proposal_carrier_admissions
        }

    @property
    @_linearized_bank_read
    def proposal_carrier_reservations(
        self,
    ) -> dict[str, ProposalCarrierCapacityReservationV1]:
        return {
            item.reservation_id: item
            for item in self._state.proposal_carrier_reservations
        }

    @staticmethod
    def deployment_slot_id(namespace: ExecutionNamespace) -> str:
        return _opaque_id("ds", namespace.digest)

    def _next_state(self, **updates: Any) -> FactorBankStateV2:
        payload = self._state.model_dump(mode="python")
        payload.update(updates)
        payload["event_seq"] = self._state.event_seq + 1
        payload["previous_state_sha256"] = self._state.digest
        return FactorBankStateV2.model_validate(payload)

    def _next_state_at(
        self,
        event_seq: int,
        **updates: Any,
    ) -> FactorBankStateV2:
        """Build one atomic bundle state spanning its reserved local sequence."""

        if event_seq <= self._state.event_seq:
            raise ValueError("atomic bundle event sequence must advance")
        payload = self._state.model_dump(mode="python")
        payload.update(updates)
        payload["event_seq"] = event_seq
        payload["previous_state_sha256"] = self._state.digest
        return FactorBankStateV2.model_validate(payload)

    def _install(self, candidate: FactorBankStateV2) -> None:
        candidate = FactorBankStateV2.model_validate(
            candidate.model_dump(mode="python")
        )
        self._validate_state(candidate)
        self._state = candidate

    def _transition(self, transition_id: str, owner_kind: OwnerKind | None = None) -> ScientificTransitionV2:
        direct = self.direct_transitions.get(transition_id)
        whole = self.whole_transitions.get(transition_id)
        transition = direct or whole
        if transition is None:
            raise ValueError("scientific transition does not exist")
        if owner_kind is not None and transition.owner_kind != owner_kind:
            raise ValueError("transition owner kind mismatch")
        return transition

    @staticmethod
    def _projected_action_transition(
        transition: DirectFactorTransitionV2,
    ) -> DirectFactorTransitionV2:
        """Return the exact live inert bytes committed by an admission.

        Archival may later change only ``structural_state`` and successful
        action finalization adds only ``proposal_action_committed_seq``.  The
        admission must continue to authenticate the projection-time edge
        across both lifecycle changes.
        """

        return transition.model_copy(
            update={
                "structural_state": "live",
                "proposal_action_committed_seq": None,
            }
        )

    @staticmethod
    def _projected_carrier_row(row: Any) -> Any:
        """Reconstruct the immutable live row hashed at projection time."""

        return row.model_copy(update={"structural_state": "live"})

    @staticmethod
    def _admission_terminal_sha256(
        *,
        disposition: Literal["admitted", "quarantined"],
        action: ProposalActionV2,
        projected_transition_sha256: str,
        committed_transition: DirectFactorTransitionV2 | None = None,
        abort_receipt: ProposalActionAbortReceiptV2 | None = None,
    ) -> str:
        """Bind one admission terminal without introducing a digest cycle."""

        return _sha256(
            {
                "terminal_version": "sft_carrier_admission_terminal_v1",
                "disposition": disposition,
                "action_sha256": action.digest,
                "projected_transition_sha256": projected_transition_sha256,
                "committed_transition_sha256": (
                    _sha256(
                        committed_transition.model_copy(
                            update={"structural_state": "live"}
                        )
                    )
                    if committed_transition is not None
                    else None
                ),
                "abort_receipt_sha256": (
                    _sha256(abort_receipt)
                    if abort_receipt is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _factor_carrier_key_sha256(factor: FactorRevisionV2) -> str:
        """Canonical content authority key shared by revision aliases."""

        return _sha256(
            {
                "key_version": "sft_factor_carrier_key_v1",
                "namespace_digest": factor.namespace.digest,
                "logical_factor_id": factor.logical_factor_id,
                "carrier": factor.carrier,
                "locator": factor.locator,
                "binding_status": factor.binding_status,
                "content_sha256": factor.content_sha256,
            }
        )

    def _composition_carrier_key_sha256(
        self,
        state: FactorBankStateV2,
        composition: CompositionRevisionV2,
    ) -> str:
        """Canonical complete-artifact key invariant to storage aliases."""

        factors = {item.revision_id: item for item in state.factors}
        canonical_bindings: list[tuple[str, str]] = []
        for slot_id, revision_id in sorted(composition.binding_map.items()):
            factor = factors.get(revision_id)
            if factor is None:
                raise ValueError(
                    "composition carrier key names a missing factor revision"
                )
            canonical_bindings.append(
                (slot_id, self._factor_carrier_key_sha256(factor))
            )
        return _sha256(
            {
                "key_version": "sft_composition_carrier_key_v1",
                "namespace_digest": composition.namespace.digest,
                "carrier": composition.carrier,
                "artifact_sha256": composition.artifact_sha256,
                "canonical_bindings": canonical_bindings,
            }
        )

    def _canonical_scientific_edge_sha256(
        self,
        state: FactorBankStateV2,
        transition: ScientificTransitionV2,
    ) -> str:
        """Identify one exact intervention independently of storage aliases.

        Portable pairs deliberately omit the fixed background so evidence can
        inform proposal screening across related artifacts.  Scientific credit
        is narrower: source, target, locus and namespace must all match after
        factor/composition aliases have been reduced to their carrier keys.
        Proof and proposal-action bytes are support/activation records, not a
        license to create a second owner for the same intervention.
        """

        compositions = {
            item.composition_id: item for item in state.compositions
        }
        source = compositions.get(transition.source_composition_id)
        target = compositions.get(transition.target_composition_id)
        if source is None or target is None:
            raise ValueError(
                "canonical scientific edge names a missing composition"
            )
        payload: dict[str, Any] = {
            "key_version": "sft_canonical_scientific_edge_v1",
            "owner_kind": transition.owner_kind,
            "namespace_digest": transition.namespace.digest,
            "source_composition_carrier_key_sha256": (
                self._composition_carrier_key_sha256(state, source)
            ),
            "target_composition_carrier_key_sha256": (
                self._composition_carrier_key_sha256(state, target)
            ),
        }
        if isinstance(transition, DirectFactorTransitionV2):
            factors = {item.revision_id: item for item in state.factors}
            old = factors.get(transition.from_revision_id)
            new = factors.get(transition.to_revision_id)
            if old is None or new is None:
                raise ValueError(
                    "canonical scientific edge names a missing factor"
                )
            payload.update(
                {
                    "slot_id": transition.slot_id,
                    "typed_locus_sha256": self._typed_locus_sha256(
                        old,
                        transition.slot_id,
                    ),
                    "canonical_background_sha256": (
                        self._canonical_background_sha256(
                            state,
                            transition,
                        )
                    ),
                    "from_factor_carrier_key_sha256": (
                        self._factor_carrier_key_sha256(old)
                    ),
                    "to_factor_carrier_key_sha256": (
                        self._factor_carrier_key_sha256(new)
                    ),
                }
            )
        else:
            payload["changed_slot_ids"] = transition.changed_slot_ids
            payload["canonical_background_sha256"] = (
                self._canonical_background_sha256(state, transition)
            )
        return _sha256(payload)

    @staticmethod
    def _typed_locus_sha256(
        factor: FactorRevisionV2,
        slot_id: str,
    ) -> str:
        return _sha256(
            {
                "key_version": "sft_typed_locus_v1",
                "namespace_digest": factor.namespace.digest,
                "carrier": factor.carrier,
                "slot_id": slot_id,
                "logical_factor_id": factor.logical_factor_id,
                "locator": factor.locator,
                "binding_status": factor.binding_status,
            }
        )

    def _canonical_background_sha256(
        self,
        state: FactorBankStateV2,
        transition: ScientificTransitionV2,
    ) -> str:
        compositions = {
            item.composition_id: item for item in state.compositions
        }
        source = compositions.get(transition.source_composition_id)
        if source is None:
            raise ValueError("canonical background source composition is missing")
        source_key = self._composition_carrier_key_sha256(state, source)
        if isinstance(transition, DirectFactorTransitionV2):
            factors = {item.revision_id: item for item in state.factors}
            old = factors.get(transition.from_revision_id)
            if old is None:
                raise ValueError("canonical background source factor is missing")
            return self._canonical_direct_background_sha256(
                state,
                source=source,
                source_factor=old,
                slot_id=transition.slot_id,
            )
        return _sha256(
            {
                "key_version": "sft_whole_background_v1",
                "namespace_digest": transition.namespace.digest,
                "source_composition_carrier_key_sha256": source_key,
                "changed_slot_ids": transition.changed_slot_ids,
            }
        )

    def _canonical_direct_background_sha256(
        self,
        state: FactorBankStateV2,
        *,
        source: CompositionRevisionV2,
        source_factor: FactorRevisionV2,
        slot_id: str,
    ) -> str:
        """Host-recompute the current proposal/probe background."""

        if (
            source.namespace != source_factor.namespace
            or source.binding_map.get(slot_id) != source_factor.revision_id
        ):
            raise ValueError(
                "canonical proposal background does not join its source locus"
            )
        return _sha256(
            {
                "key_version": "sft_direct_background_v1",
                "namespace_digest": source.namespace.digest,
                "source_composition_carrier_key_sha256": (
                    self._composition_carrier_key_sha256(state, source)
                ),
                "typed_locus_sha256": self._typed_locus_sha256(
                    source_factor,
                    slot_id,
                ),
                "from_factor_carrier_key_sha256": (
                    self._factor_carrier_key_sha256(source_factor)
                ),
            }
        )

    def _credit_owner_transition_id(
        self,
        state: FactorBankStateV2,
        transition: ScientificTransitionV2,
    ) -> str:
        """Return the permanent earliest owner of one canonical edge.

        Action-owned duplicates remain useful as exact transactional activation
        records, but they cannot multiply scientific evidence.  Archived
        transitions remain in the authenticated state, so an alias cannot gain
        ownership merely because the original edge became cold or tombstoned.
        """

        canonical_key = self._canonical_scientific_edge_sha256(
            state,
            transition,
        )
        siblings = [
            item
            for item in (*state.direct_transitions, *state.whole_transitions)
            if self._canonical_scientific_edge_sha256(state, item)
            == canonical_key
        ]
        durable: list[tuple[int, ScientificTransitionV2]] = []
        for item in siblings:
            if (
                isinstance(item, DirectFactorTransitionV2)
                and item.proposal_action_id is not None
            ):
                if not self._transition_has_execution_authority(state, item):
                    continue
                assert item.proposal_action_committed_seq is not None
                durable.append((item.proposal_action_committed_seq, item))
            else:
                durable.append((item.created_seq, item))
        if not durable:
            raise ValueError("canonical scientific edge has no durable owner")
        return min(
            durable,
            key=lambda item: (item[0], item[1].transition_id),
        )[1].transition_id

    @staticmethod
    def _proposal_carrier_reservation_for_action(
        state: FactorBankStateV2,
        action_id: str,
    ) -> ProposalCarrierCapacityReservationV1 | None:
        return next(
            (
                item
                for item in state.proposal_carrier_reservations
                if item.action_id == action_id
            ),
            None,
        )

    @staticmethod
    def _unmaterialized_carrier_reservations(
        state: FactorBankStateV2,
        *,
        excluding_action_id: str | None = None,
    ) -> tuple[ProposalCarrierCapacityReservationV1, ...]:
        return tuple(
            item
            for item in state.proposal_carrier_reservations
            if item.state == "reserved"
            and item.action_id != excluding_action_id
        )

    @staticmethod
    def _terminal_pending_carrier_reservations(
        state: FactorBankStateV2,
    ) -> tuple[ProposalCarrierCapacityReservationV1, ...]:
        """Reservations whose action/admission terminal bytes are still owed."""

        return tuple(
            item
            for item in state.proposal_carrier_reservations
            if item.state in {"reserved", "materialized"}
        )

    @staticmethod
    def _proposal_carrier_reservation_body(
        *,
        action_id: str,
        namespace_digest: str,
        prepared_seq: int,
        policy: CapacityPolicyV1,
    ) -> dict[str, Any]:
        """Derive reservation identity without the action-intent digest cycle."""

        return {
            "reservation_version": "sft_proposal_carrier_capacity_v1",
            "action_id": action_id,
            "namespace_digest": namespace_digest,
            "capacity_policy_sha256": policy.digest,
            "reserved_factor_records": 1,
            "reserved_composition_records": 1,
            "reserved_hot_composition_slots": 1,
            "reserved_transition_records": 1,
            "reserved_admission_records": 1,
            "reserved_hot_metadata_bytes": (
                policy.max_generated_target_metadata_bytes
            ),
            "reserved_artifact_bytes": (
                policy.max_generated_target_artifact_bytes
            ),
            "reserved_prompt_summary_tokens": (
                policy.max_generated_target_prompt_summary_tokens
            ),
            "reserved_structural_bytes": (
                policy.max_generated_carrier_structural_bytes
            ),
            "reserved_transition_bytes": policy.max_generated_transition_bytes,
            "reserved_admission_bytes": policy.max_generated_admission_bytes,
            "reserved_owner_slab_bytes": policy.max_generated_owner_slab_bytes,
            "state": "reserved",
            "created_seq": prepared_seq,
            "materialized_seq": None,
            "released_seq": None,
            "consumed_seq": None,
        }

    @staticmethod
    def _proposal_carrier_reservation_id(body: Mapping[str, Any]) -> str:
        identity = dict(body)
        for field in (
            "state",
            "materialized_seq",
            "released_seq",
            "consumed_seq",
        ):
            identity.pop(field)
        return _opaque_id("pcr", identity)

    def _reserve_generated_carrier_capacity(
        self,
        *,
        action: ProposalActionV2,
        namespace: ExecutionNamespace,
    ) -> ProposalCarrierCapacityReservationV1:
        """Reserve the complete worst-case generated bundle before START."""

        if action.branch not in {"mutate", "fresh"}:
            raise ValueError("only a generated action owns carrier capacity")
        policy = self._state.capacity_policy
        active = self._unmaterialized_carrier_reservations(self._state)
        minimum_owner_slab_bytes = (
            len(_canonical_json(action).encode("utf-8"))
            + _GENERATED_OWNER_SUCCESSOR_OVERHEAD_BYTES
        )
        if policy.max_generated_owner_slab_bytes < minimum_owner_slab_bytes:
            raise RuntimeError(
                "carrier_capacity: owner-slab preflight failed before START"
            )
        if len(self._state.factors) + len(active) + 1 > policy.max_factor_records:
            raise RuntimeError("carrier_capacity: factor preflight failed before START")
        if (
            len(self._state.compositions) + len(active) + 1
            > policy.max_composition_records
        ):
            raise RuntimeError(
                "carrier_capacity: composition preflight failed before START"
            )
        if (
            len(self._state.direct_transitions)
            + len(self._state.whole_transitions)
            + len(active)
            + 1
            > policy.max_transition_records
        ):
            raise RuntimeError(
                "carrier_capacity: transition preflight failed before START"
            )
        if (
            len(self._state.proposal_carrier_admissions)
            + len(active)
            + 1
            > policy.max_proposal_carrier_admissions
        ):
            raise RuntimeError(
                "carrier_capacity: admission preflight failed before START"
            )
        scoped_live = tuple(
            item
            for item in self._state.compositions
            if item.namespace == namespace and item.structural_state == "live"
        )
        scoped_reserved = tuple(
            item for item in active if item.namespace_digest == namespace.digest
        )
        if (
            len(scoped_live) + len(scoped_reserved) + 1
            > policy.max_hot_compositions_per_namespace
            + policy.unknown_structural_reserve
        ):
            raise RuntimeError(
                "carrier_capacity: hot-composition preflight failed before START"
            )
        if (
            sum(item.canonical_metadata_bytes for item in scoped_live)
            + sum(item.reserved_hot_metadata_bytes for item in scoped_reserved)
            + policy.max_generated_target_metadata_bytes
            > policy.max_hot_metadata_bytes
        ):
            raise RuntimeError(
                "carrier_capacity: metadata-byte preflight failed before START"
            )
        if (
            sum(item.artifact_bytes for item in scoped_live)
            + sum(item.reserved_artifact_bytes for item in scoped_reserved)
            + policy.max_generated_target_artifact_bytes
            > policy.max_hot_artifact_bytes_per_namespace
        ):
            raise RuntimeError(
                "carrier_capacity: artifact-byte preflight failed before START"
            )
        if (
            sum(item.prompt_summary_tokens for item in scoped_live)
            + sum(item.reserved_prompt_summary_tokens for item in scoped_reserved)
            + policy.max_generated_target_prompt_summary_tokens
            > policy.max_prompt_summary_tokens_per_namespace
        ):
            raise RuntimeError(
                "carrier_capacity: prompt-token preflight failed before START"
            )
        reserved_total_bytes = (
            policy.max_generated_carrier_structural_bytes
            + policy.max_generated_target_metadata_bytes
            + policy.max_generated_target_artifact_bytes
            + policy.max_generated_transition_bytes
            + policy.max_generated_admission_bytes
            + policy.max_generated_owner_slab_bytes
        )
        if (
            sum(item.reserved_total_bytes for item in active)
            + reserved_total_bytes
            > policy.max_active_generated_carrier_reservation_bytes
        ):
            raise RuntimeError(
                "carrier_capacity: closure-byte preflight failed before START"
            )
        active_owner_slab_bytes = sum(
            item.reserved_owner_slab_bytes
            for item in self._terminal_pending_carrier_reservations(self._state)
        )
        proposal_bytes = sum(
            len(_canonical_json(item).encode("utf-8"))
            for item in (
                *self._state.proposal_decisions,
                *self._state.proposal_lifetime_counters,
                *self._state.proposal_actions,
                *self._state.proposal_carrier_reservations,
                *self._state.proposal_carrier_admissions,
            )
        )
        if (
            proposal_bytes
            + active_owner_slab_bytes
            + policy.max_generated_owner_slab_bytes
            > policy.max_proposal_action_bytes
        ):
            raise RuntimeError(
                "carrier_capacity: proposal-byte preflight failed before START"
            )
        body = self._proposal_carrier_reservation_body(
            action_id=action.action_id,
            namespace_digest=namespace.digest,
            prepared_seq=action.prepared_seq,
            policy=policy,
        )
        reservation_id = self._proposal_carrier_reservation_id(body)
        if action.carrier_capacity_reservation_id != reservation_id:
            raise ValueError("proposal action does not commit its carrier reservation")
        return ProposalCarrierCapacityReservationV1(
            reservation_id=reservation_id,
            **body,
        )

    @staticmethod
    def _assert_carrier_closure_fits_reservation(
        reservation: ProposalCarrierCapacityReservationV1,
        *,
        action: ProposalActionV2,
        factor: FactorRevisionV2,
        composition: CompositionRevisionV2,
        transition: DirectFactorTransitionV2 | None,
        admission: ProposalCarrierAdmissionV1,
    ) -> None:
        structural_bytes = len(
            _canonical_json((factor, composition)).encode("utf-8")
        )
        transition_bytes = (
            len(_canonical_json(transition).encode("utf-8"))
            if transition is not None
            else 0
        )
        admission_bytes = len(_canonical_json(admission).encode("utf-8"))
        owner_slab_bytes = len(
            _canonical_json((action, admission)).encode("utf-8")
        )
        if not (
            composition.canonical_metadata_bytes
            <= reservation.reserved_hot_metadata_bytes
            and composition.artifact_bytes
            <= reservation.reserved_artifact_bytes
            and composition.prompt_summary_tokens
            <= reservation.reserved_prompt_summary_tokens
            and structural_bytes <= reservation.reserved_structural_bytes
            and transition_bytes <= reservation.reserved_transition_bytes
            and admission_bytes <= reservation.reserved_admission_bytes
            and owner_slab_bytes <= reservation.reserved_owner_slab_bytes
        ):
            raise ValueError(
                "generated carrier closure exceeds its pre-START reservation"
            )

    @staticmethod
    def _row_admission_matches(
        admission: ProposalCarrierAdmissionV1,
        *,
        row_kind: Literal["factor", "composition"],
        row_id: str,
        factor_carrier_key_sha256: str | None = None,
        composition_carrier_key_sha256: str | None = None,
    ) -> bool:
        if row_kind == "factor":
            return bool(
                factor_carrier_key_sha256 is not None
                and admission.target_factor_carrier_key_sha256
                == factor_carrier_key_sha256
            )
        return bool(
            composition_carrier_key_sha256 is not None
            and admission.target_composition_carrier_key_sha256
            == composition_carrier_key_sha256
        )

    def _row_has_non_action_authority(
        self,
        state: FactorBankStateV2,
        *,
        row_kind: Literal["factor", "composition"],
        row_id: str,
        before_seq: int | None = None,
        excluding_transition_id: str | None = None,
    ) -> bool:
        """Replay canonical structural/deployment authority for one row.

        Revision and composition identifiers are storage joins.  Authority is
        attached to the canonical carrier key so an alias neither loses a
        legitimate owner nor invents a second scientific owner.
        """

        def before(value: int) -> bool:
            return before_seq is None or value < before_seq

        factors = {item.revision_id: item for item in state.factors}
        compositions = {
            item.composition_id: item for item in state.compositions
        }

        requested_factor_key: str | None = None
        requested_composition_key: str | None = None
        if row_kind == "factor":
            requested = factors.get(row_id)
            if requested is None:
                return False
            requested_factor_key = self._factor_carrier_key_sha256(requested)
        else:
            requested = compositions.get(row_id)
            if requested is None:
                return False
            requested_composition_key = self._composition_carrier_key_sha256(
                state,
                requested,
            )

        def target_owns(target_composition_id: str) -> bool:
            target = compositions.get(target_composition_id)
            if target is None:
                return False
            if row_kind == "composition":
                return (
                    self._composition_carrier_key_sha256(state, target)
                    == requested_composition_key
                )
            return any(
                self._factor_carrier_key_sha256(factors[factor_id])
                == requested_factor_key
                for factor_id in target.binding_map.values()
            )

        for transition in state.direct_transitions:
            if (
                transition.transition_id == excluding_transition_id
                or transition.proposal_action_id is not None
                or not before(transition.created_seq)
            ):
                continue
            if target_owns(transition.target_composition_id):
                return True
        for transition in state.whole_transitions:
            if not before(transition.created_seq):
                continue
            if target_owns(transition.target_composition_id):
                return True
        for receipt in state.base_receipts:
            if not before(receipt.emitted_seq):
                continue
            if target_owns(receipt.composition_id):
                return True
        for snapshot in state.deployment_snapshots:
            if not before(snapshot.created_seq):
                continue
            if target_owns(snapshot.composition_id):
                return True
        return False

    def _action_matches_exact_locus(
        self,
        state: FactorBankStateV2,
        action: ProposalActionV2,
        *,
        namespace_digest: str,
        source_composition_id: str,
        slot_id: str,
        from_revision_id: str,
    ) -> bool:
        """Join canonical source/locus identity, not caller-chosen row IDs.

        Storage aliases are deliberately legal, but they cannot split the
        ownership lock.  Both complete source bindings/artifact content and
        the changed factor carrier are normalized through host-recomputed
        canonical keys before comparison.
        """

        compositions = {
            item.composition_id: item for item in state.compositions
        }
        factors = {item.revision_id: item for item in state.factors}
        action_source = compositions.get(action.source_composition_id)
        candidate_source = compositions.get(source_composition_id)
        action_factor = factors.get(action.from_revision_id)
        candidate_factor = factors.get(from_revision_id)
        if any(
            item is None
            for item in (
                action_source,
                candidate_source,
                action_factor,
                candidate_factor,
            )
        ):
            return False
        assert action_source is not None and candidate_source is not None
        assert action_factor is not None and candidate_factor is not None
        return bool(
            action.namespace_digest == namespace_digest
            == candidate_source.namespace.digest
            and action.slot_id == slot_id
            and self._composition_carrier_key_sha256(
                state,
                action_source,
            )
            == self._composition_carrier_key_sha256(
                state,
                candidate_source,
            )
            and self._factor_carrier_key_sha256(action_factor)
            == self._factor_carrier_key_sha256(candidate_factor)
        )

    def _assert_no_active_action_ordinary_owner(
        self,
        state: FactorBankStateV2,
        *,
        namespace_digest: str,
        source_composition_id: str,
        slot_ids_and_from_revisions: Sequence[tuple[str, str]],
    ) -> None:
        """Fence ordinary ownership while an exact action locus is reserved.

        Generated bytes are not known at PREPARE, so comparing target content
        would recreate the laundering gap.  The safe, host-checkable lock key
        is the source composition plus its typed factor locus.  Structural row
        appends remain legal; only an ordinary scientific owner is forbidden
        until the action reaches a terminal state.
        """

        loci = set(slot_ids_and_from_revisions)
        for action in state.proposal_actions:
            if action.state not in {"prepared", "executing"}:
                continue
            if any(
                self._action_matches_exact_locus(
                    state,
                    action,
                    namespace_digest=namespace_digest,
                    source_composition_id=source_composition_id,
                    slot_id=slot_id,
                    from_revision_id=from_revision_id,
                )
                for slot_id, from_revision_id in loci
            ):
                raise ValueError(
                    "ordinary transition is fenced by an active proposal action locus"
                )

    def _ordinary_transition_lands_in_action_window(
        self,
        state: FactorBankStateV2,
        transition: ScientificTransitionV2,
        action: ProposalActionV2,
    ) -> bool:
        """Replay-detect an ordinary owner written after PREPARE and pre-terminal."""

        if (
            isinstance(transition, DirectFactorTransitionV2)
            and transition.proposal_action_id is not None
        ):
            return False
        terminal_seq = (
            action.updated_seq
            if action.state in {"committed", "aborted"}
            else state.event_seq
        )
        if not (
            action.prepared_seq < transition.created_seq <= terminal_seq
            and transition.namespace.digest == action.namespace_digest
        ):
            return False
        if isinstance(transition, DirectFactorTransitionV2):
            return self._action_matches_exact_locus(
                state,
                action,
                namespace_digest=transition.namespace.digest,
                source_composition_id=transition.source_composition_id,
                slot_id=transition.slot_id,
                from_revision_id=transition.from_revision_id,
            )
        source = next(
            (
                item
                for item in state.compositions
                if item.composition_id == transition.source_composition_id
            ),
            None,
        )
        if source is None or action.slot_id not in transition.changed_slot_ids:
            return False
        from_revision_id = source.binding_map.get(action.slot_id)
        if from_revision_id is None:
            return False
        return self._action_matches_exact_locus(
            state,
            action,
            namespace_digest=transition.namespace.digest,
            source_composition_id=transition.source_composition_id,
            slot_id=action.slot_id,
            from_revision_id=from_revision_id,
        )

    def _row_is_carrier_eligible(
        self,
        state: FactorBankStateV2,
        *,
        row_kind: Literal["factor", "composition"],
        row_id: str,
        before_seq: int | None = None,
        excluding_transition_id: str | None = None,
        factor_carrier_key_sha256: str | None = None,
        composition_carrier_key_sha256: str | None = None,
    ) -> bool:
        """Return host-replayed current or historical carrier eligibility."""

        if row_kind == "factor" and factor_carrier_key_sha256 is None:
            factor = next(
                (item for item in state.factors if item.revision_id == row_id),
                None,
            )
            if factor is None:
                return False
            factor_carrier_key_sha256 = self._factor_carrier_key_sha256(factor)
        elif row_kind == "composition" and composition_carrier_key_sha256 is None:
            composition = next(
                (
                    item
                    for item in state.compositions
                    if item.composition_id == row_id
                ),
                None,
            )
            if composition is None:
                return False
            composition_carrier_key_sha256 = (
                self._composition_carrier_key_sha256(state, composition)
            )

        admissions = [
            item
            for item in state.proposal_carrier_admissions
            if self._row_admission_matches(
                item,
                row_kind=row_kind,
                row_id=row_id,
                factor_carrier_key_sha256=factor_carrier_key_sha256,
                composition_carrier_key_sha256=(
                    composition_carrier_key_sha256
                ),
            )
            and (before_seq is None or item.created_seq < before_seq)
        ]
        if not admissions:
            return self._row_has_non_action_authority(
                state,
                row_kind=row_kind,
                row_id=row_id,
                before_seq=before_seq,
                excluding_transition_id=excluding_transition_id,
            )
        before_flag = (
            "factor_independently_eligible_before"
            if row_kind == "factor"
            else "composition_independently_eligible_before"
        )
        if any(bool(getattr(item, before_flag)) for item in admissions):
            return True
        if any(
            item.state == "admitted"
            and item.terminal_seq is not None
            and (before_seq is None or item.terminal_seq < before_seq)
            for item in admissions
        ):
            return True
        # Once an action has claimed a canonical carrier key, only the
        # admission's frozen pre-PREPARE authority or an accepted action
        # terminal may make it executable.  A later ordinary owner cannot
        # retroactively turn staged/quarantined output into an import.
        return False

    def _row_can_receive_non_action_authority(
        self,
        state: FactorBankStateV2,
        *,
        row_kind: Literal["factor", "composition"],
        row_id: str,
        before_seq: int | None = None,
        excluding_transition_id: str | None = None,
    ) -> bool:
        """Allow first authority, but never let it rehabilitate quarantine.

        A pristine storage row may become authoritative through an ordinary
        transition or base receipt.  Once an action has claimed its canonical
        carrier key, however, the admission terminal is the only authority
        transition: an ordinary writer cannot turn staged or quarantined bytes
        into an executable import.
        """

        factor_key: str | None = None
        composition_key: str | None = None
        if row_kind == "factor":
            factor = next(
                (item for item in state.factors if item.revision_id == row_id),
                None,
            )
            if factor is None:
                return False
            factor_key = self._factor_carrier_key_sha256(factor)
        else:
            composition = next(
                (
                    item
                    for item in state.compositions
                    if item.composition_id == row_id
                ),
                None,
            )
            if composition is None:
                return False
            composition_key = self._composition_carrier_key_sha256(
                state,
                composition,
            )
        prior_admissions = [
            item
            for item in state.proposal_carrier_admissions
            if self._row_admission_matches(
                item,
                row_kind=row_kind,
                row_id=row_id,
                factor_carrier_key_sha256=factor_key,
                composition_carrier_key_sha256=composition_key,
            )
            and (before_seq is None or item.created_seq < before_seq)
        ]
        if not prior_admissions:
            row = factor if row_kind == "factor" else composition
            return before_seq is None or row.created_seq < before_seq
        return self._row_is_carrier_eligible(
            state,
            row_kind=row_kind,
            row_id=row_id,
            before_seq=before_seq,
            excluding_transition_id=excluding_transition_id,
            factor_carrier_key_sha256=factor_key,
            composition_carrier_key_sha256=composition_key,
        )

    def _composition_can_receive_non_action_authority(
        self,
        state: FactorBankStateV2,
        composition: CompositionRevisionV2,
        *,
        before_seq: int | None = None,
    ) -> bool:
        return bool(
            self._row_can_receive_non_action_authority(
                state,
                row_kind="composition",
                row_id=composition.composition_id,
                before_seq=before_seq,
            )
            and all(
                self._row_can_receive_non_action_authority(
                    state,
                    row_kind="factor",
                    row_id=factor_id,
                    before_seq=before_seq,
                )
                for factor_id in composition.binding_map.values()
            )
        )

    def _row_was_independently_eligible_before_action_edge(
        self,
        state: FactorBankStateV2,
        *,
        row_kind: Literal["factor", "composition"],
        row_id: str,
        action: ProposalActionV2,
        edge_created_seq: int,
    ) -> bool:
        """Replay the Bank-owned admission flag for a pre-existing target.

        A row which merely appeared after PREPARE cannot call itself
        pre-existing.  It needs an earlier admitted action, an inherited
        independent flag, or a non-action/deployment owner.
        """

        factor_carrier_key_sha256: str | None = None
        composition_carrier_key_sha256: str | None = None
        if row_kind == "factor":
            factor = next(
                (item for item in state.factors if item.revision_id == row_id),
                None,
            )
            if factor is None:
                return False
            factor_carrier_key_sha256 = self._factor_carrier_key_sha256(factor)
        else:
            composition = next(
                (
                    item
                    for item in state.compositions
                    if item.composition_id == row_id
                ),
                None,
            )
            if composition is None:
                return False
            composition_carrier_key_sha256 = (
                self._composition_carrier_key_sha256(state, composition)
            )

        if edge_created_seq <= action.prepared_seq:
            return False
        authority_cutoff_seq = action.prepared_seq
        prior = [
            item
            for item in state.proposal_carrier_admissions
            if self._row_admission_matches(
                item,
                row_kind=row_kind,
                row_id=row_id,
                factor_carrier_key_sha256=factor_carrier_key_sha256,
                composition_carrier_key_sha256=(
                    composition_carrier_key_sha256
                ),
            )
            and item.created_seq < authority_cutoff_seq
        ]
        before_flag = (
            "factor_independently_eligible_before"
            if row_kind == "factor"
            else "composition_independently_eligible_before"
        )
        if any(bool(getattr(item, before_flag)) for item in prior):
            return True
        if any(
            item.state == "admitted"
            and item.terminal_seq is not None
            and item.terminal_seq < authority_cutoff_seq
            for item in prior
        ):
            return True
        return self._row_has_non_action_authority(
            state,
            row_kind=row_kind,
            row_id=row_id,
            before_seq=authority_cutoff_seq,
        )

    @staticmethod
    def _admission_for_transition(
        state: FactorBankStateV2,
        transition_id: str,
    ) -> ProposalCarrierAdmissionV1 | None:
        return next(
            (
                item
                for item in state.proposal_carrier_admissions
                if item.transition_id == transition_id
            ),
            None,
        )

    def _transition_has_execution_authority(
        self,
        state: FactorBankStateV2,
        transition: ScientificTransitionV2,
    ) -> bool:
        if not isinstance(transition, DirectFactorTransitionV2):
            return True
        if transition.proposal_action_id is None:
            return True
        admission = self._admission_for_transition(
            state,
            transition.transition_id,
        )
        return bool(
            transition.proposal_action_committed_seq is not None
            and admission is not None
            and admission.action_id == transition.proposal_action_id
            and admission.state == "admitted"
            and admission.terminal_seq
            == transition.proposal_action_committed_seq
        )

    def _composition_has_carrier_authority(
        self,
        state: FactorBankStateV2,
        composition: CompositionRevisionV2,
        *,
        before_seq: int | None = None,
    ) -> bool:
        """Require authority for a complete artifact and every bound factor."""

        return bool(
            self._row_is_carrier_eligible(
                state,
                row_kind="composition",
                row_id=composition.composition_id,
                before_seq=before_seq,
            )
            and all(
                self._row_is_carrier_eligible(
                    state,
                    row_kind="factor",
                    row_id=factor_id,
                    before_seq=before_seq,
                )
                for factor_id in composition.binding_map.values()
            )
        )

    def _harmful_transition_ids(
        self,
        assessment_overrides: Sequence[EdgeAssessmentV2] = (),
    ) -> set[str]:
        """Return canonical edge identities poisoned by verified harm.

        Epochs are scheduling identities, not scientific interventions.  A new
        epoch or storage/action alias therefore cannot wash away a harmful
        result for the same sealed intervention.  Archived harmful results
        remain authoritative through their transition-scoped tombstones; a
        genuinely different canonical intervention may be evaluated
        independently.
        """

        assessments = {item.plan_id: item for item in self._state.assessments}
        assessments.update({item.plan_id: item for item in assessment_overrides})
        harmful_seeds = {
            item.transition_id
            for item in assessments.values()
            if item.catastrophic_harm or item.label == "harmful"
        }
        harmful_seeds.update(
            item.subject_id
            for item in self._state.tombstones
            if item.disposition == "harmful"
        )
        transitions: dict[str, ScientificTransitionV2] = {
            **self.direct_transitions,
            **self.whole_transitions,
        }
        harmful_keys = {
            self._canonical_scientific_edge_sha256(
                self._state,
                transitions[transition_id],
            )
            for transition_id in harmful_seeds
            if transition_id in transitions
        }
        harmful_keys.update(
            self._rollback_harm_evidence_by_edge(self._state)
        )
        harmful = set(harmful_seeds)
        harmful.update(
            transition.transition_id
            for transition in transitions.values()
            if self._canonical_scientific_edge_sha256(
                self._state,
                transition,
            )
            in harmful_keys
        )
        return harmful

    def _rollback_harm_evidence_by_edge(
        self,
        state: FactorBankStateV2,
    ) -> dict[str, tuple[str, ...]]:
        """Reduce closed TRAIN monitor rollbacks to canonical edge evidence.

        A rollback is scientific negative evidence only for
        ``train_monitor_harm``.  Support/integrity rollbacks protect serving
        state but do not claim that the intervention itself was harmful.  The
        reducer requires the full trigger -> record -> deployed snapshot ->
        transition join, so a dangling authenticated row cannot poison an
        unrelated edge.  ``_validate_state`` independently requires this join
        for every persisted rollback.
        """

        transitions: dict[str, ScientificTransitionV2] = {
            **{item.transition_id: item for item in state.direct_transitions},
            **{item.transition_id: item for item in state.whole_transitions},
        }
        snapshots = {
            item.snapshot_id: item for item in state.deployment_snapshots
        }
        records_by_trigger: dict[str, list[RollbackRecordV2]] = {}
        for record in state.rollback_records:
            records_by_trigger.setdefault(record.trigger_id, []).append(record)
        evidence_by_edge: dict[str, list[str]] = {}
        for trigger in state.rollback_triggers:
            if trigger.kind != "train_monitor_harm":
                continue
            records = records_by_trigger.get(trigger.trigger_id, [])
            if len(records) != 1:
                continue
            record = records[0]
            snapshot = snapshots.get(trigger.active_snapshot_id)
            if not (
                record.old_snapshot_id == trigger.active_snapshot_id
                and record.deployment_slot_id == trigger.deployment_slot_id
                and record.old_generation == trigger.expected_head_generation
                and record.created_seq == trigger.emitted_seq
                and snapshot is not None
                and snapshot.deployment_slot_id == trigger.deployment_slot_id
                and snapshot.transition_id is not None
                and snapshot.transition_id in transitions
            ):
                continue
            transition = transitions[snapshot.transition_id]
            edge_key = self._canonical_scientific_edge_sha256(
                state,
                transition,
            )
            evidence_by_edge.setdefault(edge_key, []).append(
                _sha256(
                    {
                        "rollback_trigger": trigger,
                        "rollback_record": record,
                        "deployed_snapshot": snapshot,
                        "canonical_scientific_edge_key_sha256": edge_key,
                    }
                )
            )
        return {
            edge_key: tuple(sorted(set(evidence_roots)))
            for edge_key, evidence_roots in evidence_by_edge.items()
        }

    @staticmethod
    def _portable_pair_sha256_from_factors(
        transition: ScientificTransitionV2,
        factors: Mapping[str, FactorRevisionV2],
    ) -> str:
        """Canonical content/locus pair identity, independent of revision aliases."""

        if isinstance(transition, DirectFactorTransitionV2):
            old = factors[transition.from_revision_id]
            new = factors[transition.to_revision_id]
            return _sha256(
                {
                    "owner_kind": "direct_factor",
                    "namespace": transition.namespace.digest,
                    "slot": transition.slot_id,
                    "locus": {
                        "carrier": old.carrier,
                        "logical_factor_id": old.logical_factor_id,
                        "locator": old.locator,
                        "binding_status": old.binding_status,
                    },
                    "from_content": old.content_sha256,
                    "to_content": new.content_sha256,
                }
            )
        return _sha256(
            {
                "owner_kind": "whole_composition",
                "namespace": transition.namespace.digest,
                "changed_slots": transition.changed_slot_ids,
                "from_artifact": transition.source_artifact_sha256,
                "to_artifact": transition.target_artifact_sha256,
            }
        )

    def _portable_pair_sha256(
        self,
        transition: ScientificTransitionV2,
    ) -> str:
        return self._portable_pair_sha256_from_factors(transition, self.factors)

    @staticmethod
    def _transition_background_sha256(
        transition: ScientificTransitionV2,
    ) -> str:
        return (
            transition.fixed_background_sha256
            if isinstance(transition, DirectFactorTransitionV2)
            else _sha256({"whole": transition.changed_slot_ids})
        )

    def _harmful_portable_pair_sha256s(self) -> set[str]:
        transitions: dict[str, ScientificTransitionV2] = {
            **self.direct_transitions,
            **self.whole_transitions,
        }
        result = {
            item.portable_pair_sha256
            for item in self._state.tombstones
            if item.disposition == "harmful"
        }
        for assessment in self._state.assessments:
            if not (
                assessment.catastrophic_harm
                or assessment.label == "harmful"
            ):
                continue
            transition = transitions.get(assessment.transition_id)
            if transition is not None:
                result.add(self._portable_pair_sha256(transition))
        return result

    @_atomic_bank_update
    def add_factor(self, factor: FactorRevisionV2) -> None:
        factor = FactorRevisionV2.model_validate(factor.model_dump(mode="python"))
        if factor.revision_id in self.factors:
            raise ValueError("factor revision already exists")
        reserved = self._unmaterialized_carrier_reservations(
            self._state,
        )
        if (
            len(self._state.factors) + len(reserved)
            >= self._state.capacity_policy.max_factor_records
        ):
            raise RuntimeError("factor record capacity is exhausted")
        if factor.created_seq != self._state.event_seq + 1:
            raise ValueError("factor created_seq must equal the next Bank event")
        self._install(self._next_state(factors=(*self._state.factors, factor)))

    @_atomic_bank_update
    def add_composition(self, composition: CompositionRevisionV2) -> None:
        composition = CompositionRevisionV2.model_validate(
            composition.model_dump(mode="python")
        )
        if composition.composition_id in self.compositions:
            raise ValueError("composition revision already exists")
        policy = self._state.capacity_policy
        reserved = self._unmaterialized_carrier_reservations(
            self._state,
        )
        if len(self._state.compositions) + len(reserved) >= (
            policy.max_composition_records
        ):
            raise RuntimeError("composition record capacity is exhausted")
        scoped_live = [
            item
            for item in self._state.compositions
            if item.namespace == composition.namespace and item.structural_state == "live"
        ]
        scoped_reserved = [
            item
            for item in reserved
            if item.namespace_digest == composition.namespace.digest
        ]
        if len(scoped_live) + len(scoped_reserved) >= (
            policy.max_hot_compositions_per_namespace
            + policy.unknown_structural_reserve
        ):
            raise RuntimeError("hot composition capacity is exhausted for this namespace")
        if (
            sum(item.canonical_metadata_bytes for item in scoped_live)
            + sum(item.reserved_hot_metadata_bytes for item in scoped_reserved)
            + composition.canonical_metadata_bytes
            > policy.max_hot_metadata_bytes
        ):
            raise RuntimeError("hot composition metadata-byte capacity is exhausted")
        if (
            sum(item.artifact_bytes for item in scoped_live)
            + sum(item.reserved_artifact_bytes for item in scoped_reserved)
            + composition.artifact_bytes
            > policy.max_hot_artifact_bytes_per_namespace
        ):
            raise RuntimeError("hot composition artifact-byte capacity is exhausted")
        if (
            sum(item.prompt_summary_tokens for item in scoped_live)
            + sum(item.reserved_prompt_summary_tokens for item in scoped_reserved)
            + composition.prompt_summary_tokens
            > policy.max_prompt_summary_tokens_per_namespace
        ):
            raise RuntimeError("prompt-summary token capacity is exhausted")
        if composition.created_seq != self._state.event_seq + 1:
            raise ValueError("composition created_seq must equal the next Bank event")
        self._install(
            self._next_state(compositions=(*self._state.compositions, composition))
        )

    @_atomic_bank_update
    def register_direct_bundle(
        self,
        *,
        factors: Sequence[FactorRevisionV2],
        compositions: Sequence[CompositionRevisionV2],
        transition_fields: Mapping[str, Any],
    ) -> DirectFactorTransitionV2:
        """Install one registry-proved structural bundle as a single mutation.

        A canonical adapter may need to append previously unseen content before
        the edge can be verified.  None of those structural rows may survive if
        the final full-bundle verifier rejects the edge.  The normal append
        methods remain useful for fixtures, while production adapters use this
        transaction boundary.
        """

        fields = dict(transition_fields)
        fields.setdefault("proposal_action_id", None)
        fields.setdefault("proposal_action_intent_sha256", None)
        action_id = fields.get("proposal_action_id")
        consumer_action_id: str | None = None
        if isinstance(action_id, str):
            action = next(
                (
                    item
                    for item in self._state.proposal_actions
                    if item.action_id == action_id
                ),
                None,
            )
            reservation = self._proposal_carrier_reservation_for_action(
                self._state,
                action_id,
            )
            if (
                action is not None
                and action.branch in {"mutate", "fresh"}
                and reservation is not None
                and reservation.state == "reserved"
            ):
                consumer_action_id = action_id
        reserved = self._unmaterialized_carrier_reservations(
            self._state,
            excluding_action_id=consumer_action_id,
        )
        staged_factors = list(self._state.factors)
        staged_compositions = list(self._state.compositions)
        factor_ids = {item.revision_id for item in staged_factors}
        composition_ids = {item.composition_id for item in staged_compositions}
        next_seq = self._state.event_seq
        for raw_factor in factors:
            factor = FactorRevisionV2.model_validate(
                raw_factor.model_dump(mode="python")
            )
            if factor.revision_id in factor_ids:
                raise ValueError("direct bundle contains an existing factor")
            if (
                len(staged_factors) + len(reserved)
                >= self._state.capacity_policy.max_factor_records
            ):
                raise RuntimeError("factor record capacity is exhausted")
            next_seq += 1
            if factor.created_seq != next_seq:
                raise ValueError(
                    "bundle factor created_seq must equal its next local event"
                )
            staged_factors.append(factor)
            factor_ids.add(factor.revision_id)
        for raw_composition in compositions:
            composition = CompositionRevisionV2.model_validate(
                raw_composition.model_dump(mode="python")
            )
            if composition.composition_id in composition_ids:
                raise ValueError("direct bundle contains an existing composition")
            policy = self._state.capacity_policy
            if len(staged_compositions) + len(reserved) >= (
                policy.max_composition_records
            ):
                raise RuntimeError("composition record capacity is exhausted")
            scoped_live = [
                item
                for item in staged_compositions
                if item.namespace == composition.namespace
                and item.structural_state == "live"
            ]
            scoped_reserved = [
                item
                for item in reserved
                if item.namespace_digest == composition.namespace.digest
            ]
            if len(scoped_live) + len(scoped_reserved) >= (
                policy.max_hot_compositions_per_namespace
                + policy.unknown_structural_reserve
            ):
                raise RuntimeError(
                    "hot composition capacity is exhausted for this namespace"
                )
            if (
                sum(item.canonical_metadata_bytes for item in scoped_live)
                + sum(
                    item.reserved_hot_metadata_bytes
                    for item in scoped_reserved
                )
                + composition.canonical_metadata_bytes
                > policy.max_hot_metadata_bytes
            ):
                raise RuntimeError(
                    "hot composition metadata-byte capacity is exhausted"
                )
            if (
                sum(item.artifact_bytes for item in scoped_live)
                + sum(
                    item.reserved_artifact_bytes
                    for item in scoped_reserved
                )
                + composition.artifact_bytes
                > policy.max_hot_artifact_bytes_per_namespace
            ):
                raise RuntimeError(
                    "hot composition artifact-byte capacity is exhausted"
                )
            if (
                sum(item.prompt_summary_tokens for item in scoped_live)
                + sum(
                    item.reserved_prompt_summary_tokens
                    for item in scoped_reserved
                )
                + composition.prompt_summary_tokens
                > policy.max_prompt_summary_tokens_per_namespace
            ):
                raise RuntimeError("prompt-summary token capacity is exhausted")
            next_seq += 1
            if composition.created_seq != next_seq:
                raise ValueError(
                    "bundle composition created_seq must equal its next local event"
                )
            staged_compositions.append(composition)
            composition_ids.add(composition.composition_id)
        working_payload = self._state.model_dump(mode="python")
        working_payload.update(
            {
                "event_seq": next_seq,
                "factors": tuple(staged_factors),
                "compositions": tuple(staged_compositions),
            }
        )
        working_state = FactorBankStateV2.model_validate(working_payload)
        return self._register_direct_transition_impl(
            **fields,
            bundle_new_factor_ids=frozenset(
                item.revision_id for item in factors
            ),
            bundle_new_composition_ids=frozenset(
                item.composition_id for item in compositions
            ),
            working_state=working_state,
            created_seq_override=next_seq + 1,
        )

    @_atomic_bank_update
    def register_direct_transition(
        self,
        *,
        source_composition_id: str,
        target_composition_id: str,
        slot_id: str,
        binding_proof_id: str,
        binding_proof_sha256: str,
        masked_background_sha256: str,
        binding_verifier_epoch: str,
        origin_branch: ScientificBranch,
        proposal_action_id: str | None = None,
        proposal_action_intent_sha256: str | None = None,
    ) -> DirectFactorTransitionV2:
        return self._register_direct_transition_impl(
            source_composition_id=source_composition_id,
            target_composition_id=target_composition_id,
            slot_id=slot_id,
            binding_proof_id=binding_proof_id,
            binding_proof_sha256=binding_proof_sha256,
            masked_background_sha256=masked_background_sha256,
            binding_verifier_epoch=binding_verifier_epoch,
            origin_branch=origin_branch,
            proposal_action_id=proposal_action_id,
            proposal_action_intent_sha256=proposal_action_intent_sha256,
            bundle_new_factor_ids=frozenset(),
            bundle_new_composition_ids=frozenset(),
            working_state=None,
            created_seq_override=None,
        )

    def _register_direct_transition_impl(
        self,
        *,
        source_composition_id: str,
        target_composition_id: str,
        slot_id: str,
        binding_proof_id: str,
        binding_proof_sha256: str,
        masked_background_sha256: str,
        binding_verifier_epoch: str,
        origin_branch: ScientificBranch,
        proposal_action_id: str | None,
        proposal_action_intent_sha256: str | None,
        bundle_new_factor_ids: frozenset[str],
        bundle_new_composition_ids: frozenset[str],
        working_state: FactorBankStateV2 | None,
        created_seq_override: int | None,
    ) -> DirectFactorTransitionV2:
        state = working_state or self._state
        factors_by_id = {item.revision_id: item for item in state.factors}
        compositions_by_id = {
            item.composition_id: item for item in state.compositions
        }
        source = compositions_by_id[source_composition_id]
        target = compositions_by_id[target_composition_id]
        if source.namespace != target.namespace:
            raise ValueError("direct transition crosses its execution namespace")
        if source.structural_state != "live" or target.structural_state != "live":
            raise ValueError("direct transition requires live source and target compositions")
        source_map, target_map = source.binding_map, target.binding_map
        if set(source_map) != set(target_map) or slot_id not in source_map:
            raise ValueError("direct transition requires the same complete slot domain")
        changed = [slot for slot in sorted(source_map) if source_map[slot] != target_map[slot]]
        if changed != [slot_id]:
            raise ValueError("direct transition requires exactly one changed slot")
        old = factors_by_id[source_map[slot_id]]
        new = factors_by_id[target_map[slot_id]]
        if not (
            old.structural_state == new.structural_state == "live"
            and old.namespace == new.namespace == source.namespace
            and old.carrier == new.carrier
            and old.logical_factor_id == new.logical_factor_id
            and old.locator == new.locator
            and old.binding_status == new.binding_status == "proven_factorized"
            and old.content_sha256 != new.content_sha256
        ):
            raise ValueError(
                "direct transition requires one live, content-changing typed locus"
            )
        action: ProposalActionV2 | None = None
        carrier_reservation: ProposalCarrierCapacityReservationV1 | None = None
        if proposal_action_id is not None:
            action = next(
                (
                    item for item in state.proposal_actions
                    if item.action_id == proposal_action_id
                ),
                None,
            )
            expected_state = (
                "prepared" if origin_branch == "reuse" else "executing"
            )
            if action is None or not (
                action.state == expected_state
                and action.branch == origin_branch
                and proposal_action_intent_sha256 == action.action_intent_sha256
                and action.namespace_digest == source.namespace.digest
                and action.source_composition_id == source.composition_id
                and action.slot_id == slot_id
                and action.from_revision_id == old.revision_id
                and (
                    origin_branch != "reuse"
                    or (
                        action.selected_target_revision_id == new.revision_id
                        and action.selected_target_content_sha256
                        == new.content_sha256
                    )
                )
                and (
                    origin_branch != "mutate"
                    or new.parent_revision_id == old.revision_id
                )
                and (
                    origin_branch != "fresh"
                    or new.parent_revision_id is None
                )
            ):
                raise ValueError(
                    "direct transition does not match its prepared proposal action"
                )
            if any(
                item.proposal_action_id == action.action_id
                for item in state.direct_transitions
            ):
                raise ValueError("proposal action already owns a local edge")
            if action.branch in {"mutate", "fresh"}:
                carrier_reservation = (
                    self._proposal_carrier_reservation_for_action(
                        state,
                        action.action_id,
                    )
                )
                if carrier_reservation is None or not (
                    carrier_reservation.state == "reserved"
                    and carrier_reservation.namespace_digest
                    == action.namespace_digest
                    and carrier_reservation.created_seq
                    == action.prepared_seq
                ):
                    raise RuntimeError(
                        "generated action lacks reserved carrier capacity"
                    )
        elif proposal_action_intent_sha256 is not None:
            raise ValueError("proposal action intent lacks its action id")
        else:
            self._assert_no_active_action_ordinary_owner(
                state,
                namespace_digest=source.namespace.digest,
                source_composition_id=source.composition_id,
                slot_ids_and_from_revisions=((slot_id, old.revision_id),),
            )
        background_ids = tuple(
            source_map[slot] for slot in sorted(source_map) if slot != slot_id
        )
        background = tuple(factors_by_id[item] for item in background_ids)
        fixed_background = _sha256(
            [(slot, source_map[slot]) for slot in sorted(source_map) if slot != slot_id]
        )
        created_seq = (
            created_seq_override
            if created_seq_override is not None
            else self._state.event_seq + 1
        )
        transition_id = _opaque_id(
            "dt",
            {
                "namespace": source.namespace.digest,
                "source": source.composition_id,
                "target": target.composition_id,
                "slot": slot_id,
                "from": old.revision_id,
                "to": new.revision_id,
                "background": fixed_background,
                "proof": binding_proof_sha256,
                "branch": origin_branch,
                "proposal_action": proposal_action_id,
                "proposal_intent": proposal_action_intent_sha256,
            },
        )
        transition = DirectFactorTransitionV2(
            transition_id=transition_id,
            namespace=source.namespace,
            source_composition_id=source.composition_id,
            target_composition_id=target.composition_id,
            slot_id=slot_id,
            from_revision_id=old.revision_id,
            to_revision_id=new.revision_id,
            fixed_background_sha256=fixed_background,
            masked_background_sha256=masked_background_sha256,
            binding_proof_id=binding_proof_id,
            binding_proof_sha256=binding_proof_sha256,
            binding_verifier_epoch=binding_verifier_epoch,
            origin_branch=origin_branch,
            proposal_action_id=proposal_action_id,
            proposal_action_intent_sha256=proposal_action_intent_sha256,
            created_seq=created_seq,
        )
        target_factor_was_new = new.revision_id in bundle_new_factor_ids
        target_composition_was_new = (
            target.composition_id in bundle_new_composition_ids
        )
        admission: ProposalCarrierAdmissionV1 | None = None
        if action is None:
            if not self._row_can_receive_non_action_authority(
                state,
                row_kind="factor",
                row_id=new.revision_id,
                before_seq=created_seq,
            ) or not self._row_can_receive_non_action_authority(
                state,
                row_kind="composition",
                row_id=target.composition_id,
                before_seq=created_seq,
            ):
                raise ValueError(
                    "unowned transition cannot launder an ineligible carrier"
                )
        else:
            if bundle_new_factor_ids - {new.revision_id}:
                raise ValueError(
                    "action bundle contains a factor outside its exact target carrier"
                )
            if bundle_new_composition_ids - {target.composition_id}:
                raise ValueError(
                    "action bundle contains a composition outside its exact target carrier"
                )
            reserved_admission_slots = len(
                self._unmaterialized_carrier_reservations(
                    state,
                    excluding_action_id=(
                        action.action_id
                        if carrier_reservation is not None
                        else None
                    ),
                )
            )
            if (
                len(state.proposal_carrier_admissions)
                + reserved_admission_slots
                >= state.capacity_policy.max_proposal_carrier_admissions
            ):
                raise RuntimeError(
                    "proposal carrier-admission capacity is exhausted"
                )
            factor_before = bool(
                not target_factor_was_new
                and self._row_was_independently_eligible_before_action_edge(
                    state,
                    row_kind="factor",
                    row_id=new.revision_id,
                    action=action,
                    edge_created_seq=created_seq,
                )
            )
            composition_before = bool(
                not target_composition_was_new
                and self._row_was_independently_eligible_before_action_edge(
                    state,
                    row_kind="composition",
                    row_id=target.composition_id,
                    action=action,
                    edge_created_seq=created_seq,
                )
            )
            if target_factor_was_new and any(
                item.revision_id != new.revision_id
                and self._factor_carrier_key_sha256(item)
                == self._factor_carrier_key_sha256(new)
                for item in state.factors
            ):
                raise ValueError(
                    "new action target duplicates an existing carrier key"
                )
            if target_composition_was_new and any(
                item.composition_id != target.composition_id
                and self._composition_carrier_key_sha256(state, item)
                == self._composition_carrier_key_sha256(state, target)
                for item in state.compositions
            ):
                raise ValueError(
                    "new action target duplicates an existing composition carrier key"
                )
            if not target_factor_was_new and not factor_before:
                raise ValueError(
                    "action target factor lacks independent carrier authority"
                )
            if not target_composition_was_new and not composition_before:
                raise ValueError(
                    "action target composition lacks independent carrier authority"
                )
            projected_sha256 = _sha256(
                self._projected_action_transition(transition)
            )
            body = {
                "admission_version": "sft_proposal_carrier_admission_v2",
                "action_id": action.action_id,
                "action_intent_sha256": action.action_intent_sha256,
                "transition_id": transition.transition_id,
                "projected_transition_sha256": projected_sha256,
                "namespace_digest": transition.namespace.digest,
                "source_composition_id": transition.source_composition_id,
                "target_composition_id": transition.target_composition_id,
                "target_composition_sha256": _sha256(
                    self._projected_carrier_row(target)
                ),
                "target_composition_carrier_key_sha256": (
                    self._composition_carrier_key_sha256(state, target)
                ),
                "target_factor_revision_id": transition.to_revision_id,
                "target_factor_sha256": _sha256(
                    self._projected_carrier_row(new)
                ),
                "target_factor_carrier_key_sha256": (
                    self._factor_carrier_key_sha256(new)
                ),
                "independent_authority_cutoff_seq": action.prepared_seq,
                "factor_independently_eligible_before": factor_before,
                "composition_independently_eligible_before": composition_before,
                "state": "staged",
                "created_seq": created_seq,
                "terminal_seq": None,
                "terminal_sha256": None,
            }
            identity = dict(body)
            for field in ("state", "terminal_seq", "terminal_sha256"):
                identity.pop(field)
            admission = ProposalCarrierAdmissionV1(
                admission_id=_opaque_id("pca", identity),
                **body,
            )
            if carrier_reservation is not None:
                self._assert_carrier_closure_fits_reservation(
                    carrier_reservation,
                    action=action,
                    factor=new,
                    composition=target,
                    transition=transition,
                    admission=admission,
                )
        if any(
            item.transition_id == transition.transition_id
            for item in state.direct_transitions
        ):
            raise ValueError("direct transition already exists")
        canonical_edge_sha256 = self._canonical_scientific_edge_sha256(
            state,
            transition,
        )
        canonical_siblings = tuple(
            item
            for item in (*state.direct_transitions, *state.whole_transitions)
            if self._canonical_scientific_edge_sha256(state, item)
            == canonical_edge_sha256
        )
        if action is None and canonical_siblings:
            raise ValueError(
                "canonical scientific edge already has a credit owner"
            )
        if action is not None and any(
            item.structural_state != "live" for item in canonical_siblings
        ):
            raise ValueError(
                "archived canonical scientific edge cannot be reactivated"
            )
        harmful_transition_ids = self._harmful_transition_ids()
        if any(
            item.transition_id in harmful_transition_ids
            for item in canonical_siblings
        ):
            raise ValueError("canonical scientific edge has verified harm")
        reserved_transition_slots = len(
            self._unmaterialized_carrier_reservations(
                state,
                excluding_action_id=(
                    action.action_id
                    if carrier_reservation is not None and action is not None
                    else None
                ),
            )
        )
        if (
            len(state.direct_transitions)
            + len(state.whole_transitions)
            + reserved_transition_slots
            >= state.capacity_policy.max_transition_records
        ):
            raise RuntimeError("scientific transition record capacity is exhausted")
        if self._direct_binding_verifier is None:
            raise RuntimeError("no trusted direct binding verifier is installed")
        try:
            verified = bool(
                self._direct_binding_verifier(
                    transition, source, target, old, new, background
                )
            )
        except Exception as exc:
            raise RuntimeError("trusted direct binding verification failed") from exc
        if not verified:
            raise ValueError("trusted direct binding verifier rejected the canonical bundle")
        updates: dict[str, Any] = {
            "factors": state.factors,
            "compositions": state.compositions,
            "direct_transitions": (*state.direct_transitions, transition),
        }
        if admission is not None:
            updates["proposal_carrier_admissions"] = (
                *state.proposal_carrier_admissions,
                admission,
            )
        if carrier_reservation is not None:
            materialized_reservation = carrier_reservation.model_copy(
                update={
                    "state": "materialized",
                    "materialized_seq": created_seq,
                }
            )
            updates["proposal_carrier_reservations"] = tuple(
                materialized_reservation
                if item.reservation_id == carrier_reservation.reservation_id
                else item
                for item in state.proposal_carrier_reservations
            )
        self._install(self._next_state_at(created_seq, **updates))
        return transition

    @_atomic_bank_update
    def register_whole_transition(
        self,
        *,
        source_composition_id: str,
        target_composition_id: str,
        operation_receipt_sha256: str,
        operation_verifier_epoch: str,
        origin_branch: ScientificBranch,
    ) -> WholeCompositionTransitionV2:
        return self._register_whole_transition_impl(
            source_composition_id=source_composition_id,
            target_composition_id=target_composition_id,
            operation_receipt_sha256=operation_receipt_sha256,
            operation_verifier_epoch=operation_verifier_epoch,
            origin_branch=origin_branch,
            working_state=None,
            created_seq_override=None,
        )

    def _staged_bundle_state(
        self,
        *,
        factors: Sequence[FactorRevisionV2],
        compositions: Sequence[CompositionRevisionV2],
    ) -> tuple[FactorBankStateV2, int]:
        """Stage previously unseen rows exactly like ``register_direct_bundle``.

        The staged rows exist only in the returned working state; nothing is
        installed until the transition registrar accepts the complete bundle.
        """

        reserved = self._unmaterialized_carrier_reservations(self._state)
        staged_factors = list(self._state.factors)
        staged_compositions = list(self._state.compositions)
        factor_ids = {item.revision_id for item in staged_factors}
        composition_ids = {item.composition_id for item in staged_compositions}
        next_seq = self._state.event_seq
        for raw_factor in factors:
            factor = FactorRevisionV2.model_validate(
                raw_factor.model_dump(mode="python")
            )
            if factor.revision_id in factor_ids:
                raise ValueError("whole bundle contains an existing factor")
            if (
                len(staged_factors) + len(reserved)
                >= self._state.capacity_policy.max_factor_records
            ):
                raise RuntimeError("factor record capacity is exhausted")
            next_seq += 1
            if factor.created_seq != next_seq:
                raise ValueError(
                    "bundle factor created_seq must equal its next local event"
                )
            staged_factors.append(factor)
            factor_ids.add(factor.revision_id)
        for raw_composition in compositions:
            composition = CompositionRevisionV2.model_validate(
                raw_composition.model_dump(mode="python")
            )
            if composition.composition_id in composition_ids:
                raise ValueError("whole bundle contains an existing composition")
            policy = self._state.capacity_policy
            if len(staged_compositions) + len(reserved) >= (
                policy.max_composition_records
            ):
                raise RuntimeError("composition record capacity is exhausted")
            scoped_live = [
                item
                for item in staged_compositions
                if item.namespace == composition.namespace
                and item.structural_state == "live"
            ]
            scoped_reserved = [
                item
                for item in reserved
                if item.namespace_digest == composition.namespace.digest
            ]
            if len(scoped_live) + len(scoped_reserved) >= (
                policy.max_hot_compositions_per_namespace
                + policy.unknown_structural_reserve
            ):
                raise RuntimeError(
                    "hot composition capacity is exhausted for this namespace"
                )
            if (
                sum(item.canonical_metadata_bytes for item in scoped_live)
                + sum(
                    item.reserved_hot_metadata_bytes
                    for item in scoped_reserved
                )
                + composition.canonical_metadata_bytes
                > policy.max_hot_metadata_bytes
            ):
                raise RuntimeError(
                    "hot composition metadata-byte capacity is exhausted"
                )
            if (
                sum(item.artifact_bytes for item in scoped_live)
                + sum(
                    item.reserved_artifact_bytes
                    for item in scoped_reserved
                )
                + composition.artifact_bytes
                > policy.max_hot_artifact_bytes_per_namespace
            ):
                raise RuntimeError(
                    "hot composition artifact-byte capacity is exhausted"
                )
            if (
                sum(item.prompt_summary_tokens for item in scoped_live)
                + sum(
                    item.reserved_prompt_summary_tokens
                    for item in scoped_reserved
                )
                + composition.prompt_summary_tokens
                > policy.max_prompt_summary_tokens_per_namespace
            ):
                raise RuntimeError("prompt-summary token capacity is exhausted")
            next_seq += 1
            if composition.created_seq != next_seq:
                raise ValueError(
                    "bundle composition created_seq must equal its next local event"
                )
            staged_compositions.append(composition)
            composition_ids.add(composition.composition_id)
        working_payload = self._state.model_dump(mode="python")
        working_payload.update(
            {
                "event_seq": next_seq,
                "factors": tuple(staged_factors),
                "compositions": tuple(staged_compositions),
            }
        )
        return FactorBankStateV2.model_validate(working_payload), next_seq

    @_atomic_bank_update
    def register_whole_bundle(
        self,
        *,
        factors: Sequence[FactorRevisionV2],
        compositions: Sequence[CompositionRevisionV2],
        transition_fields: Mapping[str, Any],
    ) -> WholeCompositionTransitionV2:
        """Install one operation-proved whole-composition bundle atomically.

        The whole-composition analog of ``register_direct_bundle``: previously
        unseen factor/composition rows and their ordinary whole transition
        either all land or none do, and the trusted whole-operation verifier
        judges the transaction against the complete staged bundle.
        """

        working_state, next_seq = self._staged_bundle_state(
            factors=factors,
            compositions=compositions,
        )
        return self._register_whole_transition_impl(
            **dict(transition_fields),
            working_state=working_state,
            created_seq_override=next_seq + 1,
        )

    def _register_whole_transition_impl(
        self,
        *,
        source_composition_id: str,
        target_composition_id: str,
        operation_receipt_sha256: str,
        operation_verifier_epoch: str,
        origin_branch: ScientificBranch,
        working_state: FactorBankStateV2 | None,
        created_seq_override: int | None,
    ) -> WholeCompositionTransitionV2:
        state = working_state if working_state is not None else self._state
        compositions_by_id = {
            item.composition_id: item for item in state.compositions
        }
        source = compositions_by_id[source_composition_id]
        target = compositions_by_id[target_composition_id]
        if source.namespace != target.namespace:
            raise ValueError("whole transition crosses its execution namespace")
        if source.structural_state != "live" or target.structural_state != "live":
            raise ValueError("whole transition requires live source and target compositions")
        created_seq = (
            created_seq_override
            if created_seq_override is not None
            else self._state.event_seq + 1
        )
        authority_seq = created_seq
        if not self._row_can_receive_non_action_authority(
            state,
            row_kind="composition",
            row_id=target.composition_id,
            before_seq=authority_seq,
        ) or any(
            not self._row_can_receive_non_action_authority(
                state,
                row_kind="factor",
                row_id=factor_id,
                before_seq=authority_seq,
            )
            for factor_id in target.binding_map.values()
        ):
            raise ValueError(
                "whole transition cannot launder an ineligible carrier"
            )
        if source.artifact_sha256 == target.artifact_sha256:
            raise ValueError("whole transition must change complete artifact content")
        slots = sorted(set(source.binding_map) | set(target.binding_map))
        changed = tuple(
            slot for slot in slots if source.binding_map.get(slot) != target.binding_map.get(slot)
        )
        self._assert_no_active_action_ordinary_owner(
            state,
            namespace_digest=source.namespace.digest,
            source_composition_id=source.composition_id,
            slot_ids_and_from_revisions=tuple(
                (slot_id, source.binding_map[slot_id])
                for slot_id in changed
                if slot_id in source.binding_map
            ),
        )
        transition_id = _opaque_id(
            "wt",
            {
                "namespace": source.namespace.digest,
                "source": source.composition_id,
                "target": target.composition_id,
                "changed": changed,
                "receipt": operation_receipt_sha256,
                "branch": origin_branch,
            },
        )
        transition = WholeCompositionTransitionV2(
            transition_id=transition_id,
            namespace=source.namespace,
            source_composition_id=source.composition_id,
            target_composition_id=target.composition_id,
            changed_slot_ids=changed,
            source_artifact_sha256=source.artifact_sha256,
            target_artifact_sha256=target.artifact_sha256,
            operation_receipt_sha256=operation_receipt_sha256,
            operation_verifier_epoch=operation_verifier_epoch,
            origin_branch=origin_branch,
            created_seq=created_seq,
        )
        if any(
            item.transition_id == transition.transition_id
            for item in state.whole_transitions
        ):
            raise ValueError("whole transition already exists")
        canonical_edge_sha256 = self._canonical_scientific_edge_sha256(
            state,
            transition,
        )
        if any(
            self._canonical_scientific_edge_sha256(state, item)
            == canonical_edge_sha256
            for item in (
                *state.direct_transitions,
                *state.whole_transitions,
            )
        ):
            raise ValueError(
                "canonical scientific edge already has a credit owner"
            )
        reserved_transition_slots = len(
            self._unmaterialized_carrier_reservations(state)
        )
        if (
            len(state.direct_transitions)
            + len(state.whole_transitions)
            + reserved_transition_slots
            >= state.capacity_policy.max_transition_records
        ):
            raise RuntimeError("scientific transition record capacity is exhausted")
        if self._whole_operation_verifier is None:
            raise RuntimeError("no trusted whole-operation verifier is installed")
        try:
            verified = bool(self._whole_operation_verifier(transition, source, target))
        except Exception as exc:
            raise RuntimeError("trusted whole-operation verification failed") from exc
        if not verified:
            raise ValueError("trusted whole-operation verifier rejected the transaction")
        self._install(
            self._next_state_at(
                created_seq,
                factors=state.factors,
                compositions=state.compositions,
                whole_transitions=(*state.whole_transitions, transition),
            )
        )
        return transition

    @_atomic_bank_update
    def seal_probe_plan(
        self,
        *,
        transition_id: str,
        owner_kind: OwnerKind,
        epoch_id: str,
        unit_commitments: Sequence[str],
        arm_orders: Sequence[Literal["AB", "BA"]],
        assignment_manifest_sha256: str,
        runner_version: str,
        budget: ExecutionBudget,
        aggregate_policy: AggregatePolicyV1 | None = None,
    ) -> ProbePlanV2:
        transition = self._transition(transition_id, owner_kind)
        if transition.structural_state != "live":
            raise ValueError("only a live scientific transition can receive a probe plan")
        if not self._transition_has_execution_authority(
            self._state,
            transition,
        ):
            raise ValueError(
                "proposal action edge is inert until action finalization"
            )
        canonical_edge_key = self._canonical_scientific_edge_sha256(
            self._state,
            transition,
        )
        canonical_background = self._canonical_background_sha256(
            self._state,
            transition,
        )
        credit_owner_transition_id = self._credit_owner_transition_id(
            self._state,
            transition,
        )
        if credit_owner_transition_id != transition.transition_id:
            raise ValueError(
                "canonical scientific edge already has a different credit owner"
            )
        if len(self._state.plans) >= self._state.capacity_policy.max_plan_records:
            raise RuntimeError("probe-plan record capacity is exhausted")
        if transition_id in self._harmful_transition_ids():
            raise ValueError(
                "harmful scientific transition requires a new transition, not a new epoch"
            )
        if (canonical_edge_key, epoch_id) in self._state.used_edge_epochs:
            raise ValueError("canonical scientific edge epoch was already used")
        policy = AggregatePolicyV1.model_validate(
            (aggregate_policy or AggregatePolicyV1()).model_dump(mode="python")
        )
        budget = ExecutionBudget.model_validate(budget.model_dump(mode="python"))
        if len(unit_commitments) != 6 or len(arm_orders) != 6:
            raise ValueError("probe plan requires exactly six outcome-before units")
        units = tuple(
            ProbeUnitV2(
                ordinal=index,
                role="primary" if index < 4 else "reserve",
                unit_commitment=unit,
                arm_order=arm_orders[index],
            )
            for index, unit in enumerate(unit_commitments)
        )
        existing_unit_commitments = {
            unit_commitment
            for used_edge_key, unit_commitment
            in self._state.used_unit_commitments
            if used_edge_key == canonical_edge_key
        }
        if existing_unit_commitments.intersection(
            unit.unit_commitment for unit in units
        ):
            raise ValueError(
                "probe epoch reuses a unit commitment from the same canonical edge"
            )
        prior_plans = sorted(
            (
                item
                for item in self._state.plans
                if item.canonical_scientific_edge_key_sha256
                == canonical_edge_key
            ),
            key=lambda item: (item.created_seq, item.plan_id),
        )
        if prior_plans:
            if len(prior_plans) >= (
                self._state.capacity_policy.max_infrastructure_epochs_per_edge
            ):
                raise ValueError(
                    "canonical scientific edge exhausted infrastructure-only epochs"
                )
            latest = prior_plans[-1]
            latest_assessment = self.assessments[latest.plan_id]
            if not (
                latest_assessment.settled
                and latest_assessment.label == "infrastructure_exhausted"
                and latest_assessment.n_complete == 0
                and latest_assessment.n_open == 0
                and not any(
                    item.plan_id == latest.plan_id and item.state == "open"
                    for item in self._state.attempts
                )
                and not any(
                    item.plan_id == latest.plan_id and item.state == "pending"
                    for item in self._state.gate_opportunities
                )
            ):
                raise ValueError(
                    "canonical scientific edge permits only zero-complete "
                    "infrastructure retry"
                )
        if len(self._state.used_unit_commitments) + len(units) > (
            self._state.capacity_policy.max_unit_commitments
        ):
            raise RuntimeError("unit-commitment capacity is exhausted")
        used_unit_commitments = tuple(
            sorted(
                (
                    *self._state.used_unit_commitments,
                    *((canonical_edge_key, item.unit_commitment) for item in units),
                )
            )
        )
        used_edge_epochs = tuple(
            sorted(
                (*self._state.used_edge_epochs, (canonical_edge_key, epoch_id))
            )
        )
        source = self.compositions[transition.source_composition_id]
        target = self.compositions[transition.target_composition_id]
        fixed = (
            transition.fixed_background_sha256
            if isinstance(transition, DirectFactorTransitionV2)
            else _sha256({"whole": transition.changed_slot_ids})
        )
        support = (
            transition.binding_proof_sha256
            if isinstance(transition, DirectFactorTransitionV2)
            else transition.operation_receipt_sha256
        )
        created_seq = self._state.event_seq + 1
        plan_id = _opaque_id(
            "pp",
            {
                "transition": transition.transition_id,
                "canonical_scientific_edge": canonical_edge_key,
                "canonical_background": canonical_background,
                "credit_owner_transition": credit_owner_transition_id,
                "epoch": epoch_id,
                "units": units,
                "policy": policy.digest,
                "budget": budget.digest,
                "manifest": assignment_manifest_sha256,
            },
        )
        plan = ProbePlanV2(
            plan_id=plan_id,
            epoch_id=epoch_id,
            owner_kind=owner_kind,
            transition_id=transition.transition_id,
            canonical_scientific_edge_key_sha256=canonical_edge_key,
            canonical_background_sha256=canonical_background,
            credit_owner_transition_id=credit_owner_transition_id,
            namespace_digest=transition.namespace.digest,
            source_snapshot_sha256=_sha256(source),
            target_snapshot_sha256=_sha256(target),
            source_artifact_sha256=source.artifact_sha256,
            target_artifact_sha256=target.artifact_sha256,
            fixed_background_sha256=fixed,
            binding_or_operation_proof_sha256=support,
            aggregate_policy=policy,
            aggregate_policy_sha256=policy.digest,
            units=units,
            assignment_manifest_sha256=assignment_manifest_sha256,
            runner_version=runner_version,
            model_name=transition.namespace.model_name,
            runtime_version=transition.namespace.runtime_version,
            budget=budget,
            budget_sha256=budget.digest,
            created_seq=created_seq,
        )
        if self._plan_verifier is None:
            raise RuntimeError("no trusted outcome-before plan verifier is installed")
        try:
            verified = bool(self._plan_verifier(plan))
        except Exception as exc:
            raise RuntimeError("trusted probe-plan verification failed") from exc
        if not verified:
            raise ValueError("trusted probe-plan verifier rejected the assignment manifest")
        active_reservations = [
            item for item in self._state.reservations if item.state == "active"
        ]
        settled_attempts_by_plan = {
            reservation.plan_id: sum(
                attempt.plan_id == reservation.plan_id and attempt.state != "open"
                for attempt in self._state.attempts
            )
            for reservation in active_reservations
        }
        scoped_plans = [
            item for item in active_reservations
            if item.namespace_digest == transition.namespace.digest
        ]
        if len(scoped_plans) >= self._state.capacity_policy.max_live_plans_per_namespace:
            raise RuntimeError("probe-plan capacity is exhausted for this namespace")
        attempts_per_active_plan = {
            item.plan_id: sum(
                attempt.plan_id == item.plan_id
                for attempt in self._state.attempts
            )
            for item in active_reservations
        }
        remaining_attempt_slots = sum(
            6 - attempts_per_active_plan[item.plan_id]
            for item in active_reservations
        )
        if len(self._state.attempts) + remaining_attempt_slots + 6 > (
            self._state.capacity_policy.max_attempt_records
        ):
            raise RuntimeError("attempt capacity reservation would exceed its hard cap")
        materialized_receipts, remaining_receipt_slots = (
            _receipt_record_capacity_usage(
                self._state.attempts,
                (item.plan_id for item in active_reservations),
            )
        )
        if materialized_receipts + remaining_receipt_slots + 24 > (
            self._state.capacity_policy.max_receipt_records
        ):
            raise RuntimeError("receipt capacity reservation would exceed its hard cap")
        if len(self._state.used_roots) + sum(
            3 * (6 - settled_attempts_by_plan[item.plan_id])
            for item in active_reservations
        ) + 18 > self._state.capacity_policy.max_consumed_root_ids:
            raise RuntimeError(
                "physical-root lifetime reservation would exceed its hard cap"
            )
        if len(self._state.used_receipts) + sum(
            3 * (6 - settled_attempts_by_plan[item.plan_id])
            for item in active_reservations
        ) + 18 > self._state.capacity_policy.max_consumed_receipt_ids:
            raise RuntimeError(
                "receipt-id lifetime reservation would exceed its hard cap"
            )
        reservation = PlanCapacityReservationV2(
            reservation_id=_opaque_id("pr", plan.plan_id),
            plan_id=plan.plan_id,
            namespace_digest=plan.namespace_digest,
            created_seq=created_seq,
        )
        assessment = recompute_assessment(plan, (), revision_seq=created_seq)
        self._install(
            self._next_state(
                plans=(*self._state.plans, plan),
                reservations=(*self._state.reservations, reservation),
                assessments=(*self._state.assessments, assessment),
                used_edge_epochs=used_edge_epochs,
                used_unit_commitments=used_unit_commitments,
            )
        )
        return plan

    @_atomic_bank_update
    def open_next_attempt(
        self,
        plan_id: str,
        assignment: AssignmentReceiptV2,
        runner_lease: RunnerLeaseGrantV1,
    ) -> ProbeAttemptV3:
        plan = self.plans[plan_id]
        if plan.transition_id in self._harmful_transition_ids():
            raise ValueError(
                "harmful scientific transition cannot continue through another epoch"
            )
        assignment = AssignmentReceiptV2.model_validate(
            assignment.model_dump(mode="python")
        )
        runner_lease = RunnerLeaseGrantV1.model_validate(
            runner_lease.model_dump(mode="python")
        )
        plan_attempts = [item for item in self._state.attempts if item.plan_id == plan_id]
        assessment = self.assessments[plan_id]
        ordinal = next_allowed_ordinal(plan, plan_attempts, assessment)
        if ordinal is None:
            raise ValueError("probe plan cannot open another attempt")
        unit = plan.units[ordinal]
        joins = (
            assignment.plan_id == plan.plan_id,
            assignment.plan_sha256 == plan.digest,
            assignment.ordinal == ordinal,
            assignment.unit_commitment == unit.unit_commitment,
            assignment.arm_order == unit.arm_order,
            assignment.assignment_manifest_sha256 == plan.assignment_manifest_sha256,
            assignment.without_replacement_index == ordinal,
        )
        if not all(joins):
            raise ValueError("assignment receipt differs from the frozen plan ordinal")
        if any(
            item.assignment.assignment_receipt_id == assignment.assignment_receipt_id
            for item in self._state.attempts
        ):
            raise ValueError("assignment receipt has already been consumed")
        if self._assignment_verifier is None:
            raise RuntimeError("no trusted assignment receipt verifier is installed")
        try:
            verified = bool(self._assignment_verifier(assignment, plan))
        except Exception as exc:
            raise RuntimeError("trusted assignment verification failed") from exc
        if not verified:
            raise ValueError("trusted assignment verifier rejected the receipt")
        expected_attempt_id = _opaque_id("at", {"plan": plan_id, "ordinal": ordinal})
        lease_joins = (
            runner_lease.attempt_id == expected_attempt_id,
            runner_lease.plan_id == plan.plan_id,
            runner_lease.ordinal == ordinal,
            runner_lease.assignment_receipt_sha256 == _sha256(assignment),
            runner_lease.scheduled_arm_order == assignment.arm_order,
            runner_lease.fencing_generation == 1,
        )
        if not all(lease_joins):
            raise ValueError("runner lease differs from the exact frozen attempt")
        if any(
            item.runner_lease.lease_id == runner_lease.lease_id
            or item.runner_lease.runner_lease_token_sha256
            == runner_lease.runner_lease_token_sha256
            for item in self._state.attempts
        ):
            raise ValueError("runner lease or token has already been consumed")
        if self._runner_lease_verifier is None:
            raise RuntimeError("no trusted runner lease verifier is installed")
        try:
            lease_verified = bool(
                self._runner_lease_verifier(runner_lease, assignment, plan)
            )
        except Exception as exc:
            raise RuntimeError("trusted runner lease verification failed") from exc
        if not lease_verified:
            raise ValueError("trusted runner lease verifier rejected the grant")
        created_seq = self._state.event_seq + 1
        attempt = ProbeAttemptV3(
            attempt_id=expected_attempt_id,
            plan_id=plan_id,
            ordinal=ordinal,
            state="open",
            assignment=assignment,
            runner_lease=runner_lease,
            opened_seq=created_seq,
        )
        attempts = (*self._state.attempts, attempt)
        new_assessment = recompute_assessment(
            plan,
            [item for item in attempts if item.plan_id == plan_id],
            revision_seq=created_seq,
        )
        assessments = tuple(
            new_assessment if item.plan_id == plan_id else item
            for item in self._state.assessments
        )
        self._install(self._next_state(attempts=attempts, assessments=assessments))
        return attempt

    def _receipt_join_reason(
        self,
        *,
        plan: ProbePlanV2,
        attempt: ProbeAttemptV3,
        pair_receipt: PairExecutionReceiptV2,
        receipt: ArmReceiptV2,
        arm: Literal["source", "target"],
    ) -> str | None:
        transition = self._transition(plan.transition_id, plan.owner_kind)
        composition_id = (
            transition.source_composition_id if arm == "source"
            else transition.target_composition_id
        )
        composition = self.compositions[composition_id]
        expected_artifact = (
            plan.source_artifact_sha256 if arm == "source"
            else plan.target_artifact_sha256
        )
        expected_direct = (
            (
                transition.from_revision_id if arm == "source"
                else transition.to_revision_id,
            )
            if isinstance(transition, DirectFactorTransitionV2)
            else ()
        )
        expected_support_id = (
            transition.binding_proof_id
            if isinstance(transition, DirectFactorTransitionV2)
            else transition.transition_id
        )
        expected_position = (
            0
            if (
                (pair_receipt.observed_arm_order == "AB" and arm == "source")
                or (pair_receipt.observed_arm_order == "BA" and arm == "target")
            )
            else 1
        )
        checks = (
            (receipt.plan_id == plan.plan_id, "receipt_plan_mismatch"),
            (receipt.ordinal == attempt.ordinal, "receipt_ordinal_mismatch"),
            (receipt.arm == arm, "receipt_arm_mismatch"),
            (
                receipt.observed_arm_order == pair_receipt.observed_arm_order,
                "observed_arm_order_mismatch",
            ),
            (receipt.arm_position == expected_position, "arm_position_mismatch"),
            (
                receipt.pair_execution_receipt_sha256 == pair_receipt.digest,
                "pair_execution_receipt_mismatch",
            ),
            (receipt.unit_commitment == attempt.assignment.unit_commitment, "receipt_unit_mismatch"),
            (
                receipt.assignment_receipt_sha256 == _sha256(attempt.assignment),
                "receipt_assignment_mismatch",
            ),
            (receipt.namespace_digest == plan.namespace_digest, "receipt_namespace_mismatch"),
            (receipt.composition_id == composition_id, "receipt_composition_mismatch"),
            (receipt.assigned_artifact_sha256 == expected_artifact, "assigned_hash_mismatch"),
            (receipt.materialized_artifact_sha256 == expected_artifact, "materialized_hash_mismatch"),
            (receipt.selected_artifact_sha256 == expected_artifact, "selected_hash_mismatch"),
            (receipt.loaded_artifact_sha256 == expected_artifact, "loaded_hash_mismatch"),
            (
                tuple(sorted(receipt.loaded_binding_ids))
                == tuple(sorted(composition.binding_map.values())),
                "loaded_binding_mismatch",
            ),
            (
                tuple(receipt.activated_direct_factor_revision_ids) == expected_direct,
                "direct_activation_mismatch",
            ),
            (receipt.binding_proof_id == expected_support_id, "binding_proof_mismatch"),
            (receipt.model_name == plan.model_name, "receipt_model_mismatch"),
            (receipt.runtime_version == plan.runtime_version, "receipt_runtime_mismatch"),
            (receipt.budget_sha256 == plan.budget_sha256, "receipt_budget_mismatch"),
            (receipt.usage.within(plan.budget), "budget_violation"),
        )
        for passed, reason in checks:
            if not passed:
                return reason
        if self._arm_receipt_verifier is None:
            return "missing_trusted_receipt_verifier"
        try:
            valid = bool(self._arm_receipt_verifier(receipt, plan, attempt.assignment))
        except Exception:
            valid = False
        return None if valid else "untrusted_execution_receipt"

    def _candidate_snapshot(
        self,
        *,
        assessment: EdgeAssessmentV2,
        head: DeploymentHeadV2,
    ) -> str:
        plan = self.plans[assessment.plan_id]
        transition = self._transition(plan.transition_id, plan.owner_kind)
        target = self.compositions[transition.target_composition_id]
        dependencies = tuple(
            sorted(
                (slot, self.factors[factor_id])
                for slot, factor_id in target.binding_map.items()
            )
        )
        return _sha256(
            {
                "plan": plan,
                "assessment": assessment,
                "transition": transition,
                "target": target,
                "dependencies": dependencies,
                "namespace": transition.namespace,
                "capacity_policy": self._state.capacity_policy,
                "incumbent_head": head,
            }
        )

    def _sync_gate_opportunities(
        self,
        *,
        assessments: Sequence[EdgeAssessmentV2],
        heads: Sequence[DeploymentHeadV2] | None = None,
        existing: Sequence[GateOpportunityV2] | None = None,
        event_seq: int,
    ) -> tuple[GateOpportunityV2, ...]:
        head_by_slot = {
            item.deployment_slot_id: item
            for item in (heads if heads is not None else self._state.deployment_heads)
        }
        result = list(existing if existing is not None else self._state.gate_opportunities)
        harmful_transition_ids = self._harmful_transition_ids(assessments)
        plan_by_id = self.plans
        # Revoke stale authority before considering any new opportunity.  In
        # particular, an opportunity cannot survive a head move away from the
        # exact source composition of its scientific transition.
        for index, opportunity in enumerate(result):
            if opportunity.state != "pending":
                continue
            plan = plan_by_id.get(opportunity.plan_id)
            if plan is None:
                continue
            transition = self._transition(plan.transition_id, plan.owner_kind)
            head = head_by_slot.get(opportunity.deployment_slot_id)
            if (
                transition.transition_id in harmful_transition_ids
                or head is None
                or head.state != "active"
                or head.active_snapshot_id is None
                or head.active_composition_id != transition.source_composition_id
            ):
                result[index] = opportunity.model_copy(update={"state": "revoked"})
        by_plan = {
            item.plan_id: item for item in result if item.state == "pending"
        }
        for assessment in assessments:
            plan = self.plans.get(assessment.plan_id)
            if plan is None:
                continue
            transition = self._transition(plan.transition_id, plan.owner_kind)
            slot_id = self.deployment_slot_id(transition.namespace)
            head = head_by_slot.get(slot_id)
            eligible = bool(
                assessment.settled
                and assessment.label == "candidate"
                and assessment.n_open == 0
                and head is not None
                and head.state == "active"
                and head.active_snapshot_id is not None
                and head.active_composition_id == transition.source_composition_id
                and transition.transition_id not in harmful_transition_ids
            )
            pending = by_plan.get(plan.plan_id)
            if not eligible:
                if pending is not None:
                    replacement = pending.model_copy(update={"state": "revoked"})
                    result = [
                        replacement if item.opportunity_id == pending.opportunity_id else item
                        for item in result
                    ]
                continue
            assert head is not None and head.active_snapshot_id is not None
            candidate_snapshot = self._candidate_snapshot(
                assessment=assessment,
                head=head,
            )
            if pending is not None:
                if (
                    pending.candidate_snapshot_sha256 == candidate_snapshot
                    and pending.settled_assessment_sha256 == assessment.digest
                    and pending.incumbent_snapshot_id == head.active_snapshot_id
                    and pending.expiry_seq >= event_seq
                ):
                    continue
                revoked = pending.model_copy(update={"state": "revoked"})
                result = [
                    revoked if item.opportunity_id == pending.opportunity_id else item
                    for item in result
                ]
            opportunity = GateOpportunityV2(
                opportunity_id=_opaque_id(
                    "go",
                    {
                        "plan": plan.plan_id,
                        "assessment": assessment.digest,
                        "candidate": candidate_snapshot,
                        "incumbent": head.active_snapshot_id,
                    },
                ),
                deployment_slot_id=slot_id,
                namespace_digest=plan.namespace_digest,
                transition_id=plan.transition_id,
                plan_id=plan.plan_id,
                settled_assessment_sha256=assessment.digest,
                candidate_snapshot_sha256=candidate_snapshot,
                incumbent_snapshot_id=head.active_snapshot_id,
                created_seq=event_seq,
                expiry_seq=(
                    event_seq
                    + self._state.capacity_policy.gate_opportunity_ttl_events
                ),
            )
            pending_in_namespace = sum(
                item.state == "pending"
                and item.namespace_digest == opportunity.namespace_digest
                for item in result
            )
            if pending_in_namespace >= (
                self._state.capacity_policy.max_pending_gate_per_namespace
            ):
                # Evidence remains settled, but the Bank never creates
                # authority beyond its hard pending-gate capacity.  A later
                # synchronization may admit it after capacity is released.
                continue
            if opportunity.opportunity_id not in {
                item.opportunity_id for item in result
            }:
                result.append(opportunity)
        return tuple(result)

    @_atomic_bank_update
    def cancel_open_attempt(
        self,
        attempt_id: str,
        receipt: AttemptCancellationReceiptV3,
    ) -> ProbeAttemptV3:
        """Cancel one exact open assignment at the trusted runner boundary.

        Cancellation consumes the frozen assignment and advances the attempt
        ordinal, but contributes no scientific vote.  Its authenticated runner
        journal prefix permanently consumes the terminal event root and the
        zero, one, or two physical arm roots that started before the crash.
        """

        attempt = self.attempts[attempt_id]
        receipt = AttemptCancellationReceiptV3.model_validate(
            receipt.model_dump(mode="python")
        )
        if attempt.state == "cancelled":
            if attempt.cancellation_receipt == receipt:
                return attempt
            raise ValueError("attempt already owns a different cancellation terminal")
        if attempt.state != "open":
            raise ValueError("only the exact open attempt can be cancelled")
        plan = self.plans[attempt.plan_id]
        assessment_before = self.assessments[plan.plan_id]
        if assessment_before.settled:
            raise ValueError("settled probe plan rejects late cancellation")
        joins = (
            receipt.attempt_id == attempt.attempt_id,
            receipt.plan_id == plan.plan_id,
            receipt.ordinal == attempt.ordinal,
            receipt.assignment_receipt_sha256 == _sha256(attempt.assignment),
            receipt.expected_opened_seq == attempt.opened_seq,
            receipt.expected_open_attempt_sha256 == _sha256(attempt),
            receipt.scheduled_arm_order == attempt.assignment.arm_order,
            receipt.runner_lease_sha256 == attempt.runner_lease.digest,
            receipt.runner_lease_token_sha256
            == attempt.runner_lease.runner_lease_token_sha256,
            receipt.runner_session_id == attempt.runner_lease.runner_session_id,
            receipt.journal_anchor_sha256
            == attempt.runner_lease.journal_anchor_sha256,
            receipt.fencing_generation == attempt.runner_lease.fencing_generation,
            receipt.next_fencing_generation == 2,
        )
        if not all(joins):
            raise ValueError("cancellation receipt differs from the exact open attempt")
        root_ids = (
            *(item.root_id for item in receipt.started_arm_roots),
            receipt.runner_event_root_sha256,
        )
        receipt_ids = (receipt.cancellation_id,)
        used_roots = dict(self._state.used_roots)
        used_receipts = dict(self._state.used_receipts)
        if any(item in used_roots for item in root_ids):
            raise ValueError("cancellation reuses a consumed physical/journal root")
        if any(item in used_receipts for item in receipt_ids):
            raise ValueError("cancellation receipt has already been consumed")
        if len(used_roots) + len(root_ids) > (
            self._state.capacity_policy.max_consumed_root_ids
        ):
            raise RuntimeError("consumed physical-root capacity is exhausted")
        if len(used_receipts) + len(receipt_ids) > (
            self._state.capacity_policy.max_consumed_receipt_ids
        ):
            raise RuntimeError("consumed receipt-id capacity is exhausted")
        if self._cancellation_verifier is None:
            raise RuntimeError("no trusted cancellation verifier is installed")
        try:
            verified = bool(self._cancellation_verifier(receipt, attempt, plan))
        except Exception as exc:
            raise RuntimeError("trusted cancellation verification failed") from exc
        if not verified:
            raise ValueError("trusted cancellation verifier rejected the receipt")

        next_seq = self._state.event_seq + 1
        cancelled_attempt = attempt.model_copy(
            update={
                "state": "cancelled",
                "disposition_reason": receipt.safe_failure_code,
                "cancellation_receipt": receipt,
                "presented_root_ids": root_ids,
                "presented_receipt_ids": receipt_ids,
                "settled_seq": next_seq,
            }
        )
        attempts = tuple(
            cancelled_attempt if item.attempt_id == attempt_id else item
            for item in self._state.attempts
        )
        assessment = recompute_assessment(
            plan,
            [item for item in attempts if item.plan_id == plan.plan_id],
            revision_seq=next_seq,
        )
        assessments = tuple(
            assessment if item.plan_id == plan.plan_id else item
            for item in self._state.assessments
        )
        reservations = tuple(
            item.model_copy(update={"state": "released", "released_seq": next_seq})
            if item.plan_id == plan.plan_id and assessment.settled
            else item
            for item in self._state.reservations
        )
        opportunities = self._sync_gate_opportunities(
            assessments=(assessment,),
            event_seq=next_seq,
        )
        self._install(
            self._next_state(
                attempts=attempts,
                assessments=assessments,
                reservations=reservations,
                gate_opportunities=opportunities,
                used_roots=tuple(
                    sorted(
                        {
                            **used_roots,
                            **{item: attempt.attempt_id for item in root_ids},
                        }.items()
                    )
                ),
                used_receipts=tuple(
                    sorted(
                        {
                            **used_receipts,
                            receipt.cancellation_id: attempt.attempt_id,
                        }.items()
                    )
                ),
            )
        )
        return cancelled_attempt

    @_atomic_bank_update
    def commit_attempt(
        self,
        attempt_id: str,
        source_receipt: ArmReceiptV2,
        target_receipt: ArmReceiptV2,
        pair_execution_receipt: PairExecutionReceiptV2,
    ) -> ProbeAttemptV3:
        attempt = self.attempts[attempt_id]
        if attempt.state != "open":
            raise ValueError("only the unique open attempt can be committed")
        plan = self.plans[attempt.plan_id]
        assessment_before = self.assessments[plan.plan_id]
        if assessment_before.settled:
            raise ValueError("settled probe plan rejects late execution receipts")
        source_receipt = ArmReceiptV2.model_validate(
            source_receipt.model_dump(mode="python")
        )
        target_receipt = ArmReceiptV2.model_validate(
            target_receipt.model_dump(mode="python")
        )
        pair_execution_receipt = PairExecutionReceiptV2.model_validate(
            pair_execution_receipt.model_dump(mode="python")
        )
        if self._pair_execution_receipt_verifier is None:
            raise RuntimeError(
                "no trusted paired-execution receipt verifier is installed"
            )
        try:
            pair_verified = bool(
                self._pair_execution_receipt_verifier(
                    pair_execution_receipt, attempt, plan
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "trusted paired-execution verification failed"
            ) from exc
        receipts = (source_receipt, target_receipt)
        expected_pair_root = paired_execution_root_v2(
            assignment=attempt.assignment,
            pair_receipt=pair_execution_receipt,
        )
        pair_roots = {
            source_receipt.paired_execution_root_sha256,
            target_receipt.paired_execution_root_sha256,
        }
        roots = (
            source_receipt.root_id,
            target_receipt.root_id,
            pair_execution_receipt.runner_event_root_sha256,
        )
        receipt_ids = (
            source_receipt.receipt_id,
            target_receipt.receipt_id,
            pair_execution_receipt.pair_receipt_id,
        )
        used_roots = dict(self._state.used_roots)
        used_receipts = dict(self._state.used_receipts)
        if pair_execution_receipt.runner_event_root_sha256 in used_roots:
            raise ValueError("pair terminal reuses a consumed raw journal root")
        if pair_execution_receipt.pair_receipt_id in used_receipts:
            raise ValueError("pair terminal receipt has already been consumed")
        new_root_ids = {item for item in roots if item not in used_roots}
        new_receipt_ids = {item for item in receipt_ids if item not in used_receipts}
        if len(used_roots) + len(new_root_ids) > (
            self._state.capacity_policy.max_consumed_root_ids
        ):
            raise RuntimeError("consumed physical-root capacity is exhausted")
        if len(used_receipts) + len(new_receipt_ids) > (
            self._state.capacity_policy.max_consumed_receipt_ids
        ):
            raise RuntimeError("consumed receipt-id capacity is exhausted")
        reason: str | None = None
        if len(set(roots)) != 3:
            reason = "duplicate_arm_or_pair_root"
        elif pair_roots != {expected_pair_root}:
            reason = "paired_execution_root_mismatch"
        elif not (
            pair_execution_receipt.plan_id == plan.plan_id
            and pair_execution_receipt.ordinal == attempt.ordinal
            and pair_execution_receipt.assignment_receipt_sha256
            == _sha256(attempt.assignment)
            and pair_execution_receipt.expected_open_attempt_sha256
            == _sha256(attempt)
            and pair_execution_receipt.scheduled_arm_order
            == attempt.assignment.arm_order
            and pair_execution_receipt.runner_lease_sha256
            == attempt.runner_lease.digest
            and pair_execution_receipt.runner_lease_token_sha256
            == attempt.runner_lease.runner_lease_token_sha256
            and pair_execution_receipt.runner_session_id
            == attempt.runner_lease.runner_session_id
            and pair_execution_receipt.journal_anchor_sha256
            == attempt.runner_lease.journal_anchor_sha256
            and pair_execution_receipt.fencing_generation
            == attempt.runner_lease.fencing_generation
            and pair_execution_receipt.source_root_id == source_receipt.root_id
            and pair_execution_receipt.target_root_id == target_receipt.root_id
        ):
            reason = "pair_execution_attempt_fence_mismatch"
        elif not pair_verified:
            reason = "unverified_pair_execution_receipt"
        elif pair_execution_receipt.observed_arm_order != attempt.assignment.arm_order:
            reason = "physical_arm_order_violation"
        elif source_receipt.observed_arm_order != target_receipt.observed_arm_order:
            reason = "inconsistent_observed_arm_order"
        elif source_receipt.arm_position == target_receipt.arm_position:
            reason = "duplicate_arm_position"
        elif len(set(receipt_ids)) != 3:
            reason = "duplicate_receipt_id"
        elif any(item in used_roots for item in roots):
            reason = "reused_physical_root"
        elif any(item in used_receipts for item in receipt_ids):
            reason = "reused_receipt_id"
        else:
            for arm, receipt in (("source", source_receipt), ("target", target_receipt)):
                reason = self._receipt_join_reason(
                    plan=plan,
                    attempt=attempt,
                    pair_receipt=pair_execution_receipt,
                    receipt=receipt,
                    arm=arm,
                )
                if reason is not None:
                    break
        next_seq = self._state.event_seq + 1
        if reason is None:
            for item in roots:
                used_roots[item] = attempt.attempt_id
            for item in receipt_ids:
                used_receipts[item] = attempt.attempt_id
            non_algorithmic = any(
                item.execution_class in {"infrastructure_failure", "harness_failure"}
                for item in receipts
            )
            settled_attempt = attempt.model_copy(
                update={
                    "state": "incomplete" if non_algorithmic else "complete",
                    "pair_execution_receipt": pair_execution_receipt,
                    "source_receipt": source_receipt,
                    "target_receipt": target_receipt,
                    "presented_root_ids": roots,
                    "presented_receipt_ids": receipt_ids,
                    "disposition_reason": (
                        "non_algorithm_failure" if non_algorithmic else "complete"
                    ),
                    "settled_seq": next_seq,
                }
            )
        else:
            # New, otherwise-unclaimed physical identifiers remain consumed even
            # when the producer/body fails verification.
            for item in roots:
                if item not in used_roots:
                    used_roots[item] = attempt.attempt_id
            for item in receipt_ids:
                if item not in used_receipts:
                    used_receipts[item] = attempt.attempt_id
            settled_attempt = attempt.model_copy(
                update={
                    "state": "quarantine",
                    "pair_execution_receipt": pair_execution_receipt,
                    "source_receipt": source_receipt,
                    "target_receipt": target_receipt,
                    "presented_root_ids": roots,
                    "presented_receipt_ids": receipt_ids,
                    "disposition_reason": reason,
                    "settled_seq": next_seq,
                }
            )
        attempts = tuple(
            settled_attempt if item.attempt_id == attempt_id else item
            for item in self._state.attempts
        )
        assessment = recompute_assessment(
            plan,
            [item for item in attempts if item.plan_id == plan.plan_id],
            revision_seq=next_seq,
        )
        assessments = tuple(
            assessment if item.plan_id == plan.plan_id else item
            for item in self._state.assessments
        )
        reservations = tuple(
            item.model_copy(update={"state": "released", "released_seq": next_seq})
            if item.plan_id == plan.plan_id and assessment.settled
            else item
            for item in self._state.reservations
        )
        opportunities = self._sync_gate_opportunities(
            assessments=(assessment,),
            event_seq=next_seq,
        )
        candidate = self._next_state(
            attempts=attempts,
            assessments=assessments,
            reservations=reservations,
            gate_opportunities=opportunities,
            used_roots=tuple(sorted(used_roots.items())),
            used_receipts=tuple(sorted(used_receipts.items())),
        )
        self._install(candidate)
        return settled_attempt

    @_atomic_bank_update
    def register_base_snapshot(
        self,
        receipt: BaseSnapshotReceiptV2,
    ) -> DeploymentSnapshotV2:
        receipt = BaseSnapshotReceiptV2.model_validate(
            receipt.model_dump(mode="python")
        )
        if receipt.emitted_seq != self._state.event_seq + 1:
            raise ValueError("base snapshot receipt must be emitted for the next event")
        composition = self.compositions.get(receipt.composition_id)
        if composition is None:
            raise ValueError("base snapshot composition does not exist")
        if not self._composition_can_receive_non_action_authority(
            self._state,
            composition,
            before_seq=receipt.emitted_seq,
        ):
            raise ValueError(
                "base snapshot cannot admit an uncommitted proposal carrier"
            )
        slot_id = self.deployment_slot_id(composition.namespace)
        if receipt.deployment_slot_id != slot_id:
            raise ValueError("base snapshot crosses its deployment namespace")
        if receipt.namespace_digest != composition.namespace.digest:
            raise ValueError("base snapshot namespace digest mismatch")
        if receipt.loaded_artifact_sha256 != composition.artifact_sha256:
            raise ValueError("base snapshot did not load the registered artifact")
        binding_map_sha256 = _sha256(sorted(composition.binding_map.items()))
        if receipt.binding_map_sha256 != binding_map_sha256:
            raise ValueError("base snapshot binding map mismatch")
        if slot_id in self.deployment_heads:
            raise ValueError("deployment slot already has a base/active head")
        if len(self._state.deployment_heads) >= (
            self._state.capacity_policy.max_deployment_slots
        ):
            raise RuntimeError("deployment-slot capacity is exhausted")
        if self._base_snapshot_verifier is None:
            raise RuntimeError("no trusted base-snapshot verifier is installed")
        try:
            verified = bool(self._base_snapshot_verifier(receipt, self._state))
        except Exception as exc:
            raise RuntimeError("trusted base-snapshot verification failed") from exc
        if not verified:
            raise ValueError("trusted base-snapshot verifier rejected the receipt")
        next_seq = self._state.event_seq + 1
        scientific_snapshot = _sha256(
            {
                "base_receipt": receipt,
                "composition": composition,
                "capacity_policy": self._state.capacity_policy,
            }
        )
        snapshot = DeploymentSnapshotV2(
            snapshot_id=_opaque_id("dsnap", receipt.attestation_sha256),
            deployment_slot_id=slot_id,
            namespace_digest=composition.namespace.digest,
            composition_id=composition.composition_id,
            transition_id=None,
            artifact_sha256=composition.artifact_sha256,
            binding_map_sha256=binding_map_sha256,
            accepted_gate_decision_id=None,
            accepted_gate_receipt_sha256=None,
            scientific_snapshot_sha256=scientific_snapshot,
            predecessor_snapshot_id=None,
            is_base_fallback=True,
            created_seq=next_seq,
        )
        head = DeploymentHeadV2(
            deployment_slot_id=slot_id,
            namespace_digest=composition.namespace.digest,
            active_snapshot_id=snapshot.snapshot_id,
            active_composition_id=composition.composition_id,
            active_transition_id=None,
            accepted_gate_receipt_sha256=None,
            active_snapshot_sha256=_sha256(snapshot),
            predecessor_snapshot_id=None,
            rollback_lease_expiry_seq=None,
            base_fallback_snapshot_id=snapshot.snapshot_id,
            generation=0,
            state="active",
            updated_seq=next_seq,
        )
        heads = (*self._state.deployment_heads, head)
        opportunities = self._sync_gate_opportunities(
            assessments=self._state.assessments,
            heads=heads,
            event_seq=next_seq,
        )
        self._install(
            self._next_state(
                base_receipts=(*self._state.base_receipts, receipt),
                deployment_snapshots=(*self._state.deployment_snapshots, snapshot),
                deployment_heads=heads,
                gate_opportunities=opportunities,
            )
        )
        return snapshot

    @_atomic_bank_update
    def apply_gate(self, receipt: GateReceiptV2) -> DeploymentHeadV2 | None:
        receipt = GateReceiptV2.model_validate(receipt.model_dump(mode="python"))
        opportunities = {
            item.opportunity_id: item for item in self._state.gate_opportunities
        }
        opportunity = opportunities.get(receipt.opportunity_id)
        if opportunity is None or opportunity.state != "pending":
            raise ValueError("gate receipt does not consume one pending opportunity")
        if self._state.event_seq > opportunity.expiry_seq:
            raise ValueError("gate opportunity has expired")
        if receipt.emitted_seq != self._state.event_seq + 1:
            raise ValueError("gate receipt must be emitted for the next event")
        assessment = self.assessments[opportunity.plan_id]
        if not (
            assessment.settled
            and assessment.label == "candidate"
            and assessment.n_open == 0
            and assessment.digest == opportunity.settled_assessment_sha256
        ):
            raise ValueError("gate opportunity is no longer locally eligible")
        plan = self.plans[opportunity.plan_id]
        transition = self._transition(plan.transition_id, plan.owner_kind)
        if transition.transition_id in self._harmful_transition_ids():
            raise ValueError(
                "harmful scientific transition cannot be promoted by another epoch"
            )
        if any(
            item.plan_id == plan.plan_id and item.state == "open"
            for item in self._state.attempts
        ):
            raise ValueError("gate cannot consume a plan with an open attempt")
        head = self.deployment_heads[opportunity.deployment_slot_id]
        snapshots = {
            item.snapshot_id: item for item in self._state.deployment_snapshots
        }
        incumbent = snapshots[opportunity.incumbent_snapshot_id]
        current_candidate = self._candidate_snapshot(
            assessment=assessment,
            head=head,
        )
        expected = (
            receipt.deployment_slot_id == opportunity.deployment_slot_id,
            head.state == "active",
            head.active_snapshot_id == opportunity.incumbent_snapshot_id,
            head.active_composition_id == transition.source_composition_id,
            receipt.candidate_snapshot_sha256
            == opportunity.candidate_snapshot_sha256
            == current_candidate,
            receipt.settled_assessment_sha256 == assessment.digest,
            receipt.incumbent_snapshot_sha256 == _sha256(incumbent),
            receipt.aggregate_summary_sha256 == _sha256(assessment.strict_summary),
        )
        if not all(expected):
            raise ValueError("gate receipt differs from the frozen candidate/incumbent closure")
        if any(item.decision_id == receipt.decision_id for item in self._state.gate_receipts):
            raise ValueError("gate decision identifier has already been consumed")
        if len(self._state.gate_receipts) >= self._state.capacity_policy.max_gate_receipts:
            raise RuntimeError("gate-receipt capacity is exhausted")
        if self._gate_verifier is None:
            raise RuntimeError("no trusted strict gate verifier is installed")
        try:
            verified = bool(self._gate_verifier(receipt, self._state))
        except Exception as exc:
            raise RuntimeError("trusted strict gate verification failed") from exc
        if not verified:
            raise ValueError("trusted strict gate verifier rejected the receipt")
        next_seq = self._state.event_seq + 1
        terminal_state: OpportunityState = "consumed" if receipt.accepted else "rejected"
        updated_opportunity = opportunity.model_copy(
            update={"state": terminal_state, "decision_id": receipt.decision_id}
        )
        opportunity_rows = tuple(
            updated_opportunity if item.opportunity_id == opportunity.opportunity_id else item
            for item in self._state.gate_opportunities
        )
        if not receipt.accepted:
            self._install(
                self._next_state(
                    gate_opportunities=opportunity_rows,
                    gate_receipts=(*self._state.gate_receipts, receipt),
                )
            )
            return None
        target = self.compositions[transition.target_composition_id]
        if len(self._state.deployment_snapshots) + 1 > (
            self._state.capacity_policy.max_hot_compositions_per_namespace * max(
                1, len(self._state.deployment_heads)
            )
        ):
            capacity_rejected = updated_opportunity.model_copy(
                update={"state": "capacity_rejected"}
            )
            opportunity_rows = tuple(
                capacity_rejected if item.opportunity_id == opportunity.opportunity_id else item
                for item in opportunity_rows
            )
            self._install(
                self._next_state(
                    gate_opportunities=opportunity_rows,
                    gate_receipts=(*self._state.gate_receipts, receipt),
                )
            )
            return None
        gate_receipt_sha = _sha256(receipt)
        snapshot = DeploymentSnapshotV2(
            snapshot_id=_opaque_id("dsnap", {"decision": receipt.decision_id}),
            deployment_slot_id=head.deployment_slot_id,
            namespace_digest=head.namespace_digest,
            composition_id=target.composition_id,
            transition_id=transition.transition_id,
            artifact_sha256=target.artifact_sha256,
            binding_map_sha256=_sha256(sorted(target.binding_map.items())),
            accepted_gate_decision_id=receipt.decision_id,
            accepted_gate_receipt_sha256=gate_receipt_sha,
            scientific_snapshot_sha256=opportunity.candidate_snapshot_sha256,
            predecessor_snapshot_id=head.active_snapshot_id,
            is_base_fallback=False,
            created_seq=next_seq,
        )
        new_head = DeploymentHeadV2(
            deployment_slot_id=head.deployment_slot_id,
            namespace_digest=head.namespace_digest,
            active_snapshot_id=snapshot.snapshot_id,
            active_composition_id=target.composition_id,
            active_transition_id=transition.transition_id,
            accepted_gate_receipt_sha256=gate_receipt_sha,
            active_snapshot_sha256=_sha256(snapshot),
            predecessor_snapshot_id=head.active_snapshot_id,
            rollback_lease_expiry_seq=(
                next_seq + self._state.capacity_policy.rollback_lease_events
            ),
            base_fallback_snapshot_id=head.base_fallback_snapshot_id,
            generation=head.generation + 1,
            state="active",
            updated_seq=next_seq,
        )
        heads = tuple(
            new_head if item.deployment_slot_id == head.deployment_slot_id else item
            for item in self._state.deployment_heads
        )
        # The successful head swap consumes all authority derived from the old
        # incumbent in this deployment slot.  Revoke sibling opportunities in
        # the same atomic state installation so none can race the new head.
        opportunity_rows = tuple(
            item.model_copy(update={"state": "revoked"})
            if (
                item.opportunity_id != opportunity.opportunity_id
                and item.deployment_slot_id == head.deployment_slot_id
                and item.state == "pending"
            )
            else item
            for item in opportunity_rows
        )
        self._install(
            self._next_state(
                gate_opportunities=opportunity_rows,
                gate_receipts=(*self._state.gate_receipts, receipt),
                deployment_snapshots=(*self._state.deployment_snapshots, snapshot),
                deployment_heads=heads,
            )
        )
        return new_head

    @_atomic_bank_update
    def apply_rollback(self, trigger: RollbackTriggerV2) -> RollbackRecordV2:
        trigger = RollbackTriggerV2.model_validate(trigger.model_dump(mode="python"))
        head = self.deployment_heads.get(trigger.deployment_slot_id)
        if head is None or head.state != "active" or head.active_snapshot_id is None:
            raise ValueError("rollback trigger does not name an active deployment head")
        if (
            trigger.expected_head_generation != head.generation
            or trigger.active_snapshot_id != head.active_snapshot_id
        ):
            raise ValueError("rollback trigger is stale for the active head")
        if trigger.emitted_seq != self._state.event_seq + 1:
            raise ValueError("rollback trigger must be emitted for the next event")
        if any(item.trigger_id == trigger.trigger_id for item in self._state.rollback_triggers):
            raise ValueError("rollback trigger has already been consumed")
        if self._rollback_verifier is None:
            raise RuntimeError("no trusted TRAIN rollback verifier is installed")
        try:
            verified = bool(self._rollback_verifier(trigger, self._state))
        except Exception as exc:
            raise RuntimeError("trusted rollback verification failed") from exc
        if not verified:
            raise ValueError("trusted rollback verifier rejected the trigger")
        snapshots = {
            item.snapshot_id: item for item in self._state.deployment_snapshots
        }
        old_snapshot = snapshots[head.active_snapshot_id]
        restored: DeploymentSnapshotV2 | None = None
        disposition: Literal["restored_predecessor", "restored_base", "disabled"]
        if old_snapshot.predecessor_snapshot_id in snapshots:
            restored = snapshots[old_snapshot.predecessor_snapshot_id]
            disposition = "restored_predecessor"
        elif head.base_fallback_snapshot_id in snapshots:
            restored = snapshots[head.base_fallback_snapshot_id]
            disposition = "restored_base"
        else:
            disposition = "disabled"
        next_seq = self._state.event_seq + 1
        record = RollbackRecordV2(
            rollback_id=_opaque_id(
                "rb", {"trigger": trigger.trigger_id, "generation": head.generation}
            ),
            trigger_id=trigger.trigger_id,
            deployment_slot_id=head.deployment_slot_id,
            old_snapshot_id=head.active_snapshot_id,
            restored_snapshot_id=restored.snapshot_id if restored else None,
            old_generation=head.generation,
            new_generation=head.generation + 1,
            disposition=disposition,
            created_seq=next_seq,
        )
        if restored is None:
            new_head = DeploymentHeadV2(
                deployment_slot_id=head.deployment_slot_id,
                namespace_digest=head.namespace_digest,
                active_snapshot_id=None,
                active_composition_id=None,
                active_transition_id=None,
                accepted_gate_receipt_sha256=None,
                active_snapshot_sha256=None,
                predecessor_snapshot_id=None,
                rollback_lease_expiry_seq=None,
                base_fallback_snapshot_id=head.base_fallback_snapshot_id,
                generation=head.generation + 1,
                state="disabled",
                updated_seq=next_seq,
            )
        else:
            new_head = DeploymentHeadV2(
                deployment_slot_id=head.deployment_slot_id,
                namespace_digest=head.namespace_digest,
                active_snapshot_id=restored.snapshot_id,
                active_composition_id=restored.composition_id,
                active_transition_id=restored.transition_id,
                accepted_gate_receipt_sha256=restored.accepted_gate_receipt_sha256,
                active_snapshot_sha256=_sha256(restored),
                predecessor_snapshot_id=None,
                rollback_lease_expiry_seq=None,
                base_fallback_snapshot_id=head.base_fallback_snapshot_id,
                generation=head.generation + 1,
                state="active",
                updated_seq=next_seq,
            )
        heads = tuple(
            new_head if item.deployment_slot_id == head.deployment_slot_id else item
            for item in self._state.deployment_heads
        )
        harmful_edge_key: str | None = None
        if trigger.kind == "train_monitor_harm" and old_snapshot.transition_id:
            old_transition = {
                **self.direct_transitions,
                **self.whole_transitions,
            }.get(old_snapshot.transition_id)
            if old_transition is not None:
                harmful_edge_key = self._canonical_scientific_edge_sha256(
                    self._state,
                    old_transition,
                )
        gate_opportunities: list[GateOpportunityV2] = []
        for opportunity in self._state.gate_opportunities:
            revoke = False
            if opportunity.state == "pending":
                opportunity_plan = self.plans.get(opportunity.plan_id)
                if (
                    harmful_edge_key is not None
                    and opportunity_plan is not None
                    and opportunity_plan.canonical_scientific_edge_key_sha256
                    == harmful_edge_key
                ):
                    revoke = True
                if opportunity.deployment_slot_id == head.deployment_slot_id:
                    opportunity_transition = (
                        self._transition(
                            opportunity_plan.transition_id,
                            opportunity_plan.owner_kind,
                        )
                        if opportunity_plan is not None
                        else None
                    )
                    if (
                        new_head.state != "active"
                        or opportunity_transition is None
                        or opportunity_transition.source_composition_id
                        != new_head.active_composition_id
                    ):
                        revoke = True
            gate_opportunities.append(
                opportunity.model_copy(update={"state": "revoked"})
                if revoke
                else opportunity
            )
        self._install(
            self._next_state(
                rollback_triggers=(*self._state.rollback_triggers, trigger),
                rollback_records=(*self._state.rollback_records, record),
                deployment_heads=heads,
                gate_opportunities=tuple(gate_opportunities),
            )
        )
        return record

    @_linearized_bank_read
    def retrieve(
        self,
        namespace: ExecutionNamespace,
        *,
        limit: int = 3,
    ) -> list[CompositionRevisionV2]:
        namespace = ExecutionNamespace.model_validate(namespace.model_dump(mode="python"))
        if limit < 0:
            raise ValueError("retrieval limit must be non-negative")
        heads = [
            item for item in self._state.deployment_heads
            if item.namespace_digest == namespace.digest and item.state == "active"
        ]
        heads.sort(key=lambda item: (-item.generation, item.deployment_slot_id))
        return [
            self.compositions[item.active_composition_id]
            for item in heads[:limit]
            if item.active_composition_id is not None
        ]

    @staticmethod
    def _proposal_counter_witnesses(
        state: FactorBankStateV2,
        *,
        cell_sha256: str,
        candidates: Sequence[PortableCandidateV1],
    ) -> tuple[CandidateCounterWitnessV1, ...]:
        """Project only current-slate rows from the rooted lifetime table."""

        table = {
            (item.cell_sha256, item.target_factor_key_sha256): item
            for item in state.proposal_lifetime_counters
        }
        witnesses: list[CandidateCounterWitnessV1] = []
        for candidate in sorted(
            candidates,
            key=lambda item: item.target_factor_key_sha256,
        ):
            counter = table.get(
                (cell_sha256, candidate.target_factor_key_sha256)
            )
            witnesses.append(
                counter.witness
                if counter is not None
                else CandidateCounterWitnessV1(
                    cell_sha256=cell_sha256,
                    target_factor_key_sha256=(
                        candidate.target_factor_key_sha256
                    ),
                )
            )
        return tuple(witnesses)

    def _proposal_lineage_niche(
        self,
        factor: FactorRevisionV2,
    ) -> LineageNicheV1:
        factor_key = self._factor_carrier_key_sha256(factor)
        provenance_owner = min(
            (
                item
                for item in self._state.factors
                if self._factor_carrier_key_sha256(item) == factor_key
            ),
            key=lambda item: (item.created_seq, item.revision_id),
        )
        chain = [provenance_owner]
        seen = {provenance_owner.revision_id}
        current = provenance_owner
        while current.parent_revision_id is not None:
            parent = self.factors.get(current.parent_revision_id)
            if parent is None or parent.revision_id in seen:
                raise ValueError("proposal target has invalid factor ancestry")
            if not (
                parent.namespace == provenance_owner.namespace
                and parent.logical_factor_id
                == provenance_owner.logical_factor_id
                and parent.carrier == provenance_owner.carrier
                and parent.locator == provenance_owner.locator
            ):
                raise ValueError("proposal target ancestry crosses its exact locus")
            chain.append(parent)
            seen.add(parent.revision_id)
            current = parent
        root = chain[-1]
        return LineageNicheV1(
            origin_branch=root.origin_branch,
            root_revision_id=root.revision_id,
            provenance_family_sha256=_sha256(
                {
                    "namespace": provenance_owner.namespace.digest,
                    "logical_factor": provenance_owner.logical_factor_id,
                    "carrier": provenance_owner.carrier,
                    "locator": provenance_owner.locator,
                    "root_revision": root.revision_id,
                    "ancestry": tuple(item.revision_id for item in reversed(chain)),
                }
            ),
            canonical_lineage_key_sha256=_sha256(
                {
                    "namespace": provenance_owner.namespace.digest,
                    "logical_factor": provenance_owner.logical_factor_id,
                    "carrier": provenance_owner.carrier,
                    "locator": provenance_owner.locator,
                    "origin_branch": root.origin_branch,
                    "canonical_ancestry": tuple(
                        self._factor_carrier_key_sha256(item)
                        for item in reversed(chain)
                    ),
                }
            ),
        )

    def _proposal_portable_signs(
        self,
        *,
        slot_id: str,
        from_revision_id: str,
        to_revision_id: str,
    ) -> tuple[PortableBackgroundSignV1, ...]:
        """Reduce authoritative lifetime edge evidence to one sign/background.

        A background cannot be counted twice through repeated plan epochs.  Any
        harm dominates; mixed benefit/null is conservatively null; benefit is
        portable only when no contradictory scientific terminal exists.
        """

        assessments_by_transition: dict[str, list[EdgeAssessmentV2]] = {}
        for assessment in self._state.assessments:
            assessments_by_transition.setdefault(
                assessment.transition_id, []
            ).append(assessment)
        tombstones_by_transition: dict[str, list[NegativeTombstoneV2]] = {}
        for tombstone in self._state.tombstones:
            tombstones_by_transition.setdefault(
                tombstone.subject_id, []
            ).append(tombstone)
        leaves_by_transition: dict[str, list[PortableEvidenceLeafV1]] = {}
        for leaf in self._state.portable_evidence_leaves:
            leaves_by_transition.setdefault(leaf.transition_id, []).append(leaf)
        rollback_harm_by_edge = self._rollback_harm_evidence_by_edge(
            self._state
        )
        by_background: dict[str, list[tuple[str, str]]] = {}
        requested_from = self.factors.get(from_revision_id)
        requested_to = self.factors.get(to_revision_id)
        if requested_from is None or requested_to is None:
            raise ValueError("portable proposal pair names a missing factor")
        requested_from_key = self._factor_carrier_key_sha256(requested_from)
        requested_to_key = self._factor_carrier_key_sha256(requested_to)
        for transition in self._state.direct_transitions:
            transition_from = self.factors[transition.from_revision_id]
            transition_to = self.factors[transition.to_revision_id]
            if not (
                transition.slot_id == slot_id
                and self._factor_carrier_key_sha256(transition_from)
                == requested_from_key
                and self._factor_carrier_key_sha256(transition_to)
                == requested_to_key
            ):
                continue
            observations: list[tuple[str, str]] = []
            for assessment in assessments_by_transition.get(
                transition.transition_id, []
            ):
                sign = _portable_sign_for_assessment(assessment)
                if sign is None:
                    continue
                observations.append((sign, assessment.evidence_root_sha256))
            observations.extend(
                (leaf.sign, leaf.evidence_root_sha256)
                for leaf in leaves_by_transition.get(
                    transition.transition_id, []
                )
            )
            for tombstone in tombstones_by_transition.get(
                transition.transition_id, []
            ):
                if tombstone.disposition == "harmful":
                    observations.append(("harm", tombstone.evidence_root_sha256))
            edge_key = self._canonical_scientific_edge_sha256(
                self._state,
                transition,
            )
            observations.extend(
                ("harm", evidence_root_sha256)
                for evidence_root_sha256 in rollback_harm_by_edge.get(
                    edge_key,
                    (),
                )
            )
            if observations:
                by_background.setdefault(
                    self._canonical_background_sha256(
                        self._state,
                        transition,
                    ),
                    [],
                ).extend(observations)
        reduced: list[PortableBackgroundSignV1] = []
        for background in sorted(by_background):
            observations = sorted(set(by_background[background]))
            labels = {item[0] for item in observations}
            if "harm" in labels:
                sign = "harm"
            elif "null" in labels:
                sign = "null"
            elif "benefit" in labels:
                sign = "benefit"
            elif "all_zero" in labels:
                sign = "all_zero"
            else:
                sign = "infrastructure"
            reduced.append(
                PortableBackgroundSignV1(
                    fixed_background_sha256=background,
                    sign=sign,
                    evidence_root_sha256=_sha256(observations),
                )
            )
        return tuple(reduced)

    def _proposal_candidate_slate(
        self,
        *,
        opportunity: RepairOpportunityV2,
        source_factor: FactorRevisionV2,
        slot_id: str,
    ) -> tuple[tuple[PortableCandidateV1, ...], str, int]:
        """Derive the complete bounded candidate slate from Bank state.

        Callers may choose only a host-allowed exact locus.  They cannot omit
        an inconvenient target, change selector policy, or inject evidence.
        When more than sixteen compatible content owners exist, a public
        canonical-cell/lifetime-ordinal reservoir supplies a deterministic,
        outcome-independent bounded slate.  Exact storage identifiers cannot
        perturb membership or order.  Evidence overflow fails that target
        closed instead of sampling a misleading sign distribution.
        """

        canonical_by_content: dict[str, FactorRevisionV2] = {}
        source_factor_key = self._factor_carrier_key_sha256(source_factor)
        source = self.compositions.get(opportunity.source_composition_id)
        if source is None or source.binding_map.get(slot_id) != source_factor.revision_id:
            raise ValueError("proposal slate source is not loaded at its exact slot")
        locus = ExactFactorLocusV1(
            carrier=source_factor.carrier,
            slot_id=slot_id,
            logical_factor_id=source_factor.logical_factor_id,
            locator_surface=source_factor.locator.surface,
            locator_path=source_factor.locator.path,
            locator_version=source_factor.locator.locator_version,
        )
        scheduler_cell = ExactProposalCellV1(
            namespace=source.namespace,
            locus=locus,
            from_revision_id=source_factor.revision_id,
            canonical_from_factor_key_sha256=source_factor_key,
            canonical_background_sha256=(
                self._canonical_direct_background_sha256(
                    self._state,
                    source=source,
                    source_factor=source_factor,
                    slot_id=slot_id,
                )
            ),
        )
        prior_decisions = [
            item
            for item in self._state.proposal_decisions
            if (
                item.cursor_committed
                and item.proposal_receipt.request.cell.scheduler_key_sha256
                == scheduler_cell.scheduler_key_sha256
            )
        ]
        scheduler_cursor = (
            max(
                prior_decisions,
                key=lambda item: (item.created_seq, item.decision_id),
            ).proposal_receipt.projected_cursor
            if prior_decisions
            else ProposalCursorV1.empty(scheduler_cell)
        )
        scheduler_ordinal = scheduler_cursor.lifetime_ordinal
        for factor in self._state.factors:
            if not (
                factor.structural_state == "live"
                and factor.binding_status == "proven_factorized"
                and self._row_is_carrier_eligible(
                    self._state,
                    row_kind="factor",
                    row_id=factor.revision_id,
                    factor_carrier_key_sha256=(
                        self._factor_carrier_key_sha256(factor)
                    ),
                )
                and factor.namespace == source_factor.namespace
                and factor.logical_factor_id == source_factor.logical_factor_id
                and factor.carrier == source_factor.carrier
                and factor.locator == source_factor.locator
                and self._factor_carrier_key_sha256(factor)
                != source_factor_key
            ):
                continue
            current = canonical_by_content.get(factor.content_sha256)
            if current is None or (
                factor.created_seq,
                factor.revision_id,
            ) < (
                current.created_seq,
                current.revision_id,
            ):
                canonical_by_content[factor.content_sha256] = factor
        candidates: list[PortableCandidateV1] = []
        for target in canonical_by_content.values():
            signs = self._proposal_portable_signs(
                slot_id=slot_id,
                from_revision_id=source_factor.revision_id,
                to_revision_id=target.revision_id,
            )
            if len(signs) > EdgeProposalPolicyV1().max_backgrounds_per_candidate:
                continue
            candidates.append(
                PortableCandidateV1(
                    target_revision_id=target.revision_id,
                    target_factor_key_sha256=(
                        self._factor_carrier_key_sha256(target)
                    ),
                    target_content_sha256=target.content_sha256,
                    lineage_niche=self._proposal_lineage_niche(target),
                    background_signs=signs,
                )
            )
        def scheduler_projection(candidate: PortableCandidateV1) -> dict[str, Any]:
            return {
                "target_factor_key_sha256": candidate.target_factor_key_sha256,
                "target_content_sha256": candidate.target_content_sha256,
                "canonical_lineage_key_sha256": (
                    candidate.lineage_niche.exposure_key_sha256
                ),
                "background_signs": candidate.background_signs,
            }

        universe = tuple(
            sorted(
                candidates,
                key=lambda candidate: candidate.target_factor_key_sha256,
            )
        )
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                _sha256(
                    {
                        "slate_policy": _PROPOSAL_CANDIDATE_SLATE_POLICY_SHA256,
                        "scheduler_cell_sha256": (
                            scheduler_cell.scheduler_key_sha256
                        ),
                        "scheduler_ordinal": scheduler_ordinal,
                        "candidate": scheduler_projection(candidate),
                    }
                ),
                candidate.target_factor_key_sha256,
            )
        )
        policy = EdgeProposalPolicyV1()
        request = ProposalRequestV1(
            opportunity_id=opportunity.opportunity_id,
            cell=scheduler_cell,
        )
        counter_root = _proposal_lifetime_counter_root(
            self._state.proposal_lifetime_counters,
            cell_sha256=scheduler_cell.scheduler_key_sha256,
        )
        counter_witness_by_target = {
            item.target_factor_key_sha256: item.witness
            for item in self._state.proposal_lifetime_counters
            if item.cell_sha256 == scheduler_cell.scheduler_key_sha256
        }
        admitted: list[PortableCandidateV1] = []
        for candidate in ranked:
            proposed = (*admitted, candidate)
            if not proposal_slate_fits_byte_bounds(
                request=request,
                cursor=scheduler_cursor,
                candidates=proposed,
                proposal_counter_state_sha256=counter_root,
                candidate_counter_witnesses=(
                    tuple(
                        counter_witness_by_target.get(
                            item.target_factor_key_sha256,
                            CandidateCounterWitnessV1(
                                cell_sha256=(
                                    scheduler_cell.scheduler_key_sha256
                                ),
                                target_factor_key_sha256=(
                                    item.target_factor_key_sha256
                                ),
                            ),
                        )
                        for item in sorted(
                            proposed,
                            key=lambda item: item.target_factor_key_sha256,
                        )
                    )
                ),
                policy=policy,
            ):
                # A large candidate cannot suppress later smaller candidates in
                # the same canonical public order.
                continue
            admitted.append(candidate)
            if len(admitted) == policy.max_candidates:
                break
        slate = tuple(admitted)
        return (
            slate,
            _sha256(tuple(scheduler_projection(item) for item in universe)),
            len(universe),
        )

    def _expected_proposal_cursor(
        self,
        receipt: ProposalReceiptV1,
    ) -> ProposalCursorV1:
        cell_sha256 = receipt.request.cell.scheduler_key_sha256
        prior = [
            item
            for item in self._state.proposal_decisions
            if (
                item.proposal_receipt.request.cell.scheduler_key_sha256
                == cell_sha256
            )
            and item.cursor_committed
        ]
        if not prior:
            return ProposalCursorV1.empty(receipt.request.cell)
        latest = max(prior, key=lambda item: (item.created_seq, item.decision_id))
        return latest.proposal_receipt.projected_cursor

    def _validate_proposal_receipt_for_opportunity(
        self,
        *,
        opportunity: RepairOpportunityV2,
        receipt: ProposalReceiptV1,
    ) -> tuple[CompositionRevisionV2, FactorRevisionV2, FactorRevisionV2 | None]:
        receipt = replay_validate_proposal_receipt(receipt)
        if receipt.request.opportunity_id != opportunity.opportunity_id:
            raise ValueError("proposal receipt crosses its repair opportunity")
        source = self.compositions.get(opportunity.source_composition_id)
        if source is None or source.structural_state != "live":
            raise ValueError("proposal source composition is not live")
        cell = receipt.request.cell
        locus = cell.locus
        if cell.namespace != source.namespace:
            raise ValueError("proposal cell crosses its exact execution namespace")
        from_revision_id = source.binding_map.get(locus.slot_id)
        if from_revision_id != cell.from_revision_id:
            raise ValueError("proposal comparator is not loaded at its exact slot")
        source_factor = self.factors.get(cell.from_revision_id)
        if source_factor is None or not (
            source_factor.structural_state == "live"
            and source_factor.binding_status == "proven_factorized"
            and source_factor.namespace == cell.namespace
            and source_factor.logical_factor_id == locus.logical_factor_id
            and source_factor.carrier == locus.carrier
            and source_factor.locator.surface == locus.locator_surface
            and source_factor.locator.path == locus.locator_path
            and source_factor.locator.locator_version == locus.locator_version
        ):
            raise ValueError("proposal locus is not the host-proved source factor")
        if cell.canonical_background_sha256 != (
            self._canonical_direct_background_sha256(
                self._state,
                source=source,
                source_factor=source_factor,
                slot_id=locus.slot_id,
            )
        ):
            raise ValueError("proposal cell crosses its canonical source background")
        if cell.canonical_from_factor_key_sha256 != (
            self._factor_carrier_key_sha256(source_factor)
        ):
            raise ValueError("proposal cell crosses its canonical comparator")
        if locus.logical_factor_id not in opportunity.host_allowed_locator_ids:
            raise ValueError("proposal locus was not allowed by the repair opportunity")
        candidate_slate, _universe_sha256, _universe_count = (
            self._proposal_candidate_slate(
                opportunity=opportunity,
                source_factor=source_factor,
                slot_id=locus.slot_id,
            )
        )
        expected_receipt = select_exact_edge_proposal(
            SFTProposalInputV1(
                request=ProposalRequestV1(
                    opportunity_id=opportunity.opportunity_id,
                    cell=cell,
                ),
                policy=EdgeProposalPolicyV1(),
                cursor=self._expected_proposal_cursor(receipt),
                candidates=candidate_slate,
                proposal_counter_state_sha256=(
                    _proposal_lifetime_counter_root(
                        self._state.proposal_lifetime_counters,
                        cell_sha256=cell.scheduler_key_sha256,
                    )
                ),
                candidate_counter_witnesses=(
                    self._proposal_counter_witnesses(
                        self._state,
                        cell_sha256=cell.scheduler_key_sha256,
                        candidates=candidate_slate,
                    )
                ),
            )
        )
        if receipt != expected_receipt:
            raise ValueError(
                "proposal receipt is not the exact host-derived candidate slate"
            )
        selected_target: FactorRevisionV2 | None = None
        for snapshot in receipt.candidate_manifest:
            candidate = snapshot.candidate
            target = self.factors.get(candidate.target_revision_id)
            if target is None or not (
                target.structural_state == "live"
                and target.binding_status == "proven_factorized"
                and self._row_is_carrier_eligible(
                    self._state,
                    row_kind="factor",
                    row_id=target.revision_id,
                    factor_carrier_key_sha256=(
                        self._factor_carrier_key_sha256(target)
                    ),
                )
                and target.namespace == source_factor.namespace
                and target.logical_factor_id == source_factor.logical_factor_id
                and target.carrier == source_factor.carrier
                and target.locator == source_factor.locator
                and target.content_sha256 == candidate.target_content_sha256
                and self._factor_carrier_key_sha256(target)
                == candidate.target_factor_key_sha256
                and candidate.target_factor_key_sha256
                != cell.canonical_from_factor_key_sha256
                and target.revision_id != source_factor.revision_id
            ):
                raise ValueError("proposal candidate is not a compatible live factor")
            aliases = sorted(
                (
                    item
                    for item in self._state.factors
                    if item.structural_state == "live"
                    and item.namespace == target.namespace
                    and item.logical_factor_id == target.logical_factor_id
                    and item.carrier == target.carrier
                    and item.locator == target.locator
                    and item.content_sha256 == target.content_sha256
                    and self._row_is_carrier_eligible(
                        self._state,
                        row_kind="factor",
                        row_id=item.revision_id,
                        factor_carrier_key_sha256=(
                            self._factor_carrier_key_sha256(item)
                        ),
                    )
                ),
                key=lambda item: (item.created_seq, item.revision_id),
            )
            if not aliases or candidate.target_revision_id != aliases[0].revision_id:
                raise ValueError("proposal candidate is not the canonical content owner")
            if candidate.lineage_niche != self._proposal_lineage_niche(target):
                raise ValueError("proposal candidate lineage is not reproducible")
            expected_signs = self._proposal_portable_signs(
                slot_id=locus.slot_id,
                from_revision_id=source_factor.revision_id,
                to_revision_id=target.revision_id,
            )
            if candidate.background_signs != expected_signs:
                raise ValueError("proposal candidate signs are not Bank-authoritative")
            if candidate.target_revision_id == receipt.selected_target_revision_id:
                selected_target = target
        if receipt.cursor_before != self._expected_proposal_cursor(receipt):
            raise ValueError("proposal cursor is not the exact durable cell successor")
        if (receipt.selection_mode == "no_safe_reuse") != (
            selected_target is None
        ):
            raise ValueError("proposal selected target is absent from its exact manifest")
        if selected_target is not None and (
            selected_target.content_sha256
            != receipt.selected_target_content_sha256
            or self._proposal_lineage_niche(
                selected_target
            ).exposure_key_sha256
            != receipt.selected_lineage_niche_sha256
        ):
            raise ValueError("proposal selected target closure is inconsistent")
        return source, source_factor, selected_target

    def _verify_generation_context(
        self,
        *,
        context: ProposalGenerationContextV1,
        opportunity: RepairOpportunityV2,
        receipt: ProposalReceiptV1,
        source: CompositionRevisionV2,
        source_factor: FactorRevisionV2,
    ) -> ProposalGenerationContextV1:
        context = ProposalGenerationContextV1.model_validate(
            context.model_dump(mode="python")
        )
        locus = receipt.request.cell.locus
        failure = next(
            (
                item for item in self._state.failures
                if item.failure_class == "algorithm"
                and _opaque_id("ro", item.failure_id) == opportunity.opportunity_id
            ),
            None,
        )
        if not (
            context.proposal_receipt_sha256 == receipt.digest
            and context.repair_opportunity_id == opportunity.opportunity_id
            and context.repair_opportunity_sha256 == opportunity.digest
            and failure is not None
            and context.failure_observation_sha256 == _sha256(failure)
            and context.namespace_digest == source.namespace.digest
            and context.source_composition_id == source.composition_id
            and context.source_artifact_id == source.artifact_revision_id
            and context.slot_id == locus.slot_id
            and context.locator_path == source_factor.locator.path
            and context.from_revision_id == source_factor.revision_id
            and context.safe_failure_code == opportunity.safe_failure_code
            and context.failure_artifact_sha256 == source.artifact_sha256
            and context.runtime_version == source.namespace.runtime_version
        ):
            raise ValueError("generation context differs from its Bank opportunity")
        if self._proposal_generation_context_verifier is None:
            raise RuntimeError(
                "no trusted proposal generation-context verifier is installed"
            )
        try:
            verified = bool(
                self._proposal_generation_context_verifier(
                    context,
                    opportunity,
                    receipt,
                    source,
                    source_factor,
                    self._state,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "trusted proposal generation-context verification failed"
            ) from exc
        if not verified:
            raise ValueError("trusted generation-context verifier rejected context")
        return context

    @staticmethod
    def _build_generation_request(
        *,
        action_id: str,
        branch: Literal["mutate", "fresh"],
        context: ProposalGenerationContextV1,
    ) -> ProposalGenerationRequestV1:
        dependencies = (
            (context.from_revision_id,) if branch == "mutate" else ()
        )
        body = {
            "request_version": "sft_proposal_generation_request_v1",
            "action_id": action_id,
            "branch": branch,
            "split": "TRAIN_UPDATE",
            "generation_context_sha256": context.digest,
            "repair_opportunity_sha256": context.repair_opportunity_sha256,
            "failure_observation_sha256": context.failure_observation_sha256,
            "namespace_digest": context.namespace_digest,
            "source_composition_id": context.source_composition_id,
            "source_artifact_id": context.source_artifact_id,
            "slot_id": context.slot_id,
            "locator_path": context.locator_path,
            "from_revision_id": context.from_revision_id,
            "dependency_factor_ids": dependencies,
            "source_manifest_sha256": context.source_manifest_sha256,
            "train_update_source_catalog_sha256": (
                context.train_update_source_catalog_sha256
            ),
            "train_update_policy_sha256": context.train_update_policy_sha256,
            "safe_failure_code": context.safe_failure_code,
            "failure_artifact_sha256": context.failure_artifact_sha256,
            "generation_policy_sha256": context.generation_policy_sha256,
            "prompt_template_sha256": context.prompt_template_sha256,
            "scalar_output_schema_sha256": (
                context.scalar_output_schema_sha256
            ),
            "model_name": context.model_name,
            "runtime_version": context.runtime_version,
            "budget": context.budget,
            "budget_sha256": context.budget_sha256,
        }
        return ProposalGenerationRequestV1(
            request_id=_opaque_id("grq", body),
            **body,
        )

    def _build_proposal_action(
        self,
        *,
        assignment: BranchAssignmentV2,
        decision: ProposalDecisionV1,
        source: CompositionRevisionV2,
        source_factor: FactorRevisionV2,
        target: FactorRevisionV2 | None,
        generation_context: ProposalGenerationContextV1 | None,
        producer_epoch: str,
        attestation_sha256: str,
        event_seq: int,
    ) -> ProposalActionV2:
        _require_id(producer_epoch, "producer_epoch")
        _require_sha(attestation_sha256, "attestation_sha256")
        assignment_sha256 = _sha256(assignment)
        action_id = _opaque_id(
            "ptx",
            {
                "assignment": assignment_sha256,
                "proposal": decision.proposal_receipt_sha256,
            },
        )
        receipt = decision.proposal_receipt
        branch = assignment.branch
        selected_target_revision_id = (
            target.revision_id if branch == "reuse" and target is not None else None
        )
        selected_target_content_sha256 = (
            target.content_sha256 if branch == "reuse" and target is not None else None
        )
        if branch == "reuse" and target is None:
            raise ValueError("reuse action requires its selected target")
        if branch != "reuse" and generation_context is None:
            raise ValueError("generated action requires its verified context")
        carrier_capacity_reservation_id: str | None = None
        if branch in {"mutate", "fresh"}:
            reservation_body = self._proposal_carrier_reservation_body(
                action_id=action_id,
                namespace_digest=source.namespace.digest,
                prepared_seq=event_seq,
                policy=self._state.capacity_policy,
            )
            carrier_capacity_reservation_id = (
                self._proposal_carrier_reservation_id(reservation_body)
            )
        generation_request = (
            self._build_generation_request(
                action_id=action_id,
                branch=branch,
                context=generation_context,
            )
            if branch in {"mutate", "fresh"} and generation_context is not None
            else None
        )
        dependencies = (
            (target.revision_id,)
            if branch == "reuse" and target is not None
            else (source_factor.revision_id,)
            if branch == "mutate"
            else ()
        )
        intent_sha256 = _proposal_action_intent_sha256(
            action_id=action_id,
            assignment_id=assignment.assignment_id,
            assignment_sha256=assignment_sha256,
            proposal_decision_id=decision.decision_id,
            proposal_decision_sha256=decision.digest,
            proposal_receipt_sha256=decision.proposal_receipt_sha256,
            branch=branch,
            namespace_digest=source.namespace.digest,
            source_composition_id=source.composition_id,
            source_artifact_id=source.artifact_revision_id,
            slot_id=receipt.request.cell.locus.slot_id,
            locator_path=source_factor.locator.path,
            from_revision_id=source_factor.revision_id,
            dependency_factor_ids=dependencies,
            selected_target_revision_id=selected_target_revision_id,
            selected_target_content_sha256=selected_target_content_sha256,
            generation_context_sha256=(
                generation_context.digest if generation_context is not None else None
            ),
            generation_request_sha256=(
                generation_request.digest if generation_request is not None else None
            ),
            carrier_capacity_reservation_id=carrier_capacity_reservation_id,
            producer_epoch=producer_epoch,
            attestation_sha256=attestation_sha256,
        )
        root_set = {
            assignment_sha256,
            decision.digest,
            decision.proposal_receipt_sha256,
            receipt.policy_sha256,
            receipt.cursor_before_sha256,
            receipt.candidate_manifest_sha256,
            receipt.projected_history_sha256,
            intent_sha256,
        }
        if generation_context is not None:
            root_set.update(
                {
                    generation_context.digest,
                    generation_context.repair_opportunity_sha256,
                    generation_context.failure_observation_sha256,
                    generation_context.source_manifest_sha256,
                    generation_context.train_update_source_catalog_sha256,
                    generation_context.train_update_policy_sha256,
                    generation_context.failure_artifact_sha256,
                    generation_context.generation_policy_sha256,
                    generation_context.prompt_template_sha256,
                    generation_context.scalar_output_schema_sha256,
                    generation_context.budget_sha256,
                }
            )
        if generation_request is not None:
            root_set.add(generation_request.digest)
        return ProposalActionV2(
            action_id=action_id,
            assignment_id=assignment.assignment_id,
            assignment_sha256=assignment_sha256,
            proposal_decision_id=decision.decision_id,
            proposal_decision_sha256=decision.digest,
            proposal_receipt_sha256=decision.proposal_receipt_sha256,
            proposal_policy_sha256=receipt.policy_sha256,
            proposal_cursor_before_sha256=receipt.cursor_before_sha256,
            proposal_candidate_manifest_sha256=receipt.candidate_manifest_sha256,
            proposal_projected_history_sha256=receipt.projected_history_sha256,
            branch=branch,
            namespace_digest=source.namespace.digest,
            source_composition_id=source.composition_id,
            source_artifact_id=source.artifact_revision_id,
            slot_id=receipt.request.cell.locus.slot_id,
            locator_path=source_factor.locator.path,
            from_revision_id=source_factor.revision_id,
            from_content_sha256=source_factor.content_sha256,
            dependency_factor_ids=dependencies,
            selected_target_revision_id=selected_target_revision_id,
            selected_target_content_sha256=selected_target_content_sha256,
            generation_context=generation_context,
            generation_request=generation_request,
            carrier_capacity_reservation_id=carrier_capacity_reservation_id,
            action_intent_sha256=intent_sha256,
            exact_additional_input_root_commitments=tuple(sorted(root_set)),
            producer_epoch=producer_epoch,
            attestation_sha256=attestation_sha256,
            prepared_seq=event_seq,
            updated_seq=event_seq,
        )

    @_atomic_bank_update
    def screen_and_allocate_branch(
        self,
        repair_opportunity_id: str,
        proposal_receipt: ProposalReceiptV1,
        *,
        producer_epoch: str,
        attestation_sha256: str,
        generation_context: ProposalGenerationContextV1 | None = None,
    ) -> tuple[
        ProposalDecisionV1,
        BranchAssignmentV2 | None,
        ProposalActionV2 | None,
    ]:
        """Atomically admit the selector decision, branch, and one action.

        ``no_safe_reuse`` removes reuse *before* the namespace-deficit branch
        choice.  If no branch remains the decision (and its advanced cursor) is
        still persisted, so retries cannot reset UNKNOWN/diversity retirement.
        A generated-capable context is concretely verified before the branch
        selector runs, so a caller cannot condition provenance on the winner.
        """

        opportunity = next(
            (
                item
                for item in self._state.repair_opportunities
                if item.opportunity_id == repair_opportunity_id
            ),
            None,
        )
        if opportunity is None:
            raise ValueError("repair opportunity does not exist")
        if self._state.event_seq > opportunity.expiry_seq:
            raise ValueError("repair opportunity has expired")
        if any(
            item.repair_opportunity_id == opportunity.opportunity_id
            for item in self._state.proposal_decisions
        ):
            raise ValueError("repair opportunity already owns a proposal decision")
        if any(
            item.repair_opportunity_id == opportunity.opportunity_id
            for item in self._state.branch_assignments
        ):
            raise ValueError("repair opportunity already owns a branch assignment")
        if len(self._state.proposal_decisions) >= (
            self._state.capacity_policy.max_proposal_decisions
        ):
            raise RuntimeError("proposal-decision capacity is exhausted")
        receipt = ProposalReceiptV1.model_validate(
            proposal_receipt.model_dump(mode="python")
        )
        source, source_factor, selected_target = (
            self._validate_proposal_receipt_for_opportunity(
                opportunity=opportunity,
                receipt=receipt,
            )
        )
        candidate_slate, universe_sha256, universe_count = (
            self._proposal_candidate_slate(
                opportunity=opportunity,
                source_factor=source_factor,
                slot_id=receipt.request.cell.locus.slot_id,
            )
        )
        slate_target_ids = tuple(
            item.candidate.target_revision_id
            for item in receipt.candidate_manifest
        )
        slate_sha256 = _sha256(
            tuple(item.candidate for item in receipt.candidate_manifest)
        )
        if tuple(
            item.target_revision_id
            for item in sorted(
                candidate_slate,
                key=lambda candidate: candidate.target_factor_key_sha256,
            )
        ) != slate_target_ids:
            raise ValueError("proposal receipt lost its host-derived candidate slate")
        proposal_scheduler_decision_sha256 = (
            _host_proposal_scheduler_decision_sha256(
                receipt=receipt,
                candidate_universe_sha256=universe_sha256,
                candidate_universe_count=universe_count,
            )
        )
        decision_id = _opaque_id(
            "pd",
            {
                "opportunity": opportunity.digest,
                "proposal": receipt.digest,
            },
        )
        feasible = tuple(
            branch
            for branch in opportunity.feasible_branches
            if not (branch == "reuse" and selected_target is None)
        )
        needs_generation_context = any(
            branch in {"mutate", "fresh"} for branch in feasible
        )
        verified_context: ProposalGenerationContextV1 | None = None
        if needs_generation_context:
            if generation_context is None:
                raise ValueError(
                    "generated feasible branches require a generation context"
                )
            verified_context = self._verify_generation_context(
                context=generation_context,
                opportunity=opportunity,
                receipt=receipt,
                source=source,
                source_factor=source_factor,
            )
        elif generation_context is not None:
            raise ValueError("generation context was supplied without a generated branch")
        slate_attestation_body = {
            "decision_id": decision_id,
            "repair_opportunity_sha256": opportunity.digest,
            "proposal_receipt_sha256": receipt.digest,
            "proposal_scheduler_decision_sha256": (
                proposal_scheduler_decision_sha256
            ),
            "proposal_counter_state_before_sha256": (
                receipt.proposal_counter_state_before_sha256
            ),
            "candidate_counter_witnesses_sha256": (
                receipt.candidate_counter_witnesses_sha256
            ),
            "candidate_slate_policy_sha256": (
                _PROPOSAL_CANDIDATE_SLATE_POLICY_SHA256
            ),
            "candidate_universe_sha256": universe_sha256,
            "candidate_universe_count": universe_count,
            "candidate_slate_target_revision_ids": slate_target_ids,
            "candidate_slate_sha256": slate_sha256,
            "candidate_slate_scheduler_sha256": (
                receipt.candidate_slate_scheduler_sha256
            ),
            "generation_context_sha256": (
                verified_context.digest if verified_context is not None else None
            ),
        }
        decision_slate_fields = {
            "proposal_scheduler_decision_sha256": (
                proposal_scheduler_decision_sha256
            ),
            "candidate_slate_policy_sha256": (
                _PROPOSAL_CANDIDATE_SLATE_POLICY_SHA256
            ),
            "candidate_universe_sha256": universe_sha256,
            "candidate_universe_count": universe_count,
            "candidate_slate_target_revision_ids": slate_target_ids,
            "candidate_slate_sha256": slate_sha256,
            "candidate_slate_scheduler_sha256": (
                receipt.candidate_slate_scheduler_sha256
            ),
            "candidate_slate_attestation_sha256": _mac(
                self._key,
                "proposal-candidate-slate-v4",
                slate_attestation_body,
            ),
            "generation_context": verified_context,
            "generation_context_sha256": (
                verified_context.digest if verified_context is not None else None
            ),
        }
        next_seq = self._state.event_seq + 1
        if not feasible:
            counter_root = _proposal_lifetime_counter_root(
                self._state.proposal_lifetime_counters,
                cell_sha256=receipt.request.cell.scheduler_key_sha256,
            )
            decision = ProposalDecisionV1(
                decision_id=decision_id,
                repair_opportunity_id=opportunity.opportunity_id,
                repair_opportunity_sha256=opportunity.digest,
                proposal_receipt=receipt,
                proposal_receipt_sha256=receipt.digest,
                proposal_counter_state_before_sha256=counter_root,
                proposal_counter_state_after_sha256=counter_root,
                committed_counter_delta=None,
                committed_counter_delta_sha256=_sha256(None),
                **decision_slate_fields,
                effective_feasible_branches=(),
                selected_branch=None,
                cursor_committed=True,
                created_seq=next_seq,
            )
            _assert_proposal_decision_byte_bound(
                decision,
                max_bytes=(
                    self._state.capacity_policy.max_proposal_decision_bytes
                ),
            )
            self._install(
                self._next_state(
                    proposal_decisions=(
                        *self._state.proposal_decisions,
                        decision,
                    )
                )
            )
            return decision, None, None
        if len(self._state.branch_assignments) >= (
            self._state.capacity_policy.max_branch_assignments
        ):
            raise RuntimeError("branch-assignment capacity is exhausted")
        opportunities = {
            item.opportunity_id: item for item in self._state.repair_opportunities
        }
        counts = {branch: 0 for branch in ("reuse", "mutate", "fresh")}
        for item in self._state.branch_assignments:
            prior = opportunities[item.repair_opportunity_id]
            if prior.namespace_digest == opportunity.namespace_digest:
                counts[item.branch] += 1
        total = sum(counts.values())
        candidates: list[tuple[float, str, ScientificBranch]] = []
        for branch in feasible:
            deficit = (total + 1) / 3 - counts[branch]
            tiebreak = _proposal_conditioned_branch_tiebreak_sha256(
                public_seed=opportunity.public_seed,
                proposal_scheduler_decision_sha256=(
                    proposal_scheduler_decision_sha256
                ),
                branch=branch,
            )
            candidates.append((deficit, tiebreak, branch))
        _deficit, tiebreak, chosen = max(candidates)
        committed_counter_delta = (
            receipt.projected_counter_delta if chosen == "reuse" else None
        )
        counter_state_before_sha256 = _proposal_lifetime_counter_root(
            self._state.proposal_lifetime_counters,
            cell_sha256=receipt.request.cell.scheduler_key_sha256,
        )
        proposal_lifetime_counters = _apply_proposal_counter_delta(
            self._state.proposal_lifetime_counters,
            committed_counter_delta,
            max_rows=(
                self._state.capacity_policy.max_proposal_lifetime_counters
            ),
        )
        counter_state_after_sha256 = _proposal_lifetime_counter_root(
            proposal_lifetime_counters,
            cell_sha256=receipt.request.cell.scheduler_key_sha256,
        )
        decision = ProposalDecisionV1(
            decision_id=decision_id,
            repair_opportunity_id=opportunity.opportunity_id,
            repair_opportunity_sha256=opportunity.digest,
            proposal_receipt=receipt,
            proposal_receipt_sha256=receipt.digest,
            proposal_counter_state_before_sha256=(
                counter_state_before_sha256
            ),
            proposal_counter_state_after_sha256=counter_state_after_sha256,
            committed_counter_delta=committed_counter_delta,
            committed_counter_delta_sha256=_sha256(committed_counter_delta),
            **decision_slate_fields,
            effective_feasible_branches=feasible,
            selected_branch=chosen,
            cursor_committed=(
                chosen == "reuse"
                or receipt.selection_mode == "no_safe_reuse"
            ),
            created_seq=next_seq,
        )
        # This is the first boundary at which every receipt, host-slate,
        # branch and optional generation-context byte is known.  Check the
        # exact closed decision before constructing/publishing its assignment,
        # action, reservation, or any successor Bank state.
        _assert_proposal_decision_byte_bound(
            decision,
            max_bytes=self._state.capacity_policy.max_proposal_decision_bytes,
        )
        assignment = BranchAssignmentV2(
            assignment_id=_opaque_id(
                "ba",
                {
                    "opportunity": opportunity.opportunity_id,
                    "namespace_ordinal": total,
                    "branch": chosen,
                    "proposal_decision": decision.digest,
                },
            ),
            repair_opportunity_id=opportunity.opportunity_id,
            repair_opportunity_sha256=opportunity.digest,
            namespace_digest=opportunity.namespace_digest,
            source_composition_id=opportunity.source_composition_id,
            branch=chosen,
            assigned_counts_before=tuple(
                (branch, counts[branch])
                for branch in ("reuse", "mutate", "fresh")
            ),
            selector_policy_sha256=(
                _PROPOSAL_CONDITIONED_BRANCH_POLICY_SHA256
            ),
            public_tiebreak_sha256=tiebreak,
            proposal_decision_id=decision.decision_id,
            proposal_decision_sha256=decision.digest,
            effective_feasible_branches=feasible,
            created_seq=next_seq,
        )
        if len(self._state.proposal_actions) >= (
            self._state.capacity_policy.max_proposal_actions
        ):
            raise RuntimeError("proposal-action capacity is exhausted")
        action = self._build_proposal_action(
            assignment=assignment,
            decision=decision,
            source=source,
            source_factor=source_factor,
            target=selected_target if chosen == "reuse" else None,
            generation_context=verified_context,
            producer_epoch=producer_epoch,
            attestation_sha256=attestation_sha256,
            event_seq=next_seq,
        )
        carrier_reservations = self._state.proposal_carrier_reservations
        if chosen in {"mutate", "fresh"}:
            carrier_reservation = self._reserve_generated_carrier_capacity(
                action=action,
                namespace=source.namespace,
            )
            carrier_reservations = (
                *carrier_reservations,
                carrier_reservation,
            )
        self._install(
            self._next_state(
                proposal_decisions=(
                    *self._state.proposal_decisions,
                    decision,
                ),
                proposal_lifetime_counters=proposal_lifetime_counters,
                branch_assignments=(
                    *self._state.branch_assignments,
                    assignment,
                ),
                proposal_actions=(
                    *self._state.proposal_actions,
                    action,
                ),
                proposal_carrier_reservations=carrier_reservations,
            )
        )
        return decision, assignment, action

    @_atomic_bank_update
    def begin_proposal_generation(
        self,
        action_id: str,
        lease: ProposalGenerationLeaseV1,
    ) -> ProposalActionV2:
        """Persist the sole generation-1 start before any external model call."""

        lease = ProposalGenerationLeaseV1.model_validate(
            lease.model_dump(mode="python")
        )
        if lease.started_seq is not None:
            raise ValueError("generation lease sequence is Bank-owned")
        action = next(
            (item for item in self._state.proposal_actions
             if item.action_id == action_id),
            None,
        )
        if action is None:
            raise ValueError("proposal action does not exist")
        if action.state == "executing":
            assert action.generation_lease is not None
            replay = lease.model_copy(
                update={"started_seq": action.generation_lease.started_seq}
            )
            if replay != action.generation_lease:
                raise ValueError("executing proposal action cannot acquire another lease")
            return action
        if action.state != "prepared" or action.branch == "reuse":
            raise ValueError("only a prepared generated action can start")
        reservation = self._proposal_carrier_reservation_for_action(
            self._state,
            action.action_id,
        )
        if reservation is None or not (
            reservation.state == "reserved"
            and reservation.namespace_digest == action.namespace_digest
            and reservation.created_seq == action.prepared_seq
        ):
            raise RuntimeError(
                "generated action lacks its pre-START carrier reservation"
            )
        request = action.generation_request
        assert request is not None
        if not (
            lease.action_id == action.action_id
            and lease.generation_request_sha256 == request.digest
            and lease.expected_prepared_action_sha256 == action.digest
        ):
            raise ValueError("generation lease does not fence the prepared action")
        persisted_lease = lease.model_copy(
            update={"started_seq": self._state.event_seq + 1}
        )
        persisted_lease = ProposalGenerationLeaseV1.model_validate(
            persisted_lease.model_dump(mode="python")
        )
        if self._proposal_generation_lease_verifier is None:
            raise RuntimeError(
                "no trusted proposal generation-lease verifier is installed"
            )
        try:
            verified = bool(
                self._proposal_generation_lease_verifier(
                    persisted_lease,
                    action,
                    self._state,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "trusted proposal generation-lease verification failed"
            ) from exc
        if not verified:
            raise ValueError("trusted generation-lease verifier rejected start")
        updated = action.model_copy(
            update={
                "state": "executing",
                "generation_lease": persisted_lease,
                "updated_seq": persisted_lease.started_seq,
            }
        )
        actions = tuple(
            updated if item.action_id == action.action_id else item
            for item in self._state.proposal_actions
        )
        self._install(self._next_state(proposal_actions=actions))
        return updated

    @_atomic_bank_update
    def finalize_proposal_action(
        self,
        action_id: str,
        *,
        transition_id: str,
        phase_terminal_sha256: str,
        generation_terminal_sha256: str | None = None,
        resolved_to_revision_id: str | None = None,
        resolved_target_content_sha256: str | None = None,
    ) -> ProposalActionV2:
        _require_sha(phase_terminal_sha256, "phase_terminal_sha256")
        if generation_terminal_sha256 is not None:
            _require_sha(
                generation_terminal_sha256,
                "generation_terminal_sha256",
            )
        if resolved_to_revision_id is not None:
            _require_id(resolved_to_revision_id, "resolved_to_revision_id")
        if resolved_target_content_sha256 is not None:
            _require_sha(
                resolved_target_content_sha256,
                "resolved_target_content_sha256",
            )
        action = next(
            (
                item
                for item in self._state.proposal_actions
                if item.action_id == action_id
            ),
            None,
        )
        if action is None:
            raise ValueError("proposal action does not exist")
        if action.state == "committed":
            if not (
                action.transition_id == transition_id
                and action.phase_terminal_sha256 == phase_terminal_sha256
                and action.generation_terminal_sha256
                == generation_terminal_sha256
                and (
                    resolved_to_revision_id is None
                    or action.resolved_to_revision_id == resolved_to_revision_id
                )
                and (
                    resolved_target_content_sha256 is None
                    or action.resolved_target_content_sha256
                    == resolved_target_content_sha256
                )
            ):
                raise ValueError("committed proposal action was replayed differently")
            return action
        expected_state = "prepared" if action.branch == "reuse" else "executing"
        if action.state != expected_state:
            raise ValueError(
                "proposal action is not in its branch-specific commit state"
            )
        transition = self.direct_transitions.get(transition_id)
        resolved_factor = (
            self.factors.get(transition.to_revision_id)
            if transition is not None
            else None
        )
        expected_resolved_id = (
            action.selected_target_revision_id
            if action.branch == "reuse"
            else resolved_to_revision_id
        )
        expected_resolved_content = (
            action.selected_target_content_sha256
            if action.branch == "reuse"
            else resolved_target_content_sha256
        )
        if action.branch == "reuse":
            if any(
                item is not None
                for item in (
                    generation_terminal_sha256,
                    resolved_to_revision_id,
                    resolved_target_content_sha256,
                )
            ):
                raise ValueError("reuse finalization cannot carry generation terminal")
        elif any(
            item is None
            for item in (
                generation_terminal_sha256,
                resolved_to_revision_id,
                resolved_target_content_sha256,
            )
        ):
            raise ValueError("generated finalization lacks terminal or resolved target")
        if transition is None or resolved_factor is None or not (
            transition.structural_state == "live"
            and transition.origin_branch == action.branch
            and transition.namespace.digest == action.namespace_digest
            and transition.source_composition_id == action.source_composition_id
            and transition.slot_id == action.slot_id
            and transition.from_revision_id == action.from_revision_id
            and transition.to_revision_id == expected_resolved_id
            and resolved_factor.content_sha256 == expected_resolved_content
            and transition.binding_proof_sha256 == phase_terminal_sha256
            and transition.proposal_action_id == action.action_id
            and transition.proposal_action_intent_sha256
            == action.action_intent_sha256
            and transition.proposal_action_committed_seq is None
        ):
            raise ValueError("proposal action does not join one exact Phase edge")
        admission = self._admission_for_transition(
            self._state,
            transition.transition_id,
        )
        if admission is None or not (
            admission.action_id == action.action_id
            and admission.action_intent_sha256 == action.action_intent_sha256
            and admission.state == "staged"
            and admission.projected_transition_sha256
            == _sha256(self._projected_action_transition(transition))
        ):
            raise ValueError(
                "proposal action lacks its exact staged carrier admission"
            )
        if generation_terminal_sha256 is not None and any(
            item.action_id != action.action_id
            and item.generation_terminal_sha256 == generation_terminal_sha256
            for item in self._state.proposal_actions
        ):
            raise ValueError("generation terminal is already owned by another action")
        next_seq = self._state.event_seq + 1
        updated = action.model_copy(
            update={
                "state": "committed",
                "generation_terminal_sha256": generation_terminal_sha256,
                "resolved_to_revision_id": expected_resolved_id,
                "resolved_target_content_sha256": expected_resolved_content,
                "phase_terminal_sha256": phase_terminal_sha256,
                "transition_id": transition.transition_id,
                "binding_proof_id": transition.binding_proof_id,
                "updated_seq": next_seq,
            }
        )
        committed_transition = transition.model_copy(
            update={"proposal_action_committed_seq": next_seq}
        )
        admitted = admission.model_copy(
            update={
                "state": "admitted",
                "terminal_seq": next_seq,
                "terminal_sha256": self._admission_terminal_sha256(
                    disposition="admitted",
                    action=updated,
                    projected_transition_sha256=(
                        admission.projected_transition_sha256
                    ),
                    committed_transition=committed_transition,
                ),
            }
        )
        actions = tuple(
            updated if item.action_id == action.action_id else item
            for item in self._state.proposal_actions
        )
        direct_transitions = tuple(
            committed_transition
            if item.transition_id == transition.transition_id
            else item
            for item in self._state.direct_transitions
        )
        admissions = tuple(
            admitted if item.admission_id == admission.admission_id else item
            for item in self._state.proposal_carrier_admissions
        )
        carrier_reservations = self._state.proposal_carrier_reservations
        if action.branch in {"mutate", "fresh"}:
            carrier_reservation = self._proposal_carrier_reservation_for_action(
                self._state,
                action.action_id,
            )
            if carrier_reservation is None or not (
                carrier_reservation.state == "materialized"
                and carrier_reservation.materialized_seq
                == transition.created_seq
            ):
                raise ValueError(
                    "generated terminal lacks materialized carrier capacity"
                )
            consumed_reservation = carrier_reservation.model_copy(
                update={"state": "consumed", "consumed_seq": next_seq}
            )
            carrier_reservations = tuple(
                consumed_reservation
                if item.reservation_id == carrier_reservation.reservation_id
                else item
                for item in carrier_reservations
            )
        candidate = self._next_state(
            proposal_actions=actions,
            direct_transitions=direct_transitions,
            proposal_carrier_admissions=admissions,
            proposal_carrier_reservations=carrier_reservations,
        )
        if self._proposal_action_terminal_verifier is None:
            raise RuntimeError(
                "no trusted proposal-action terminal verifier is installed"
            )
        try:
            terminal_verified = bool(
                self._proposal_action_terminal_verifier(
                    updated,
                    committed_transition,
                    candidate,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "trusted proposal-action terminal verification failed"
            ) from exc
        if not terminal_verified:
            raise ValueError(
                "proposal-action terminal verifier rejected the Phase edge"
            )
        self._install(candidate)
        return updated

    def _inert_edge_cleanup_blockers(
        self,
        transition_id: str,
        *,
        action_id: str,
    ) -> tuple[str, ...]:
        """Name every durable owner that makes an inert edge unsafe to remove."""

        blockers: list[str] = []
        checks = (
            ("plan", any(item.transition_id == transition_id for item in self._state.plans)),
            (
                "assessment",
                any(item.transition_id == transition_id for item in self._state.assessments),
            ),
            (
                "gate_opportunity",
                any(
                    item.transition_id == transition_id
                    for item in self._state.gate_opportunities
                ),
            ),
            (
                "failure",
                any(item.transition_id == transition_id for item in self._state.failures),
            ),
            (
                "repair_opportunity",
                any(
                    item.transition_id == transition_id
                    for item in self._state.repair_opportunities
                ),
            ),
            (
                "deployment_snapshot",
                any(
                    item.transition_id == transition_id
                    for item in self._state.deployment_snapshots
                ),
            ),
            (
                "deployment_head",
                any(
                    item.active_transition_id == transition_id
                    for item in self._state.deployment_heads
                ),
            ),
            (
                "tombstone",
                any(item.subject_id == transition_id for item in self._state.tombstones),
            ),
            (
                "portable_evidence",
                any(
                    item.transition_id == transition_id
                    for item in self._state.portable_evidence_leaves
                ),
            ),
            (
                "checkpoint",
                any(
                    transition_id in item.subject_ids
                    for item in self._state.checkpoints
                ),
            ),
            (
                "unit_commitment",
                any(
                    owner_transition_id == transition_id
                    for owner_transition_id, _commitment
                    in self._state.used_unit_commitments
                ),
            ),
            (
                "exposure",
                any(owner_id == transition_id for owner_id, _count in self._state.exposures),
            ),
            (
                "other_proposal_action",
                any(
                    item.action_id != action_id and item.transition_id == transition_id
                    for item in self._state.proposal_actions
                ),
            ),
        )
        blockers.extend(label for label, blocked in checks if blocked)
        return tuple(blockers)

    @_atomic_bank_update
    def abort_proposal_action(
        self,
        action_id: str,
        receipt: ProposalActionAbortReceiptV2,
    ) -> ProposalActionV2:
        receipt = ProposalActionAbortReceiptV2.model_validate(
            receipt.model_dump(mode="python")
        )
        if receipt.emitted_seq is not None:
            raise ValueError("proposal abort sequence is Bank-owned")
        action = next(
            (
                item
                for item in self._state.proposal_actions
                if item.action_id == action_id
            ),
            None,
        )
        if action is None:
            raise ValueError("proposal action does not exist")
        if action.state == "aborted":
            assert action.abort_receipt is not None
            replay = action.abort_receipt.model_copy(update={"emitted_seq": None})
            if replay != receipt:
                raise ValueError("aborted proposal action was replayed differently")
            return action
        if action.state not in {"prepared", "executing"}:
            raise ValueError("only a prepared or executing proposal action can abort")
        generation_reasons = {
            "generation_invalid_output",
            "generation_budget_exceeded",
            "generation_runner_crash",
            "generation_terminal_rejected",
        }
        if receipt.reason in generation_reasons:
            if action.branch == "reuse" or action.state != "executing":
                raise ValueError(
                    "generation abort requires an executing generated action"
                )
        owned_edges = tuple(
            item
            for item in self._state.direct_transitions
            if item.proposal_action_id == action.action_id
        )
        cleanup_transition: DirectFactorTransitionV2 | None = None
        cleanup_admission: ProposalCarrierAdmissionV1 | None = None
        remaining_transitions = self._state.direct_transitions
        if receipt.cleanup_transition_id is None:
            if owned_edges:
                raise ValueError(
                    "proposal action with an inert edge requires exact cleanup commitment"
                )
        else:
            generated_cleanup = (
                action.state == "executing"
                and action.branch in {"mutate", "fresh"}
                and receipt.reason in generation_reasons
            )
            reuse_cleanup = (
                action.state == "prepared"
                and action.branch == "reuse"
                and receipt.reason == "phase_rejected"
                and receipt.phase_terminal_sha256 is not None
            )
            if not (generated_cleanup or reuse_cleanup):
                raise ValueError(
                    "only an exact rejected generated or reuse action can clean an inert edge"
                )
            if len(owned_edges) != 1:
                raise ValueError(
                    "generated cleanup requires the sole action-owned inert edge"
                )
            cleanup_transition = owned_edges[0]
            lease = action.generation_lease
            target_factor = self.factors.get(cleanup_transition.to_revision_id)
            cleanup_admission = self._admission_for_transition(
                self._state,
                cleanup_transition.transition_id,
            )
            if target_factor is None or cleanup_admission is None:
                raise ValueError("generated cleanup lacks its exact started edge closure")
            if not (
                receipt.cleanup_transition_id == cleanup_transition.transition_id
                and receipt.cleanup_transition_sha256 == _sha256(cleanup_transition)
                and receipt.cleanup_action_intent_sha256
                == action.action_intent_sha256
                and (
                    receipt.phase_terminal_sha256 is None
                    or receipt.phase_terminal_sha256
                    == cleanup_transition.binding_proof_sha256
                )
                and receipt.cleanup_admission_id
                == cleanup_admission.admission_id
                and receipt.cleanup_admission_sha256
                == cleanup_admission.digest
                and cleanup_admission.action_id == action.action_id
                and cleanup_admission.action_intent_sha256
                == action.action_intent_sha256
                and cleanup_admission.transition_id
                == cleanup_transition.transition_id
                and cleanup_admission.projected_transition_sha256
                == _sha256(self._projected_action_transition(cleanup_transition))
                and cleanup_admission.state == "staged"
                and cleanup_transition.structural_state == "live"
                and cleanup_transition.proposal_action_committed_seq is None
                and cleanup_transition.proposal_action_intent_sha256
                == action.action_intent_sha256
                and cleanup_transition.origin_branch == action.branch
                and cleanup_transition.namespace.digest == action.namespace_digest
                and cleanup_transition.source_composition_id
                == action.source_composition_id
                and cleanup_transition.slot_id == action.slot_id
                and cleanup_transition.from_revision_id == action.from_revision_id
                and cleanup_transition.created_seq
                > (
                    lease.started_seq
                    if generated_cleanup and lease is not None
                    and lease.started_seq is not None
                    else action.prepared_seq
                )
                and (
                    not generated_cleanup
                    or (lease is not None and lease.started_seq is not None)
                )
                and (
                    action.branch != "mutate"
                    or target_factor.parent_revision_id == action.from_revision_id
                )
                and (
                    action.branch != "fresh"
                    or target_factor.parent_revision_id is None
                )
            ):
                raise ValueError(
                    "cleanup receipt does not join the exact generated inert edge"
                )
            blockers = self._inert_edge_cleanup_blockers(
                cleanup_transition.transition_id,
                action_id=action.action_id,
            )
            if blockers:
                raise ValueError(
                    "generated inert edge has durable downstream owners: "
                    + ",".join(blockers)
                )
            remaining_transitions = tuple(
                item
                for item in self._state.direct_transitions
                if item.transition_id != cleanup_transition.transition_id
            )
        persisted_receipt = receipt.model_copy(
            update={"emitted_seq": self._state.event_seq + 1}
        )
        persisted_receipt = ProposalActionAbortReceiptV2.model_validate(
            persisted_receipt.model_dump(mode="python")
        )
        if not (
            persisted_receipt.action_id == action.action_id
            and persisted_receipt.predecessor_state == action.state
            and persisted_receipt.expected_action_sha256 == action.digest
        ):
            raise ValueError("proposal abort does not fence the exact action")
        if self._proposal_abort_verifier is None:
            raise RuntimeError("no trusted proposal-action abort verifier is installed")
        try:
            verified = bool(self._proposal_abort_verifier(
                persisted_receipt, action, self._state
            ))
        except Exception as exc:
            raise RuntimeError("trusted proposal-action abort verification failed") from exc
        if not verified:
            raise ValueError("trusted proposal-action abort verifier rejected the fence")
        updated = action.model_copy(
            update={
                "state": "aborted",
                "abort_receipt": persisted_receipt,
                "fencing_generation": 2,
                "updated_seq": persisted_receipt.emitted_seq,
            }
        )
        actions = tuple(
            updated if item.action_id == action.action_id else item
            for item in self._state.proposal_actions
        )
        admissions = self._state.proposal_carrier_admissions
        if cleanup_admission is not None:
            quarantined = cleanup_admission.model_copy(
                update={
                    "state": "quarantined",
                    "terminal_seq": persisted_receipt.emitted_seq,
                    "terminal_sha256": self._admission_terminal_sha256(
                        disposition="quarantined",
                        action=updated,
                        projected_transition_sha256=(
                            cleanup_admission.projected_transition_sha256
                        ),
                        abort_receipt=persisted_receipt,
                    ),
                }
            )
            admissions = tuple(
                quarantined
                if item.admission_id == cleanup_admission.admission_id
                else item
                for item in admissions
            )
        carrier_reservations = self._state.proposal_carrier_reservations
        if action.branch in {"mutate", "fresh"}:
            carrier_reservation = self._proposal_carrier_reservation_for_action(
                self._state,
                action.action_id,
            )
            expected_reservation_state = (
                "materialized" if cleanup_admission is not None else "reserved"
            )
            if carrier_reservation is None or not (
                carrier_reservation.state == expected_reservation_state
                and (
                    cleanup_admission is None
                    or carrier_reservation.materialized_seq
                    == cleanup_admission.created_seq
                )
            ):
                raise ValueError(
                    "generated abort lacks its exact carrier capacity lifecycle"
                )
            terminal_state = (
                "consumed" if cleanup_admission is not None else "released"
            )
            terminal_update: dict[str, Any] = {"state": terminal_state}
            if cleanup_admission is not None:
                terminal_update["consumed_seq"] = persisted_receipt.emitted_seq
            else:
                terminal_update["released_seq"] = persisted_receipt.emitted_seq
            terminal_reservation = carrier_reservation.model_copy(
                update=terminal_update
            )
            carrier_reservations = tuple(
                terminal_reservation
                if item.reservation_id == carrier_reservation.reservation_id
                else item
                for item in carrier_reservations
            )
        candidate = self._next_state(
            proposal_actions=actions,
            direct_transitions=remaining_transitions,
            proposal_carrier_admissions=admissions,
            proposal_carrier_reservations=carrier_reservations,
        )
        self._install(candidate)
        return updated

    @_atomic_bank_update
    def record_failure(
        self,
        observation: FailureObservationV2,
        *,
        feasible_branches: Sequence[ScientificBranch] | None = None,
        opportunity_ttl_events: int = 32,
        public_seed: int = 20260713,
    ) -> RepairOpportunityV2 | None:
        observation = FailureObservationV2.model_validate(
            observation.model_dump(mode="python")
        )
        if observation.created_seq != self._state.event_seq + 1:
            raise ValueError("failure created_seq must equal the next Bank event")
        if len(self._state.failures) >= self._state.capacity_policy.max_failures:
            raise RuntimeError("failure capacity is exhausted")
        composition = self.compositions.get(observation.composition_id)
        if composition is None or composition.artifact_sha256 != observation.artifact_sha256:
            raise ValueError("failure is not bound to its complete composition")
        if not self._composition_has_carrier_authority(
            self._state,
            composition,
        ):
            raise ValueError(
                "unadmitted proposal carrier has no failure authority"
            )
        if observation.transition_id is not None:
            transition = self._transition(observation.transition_id)
            if transition.target_composition_id != composition.composition_id:
                raise ValueError("failure transition is not bound to its target")
            if not self._transition_has_execution_authority(
                self._state,
                transition,
            ):
                raise ValueError(
                    "uncommitted proposal-action edge has no failure authority"
                )
        if any(item.failure_id == observation.failure_id for item in self._state.failures):
            raise ValueError("failure observation already exists")
        if observation.failure_class != "algorithm":
            self._install(
                self._next_state(failures=(*self._state.failures, observation))
            )
            return None
        if feasible_branches is None:
            # Failure evidence is still durable, but no repair authority is
            # fabricated when the carrier has not supplied a trusted branch
            # capability decision.
            self._install(
                self._next_state(failures=(*self._state.failures, observation))
            )
            return None
        if len(self._state.repair_opportunities) >= (
            self._state.capacity_policy.max_repair_opportunities
        ):
            raise RuntimeError("repair-opportunity capacity is exhausted")
        feasible = tuple(dict.fromkeys(feasible_branches))
        if not feasible:
            raise ValueError("algorithm repair opportunity needs a feasible branch")
        allowed_locators = tuple(
            sorted(
                self.factors[factor_id].logical_factor_id
                for factor_id in composition.binding_map.values()
                if self.factors[factor_id].binding_status == "proven_factorized"
            )
        )
        next_seq = self._state.event_seq + 1
        opportunity = RepairOpportunityV2(
            opportunity_id=_opaque_id("ro", observation.failure_id),
            source_composition_id=composition.composition_id,
            namespace_digest=composition.namespace.digest,
            source_kind="algorithm_failure",
            safe_failure_code=observation.safe_failure_code,
            failed_stage=observation.failed_stage,
            transition_id=observation.transition_id,
            host_allowed_locator_ids=allowed_locators,
            feasible_branches=feasible,
            public_seed=public_seed,
            created_seq=next_seq,
            expiry_seq=next_seq + opportunity_ttl_events,
        )
        if self._repair_opportunity_verifier is None:
            raise RuntimeError(
                "no trusted repair-opportunity verifier is installed"
            )
        try:
            verified = bool(
                self._repair_opportunity_verifier(
                    opportunity,
                    observation,
                    composition,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "trusted repair-opportunity verification failed"
            ) from exc
        if not verified:
            raise ValueError(
                "trusted repair-opportunity verifier rejected branch authority"
            )
        self._install(
            self._next_state(
                failures=(*self._state.failures, observation),
                repair_opportunities=(*self._state.repair_opportunities, opportunity),
            )
        )
        return opportunity

    @_atomic_bank_update
    def allocate_branch(self, repair_opportunity_id: str) -> BranchAssignmentV2:
        opportunity = next(
            (
                item for item in self._state.repair_opportunities
                if item.opportunity_id == repair_opportunity_id
            ),
            None,
        )
        if opportunity is None:
            raise ValueError("repair opportunity does not exist")
        if self._state.event_seq > opportunity.expiry_seq:
            raise ValueError("repair opportunity has expired")
        if any(
            item.repair_opportunity_id == opportunity.opportunity_id
            for item in self._state.branch_assignments
        ):
            raise ValueError("repair opportunity already owns a branch assignment")
        if len(self._state.branch_assignments) >= (
            self._state.capacity_policy.max_branch_assignments
        ):
            raise RuntimeError("branch-assignment capacity is exhausted")
        opportunities = {
            item.opportunity_id: item for item in self._state.repair_opportunities
        }
        counts = {branch: 0 for branch in ("reuse", "mutate", "fresh")}
        for item in self._state.branch_assignments:
            prior = opportunities[item.repair_opportunity_id]
            if prior.namespace_digest == opportunity.namespace_digest:
                counts[item.branch] += 1
        total = sum(counts.values())
        candidates: list[tuple[float, str, ScientificBranch]] = []
        for branch in opportunity.feasible_branches:
            deficit = (total + 1) / 3 - counts[branch]
            tiebreak = _sha256(
                {
                    "seed": opportunity.public_seed,
                    "opportunity": opportunity.opportunity_id,
                    "branch": branch,
                }
            )
            candidates.append((deficit, tiebreak, branch))
        _deficit, tiebreak, chosen = max(candidates)
        next_seq = self._state.event_seq + 1
        assignment = BranchAssignmentV2(
            assignment_id=_opaque_id(
                "ba",
                {
                    "opportunity": opportunity.opportunity_id,
                    "namespace_ordinal": total,
                    "branch": chosen,
                },
            ),
            repair_opportunity_id=opportunity.opportunity_id,
            repair_opportunity_sha256=opportunity.digest,
            namespace_digest=opportunity.namespace_digest,
            source_composition_id=opportunity.source_composition_id,
            branch=chosen,
            assigned_counts_before=tuple(
                (branch, counts[branch]) for branch in ("reuse", "mutate", "fresh")
            ),
            selector_policy_sha256=_BRANCH_SELECTOR_POLICY_SHA256,
            public_tiebreak_sha256=tiebreak,
            created_seq=next_seq,
        )
        self._install(
            self._next_state(
                branch_assignments=(*self._state.branch_assignments, assignment)
            )
        )
        return assignment

    @_atomic_bank_update
    def archive_for_capacity(
        self,
        namespace: ExecutionNamespace,
        *,
        archive_attestation_sha256: str,
        required_hot_slots: int = 0,
        max_victims: int = 8,
    ) -> ColdCheckpointV2 | None:
        """Apply deterministic harm-before-unknown archival for one namespace.

        Active/rollback/base heads, pending gates, and unsettled/open probe
        plans form a protected closure.  Detailed settled evidence is exported
        under one host-attested Merkle root before local plan/receipt rows are
        compacted.  Factors/compositions retain structural identity only; no
        archived utility is copied to another edge.
        """

        namespace = ExecutionNamespace.model_validate(namespace.model_dump(mode="python"))
        _require_sha(archive_attestation_sha256, "archive_attestation_sha256")
        if required_hot_slots < 0:
            raise ValueError("required_hot_slots must be non-negative")
        if max_victims < 1 or max_victims > 64:
            raise ValueError("max_victims is outside the bounded range")
        if len(self._state.checkpoints) >= self._state.capacity_policy.max_checkpoints:
            raise RuntimeError("cold-checkpoint capacity is exhausted")
        plans_by_transition: dict[str, list[ProbePlanV2]] = {}
        for plan in self._state.plans:
            plans_by_transition.setdefault(plan.transition_id, []).append(plan)
        assessment_by_plan = {item.plan_id: item for item in self._state.assessments}
        protected_transition_ids = {
            item.active_transition_id
            for item in self._state.deployment_heads
            if item.state == "active" and item.active_transition_id is not None
        }
        protected_transition_ids.update(
            item.transition_id
            for item in self._state.gate_opportunities
            if item.state == "pending"
        )
        # A nonterminal proposal action is a live cross-registry transaction.  Its
        # projected edge and source/target closure cannot be archived before
        # the carrier terminal either commits or aborts the action.
        protected_transition_ids.update(
            item.transition_id
            for item in self._state.direct_transitions
            if item.proposal_action_id is not None
            and item.proposal_action_committed_seq is None
        )
        for plan in self._state.plans:
            assessment = assessment_by_plan[plan.plan_id]
            if not assessment.settled or any(
                item.plan_id == plan.plan_id and item.state == "open"
                for item in self._state.attempts
            ):
                protected_transition_ids.add(plan.transition_id)
        protected_composition_ids = {
            item.active_composition_id
            for item in self._state.deployment_heads
            if item.state == "active" and item.active_composition_id is not None
        }
        # Protect both PREPARE and START_ONCE execution windows, including exact
        # mutate parents, reuse-selected content, and a generated target once an
        # inert edge has made it locally known.
        active_actions = tuple(
            item for item in self._state.proposal_actions
            if item.state in {"prepared", "executing"}
        )
        # Before a reuse/generation action has projected its own exact member,
        # its target bytes may be absent.  Protect every existing scientific
        # member at the reserved canonical source/locus; otherwise capacity
        # archival could make the action's later exact alias look like an
        # attempted resurrection even though PREPARE preceded the checkpoint.
        protected_transition_ids.update(
            transition.transition_id
            for transition in self._state.direct_transitions
            for action in active_actions
            if action.branch == "reuse"
            and self._action_matches_exact_locus(
                self._state,
                action,
                namespace_digest=transition.namespace.digest,
                source_composition_id=transition.source_composition_id,
                slot_id=transition.slot_id,
                from_revision_id=transition.from_revision_id,
            )
        )
        protected_action_factor_ids = {
            revision_id
            for action in active_actions
            for revision_id in (
                action.from_revision_id,
                *action.dependency_factor_ids,
                action.selected_target_revision_id,
                action.resolved_to_revision_id,
            )
            if revision_id is not None
        }
        protected_composition_ids.update(
            action.source_composition_id for action in active_actions
        )
        active_action_ids = {action.action_id for action in active_actions}
        protected_composition_ids.update(
            transition.target_composition_id
            for transition in self._state.direct_transitions
            if transition.proposal_action_id in active_action_ids
        )
        protected_composition_ids.update(
            composition.composition_id
            for composition in self._state.compositions
            if composition.structural_state == "live"
            and any(
                factor_id in protected_action_factor_ids
                for factor_id in composition.binding_map.values()
            )
        )
        snapshots = {item.snapshot_id: item for item in self._state.deployment_snapshots}
        for head in self._state.deployment_heads:
            for snapshot_id in (
                head.active_snapshot_id,
                head.predecessor_snapshot_id,
                head.base_fallback_snapshot_id,
            ):
                snapshot = snapshots.get(snapshot_id or "")
                if snapshot is not None:
                    protected_composition_ids.add(snapshot.composition_id)

        label_rank = {
            "quarantine": 0,
            "harmful": 1,
            "infrastructure_exhausted": 2,
            "neutral": 3,
            "candidate": 4,
            "registered": 5,
            "probing": 5,
        }
        disposition_for_label = {
            "quarantine": "quarantine",
            "harmful": "harmful",
            "infrastructure_exhausted": "infrastructure_exhausted",
            "neutral": "neutral",
            "candidate": "expired_candidate",
            "registered": "unknown",
            "probing": "unknown",
        }
        candidates: list[
            tuple[int, int, int, int, str, ScientificTransitionV2, str, EdgeAssessmentV2 | None]
        ] = []
        transitions: tuple[ScientificTransitionV2, ...] = (
            *self._state.direct_transitions,
            *self._state.whole_transitions,
        )
        edge_key_by_transition_id = {
            item.transition_id: self._canonical_scientific_edge_sha256(
                self._state,
                item,
            )
            for item in transitions
        }
        members_by_edge_key: dict[str, list[ScientificTransitionV2]] = {}
        for item in transitions:
            members_by_edge_key.setdefault(
                edge_key_by_transition_id[item.transition_id],
                [],
            ).append(item)
        protected_edge_keys = {
            edge_key_by_transition_id[transition_id]
            for transition_id in protected_transition_ids
            if transition_id in edge_key_by_transition_id
        }
        # A zero-complete infrastructure epoch is scheduler failure, not an
        # evaluated scientific intervention.  Give its canonical owner a
        # bounded archive-stable retry window; after the lease (or retry cap)
        # capacity pressure may explicitly terminate that lifecycle.
        for edge_key, members in members_by_edge_key.items():
            edge_plans = [
                plan
                for member in members
                for plan in plans_by_transition.get(member.transition_id, [])
            ]
            if not edge_plans:
                continue
            latest_plan = max(
                edge_plans,
                key=lambda item: (item.created_seq, item.plan_id),
            )
            latest_assessment = assessment_by_plan[latest_plan.plan_id]
            if (
                latest_assessment.settled
                and latest_assessment.label == "infrastructure_exhausted"
                and latest_assessment.n_complete == 0
                and len(edge_plans)
                < self._state.capacity_policy.max_infrastructure_epochs_per_edge
                and self._state.event_seq
                <= latest_assessment.revision_seq
                + self._state.capacity_policy.infrastructure_retry_lease_events
            ):
                protected_edge_keys.add(edge_key)
        protected_transition_ids.update(
            member.transition_id
            for edge_key in protected_edge_keys
            for member in members_by_edge_key[edge_key]
        )
        for transition in transitions:
            if (
                transition.namespace != namespace
                or transition.structural_state != "live"
                or transition.transition_id in protected_transition_ids
            ):
                continue
            plans = plans_by_transition.get(transition.transition_id, [])
            assessments = [assessment_by_plan[item.plan_id] for item in plans]
            assessment = max(
                assessments,
                key=lambda item: (item.revision_seq, item.assessment_id),
                default=None,
            )
            label = assessment.label if assessment is not None else "registered"
            terminal_ops = [
                item
                for item in self._state.gate_opportunities
                if item.transition_id == transition.transition_id
                and item.state in {"rejected", "capacity_rejected"}
            ]
            if terminal_ops and label not in {"quarantine", "harmful"}:
                rank = 2
                disposition = "gate_rejected"
            else:
                rank = label_rank[label]
                disposition = disposition_for_label[label]
            evidence_count = assessment.n_complete if assessment is not None else 0
            lease = assessment.revision_seq if assessment is not None else transition.created_seq
            candidates.append(
                (
                    rank,
                    lease,
                    transition.created_seq,
                    evidence_count,
                    transition.transition_id,
                    transition,
                    disposition,
                    assessment,
                )
            )
        candidates.sort(key=lambda item: item[:5])
        candidate_items_by_edge: dict[str, list[tuple[Any, ...]]] = {}
        for item in candidates:
            candidate_items_by_edge.setdefault(
                edge_key_by_transition_id[str(item[4])],
                [],
            ).append(item)
        unknown_edge_keys = {
            edge_key_by_transition_id[str(item[4])]
            for item in candidates
            if item[0] == 5
            and all(
                sibling[0] == 5
                for sibling in candidate_items_by_edge[
                    edge_key_by_transition_id[str(item[4])]
                ]
            )
        }
        unknown_archive_budget = max(
            0,
            len(unknown_edge_keys)
            - self._state.capacity_policy.unknown_structural_reserve,
        )
        live_compositions = [
            item
            for item in self._state.compositions
            if item.namespace == namespace and item.structural_state == "live"
        ]
        target_hot = (
            self._state.capacity_policy.max_hot_compositions_per_namespace
            + self._state.capacity_policy.unknown_structural_reserve
        )
        needed = max(0, len(live_compositions) + required_hot_slots - target_hot)
        selected: list[tuple[Any, ...]] = []
        unknown_selected = 0
        selected_edge_keys: set[str] = set()
        for item in candidates:
            edge_key = edge_key_by_transition_id[str(item[4])]
            if edge_key in selected_edge_keys:
                continue
            grouped_items = candidate_items_by_edge[edge_key]
            must_archive_harm = any(member[0] <= 1 for member in grouped_items)
            if not must_archive_harm and len(selected_edge_keys) >= needed:
                continue
            if edge_key in unknown_edge_keys:
                if unknown_selected >= unknown_archive_budget:
                    continue
                unknown_selected += 1
            selected.extend(grouped_items)
            selected_edge_keys.add(edge_key)
            if len(selected_edge_keys) >= max_victims:
                break
        if not selected:
            return None
        durable_negative = [
            item
            for item in selected
            if item[6] in {"harmful", "quarantine", "gate_rejected"}
        ]
        if len(self._state.tombstones) + len(durable_negative) > (
            self._state.capacity_policy.max_recent_tombstones
        ):
            raise RuntimeError(
                "durable negative-tombstone capacity is exhausted"
            )
        archived_transition_ids = {str(item[4]) for item in selected}
        archived_plan_ids = {
            plan.plan_id
            for transition_id in archived_transition_ids
            for plan in plans_by_transition.get(transition_id, [])
        }
        archived_plans = tuple(
            plan for plan in self._state.plans if plan.plan_id in archived_plan_ids
        )
        archived_epoch_manifests = tuple(
            sorted(
                (
                    ArchivedEpochManifestV1(
                        canonical_scientific_edge_key_sha256=(
                            plan.canonical_scientific_edge_key_sha256
                        ),
                        credit_owner_transition_id=(
                            plan.credit_owner_transition_id
                        ),
                        exact_transition_id=plan.transition_id,
                        plan_id=plan.plan_id,
                        epoch_id=plan.epoch_id,
                        unit_commitments=tuple(
                            unit.unit_commitment for unit in plan.units
                        ),
                        plan_sha256=plan.digest,
                    )
                    for plan in archived_plans
                ),
                key=lambda item: item.identity_key,
            )
        )
        archived_attempt_ids = {
            item.attempt_id
            for item in self._state.attempts
            if item.plan_id in archived_plan_ids
        }
        archived_opportunity_ids = {
            item.opportunity_id
            for item in self._state.gate_opportunities
            if item.plan_id in archived_plan_ids
        }
        portable_leaf_sources: list[
            tuple[DirectFactorTransitionV2, EdgeAssessmentV2, PortableEvidenceSign]
        ] = []
        for item in selected:
            transition = item[5]
            if not isinstance(transition, DirectFactorTransitionV2):
                continue
            for plan in plans_by_transition.get(transition.transition_id, []):
                assessment = assessment_by_plan[plan.plan_id]
                sign = _portable_sign_for_assessment(assessment)
                if sign is not None:
                    portable_leaf_sources.append((transition, assessment, sign))
        if len(self._state.portable_evidence_leaves) + len(
            portable_leaf_sources
        ) > self._state.capacity_policy.max_portable_evidence_leaves:
            raise RuntimeError("portable-evidence-leaf capacity is exhausted")
        archive_payload = [
            {
                "transition": item[5],
                "disposition": item[6],
                "assessment": item[7],
                "assessments": [
                    assessment_by_plan[plan.plan_id]
                    for plan in plans_by_transition.get(str(item[4]), [])
                ],
                "plans": plans_by_transition.get(str(item[4]), []),
                "attempts": [
                    attempt
                    for attempt in self._state.attempts
                    if attempt.plan_id in archived_plan_ids
                    and attempt.plan_id
                    in {plan.plan_id for plan in plans_by_transition.get(str(item[4]), [])}
                ],
                "gate_opportunities": [
                    opportunity
                    for opportunity in self._state.gate_opportunities
                    if opportunity.transition_id == str(item[4])
                ],
            }
            for item in selected
        ]
        archive_records_sha256 = _sha256(archive_payload)
        archive_root_body = {
            "namespace_digest": namespace.digest,
            "capacity_policy_sha256": self._state.capacity_policy.digest,
            "archived_epoch_manifests": archived_epoch_manifests,
            "archive_records_sha256": archive_records_sha256,
        }
        merkle_root = _sha256(archive_root_body)
        if self._archive_verifier is None:
            raise RuntimeError("no trusted external archive verifier is installed")
        try:
            verified = bool(
                self._archive_verifier(merkle_root, archive_attestation_sha256)
            )
        except Exception as exc:
            raise RuntimeError("trusted archive verification failed") from exc
        if not verified:
            raise ValueError("trusted archive verifier rejected the checkpoint")
        next_seq = self._state.event_seq + 1
        dispositions: dict[str, int] = {}
        for item in selected:
            dispositions[str(item[6])] = dispositions.get(str(item[6]), 0) + 1
        checkpoint = ColdCheckpointV2(
            checkpoint_id=_opaque_id(
                "cp",
                {
                    "root": merkle_root,
                    "ordinal": len(self._state.checkpoints),
                },
            ),
            namespace_digest=namespace.digest,
            epoch_start_seq=min(int(item[2]) for item in selected),
            epoch_end_seq=self._state.event_seq,
            archive_records_sha256=archive_records_sha256,
            merkle_root_sha256=merkle_root,
            record_count=len(selected),
            subject_ids=tuple(sorted(archived_transition_ids)),
            disposition_counts=tuple(sorted(dispositions.items())),
            archived_epoch_manifests=archived_epoch_manifests,
            capacity_policy_sha256=self._state.capacity_policy.digest,
            archive_attestation_sha256=archive_attestation_sha256,
            created_seq=next_seq,
        )
        state_by_transition = {
            str(item[4]): (
                "quarantine"
                if item[6] == "quarantine"
                else "tombstone"
                if item[6] == "harmful"
                else "cold"
            )
            for item in selected
        }
        direct = tuple(
            item.model_copy(
                update={"structural_state": state_by_transition[item.transition_id]}
            )
            if item.transition_id in state_by_transition
            else item
            for item in self._state.direct_transitions
        )
        whole = tuple(
            item.model_copy(
                update={"structural_state": state_by_transition[item.transition_id]}
            )
            if item.transition_id in state_by_transition
            else item
            for item in self._state.whole_transitions
        )
        selected_targets = {
            item[5].target_composition_id: state_by_transition[str(item[4])]
            for item in selected
        }
        live_other_refs = {
            transition.source_composition_id
            for transition in transitions
            if transition.transition_id not in archived_transition_ids
            and transition.structural_state == "live"
        } | {
            transition.target_composition_id
            for transition in transitions
            if transition.transition_id not in archived_transition_ids
            and transition.structural_state == "live"
        }
        compositions = tuple(
            item.model_copy(update={"structural_state": selected_targets[item.composition_id]})
            if item.composition_id in selected_targets
            and item.composition_id not in protected_composition_ids
            and item.composition_id not in live_other_refs
            else item
            for item in self._state.compositions
        )
        selected_factor_states: dict[str, StructuralState] = {}
        for composition_id, structural_state in selected_targets.items():
            if composition_id in protected_composition_ids or composition_id in live_other_refs:
                continue
            for factor_id in self.compositions[composition_id].binding_map.values():
                selected_factor_states[factor_id] = structural_state
        live_factor_refs = {
            factor_id
            for composition in compositions
            if composition.structural_state == "live"
            for factor_id in composition.binding_map.values()
        }
        factors = tuple(
            item.model_copy(
                update={"structural_state": selected_factor_states[item.revision_id]}
            )
            if item.revision_id in selected_factor_states
            and item.revision_id not in live_factor_refs
            and item.revision_id not in protected_action_factor_ids
            else item
            for item in self._state.factors
        )
        new_tombstones = [
            NegativeTombstoneV2(
                tombstone_id=_opaque_id(
                    "nt",
                    {"transition": item[4], "checkpoint": checkpoint.checkpoint_id},
                ),
                subject_id=str(item[4]),
                namespace_digest=namespace.digest,
                portable_pair_sha256=self._portable_pair_sha256(item[5]),
                background_sha256=self._transition_background_sha256(item[5]),
                disposition=str(item[6]),
                artifact_sha256=self.compositions[
                    item[5].target_composition_id
                ].artifact_sha256,
                evidence_root_sha256=(
                    item[7].evidence_root_sha256 if item[7] is not None else merkle_root
                ),
                created_seq=next_seq,
            )
            for item in durable_negative
        ]
        tombstones = (*self._state.tombstones, *new_tombstones)
        new_portable_leaves: list[PortableEvidenceLeafV1] = []
        for transition, assessment, sign in portable_leaf_sources:
            body = {
                "leaf_version": "sft-portable-evidence-leaf-v1",
                "transition_id": transition.transition_id,
                "namespace_digest": transition.namespace.digest,
                "portable_pair_sha256": self._portable_pair_sha256(transition),
                "background_sha256": transition.fixed_background_sha256,
                "sign": sign,
                "evidence_root_sha256": assessment.evidence_root_sha256,
                "source_assessment_sha256": assessment.digest,
                "source_revision_seq": assessment.revision_seq,
                "checkpoint_id": checkpoint.checkpoint_id,
                "checkpoint_merkle_root_sha256": checkpoint.merkle_root_sha256,
                "created_seq": next_seq,
            }
            new_portable_leaves.append(
                PortableEvidenceLeafV1(
                    leaf_id=_opaque_id("pel", body),
                    **body,
                    bank_attestation_sha256=_mac(
                        self._key,
                        "portable-evidence-leaf-v1",
                        body,
                    ),
                )
            )
        portable_evidence_leaves = (
            *self._state.portable_evidence_leaves,
            *new_portable_leaves,
        )
        attempts = tuple(
            item for item in self._state.attempts if item.plan_id not in archived_plan_ids
        )
        opportunities = tuple(
            item
            for item in self._state.gate_opportunities
            if item.opportunity_id not in archived_opportunity_ids
        )
        candidate = self._next_state(
            direct_transitions=direct,
            whole_transitions=whole,
            factors=factors,
            compositions=compositions,
            plans=tuple(
                item for item in self._state.plans if item.plan_id not in archived_plan_ids
            ),
            reservations=tuple(
                item
                for item in self._state.reservations
                if item.plan_id not in archived_plan_ids
            ),
            attempts=attempts,
            assessments=tuple(
                item
                for item in self._state.assessments
                if item.plan_id not in archived_plan_ids
            ),
            gate_opportunities=opportunities,
            gate_receipts=tuple(
                item
                for item in self._state.gate_receipts
                if item.opportunity_id not in archived_opportunity_ids
            ),
            used_roots=tuple(
                sorted(
                    (
                        root_id,
                        checkpoint.checkpoint_id
                        if owner_id in archived_attempt_ids
                        else owner_id,
                    )
                    for root_id, owner_id in self._state.used_roots
                )
            ),
            used_receipts=tuple(
                sorted(
                    (
                        receipt_id,
                        checkpoint.checkpoint_id
                        if owner_id in archived_attempt_ids
                        else owner_id,
                    )
                    for receipt_id, owner_id in self._state.used_receipts
                )
            ),
            tombstones=tuple(tombstones),
            portable_evidence_leaves=tuple(portable_evidence_leaves),
            checkpoints=(*self._state.checkpoints, checkpoint),
        )
        self._install(candidate)
        return checkpoint

    @staticmethod
    def _candidate_snapshot_for_state(
        state: FactorBankStateV2,
        assessment: EdgeAssessmentV2,
        head: DeploymentHeadV2,
    ) -> str:
        plans = {item.plan_id: item for item in state.plans}
        direct = {item.transition_id: item for item in state.direct_transitions}
        whole = {item.transition_id: item for item in state.whole_transitions}
        compositions = {item.composition_id: item for item in state.compositions}
        factors = {item.revision_id: item for item in state.factors}
        plan = plans[assessment.plan_id]
        transition = direct.get(plan.transition_id) or whole[plan.transition_id]
        target = compositions[transition.target_composition_id]
        dependencies = tuple(
            sorted(
                (slot, factors[factor_id])
                for slot, factor_id in target.binding_map.items()
            )
        )
        return _sha256(
            {
                "plan": plan,
                "assessment": assessment,
                "transition": transition,
                "target": target,
                "dependencies": dependencies,
                "namespace": transition.namespace,
                "capacity_policy": state.capacity_policy,
                "incumbent_head": head,
            }
        )

    def _validate_state(self, state: FactorBankStateV2) -> None:
        if state.event_seq > state.capacity_policy.max_event_seq:
            raise ValueError("persisted event sequence exceeds capacity policy")
        factors = {item.revision_id: item for item in state.factors}
        compositions = {item.composition_id: item for item in state.compositions}
        direct = {item.transition_id: item for item in state.direct_transitions}
        whole = {item.transition_id: item for item in state.whole_transitions}
        transitions: dict[str, ScientificTransitionV2] = {**direct, **whole}
        if len(transitions) != len(direct) + len(whole):
            raise ValueError("direct and whole transition identifiers collide")
        canonical_groups: dict[str, list[ScientificTransitionV2]] = {}
        for transition in transitions.values():
            canonical_groups.setdefault(
                self._canonical_scientific_edge_sha256(state, transition),
                [],
            ).append(transition)
        for siblings in canonical_groups.values():
            ordinary = [
                item
                for item in siblings
                if not isinstance(item, DirectFactorTransitionV2)
                or item.proposal_action_id is None
            ]
            if len(ordinary) > 1:
                raise ValueError(
                    "canonical scientific edge has duplicate ordinary owners"
                )
            if ordinary and self._credit_owner_transition_id(
                state,
                ordinary[0],
            ) != ordinary[0].transition_id:
                raise ValueError(
                    "ordinary scientific edge does not own its canonical intervention"
                )
            live_members = [
                item for item in siblings if item.structural_state == "live"
            ]
            if live_members and len(live_members) != len(siblings):
                raise ValueError(
                    "canonical scientific edge mixes live and archived aliases"
                )
        for factor in state.factors:
            if factor.created_seq > state.event_seq:
                raise ValueError("factor revision is future-dated")
            if factor.parent_revision_id is not None:
                parent = factors.get(factor.parent_revision_id)
                if parent is None:
                    raise ValueError("factor parent revision is missing")
                if parent.logical_factor_id != factor.logical_factor_id or parent.namespace != factor.namespace:
                    raise ValueError("factor parent crosses its logical identity/namespace")
                if parent.created_seq >= factor.created_seq:
                    raise ValueError("factor parent does not causally precede its child")
        for composition in state.compositions:
            if composition.created_seq > state.event_seq:
                raise ValueError("composition revision is future-dated")
            if composition.parent_composition_id is not None:
                parent = compositions.get(composition.parent_composition_id)
                if parent is None or parent.namespace != composition.namespace:
                    raise ValueError("composition parent is missing or crosses namespace")
                if parent.created_seq >= composition.created_seq:
                    raise ValueError(
                        "composition parent does not causally precede its child"
                    )
            for factor_id in composition.binding_map.values():
                factor = factors.get(factor_id)
                if factor is None or factor.namespace != composition.namespace:
                    raise ValueError("composition binding is missing or crosses namespace")
                if factor.created_seq >= composition.created_seq:
                    raise ValueError(
                        "composition binding does not causally precede its owner"
                    )
        for transition in state.direct_transitions:
            if transition.created_seq > state.event_seq:
                raise ValueError("direct transition is future-dated")
            source = compositions.get(transition.source_composition_id)
            target = compositions.get(transition.target_composition_id)
            if source is None or target is None or source.namespace != target.namespace != transition.namespace:
                raise ValueError("direct transition composition/namespace join is invalid")
            if source.namespace != transition.namespace or target.namespace != transition.namespace:
                raise ValueError("direct transition crosses its namespace")
            source_map, target_map = source.binding_map, target.binding_map
            if set(source_map) != set(target_map) or transition.slot_id not in source_map:
                raise ValueError("direct transition slot domain is invalid")
            changed = [slot for slot in sorted(source_map) if source_map[slot] != target_map[slot]]
            if changed != [transition.slot_id]:
                raise ValueError("direct transition is not an exact one-slot intervention")
            if source_map[transition.slot_id] != transition.from_revision_id or (
                target_map[transition.slot_id] != transition.to_revision_id
            ):
                raise ValueError("direct transition from/to revisions do not match compositions")
            old, new = factors[transition.from_revision_id], factors[transition.to_revision_id]
            if any(
                item.created_seq >= transition.created_seq
                for item in (source, target, old, new)
            ):
                raise ValueError(
                    "direct transition inputs do not causally precede the edge"
                )
            if (
                old.binding_status != "proven_factorized"
                or new.binding_status != "proven_factorized"
                or old.logical_factor_id != new.logical_factor_id
                or old.locator != new.locator
                or old.carrier != new.carrier
                or old.content_sha256 == new.content_sha256
            ):
                raise ValueError("direct transition factor content identity is invalid")
            background_pairs = [
                (slot, source_map[slot]) for slot in sorted(source_map)
                if slot != transition.slot_id
            ]
            if _sha256(background_pairs) != transition.fixed_background_sha256:
                raise ValueError("direct transition fixed background is invalid")
            background = tuple(factors[item[1]] for item in background_pairs)
            if self._direct_binding_verifier is None:
                raise RuntimeError("persisted direct transition requires its trusted verifier")
            try:
                valid = bool(
                    self._direct_binding_verifier(
                        transition, source, target, old, new, background
                    )
                )
            except Exception as exc:
                raise RuntimeError("persisted direct binding re-verification failed") from exc
            if not valid:
                raise ValueError("persisted direct binding bundle was rejected")
            if transition.proposal_action_id is None and any(
                self._ordinary_transition_lands_in_action_window(
                    state,
                    transition,
                    action,
                )
                for action in state.proposal_actions
            ):
                raise ValueError(
                    "persisted ordinary transition occupies a proposal action window"
                )
            if transition.proposal_action_id is None and (
                not self._row_can_receive_non_action_authority(
                    state,
                    row_kind="factor",
                    row_id=transition.to_revision_id,
                    before_seq=transition.created_seq,
                    excluding_transition_id=transition.transition_id,
                )
                or not self._row_can_receive_non_action_authority(
                    state,
                    row_kind="composition",
                    row_id=transition.target_composition_id,
                    before_seq=transition.created_seq,
                    excluding_transition_id=transition.transition_id,
                )
            ):
                raise ValueError(
                    "persisted unowned transition launders an ineligible carrier"
                )
        for transition in state.whole_transitions:
            if transition.created_seq > state.event_seq:
                raise ValueError("whole transition is future-dated")
            source = compositions.get(transition.source_composition_id)
            target = compositions.get(transition.target_composition_id)
            if source is None or target is None or source.namespace != target.namespace:
                raise ValueError("whole transition composition join is invalid")
            if source.namespace != transition.namespace:
                raise ValueError("whole transition crosses its namespace")
            if any(
                item.created_seq >= transition.created_seq
                for item in (source, target)
            ):
                raise ValueError(
                    "whole transition inputs do not causally precede the edge"
                )
            slots = sorted(set(source.binding_map) | set(target.binding_map))
            changed = tuple(
                slot for slot in slots
                if source.binding_map.get(slot) != target.binding_map.get(slot)
            )
            if changed != transition.changed_slot_ids:
                raise ValueError("whole transition changed-slot set is not reproducible")
            if (
                source.artifact_sha256 != transition.source_artifact_sha256
                or target.artifact_sha256 != transition.target_artifact_sha256
            ):
                raise ValueError("whole transition artifact join is invalid")
            if self._whole_operation_verifier is None:
                raise RuntimeError("persisted whole transition requires its trusted verifier")
            try:
                valid = bool(self._whole_operation_verifier(transition, source, target))
            except Exception as exc:
                raise RuntimeError("persisted whole-operation verification failed") from exc
            if not valid:
                raise ValueError("persisted whole-operation receipt was rejected")
            if any(
                self._ordinary_transition_lands_in_action_window(
                    state,
                    transition,
                    action,
                )
                for action in state.proposal_actions
            ):
                raise ValueError(
                    "persisted ordinary transition occupies a proposal action window"
                )
            if not self._row_can_receive_non_action_authority(
                state,
                row_kind="composition",
                row_id=transition.target_composition_id,
                before_seq=transition.created_seq,
            ) or any(
                not self._row_can_receive_non_action_authority(
                    state,
                    row_kind="factor",
                    row_id=factor_id,
                    before_seq=transition.created_seq,
                )
                for factor_id in target.binding_map.values()
            ):
                raise ValueError(
                    "persisted whole transition launders an ineligible carrier"
                )
        plans = {item.plan_id: item for item in state.plans}
        seen_plan_epoch: set[tuple[str, str]] = set()
        unit_commitments_by_edge: dict[str, set[str]] = {}
        for plan in state.plans:
            transition = transitions.get(plan.transition_id)
            if transition is None or transition.owner_kind != plan.owner_kind:
                raise ValueError("probe plan transition owner is missing")
            canonical_edge_key = self._canonical_scientific_edge_sha256(
                state,
                transition,
            )
            canonical_background = self._canonical_background_sha256(
                state,
                transition,
            )
            credit_owner_transition_id = self._credit_owner_transition_id(
                state,
                transition,
            )
            if credit_owner_transition_id != transition.transition_id:
                raise ValueError(
                    "probe plan is attached to a canonical edge alias"
                )
            if transition.structural_state != "live":
                raise ValueError("persisted probe plan owns a non-live transition")
            if (
                isinstance(transition, DirectFactorTransitionV2)
                and transition.proposal_action_id is not None
                and (
                    not self._transition_has_execution_authority(
                        state,
                        transition,
                    )
                    or plan.created_seq
                    <= transition.proposal_action_committed_seq
                )
            ):
                raise ValueError(
                    "probe plan predates proposal-action finalization"
                )
            if plan.namespace_digest != transition.namespace.digest:
                raise ValueError("probe plan crosses transition namespace")
            source = compositions[transition.source_composition_id]
            target = compositions[transition.target_composition_id]
            support = (
                transition.binding_proof_sha256
                if isinstance(transition, DirectFactorTransitionV2)
                else transition.operation_receipt_sha256
            )
            fixed = (
                transition.fixed_background_sha256
                if isinstance(transition, DirectFactorTransitionV2)
                else _sha256({"whole": transition.changed_slot_ids})
            )
            if (
                plan.canonical_scientific_edge_key_sha256
                != canonical_edge_key
                or plan.canonical_background_sha256 != canonical_background
                or plan.credit_owner_transition_id
                != credit_owner_transition_id
                or
                plan.source_snapshot_sha256 != _sha256(source)
                or plan.target_snapshot_sha256 != _sha256(target)
                or plan.source_artifact_sha256 != source.artifact_sha256
                or plan.target_artifact_sha256 != target.artifact_sha256
                or plan.binding_or_operation_proof_sha256 != support
                or plan.fixed_background_sha256 != fixed
            ):
                raise ValueError("probe plan frozen support/snapshot join is invalid")
            key = (canonical_edge_key, plan.epoch_id)
            if key in seen_plan_epoch:
                raise ValueError("canonical edge epoch has multiple probe plans")
            seen_plan_epoch.add(key)
            existing_units = unit_commitments_by_edge.setdefault(
                canonical_edge_key, set()
            )
            plan_units = {item.unit_commitment for item in plan.units}
            if existing_units.intersection(plan_units):
                raise ValueError(
                    "probe epochs reuse a unit commitment within one canonical edge"
                )
            existing_units.update(plan_units)
            if self._plan_verifier is None:
                raise RuntimeError("persisted probe plan requires its trusted verifier")
            try:
                valid = bool(self._plan_verifier(plan))
            except Exception as exc:
                raise RuntimeError("persisted probe-plan verification failed") from exc
            if not valid:
                raise ValueError("persisted probe plan was rejected")
        checkpoint_manifests = [
            manifest
            for checkpoint in state.checkpoints
            for manifest in checkpoint.archived_epoch_manifests
        ]
        archived_plan_ids = [item.plan_id for item in checkpoint_manifests]
        if len(archived_plan_ids) != len(set(archived_plan_ids)):
            raise ValueError("checkpoint plan manifests overlap")
        archived_plan_digests = [item.plan_sha256 for item in checkpoint_manifests]
        if len(archived_plan_digests) != len(set(archived_plan_digests)):
            raise ValueError("checkpoint plan digest owners overlap")
        if set(archived_plan_ids).intersection(plans):
            raise ValueError("active and checkpoint plan owners overlap")
        if len(state.plans) + len(checkpoint_manifests) > (
            state.capacity_policy.max_plan_records
        ):
            raise ValueError("persisted active/checkpoint plan owners exceed capacity")
        used_unit_commitments = set(state.used_unit_commitments)
        active_unit_commitments = {
            (plan.canonical_scientific_edge_key_sha256, unit.unit_commitment)
            for plan in state.plans
            for unit in plan.units
        }
        checkpoint_unit_rows = [
            (
                manifest.canonical_scientific_edge_key_sha256,
                unit_commitment,
            )
            for manifest in checkpoint_manifests
            for unit_commitment in manifest.unit_commitments
        ]
        if len(checkpoint_unit_rows) != len(set(checkpoint_unit_rows)):
            raise ValueError("checkpoint unit registries overlap")
        checkpoint_unit_commitments = set(checkpoint_unit_rows)
        if active_unit_commitments.intersection(checkpoint_unit_commitments):
            raise ValueError("active and checkpoint unit owners overlap")
        if used_unit_commitments != (
            active_unit_commitments | checkpoint_unit_commitments
        ):
            raise ValueError(
                "lifetime unit registry lacks an active/checkpoint owner"
            )
        known_edge_keys = set(canonical_groups)
        if any(
            edge_key not in known_edge_keys
            for edge_key, _unit_commitment in used_unit_commitments
        ):
            raise ValueError("lifetime unit registry names an unknown canonical edge")
        if len(used_unit_commitments) > state.capacity_policy.max_unit_commitments:
            raise ValueError("persisted lifetime unit commitments exceed capacity")
        used_edge_epochs = set(state.used_edge_epochs)
        active_edge_epochs = {
            (plan.canonical_scientific_edge_key_sha256, plan.epoch_id)
            for plan in state.plans
        }
        checkpoint_epoch_rows = [
            (
                manifest.canonical_scientific_edge_key_sha256,
                manifest.epoch_id,
            )
            for manifest in checkpoint_manifests
        ]
        if len(checkpoint_epoch_rows) != len(set(checkpoint_epoch_rows)):
            raise ValueError("checkpoint epoch registries overlap")
        checkpoint_edge_epochs = set(checkpoint_epoch_rows)
        if active_edge_epochs.intersection(checkpoint_edge_epochs):
            raise ValueError("active and checkpoint epoch owners overlap")
        if used_edge_epochs != (active_edge_epochs | checkpoint_edge_epochs):
            raise ValueError(
                "lifetime epoch registry lacks an active/checkpoint owner"
            )
        if any(edge_key not in known_edge_keys for edge_key, _ in used_edge_epochs):
            raise ValueError("lifetime epoch registry names an unknown canonical edge")
        if len(used_edge_epochs) > state.capacity_policy.max_plan_records:
            raise ValueError("persisted lifetime edge epochs exceed capacity")
        reservations = {item.plan_id: item for item in state.reservations}
        if set(reservations) != set(plans):
            raise ValueError("every probe plan requires one capacity reservation")
        attempts_by_plan: dict[str, list[ProbeAttemptV3]] = {item: [] for item in plans}
        for attempt in state.attempts:
            plan = plans.get(attempt.plan_id)
            if plan is None:
                raise ValueError("probe attempt plan is missing")
            attempts_by_plan[plan.plan_id].append(attempt)
            unit = plan.units[attempt.ordinal]
            assignment = attempt.assignment
            if not (
                assignment.plan_id == plan.plan_id
                and assignment.plan_sha256 == plan.digest
                and assignment.ordinal == attempt.ordinal
                and assignment.unit_commitment == unit.unit_commitment
                and assignment.arm_order == unit.arm_order
                and assignment.assignment_manifest_sha256 == plan.assignment_manifest_sha256
                and assignment.without_replacement_index == attempt.ordinal
            ):
                raise ValueError("persisted assignment differs from its frozen plan")
            if self._assignment_verifier is None:
                raise RuntimeError("persisted attempt requires assignment verifier")
            try:
                valid = bool(self._assignment_verifier(assignment, plan))
            except Exception as exc:
                raise RuntimeError("persisted assignment verification failed") from exc
            if not valid:
                raise ValueError("persisted assignment receipt was rejected")
            lease = attempt.runner_lease
            if not (
                lease.attempt_id == attempt.attempt_id
                and lease.plan_id == plan.plan_id
                and lease.ordinal == attempt.ordinal
                and lease.assignment_receipt_sha256 == _sha256(assignment)
                and lease.scheduled_arm_order == assignment.arm_order
                and lease.fencing_generation == 1
            ):
                raise ValueError("persisted runner lease does not join its attempt")
            if self._runner_lease_verifier is None:
                raise RuntimeError("persisted attempt requires runner lease verifier")
            try:
                lease_valid = bool(
                    self._runner_lease_verifier(lease, assignment, plan)
                )
            except Exception as exc:
                raise RuntimeError("persisted runner lease verification failed") from exc
            if not lease_valid:
                raise ValueError("persisted runner lease was rejected")
            if attempt.settled_seq is not None and attempt.settled_seq > state.event_seq:
                raise ValueError("attempt settlement is later than the owning Bank state")
            if attempt.state == "cancelled":
                cancellation = attempt.cancellation_receipt
                assert cancellation is not None
                open_payload = attempt.model_dump(mode="python")
                open_payload.update(
                    {
                        "state": "open",
                        "presented_root_ids": (),
                        "presented_receipt_ids": (),
                        "disposition_reason": None,
                        "cancellation_receipt": None,
                        "settled_seq": None,
                    }
                )
                open_attempt = ProbeAttemptV3.model_validate(open_payload)
                if not (
                    cancellation.attempt_id == open_attempt.attempt_id
                    and cancellation.plan_id == plan.plan_id
                    and cancellation.ordinal == open_attempt.ordinal
                    and cancellation.assignment_receipt_sha256 == _sha256(assignment)
                    and cancellation.expected_opened_seq == open_attempt.opened_seq
                    and cancellation.expected_open_attempt_sha256 == _sha256(open_attempt)
                    and cancellation.scheduled_arm_order
                    == open_attempt.assignment.arm_order
                    and cancellation.runner_lease_sha256 == lease.digest
                    and cancellation.runner_lease_token_sha256
                    == lease.runner_lease_token_sha256
                    and cancellation.runner_session_id == lease.runner_session_id
                    and cancellation.journal_anchor_sha256
                    == lease.journal_anchor_sha256
                    and cancellation.fencing_generation == lease.fencing_generation
                    and cancellation.next_fencing_generation == 2
                    and attempt.disposition_reason == cancellation.safe_failure_code
                    and attempt.presented_root_ids
                    == (
                        *(
                            item.root_id
                            for item in cancellation.started_arm_roots
                        ),
                        cancellation.runner_event_root_sha256,
                    )
                    and attempt.presented_receipt_ids
                    == (cancellation.cancellation_id,)
                ):
                    raise ValueError(
                        "persisted cancellation does not join its exact open attempt"
                    )
                if self._cancellation_verifier is None:
                    raise RuntimeError(
                        "persisted cancellation requires its trusted verifier"
                    )
                try:
                    valid = bool(
                        self._cancellation_verifier(
                            cancellation, open_attempt, plan
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted cancellation verification failed"
                    ) from exc
                if not valid:
                    raise ValueError("persisted cancellation receipt was rejected")
            if attempt.source_receipt is not None and attempt.target_receipt is not None:
                source_receipt = attempt.source_receipt
                target_receipt = attempt.target_receipt
                pair_receipt = attempt.pair_execution_receipt
                if pair_receipt is None:
                    raise ValueError("persisted arm receipts lack a terminal pair receipt")
                open_payload = attempt.model_dump(mode="python")
                open_payload.update(
                    {
                        "state": "open",
                        "pair_execution_receipt": None,
                        "source_receipt": None,
                        "target_receipt": None,
                        "presented_root_ids": (),
                        "presented_receipt_ids": (),
                        "disposition_reason": None,
                        "cancellation_receipt": None,
                        "settled_seq": None,
                    }
                )
                open_attempt = ProbeAttemptV3.model_validate(open_payload)
                if self._pair_execution_receipt_verifier is None:
                    raise RuntimeError(
                        "persisted pair receipt requires its trusted verifier"
                    )
                try:
                    pair_verified = bool(
                        self._pair_execution_receipt_verifier(
                            pair_receipt, open_attempt, plan
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted paired-execution verification failed"
                    ) from exc
                pair_root = paired_execution_root_v2(
                    assignment=assignment,
                    pair_receipt=pair_receipt,
                )
                expected_presented_roots = (
                    source_receipt.root_id,
                    target_receipt.root_id,
                    pair_receipt.runner_event_root_sha256,
                )
                pair_valid = bool(
                    pair_receipt.plan_id == plan.plan_id
                    and pair_receipt.ordinal == attempt.ordinal
                    and pair_receipt.assignment_receipt_sha256 == _sha256(assignment)
                    and pair_receipt.expected_open_attempt_sha256
                    == _sha256(open_attempt)
                    and pair_receipt.scheduled_arm_order == assignment.arm_order
                    and pair_receipt.runner_lease_sha256 == lease.digest
                    and pair_receipt.runner_lease_token_sha256
                    == lease.runner_lease_token_sha256
                    and pair_receipt.runner_session_id == lease.runner_session_id
                    and pair_receipt.journal_anchor_sha256
                    == lease.journal_anchor_sha256
                    and pair_receipt.fencing_generation == lease.fencing_generation
                    and pair_receipt.observed_arm_order == assignment.arm_order
                    and pair_receipt.source_root_id == source_receipt.root_id
                    and pair_receipt.target_root_id == target_receipt.root_id
                    and pair_verified
                    and source_receipt.observed_arm_order
                    == pair_receipt.observed_arm_order
                    and target_receipt.observed_arm_order
                    == pair_receipt.observed_arm_order
                    and source_receipt.arm_position
                    == (0 if pair_receipt.observed_arm_order == "AB" else 1)
                    and target_receipt.arm_position
                    == (1 if pair_receipt.observed_arm_order == "AB" else 0)
                    and source_receipt.paired_execution_root_sha256 == pair_root
                    and target_receipt.paired_execution_root_sha256 == pair_root
                    and source_receipt.pair_execution_receipt_sha256
                    == pair_receipt.digest
                    and target_receipt.pair_execution_receipt_sha256
                    == pair_receipt.digest
                    and len(set(expected_presented_roots)) == 3
                    and attempt.presented_root_ids == expected_presented_roots
                    and attempt.presented_receipt_ids
                    == (
                        source_receipt.receipt_id,
                        target_receipt.receipt_id,
                        pair_receipt.pair_receipt_id,
                    )
                )
                if not pair_valid and attempt.state != "quarantine":
                    raise ValueError("persisted paired execution receipt is invalid")
                transition = transitions[plan.transition_id]
                for arm, receipt in (("source", attempt.source_receipt), ("target", attempt.target_receipt)):
                    composition_id = (
                        transition.source_composition_id if arm == "source"
                        else transition.target_composition_id
                    )
                    composition = compositions[composition_id]
                    artifact = (
                        plan.source_artifact_sha256 if arm == "source"
                        else plan.target_artifact_sha256
                    )
                    expected_direct = (
                        (
                            transition.from_revision_id if arm == "source"
                            else transition.to_revision_id,
                        )
                        if isinstance(transition, DirectFactorTransitionV2) else ()
                    )
                    support_id = (
                        transition.binding_proof_id
                        if isinstance(transition, DirectFactorTransitionV2)
                        else transition.transition_id
                    )
                    if not (
                        receipt.plan_id == plan.plan_id
                        and receipt.ordinal == attempt.ordinal
                        and receipt.arm == arm
                        and receipt.observed_arm_order
                        == pair_receipt.observed_arm_order
                        and receipt.arm_position
                        == (
                            0
                            if (
                                (
                                    pair_receipt.observed_arm_order == "AB"
                                    and arm == "source"
                                )
                                or (
                                    pair_receipt.observed_arm_order == "BA"
                                    and arm == "target"
                                )
                            )
                            else 1
                        )
                        and receipt.pair_execution_receipt_sha256
                        == pair_receipt.digest
                        and receipt.assignment_receipt_sha256 == _sha256(assignment)
                        and receipt.unit_commitment == assignment.unit_commitment
                        and receipt.namespace_digest == plan.namespace_digest
                        and receipt.composition_id == composition_id
                        and receipt.assigned_artifact_sha256 == artifact
                        and receipt.materialized_artifact_sha256 == artifact
                        and receipt.selected_artifact_sha256 == artifact
                        and receipt.loaded_artifact_sha256 == artifact
                        and tuple(sorted(receipt.loaded_binding_ids))
                        == tuple(sorted(composition.binding_map.values()))
                        and receipt.activated_direct_factor_revision_ids == expected_direct
                        and receipt.binding_proof_id == support_id
                        and receipt.model_name == plan.model_name
                        and receipt.runtime_version == plan.runtime_version
                        and receipt.budget_sha256 == plan.budget_sha256
                        and receipt.usage.within(plan.budget)
                    ):
                        if attempt.state != "quarantine":
                            raise ValueError("persisted arm receipt join is invalid")
                    if self._arm_receipt_verifier is None:
                        raise RuntimeError("persisted receipt requires trusted verifier")
                    try:
                        valid = bool(self._arm_receipt_verifier(receipt, plan, assignment))
                    except Exception as exc:
                        raise RuntimeError("persisted arm receipt verification failed") from exc
                    if not valid and attempt.state != "quarantine":
                        raise ValueError("persisted execution receipt was rejected")
        for plan_id, attempts in attempts_by_plan.items():
            attempts.sort(key=lambda item: item.ordinal)
            if [item.ordinal for item in attempts] != list(range(len(attempts))):
                raise ValueError("persisted attempts do not form an ordinal prefix")
            if sum(item.state == "open" for item in attempts) > 1:
                raise ValueError("probe plan has more than one open attempt")
        used_roots = dict(state.used_roots)
        used_receipts = dict(state.used_receipts)
        checkpoint_ids = {item.checkpoint_id for item in state.checkpoints}
        attempts_by_id = {item.attempt_id: item for item in state.attempts}

        def validate_consumed_registry(
            registry: Mapping[str, str],
            *,
            receipt_registry: bool,
        ) -> None:
            attribute = (
                "presented_receipt_ids" if receipt_registry else "presented_root_ids"
            )
            label = "receipt" if receipt_registry else "physical root"
            for identity, owner_id in registry.items():
                if owner_id in checkpoint_ids:
                    continue
                owner = attempts_by_id.get(owner_id)
                if owner is None or identity not in getattr(owner, attribute):
                    raise ValueError(f"consumed {label} lacks its first owner")
            for attempt in state.attempts:
                for identity in getattr(attempt, attribute):
                    owner_id = registry.get(identity)
                    if owner_id is None:
                        raise ValueError(f"presented {label} is not consumed")
                    if owner_id == attempt.attempt_id:
                        continue
                    if attempt.state != "quarantine":
                        raise ValueError(f"shared {label} did not quarantine the replay")
                    owner = attempts_by_id.get(owner_id)
                    if owner is not None and owner.opened_seq >= attempt.opened_seq:
                        raise ValueError(f"shared {label} points to a later owner")
                    if owner is None and owner_id not in checkpoint_ids:
                        raise ValueError(f"shared {label} owner is missing")

        validate_consumed_registry(used_roots, receipt_registry=False)
        validate_consumed_registry(used_receipts, receipt_registry=True)
        assessments = {item.plan_id: item for item in state.assessments}
        if set(assessments) != set(plans):
            raise ValueError("every probe plan requires one assessment cache")
        for plan_id, plan in plans.items():
            stored = assessments[plan_id]
            recomputed = recompute_assessment(
                plan,
                attempts_by_plan[plan_id],
                revision_seq=stored.revision_seq,
            )
            if stored != recomputed:
                raise ValueError("persisted edge assessment is not a pure evidence recomputation")
            if stored.settled and any(item.state == "open" for item in attempts_by_plan[plan_id]):
                raise ValueError("settled assessment retains an open attempt")
            reservation = reservations[plan_id]
            if stored.settled != (reservation.state == "released"):
                raise ValueError("plan capacity reservation release is inconsistent")
        plans_by_edge: dict[str, list[ProbePlanV2]] = {}
        for plan in state.plans:
            plans_by_edge.setdefault(
                plan.canonical_scientific_edge_key_sha256,
                [],
            ).append(plan)
        for edge_key, scoped in plans_by_edge.items():
            ordered = sorted(
                scoped,
                key=lambda item: (item.created_seq, item.plan_id),
            )
            if len(ordered) > (
                state.capacity_policy.max_infrastructure_epochs_per_edge
            ):
                raise ValueError(
                    "canonical edge exceeds its infrastructure epoch cap"
                )
            for prior, successor in zip(ordered, ordered[1:]):
                prior_assessment = assessments[prior.plan_id]
                if not (
                    prior_assessment.settled
                    and prior_assessment.label == "infrastructure_exhausted"
                    and prior_assessment.n_complete == 0
                    and prior_assessment.n_open == 0
                    and prior_assessment.revision_seq < successor.created_seq
                    and not any(
                        item.plan_id == prior.plan_id and item.state == "open"
                        for item in state.attempts
                    )
                    and not any(
                        item.plan_id == prior.plan_id and item.state == "pending"
                        for item in state.gate_opportunities
                    )
                ):
                    raise ValueError(
                        "canonical edge retry lacks a zero-complete "
                        "infrastructure predecessor"
                    )
        snapshots = {
            item.snapshot_id: item for item in state.deployment_snapshots
        }
        deployment_heads_by_slot = {
            item.deployment_slot_id: item for item in state.deployment_heads
        }
        rollback_triggers = {
            item.trigger_id: item for item in state.rollback_triggers
        }
        rollback_records_by_trigger: dict[str, list[RollbackRecordV2]] = {}
        for record in state.rollback_records:
            rollback_records_by_trigger.setdefault(
                record.trigger_id,
                [],
            ).append(record)
        if set(rollback_records_by_trigger) != set(rollback_triggers):
            raise ValueError(
                "rollback triggers and records must form an exact join"
            )
        for trigger_id, trigger in rollback_triggers.items():
            records = rollback_records_by_trigger[trigger_id]
            if len(records) != 1:
                raise ValueError("rollback trigger must own exactly one record")
            record = records[0]
            old_snapshot = snapshots.get(trigger.active_snapshot_id)
            if old_snapshot is None:
                raise ValueError("rollback active snapshot is missing")
            if not (
                record.old_snapshot_id == trigger.active_snapshot_id
                and record.deployment_slot_id == trigger.deployment_slot_id
                and record.old_generation == trigger.expected_head_generation
                and record.created_seq == trigger.emitted_seq
                and trigger.emitted_seq <= state.event_seq
                and old_snapshot.deployment_slot_id
                == trigger.deployment_slot_id
                and old_snapshot.created_seq < trigger.emitted_seq
            ):
                raise ValueError("rollback trigger/record/snapshot join is invalid")
            if (
                old_snapshot.transition_id is not None
                and old_snapshot.transition_id not in transitions
            ):
                raise ValueError("rollback snapshot transition is missing")
            slot_head = deployment_heads_by_slot.get(
                trigger.deployment_slot_id
            )
            predecessor = (
                snapshots.get(old_snapshot.predecessor_snapshot_id)
                if old_snapshot.predecessor_snapshot_id is not None
                else None
            )
            base = (
                snapshots.get(slot_head.base_fallback_snapshot_id)
                if (
                    slot_head is not None
                    and slot_head.base_fallback_snapshot_id is not None
                )
                else None
            )
            if predecessor is not None:
                expected_restored_snapshot_id = predecessor.snapshot_id
                expected_disposition = "restored_predecessor"
            elif base is not None:
                expected_restored_snapshot_id = base.snapshot_id
                expected_disposition = "restored_base"
            else:
                expected_restored_snapshot_id = None
                expected_disposition = "disabled"
            if not (
                record.restored_snapshot_id
                == expected_restored_snapshot_id
                and record.disposition == expected_disposition
            ):
                raise ValueError("rollback restoration is not deterministic")

        harmful_assessments = [
            item
            for item in assessments.values()
            if item.catastrophic_harm or item.label == "harmful"
        ]
        harmful_tombstone_ids = {
            item.subject_id
            for item in state.tombstones
            if item.disposition == "harmful"
        }
        harmful_tombstone_edge_keys = {
            self._canonical_scientific_edge_sha256(
                state,
                transitions[transition_id],
            )
            for transition_id in harmful_tombstone_ids
            if transition_id in transitions
        }
        harmful_edge_keys = set(harmful_tombstone_edge_keys)
        harmful_edge_keys.update(
            plans[item.plan_id].canonical_scientific_edge_key_sha256
            for item in harmful_assessments
        )
        rollback_harm_by_edge = self._rollback_harm_evidence_by_edge(state)
        harmful_edge_keys.update(rollback_harm_by_edge)
        harmful_transition_ids = {
            transition.transition_id
            for edge_key in harmful_edge_keys
            for transition in canonical_groups.get(edge_key, [])
        }
        if any(
            plan.canonical_scientific_edge_key_sha256
            in harmful_tombstone_edge_keys
            for plan in state.plans
        ):
            raise ValueError("archived harmful canonical edge retains a probe epoch")
        for harmful in harmful_assessments:
            harmful_plan = plans[harmful.plan_id]
            harmful_edge_key = (
                harmful_plan.canonical_scientific_edge_key_sha256
            )
            for plan in state.plans:
                if (
                    plan.canonical_scientific_edge_key_sha256
                    == harmful_edge_key
                    and plan.plan_id != harmful.plan_id
                    and plan.created_seq > harmful.revision_seq
                ):
                    raise ValueError(
                        "harmful transition was bypassed by a later probe epoch"
                    )
            for attempt in state.attempts:
                attempt_plan = plans[attempt.plan_id]
                if (
                    attempt_plan.canonical_scientific_edge_key_sha256
                    == harmful_edge_key
                    and attempt_plan.plan_id != harmful.plan_id
                    and attempt.opened_seq > harmful.revision_seq
                ):
                    raise ValueError(
                        "probe attempt bypasses prior harm through another epoch"
                    )
        rollback_harm_seq_by_edge: dict[str, int] = {}
        for trigger in state.rollback_triggers:
            if trigger.kind != "train_monitor_harm":
                continue
            snapshot = snapshots[trigger.active_snapshot_id]
            if snapshot.transition_id is None:
                continue
            edge_key = self._canonical_scientific_edge_sha256(
                state,
                transitions[snapshot.transition_id],
            )
            rollback_harm_seq_by_edge[edge_key] = min(
                trigger.emitted_seq,
                rollback_harm_seq_by_edge.get(edge_key, trigger.emitted_seq),
            )
        for plan in state.plans:
            harm_seq = rollback_harm_seq_by_edge.get(
                plan.canonical_scientific_edge_key_sha256
            )
            if harm_seq is not None and plan.created_seq >= harm_seq:
                raise ValueError("probe plan does not causally precede rollback harm")
        for attempt in state.attempts:
            plan = plans[attempt.plan_id]
            harm_seq = rollback_harm_seq_by_edge.get(
                plan.canonical_scientific_edge_key_sha256
            )
            if harm_seq is not None and attempt.opened_seq >= harm_seq:
                raise ValueError("probe attempt does not causally precede rollback harm")
        heads = {item.deployment_slot_id: item for item in state.deployment_heads}
        base_receipts = {item.receipt_id: item for item in state.base_receipts}
        for receipt in state.base_receipts:
            composition = compositions.get(receipt.composition_id)
            if composition is None:
                raise ValueError("base receipt composition is missing")
            if receipt.emitted_seq > state.event_seq:
                raise ValueError("base receipt is future-dated")
            if not self._composition_can_receive_non_action_authority(
                state,
                composition,
                before_seq=receipt.emitted_seq,
            ):
                raise ValueError(
                    "base receipt predates proposal carrier admission"
                )
            if self._base_snapshot_verifier is None:
                raise RuntimeError("persisted base snapshot requires trusted verifier")
            try:
                valid = bool(self._base_snapshot_verifier(receipt, state))
            except Exception as exc:
                raise RuntimeError("persisted base snapshot verification failed") from exc
            if not valid:
                raise ValueError("persisted base snapshot receipt was rejected")
        gate_receipts = {item.decision_id: item for item in state.gate_receipts}
        opportunities = {item.opportunity_id: item for item in state.gate_opportunities}
        for receipt in state.gate_receipts:
            if receipt.emitted_seq > state.event_seq:
                raise ValueError("gate receipt is future-dated")
            opportunity = opportunities.get(receipt.opportunity_id)
            if opportunity is None or opportunity.decision_id != receipt.decision_id:
                raise ValueError("gate receipt opportunity chain is incomplete")
            if self._gate_verifier is None:
                raise RuntimeError("persisted gate receipt requires trusted verifier")
            try:
                valid = bool(self._gate_verifier(receipt, state))
            except Exception as exc:
                raise RuntimeError("persisted gate receipt verification failed") from exc
            if not valid:
                raise ValueError("persisted gate receipt was rejected")
        for opportunity in state.gate_opportunities:
            if opportunity.plan_id not in plans or opportunity.transition_id != plans[opportunity.plan_id].transition_id:
                raise ValueError("gate opportunity plan/transition join is invalid")
            if opportunity.state == "pending":
                assessment = assessments[opportunity.plan_id]
                head = heads.get(opportunity.deployment_slot_id)
                if head is None or head.active_snapshot_id is None:
                    raise ValueError("pending gate opportunity lacks an incumbent head")
                transition = transitions[opportunity.transition_id]
                candidate = self._candidate_snapshot_for_state(state, assessment, head)
                if not (
                    assessment.settled and assessment.label == "candidate"
                    and assessment.n_open == 0
                    and opportunity.transition_id not in harmful_transition_ids
                    and head.state == "active"
                    and head.active_composition_id == transition.source_composition_id
                    and opportunity.settled_assessment_sha256 == assessment.digest
                    and opportunity.candidate_snapshot_sha256 == candidate
                    and opportunity.incumbent_snapshot_id == head.active_snapshot_id
                ):
                    raise ValueError("pending gate opportunity is stale or ineligible")
        pending_by_namespace: dict[str, int] = {}
        for opportunity in state.gate_opportunities:
            if opportunity.state != "pending":
                continue
            pending_by_namespace[opportunity.namespace_digest] = (
                pending_by_namespace.get(opportunity.namespace_digest, 0) + 1
            )
        if any(
            count > state.capacity_policy.max_pending_gate_per_namespace
            for count in pending_by_namespace.values()
        ):
            raise ValueError("pending gate opportunities exceed namespace capacity")
        for snapshot in state.deployment_snapshots:
            composition = compositions.get(snapshot.composition_id)
            if composition is None or snapshot.namespace_digest != composition.namespace.digest:
                raise ValueError("deployment snapshot composition/namespace is invalid")
            if (
                snapshot.created_seq > state.event_seq
                or composition.created_seq >= snapshot.created_seq
            ):
                raise ValueError("deployment snapshot has invalid causal time")
            if (
                snapshot.artifact_sha256 != composition.artifact_sha256
                or snapshot.binding_map_sha256 != _sha256(sorted(composition.binding_map.items()))
            ):
                raise ValueError("deployment snapshot artifact/bindings are invalid")
            if snapshot.predecessor_snapshot_id is not None and snapshot.predecessor_snapshot_id not in snapshots:
                raise ValueError("deployment predecessor snapshot is missing")
            if snapshot.predecessor_snapshot_id is not None and (
                snapshots[snapshot.predecessor_snapshot_id].created_seq
                >= snapshot.created_seq
            ):
                raise ValueError("deployment predecessor is not causally earlier")
            if snapshot.is_base_fallback:
                matching_base_receipts = [
                    receipt
                    for receipt in state.base_receipts
                    if receipt.deployment_slot_id == snapshot.deployment_slot_id
                    and receipt.namespace_digest == snapshot.namespace_digest
                    and receipt.composition_id == snapshot.composition_id
                    and receipt.emitted_seq == snapshot.created_seq
                    and snapshot.snapshot_id
                    == _opaque_id("dsnap", receipt.attestation_sha256)
                    and snapshot.scientific_snapshot_sha256
                    == _sha256(
                        {
                            "base_receipt": receipt,
                            "composition": composition,
                            "capacity_policy": state.capacity_policy,
                        }
                    )
                ]
                if len(matching_base_receipts) != 1:
                    raise ValueError(
                        "base deployment snapshot lacks its exact receipt"
                    )
            else:
                receipt = gate_receipts.get(snapshot.accepted_gate_decision_id or "")
                if receipt is None or not receipt.accepted:
                    raise ValueError("non-base snapshot lacks an accepted gate receipt")
                if snapshot.accepted_gate_receipt_sha256 != _sha256(receipt):
                    raise ValueError("deployment snapshot gate receipt digest mismatch")
                if receipt.emitted_seq != snapshot.created_seq:
                    raise ValueError(
                        "deployment snapshot does not share its gate event"
                    )
        for head in state.deployment_heads:
            if head.updated_seq > state.event_seq:
                raise ValueError("deployment head is future-dated")
            if head.active_snapshot_id is not None:
                snapshot = snapshots.get(head.active_snapshot_id)
                if snapshot is None or snapshot.deployment_slot_id != head.deployment_slot_id:
                    raise ValueError("deployment head snapshot is missing or cross-slot")
                if (
                    head.active_composition_id != snapshot.composition_id
                    or head.active_transition_id != snapshot.transition_id
                    or head.accepted_gate_receipt_sha256 != snapshot.accepted_gate_receipt_sha256
                    or head.active_snapshot_sha256 != _sha256(snapshot)
                ):
                    raise ValueError("deployment head does not exactly mirror its snapshot")
                if snapshot.created_seq > head.updated_seq:
                    raise ValueError(
                        "deployment head predates its active snapshot"
                    )
            if head.base_fallback_snapshot_id is not None:
                base = snapshots.get(head.base_fallback_snapshot_id)
                if base is None or not base.is_base_fallback:
                    raise ValueError("deployment head base fallback is missing")
                if base.created_seq > head.updated_seq:
                    raise ValueError(
                        "deployment head predates its base fallback"
                    )
        rollback_triggers = {item.trigger_id: item for item in state.rollback_triggers}
        for trigger in state.rollback_triggers:
            if self._rollback_verifier is None:
                raise RuntimeError("persisted rollback requires trusted verifier")
            try:
                valid = bool(self._rollback_verifier(trigger, state))
            except Exception as exc:
                raise RuntimeError("persisted rollback verification failed") from exc
            if not valid:
                raise ValueError("persisted rollback trigger was rejected")
        for record in state.rollback_records:
            if record.trigger_id not in rollback_triggers:
                raise ValueError("rollback record trigger is missing")
            if record.restored_snapshot_id is not None and record.restored_snapshot_id not in snapshots:
                raise ValueError("rollback restored snapshot is missing")

        # Replay the complete per-slot head history.  Pairwise-valid rollback
        # rows are insufficient: an attacker with a stale writer key could
        # otherwise retarget both the trigger and record to a base snapshot,
        # erase monitor harm, and still satisfy every local foreign key.
        head_events_by_slot: dict[
            str,
            list[tuple[int, str, DeploymentSnapshotV2 | RollbackTriggerV2]],
        ] = {}
        for snapshot in state.deployment_snapshots:
            head_events_by_slot.setdefault(
                snapshot.deployment_slot_id,
                [],
            ).append(
                (
                    snapshot.created_seq,
                    "base" if snapshot.is_base_fallback else "gate",
                    snapshot,
                )
            )
        for trigger in state.rollback_triggers:
            head_events_by_slot.setdefault(
                trigger.deployment_slot_id,
                [],
            ).append((trigger.emitted_seq, "rollback", trigger))
        if set(head_events_by_slot) != set(heads):
            raise ValueError("deployment heads do not match replayable slot histories")
        for slot_id, events in head_events_by_slot.items():
            ordered_events = sorted(events, key=lambda item: (item[0], item[1]))
            event_seqs = [item[0] for item in ordered_events]
            if len(event_seqs) != len(set(event_seqs)):
                raise ValueError("deployment head events collide at one sequence")
            active_snapshot: DeploymentSnapshotV2 | None = None
            base_snapshot_id: str | None = None
            generation: int | None = None
            predecessor_snapshot_id: str | None = None
            rollback_lease_expiry_seq: int | None = None
            last_event_seq: int | None = None
            namespace_digest: str | None = None
            for event_seq, event_kind, event in ordered_events:
                last_event_seq = event_seq
                if event_kind == "base":
                    base_snapshot = cast(DeploymentSnapshotV2, event)
                    if active_snapshot is not None or base_snapshot_id is not None:
                        raise ValueError("deployment slot has multiple base events")
                    active_snapshot = base_snapshot
                    base_snapshot_id = base_snapshot.snapshot_id
                    generation = 0
                    predecessor_snapshot_id = None
                    rollback_lease_expiry_seq = None
                    namespace_digest = base_snapshot.namespace_digest
                    continue
                if active_snapshot is None or generation is None:
                    raise ValueError("deployment event precedes its active base")
                if event_kind == "gate":
                    candidate = cast(DeploymentSnapshotV2, event)
                    receipt = gate_receipts.get(
                        candidate.accepted_gate_decision_id or ""
                    )
                    opportunity = (
                        opportunities.get(receipt.opportunity_id)
                        if receipt is not None
                        else None
                    )
                    plan = (
                        plans.get(opportunity.plan_id)
                        if opportunity is not None
                        else None
                    )
                    transition = (
                        transitions.get(plan.transition_id)
                        if plan is not None
                        else None
                    )
                    if not (
                        receipt is not None
                        and receipt.accepted
                        and opportunity is not None
                        and plan is not None
                        and transition is not None
                        and candidate.created_seq == receipt.emitted_seq
                        and candidate.deployment_slot_id == slot_id
                        and candidate.namespace_digest == namespace_digest
                        and candidate.predecessor_snapshot_id
                        == active_snapshot.snapshot_id
                        and opportunity.incumbent_snapshot_id
                        == active_snapshot.snapshot_id
                        and receipt.incumbent_snapshot_sha256
                        == _sha256(active_snapshot)
                        and candidate.transition_id == transition.transition_id
                        and transition.source_composition_id
                        == active_snapshot.composition_id
                        and transition.target_composition_id
                        == candidate.composition_id
                        and candidate.scientific_snapshot_sha256
                        == opportunity.candidate_snapshot_sha256
                    ):
                        raise ValueError("accepted gate does not replay from its head")
                    predecessor_snapshot_id = active_snapshot.snapshot_id
                    active_snapshot = candidate
                    generation += 1
                    rollback_lease_expiry_seq = (
                        event_seq + state.capacity_policy.rollback_lease_events
                    )
                    continue
                trigger = cast(RollbackTriggerV2, event)
                records = rollback_records_by_trigger.get(
                    trigger.trigger_id,
                    [],
                )
                if not (
                    len(records) == 1
                    and trigger.active_snapshot_id
                    == active_snapshot.snapshot_id
                    and trigger.expected_head_generation == generation
                ):
                    raise ValueError("rollback does not replay from the active head")
                if (
                    trigger.kind == "train_monitor_harm"
                    and active_snapshot.transition_id is None
                ):
                    raise ValueError(
                        "TRAIN monitor harm must name a deployed scientific edge"
                    )
                record = records[0]
                restored = (
                    snapshots.get(active_snapshot.predecessor_snapshot_id)
                    if active_snapshot.predecessor_snapshot_id is not None
                    else None
                )
                if restored is not None:
                    expected_disposition = "restored_predecessor"
                elif base_snapshot_id is not None:
                    restored = snapshots.get(base_snapshot_id)
                    expected_disposition = "restored_base"
                else:
                    expected_disposition = "disabled"
                expected_restored_id = (
                    restored.snapshot_id if restored is not None else None
                )
                if not (
                    record.old_snapshot_id == active_snapshot.snapshot_id
                    and record.old_generation == generation
                    and record.new_generation == generation + 1
                    and record.restored_snapshot_id == expected_restored_id
                    and record.disposition == expected_disposition
                ):
                    raise ValueError("rollback record does not replay its head move")
                active_snapshot = restored
                generation += 1
                predecessor_snapshot_id = None
                rollback_lease_expiry_seq = None
            persisted_head = heads[slot_id]
            if generation is None or last_event_seq is None:
                raise ValueError("deployment slot has no replayable base")
            if active_snapshot is None:
                replayed_head_fields = (
                    "disabled",
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            else:
                replayed_head_fields = (
                    "active",
                    active_snapshot.snapshot_id,
                    active_snapshot.composition_id,
                    active_snapshot.transition_id,
                    active_snapshot.accepted_gate_receipt_sha256,
                    _sha256(active_snapshot),
                )
            persisted_head_fields = (
                persisted_head.state,
                persisted_head.active_snapshot_id,
                persisted_head.active_composition_id,
                persisted_head.active_transition_id,
                persisted_head.accepted_gate_receipt_sha256,
                persisted_head.active_snapshot_sha256,
            )
            if not (
                persisted_head_fields == replayed_head_fields
                and persisted_head.namespace_digest == namespace_digest
                and persisted_head.base_fallback_snapshot_id == base_snapshot_id
                and persisted_head.generation == generation
                and persisted_head.predecessor_snapshot_id
                == predecessor_snapshot_id
                and persisted_head.rollback_lease_expiry_seq
                == rollback_lease_expiry_seq
                and persisted_head.updated_seq == last_event_seq
            ):
                raise ValueError("deployment head differs from chronological replay")
        active_reservations = [item for item in state.reservations if item.state == "active"]
        settled_attempts_by_active_plan = {
            reservation.plan_id: sum(
                attempt.plan_id == reservation.plan_id and attempt.state != "open"
                for attempt in state.attempts
            )
            for reservation in active_reservations
        }
        attempts_per_active_plan = {
            item.plan_id: sum(
                attempt.plan_id == item.plan_id for attempt in state.attempts
            )
            for item in active_reservations
        }
        remaining_attempt_slots = sum(
            6 - attempts_per_active_plan[item.plan_id]
            for item in active_reservations
        )
        if len(state.attempts) + remaining_attempt_slots > (
            state.capacity_policy.max_attempt_records
        ):
            raise ValueError("active plan reservations exceed attempt capacity")
        materialized_receipts, remaining_receipt_slots = (
            _receipt_record_capacity_usage(
                state.attempts,
                (item.plan_id for item in active_reservations),
            )
        )
        if materialized_receipts + remaining_receipt_slots > (
            state.capacity_policy.max_receipt_records
        ):
            raise ValueError("active plan reservations exceed receipt capacity")
        if len(state.used_roots) + sum(
            3 * (6 - settled_attempts_by_active_plan[item.plan_id])
            for item in active_reservations
        ) > state.capacity_policy.max_consumed_root_ids:
            raise ValueError("active plans exceed consumed-root lifetime capacity")
        if len(state.used_receipts) + sum(
            3 * (6 - settled_attempts_by_active_plan[item.plan_id])
            for item in active_reservations
        ) > state.capacity_policy.max_consumed_receipt_ids:
            raise ValueError("active plans exceed consumed-receipt lifetime capacity")
        if len(state.failures) > state.capacity_policy.max_failures:
            raise ValueError("persisted failures exceed capacity")
        if len(state.repair_opportunities) > (
            state.capacity_policy.max_repair_opportunities
        ):
            raise ValueError("persisted repair opportunities exceed capacity")
        if len(state.branch_assignments) > (
            state.capacity_policy.max_branch_assignments
        ):
            raise ValueError("persisted branch assignments exceed capacity")
        if len(state.proposal_decisions) > (
            state.capacity_policy.max_proposal_decisions
        ):
            raise ValueError("persisted proposal decisions exceed capacity")
        for decision in state.proposal_decisions:
            _assert_proposal_decision_byte_bound(
                decision,
                max_bytes=(
                    state.capacity_policy.max_proposal_decision_bytes
                ),
            )
        if len(state.proposal_lifetime_counters) > (
            state.capacity_policy.max_proposal_lifetime_counters
        ):
            raise ValueError("persisted proposal lifetime counters exceed capacity")
        if len(state.proposal_lifetime_counters) > len(state.proposal_decisions):
            raise ValueError("proposal lifetime counters exceed their decision bound")
        if len(state.proposal_actions) > (
            state.capacity_policy.max_proposal_actions
        ):
            raise ValueError("persisted proposal actions exceed capacity")
        if len(state.proposal_carrier_admissions) > (
            state.capacity_policy.max_proposal_carrier_admissions
        ):
            raise ValueError(
                "persisted proposal carrier admissions exceed capacity"
            )
        if len(state.proposal_carrier_reservations) > len(state.proposal_actions):
            raise ValueError(
                "persisted carrier reservation lacks its exact action"
            )
        held_carrier_reservations = tuple(
            item
            for item in state.proposal_carrier_reservations
            if item.state == "reserved"
        )
        terminal_pending_carrier_reservations = (
            self._terminal_pending_carrier_reservations(state)
        )
        policy = state.capacity_policy
        if len(state.factors) + len(held_carrier_reservations) > (
            policy.max_factor_records
        ):
            raise ValueError("held carrier reservations exceed factor capacity")
        if len(state.compositions) + len(held_carrier_reservations) > (
            policy.max_composition_records
        ):
            raise ValueError("held carrier reservations exceed composition capacity")
        if (
            len(state.direct_transitions)
            + len(state.whole_transitions)
            + len(held_carrier_reservations)
            > policy.max_transition_records
        ):
            raise ValueError("held carrier reservations exceed transition capacity")
        if (
            len(state.proposal_carrier_admissions)
            + len(held_carrier_reservations)
            > policy.max_proposal_carrier_admissions
        ):
            raise ValueError("held carrier reservations exceed admission capacity")
        if sum(
            item.reserved_total_bytes for item in held_carrier_reservations
        ) > policy.max_active_generated_carrier_reservation_bytes:
            raise ValueError("held carrier reservation bytes exceed capacity")
        for namespace_digest in {
            item.namespace_digest for item in held_carrier_reservations
        }:
            namespace_compositions = tuple(
                item
                for item in state.compositions
                if item.namespace.digest == namespace_digest
                and item.structural_state == "live"
            )
            namespace_reservations = tuple(
                item
                for item in held_carrier_reservations
                if item.namespace_digest == namespace_digest
            )
            if (
                len(namespace_compositions) + len(namespace_reservations)
                > policy.max_hot_compositions_per_namespace
                + policy.unknown_structural_reserve
            ):
                raise ValueError(
                    "held carrier reservations exceed namespace hot capacity"
                )
            if (
                sum(
                    item.canonical_metadata_bytes
                    for item in namespace_compositions
                )
                + sum(
                    item.reserved_hot_metadata_bytes
                    for item in namespace_reservations
                )
                > policy.max_hot_metadata_bytes
            ):
                raise ValueError(
                    "held carrier reservations exceed namespace metadata capacity"
                )
            if (
                sum(item.artifact_bytes for item in namespace_compositions)
                + sum(
                    item.reserved_artifact_bytes
                    for item in namespace_reservations
                )
                > policy.max_hot_artifact_bytes_per_namespace
            ):
                raise ValueError(
                    "held carrier reservations exceed namespace artifact capacity"
                )
            if (
                sum(
                    item.prompt_summary_tokens
                    for item in namespace_compositions
                )
                + sum(
                    item.reserved_prompt_summary_tokens
                    for item in namespace_reservations
                )
                > policy.max_prompt_summary_tokens_per_namespace
            ):
                raise ValueError(
                    "held carrier reservations exceed namespace prompt capacity"
                )
        proposal_bytes = sum(
            len(_canonical_json(item).encode("utf-8"))
            for item in (
                *state.proposal_decisions,
                *state.proposal_lifetime_counters,
                *state.proposal_actions,
                *state.proposal_carrier_reservations,
                *state.proposal_carrier_admissions,
            )
        )
        if proposal_bytes + sum(
            item.reserved_owner_slab_bytes
            for item in terminal_pending_carrier_reservations
        ) > state.capacity_policy.max_proposal_action_bytes:
            raise ValueError("persisted proposal/action bytes exceed capacity")

        # An action-owned edge is intentionally inert until the exact action
        # terminal and edge commit publish together.  No execution evidence may
        # be attached earlier: otherwise exact cleanup would either erase a
        # durable observation or preserve a permanently nonterminal action.
        # Repeat the public-writer guard during full replay so an authenticated
        # state produced by an older schema cannot smuggle in that closure.
        for failure in state.failures:
            composition = compositions.get(failure.composition_id)
            if composition is None or not (
                composition.artifact_sha256 == failure.artifact_sha256
                and failure.created_seq <= state.event_seq
            ):
                raise ValueError("failure composition closure is invalid")
            if not self._composition_has_carrier_authority(
                state,
                composition,
                before_seq=failure.created_seq,
            ):
                raise ValueError(
                    "unadmitted proposal carrier has no failure authority"
                )
            if failure.transition_id is None:
                continue
            transition = transitions.get(failure.transition_id)
            if transition is None or (
                transition.target_composition_id != composition.composition_id
            ):
                raise ValueError("failure transition closure is invalid")
            if not self._transition_has_execution_authority(state, transition):
                raise ValueError(
                    "uncommitted proposal-action edge has no failure authority"
                )

        failures_by_opportunity = {
            _opaque_id("ro", item.failure_id): item
            for item in state.failures
            if item.failure_class == "algorithm"
        }
        repair_opportunities = {
            item.opportunity_id: item for item in state.repair_opportunities
        }
        for opportunity in state.repair_opportunities:
            composition = compositions.get(opportunity.source_composition_id)
            if composition is None:
                raise ValueError("repair opportunity source composition is missing")
            allowed_locators = tuple(
                sorted(
                    factors[factor_id].logical_factor_id
                    for factor_id in composition.binding_map.values()
                    if factors[factor_id].binding_status == "proven_factorized"
                )
            )
            if (
                opportunity.namespace_digest != composition.namespace.digest
                or opportunity.host_allowed_locator_ids != allowed_locators
                or opportunity.created_seq > state.event_seq
            ):
                raise ValueError("repair opportunity source/locator closure is invalid")
            if opportunity.transition_id is not None:
                transition = transitions.get(opportunity.transition_id)
                if (
                    transition is None
                    or transition.target_composition_id != composition.composition_id
                ):
                    raise ValueError("repair opportunity transition join is invalid")
            if opportunity.source_kind == "algorithm_failure":
                failure = failures_by_opportunity.get(opportunity.opportunity_id)
                if failure is None or not (
                    failure.composition_id == composition.composition_id
                    and failure.transition_id == opportunity.transition_id
                    and failure.safe_failure_code == opportunity.safe_failure_code
                    and failure.failed_stage == opportunity.failed_stage
                    and failure.created_seq == opportunity.created_seq
                ):
                    raise ValueError("repair opportunity failure provenance is invalid")
                if self._repair_opportunity_verifier is None:
                    raise RuntimeError(
                        "persisted repair opportunity requires its trusted verifier"
                    )
                try:
                    repair_verified = bool(
                        self._repair_opportunity_verifier(
                            opportunity,
                            failure,
                            composition,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted repair-opportunity verification failed"
                    ) from exc
                if not repair_verified:
                    raise ValueError(
                        "persisted repair-opportunity authority was rejected"
                    )

        def state_lineage_niche(
            factor: FactorRevisionV2,
            *,
            before_seq: int,
        ) -> LineageNicheV1:
            factor_key = self._factor_carrier_key_sha256(factor)
            provenance_owner = min(
                (
                    item
                    for item in state.factors
                    if item.created_seq < before_seq
                    and self._factor_carrier_key_sha256(item) == factor_key
                ),
                key=lambda item: (item.created_seq, item.revision_id),
            )
            chain = [provenance_owner]
            seen = {provenance_owner.revision_id}
            current = provenance_owner
            while current.parent_revision_id is not None:
                parent = factors.get(current.parent_revision_id)
                if parent is None or parent.revision_id in seen:
                    raise ValueError("persisted proposal lineage is cyclic or missing")
                if not (
                    parent.namespace == provenance_owner.namespace
                    and parent.logical_factor_id
                    == provenance_owner.logical_factor_id
                    and parent.carrier == provenance_owner.carrier
                    and parent.locator == provenance_owner.locator
                ):
                    raise ValueError("persisted proposal lineage crosses its locus")
                chain.append(parent)
                seen.add(parent.revision_id)
                current = parent
            root = chain[-1]
            return LineageNicheV1(
                origin_branch=root.origin_branch,
                root_revision_id=root.revision_id,
                provenance_family_sha256=_sha256(
                    {
                        "namespace": provenance_owner.namespace.digest,
                        "logical_factor": provenance_owner.logical_factor_id,
                        "carrier": provenance_owner.carrier,
                        "locator": provenance_owner.locator,
                        "root_revision": root.revision_id,
                        "ancestry": tuple(
                            item.revision_id for item in reversed(chain)
                        ),
                    }
                ),
                canonical_lineage_key_sha256=_sha256(
                    {
                        "namespace": provenance_owner.namespace.digest,
                        "logical_factor": provenance_owner.logical_factor_id,
                        "carrier": provenance_owner.carrier,
                        "locator": provenance_owner.locator,
                        "origin_branch": root.origin_branch,
                        "canonical_ancestry": tuple(
                            self._factor_carrier_key_sha256(item)
                            for item in reversed(chain)
                        ),
                    }
                ),
            )

        assessments_by_transition: dict[str, list[EdgeAssessmentV2]] = {}
        for assessment in state.assessments:
            assessments_by_transition.setdefault(
                assessment.transition_id, []
            ).append(assessment)
        tombstones_by_transition: dict[str, list[NegativeTombstoneV2]] = {}
        for tombstone in state.tombstones:
            tombstones_by_transition.setdefault(
                tombstone.subject_id, []
            ).append(tombstone)
        leaves_by_transition: dict[str, list[PortableEvidenceLeafV1]] = {}
        for leaf in state.portable_evidence_leaves:
            leaves_by_transition.setdefault(leaf.transition_id, []).append(leaf)

        def state_portable_signs(
            *,
            slot_id: str,
            from_revision_id: str,
            to_revision_id: str,
            cutoff_seq: int,
        ) -> tuple[PortableBackgroundSignV1, ...]:
            by_background: dict[str, list[tuple[str, str]]] = {}
            requested_from = factors.get(from_revision_id)
            requested_to = factors.get(to_revision_id)
            if requested_from is None or requested_to is None:
                raise ValueError("persisted portable pair names a missing factor")
            requested_from_key = self._factor_carrier_key_sha256(
                requested_from
            )
            requested_to_key = self._factor_carrier_key_sha256(requested_to)
            for transition in state.direct_transitions:
                transition_from = factors[transition.from_revision_id]
                transition_to = factors[transition.to_revision_id]
                if not (
                    transition.slot_id == slot_id
                    and self._factor_carrier_key_sha256(transition_from)
                    == requested_from_key
                    and self._factor_carrier_key_sha256(transition_to)
                    == requested_to_key
                ):
                    continue
                observations: list[tuple[str, str]] = []
                for assessment in assessments_by_transition.get(
                    transition.transition_id, []
                ):
                    if (
                        not assessment.settled
                        or assessment.revision_seq >= cutoff_seq
                    ):
                        continue
                    sign = _portable_sign_for_assessment(assessment)
                    if sign is None:
                        continue
                    observations.append(
                        (sign, assessment.evidence_root_sha256)
                    )
                observations.extend(
                    (leaf.sign, leaf.evidence_root_sha256)
                    for leaf in leaves_by_transition.get(
                        transition.transition_id, []
                    )
                    if leaf.source_revision_seq < cutoff_seq
                )
                for tombstone in tombstones_by_transition.get(
                    transition.transition_id, []
                ):
                    if (
                        tombstone.disposition == "harmful"
                        and tombstone.created_seq < cutoff_seq
                    ):
                        observations.append(
                            ("harm", tombstone.evidence_root_sha256)
                        )
                transition_edge_key = (
                    self._canonical_scientific_edge_sha256(
                        state,
                        transition,
                    )
                )
                for trigger in state.rollback_triggers:
                    if not (
                        trigger.kind == "train_monitor_harm"
                        and trigger.emitted_seq < cutoff_seq
                    ):
                        continue
                    deployed = snapshots.get(trigger.active_snapshot_id)
                    records = rollback_records_by_trigger.get(
                        trigger.trigger_id,
                        [],
                    )
                    if not (
                        deployed is not None
                        and deployed.transition_id in transitions
                        and len(records) == 1
                    ):
                        continue
                    rolled_transition = transitions[deployed.transition_id]
                    rolled_edge_key = (
                        self._canonical_scientific_edge_sha256(
                            state,
                            rolled_transition,
                        )
                    )
                    if rolled_edge_key != transition_edge_key:
                        continue
                    observations.append(
                        (
                            "harm",
                            _sha256(
                                {
                                    "rollback_trigger": trigger,
                                    "rollback_record": records[0],
                                    "deployed_snapshot": deployed,
                                    "canonical_scientific_edge_key_sha256": (
                                        rolled_edge_key
                                    ),
                                }
                            ),
                        )
                    )
                if observations:
                    by_background.setdefault(
                        self._canonical_background_sha256(state, transition),
                        [],
                    ).extend(observations)
            result: list[PortableBackgroundSignV1] = []
            for background in sorted(by_background):
                observations = sorted(set(by_background[background]))
                labels = {item[0] for item in observations}
                if "harm" in labels:
                    sign = "harm"
                elif "null" in labels:
                    sign = "null"
                elif "benefit" in labels:
                    sign = "benefit"
                elif "all_zero" in labels:
                    sign = "all_zero"
                else:
                    sign = "infrastructure"
                result.append(
                    PortableBackgroundSignV1(
                        fixed_background_sha256=background,
                        sign=sign,
                        evidence_root_sha256=_sha256(observations),
                    )
                )
            return tuple(result)

        decisions_by_id = {
            item.decision_id: item for item in state.proposal_decisions
        }
        decisions_by_opportunity: dict[str, ProposalDecisionV1] = {}
        cursor_by_cell: dict[str, ProposalCursorV1] = {}
        replayed_proposal_counters: tuple[ProposalLifetimeCounterV1, ...] = ()
        selected_target_by_decision: dict[str, FactorRevisionV2 | None] = {}
        for decision in sorted(
            state.proposal_decisions,
            key=lambda item: (item.created_seq, item.decision_id),
        ):
            opportunity = repair_opportunities.get(
                decision.repair_opportunity_id
            )
            if opportunity is None:
                raise ValueError("proposal decision opportunity is missing")
            if decision.repair_opportunity_id in decisions_by_opportunity:
                raise ValueError("repair opportunity owns multiple proposal decisions")
            decisions_by_opportunity[decision.repair_opportunity_id] = decision
            receipt = replay_validate_proposal_receipt(
                decision.proposal_receipt
            )
            counter_root_before = _proposal_lifetime_counter_root(
                replayed_proposal_counters,
                cell_sha256=receipt.request.cell.scheduler_key_sha256,
            )
            if not (
                receipt.proposal_counter_state_before_sha256
                == counter_root_before
                == decision.proposal_counter_state_before_sha256
            ):
                raise ValueError("proposal decision counter root is discontinuous")
            if not (
                decision.repair_opportunity_sha256 == opportunity.digest
                and receipt.request.opportunity_id == opportunity.opportunity_id
                and opportunity.created_seq < decision.created_seq
                <= opportunity.expiry_seq
                and decision.created_seq <= state.event_seq
            ):
                raise ValueError("proposal decision opportunity closure is invalid")
            if not hmac.compare_digest(
                decision.candidate_slate_attestation_sha256,
                _mac(
                    self._key,
                    "proposal-candidate-slate-v4",
                    decision.slate_attestation_body,
                ),
            ):
                raise ValueError(
                    "proposal decision candidate slate lacks host attestation"
                )
            source = compositions.get(opportunity.source_composition_id)
            if source is None or receipt.request.cell.namespace != source.namespace:
                raise ValueError("proposal decision source namespace is invalid")
            cell = receipt.request.cell
            locus = cell.locus
            counter_by_key = {
                (item.cell_sha256, item.target_factor_key_sha256): item
                for item in replayed_proposal_counters
            }
            expected_counter_witnesses = tuple(
                (
                    counter_by_key[
                        (
                            cell.scheduler_key_sha256,
                            snapshot.candidate.target_factor_key_sha256,
                        )
                    ].witness
                    if (
                        cell.scheduler_key_sha256,
                        snapshot.candidate.target_factor_key_sha256,
                    ) in counter_by_key
                    else CandidateCounterWitnessV1(
                        cell_sha256=cell.scheduler_key_sha256,
                        target_factor_key_sha256=(
                            snapshot.candidate.target_factor_key_sha256
                        ),
                    )
                )
                for snapshot in sorted(
                    receipt.candidate_manifest,
                    key=lambda item: item.candidate.target_factor_key_sha256,
                )
            )
            if receipt.candidate_counter_witnesses != expected_counter_witnesses:
                raise ValueError("proposal counter witnesses are forged or stale")
            source_factor_id = source.binding_map.get(locus.slot_id)
            source_factor = factors.get(cell.from_revision_id)
            if source_factor_id != cell.from_revision_id or source_factor is None:
                raise ValueError("proposal decision comparator is not loaded")
            if not (
                source_factor.binding_status == "proven_factorized"
                and source_factor.logical_factor_id == locus.logical_factor_id
                and source_factor.carrier == locus.carrier
                and source_factor.locator.surface == locus.locator_surface
                and source_factor.locator.path == locus.locator_path
                and source_factor.locator.locator_version == locus.locator_version
                and cell.canonical_background_sha256
                == self._canonical_direct_background_sha256(
                    state,
                    source=source,
                    source_factor=source_factor,
                    slot_id=locus.slot_id,
                )
                and cell.canonical_from_factor_key_sha256
                == self._factor_carrier_key_sha256(source_factor)
                and locus.logical_factor_id
                in opportunity.host_allowed_locator_ids
            ):
                raise ValueError("proposal decision locus closure is invalid")
            expected_cursor = cursor_by_cell.get(
                cell.scheduler_key_sha256,
                ProposalCursorV1.empty(cell),
            )
            if receipt.cursor_before != expected_cursor:
                raise ValueError("proposal decision cursor chain is discontinuous")
            selected_target: FactorRevisionV2 | None = None
            for snapshot in receipt.candidate_manifest:
                candidate = snapshot.candidate
                target = factors.get(candidate.target_revision_id)
                if target is None or not (
                    target.binding_status == "proven_factorized"
                    and self._row_is_carrier_eligible(
                        state,
                        row_kind="factor",
                        row_id=target.revision_id,
                        before_seq=decision.created_seq,
                        factor_carrier_key_sha256=(
                            self._factor_carrier_key_sha256(target)
                        ),
                    )
                    and target.namespace == source_factor.namespace
                    and target.logical_factor_id
                    == source_factor.logical_factor_id
                    and target.carrier == source_factor.carrier
                    and target.locator == source_factor.locator
                    and target.content_sha256
                    == candidate.target_content_sha256
                    and self._factor_carrier_key_sha256(target)
                    == candidate.target_factor_key_sha256
                    and candidate.target_factor_key_sha256
                    != cell.canonical_from_factor_key_sha256
                    and target.revision_id != source_factor.revision_id
                    and target.created_seq < decision.created_seq
                ):
                    raise ValueError("persisted proposal candidate is incompatible")
                aliases = sorted(
                    (
                        item
                        for item in state.factors
                        if item.namespace == target.namespace
                        and item.logical_factor_id == target.logical_factor_id
                        and item.carrier == target.carrier
                        and item.locator == target.locator
                        and item.content_sha256 == target.content_sha256
                        and item.created_seq < decision.created_seq
                        and self._row_is_carrier_eligible(
                            state,
                            row_kind="factor",
                            row_id=item.revision_id,
                            before_seq=decision.created_seq,
                            factor_carrier_key_sha256=(
                                self._factor_carrier_key_sha256(item)
                            ),
                        )
                    ),
                    key=lambda item: (item.created_seq, item.revision_id),
                )
                if candidate.target_revision_id != aliases[0].revision_id:
                    raise ValueError("persisted proposal candidate is a content alias")
                if candidate.lineage_niche != state_lineage_niche(
                    target,
                    before_seq=decision.created_seq,
                ):
                    raise ValueError("persisted proposal lineage is forged")
                if candidate.background_signs != state_portable_signs(
                    slot_id=locus.slot_id,
                    from_revision_id=source_factor.revision_id,
                    to_revision_id=target.revision_id,
                    cutoff_seq=decision.created_seq,
                ):
                    raise ValueError("persisted proposal signs are forged or stale")
                if candidate.target_revision_id == (
                    receipt.selected_target_revision_id
                ):
                    selected_target = target
            if (receipt.selection_mode == "no_safe_reuse") != (
                selected_target is None
            ):
                raise ValueError("persisted proposal target closure is invalid")
            effective = tuple(
                branch
                for branch in opportunity.feasible_branches
                if not (branch == "reuse" and selected_target is None)
            )
            if decision.effective_feasible_branches != effective:
                raise ValueError("proposal decision feasible branches do not replay")
            context = decision.generation_context
            if context is not None:
                failure = failures_by_opportunity.get(opportunity.opportunity_id)
                if not (
                    context.proposal_receipt_sha256 == receipt.digest
                    and context.repair_opportunity_id == opportunity.opportunity_id
                    and context.repair_opportunity_sha256 == opportunity.digest
                    and failure is not None
                    and context.failure_observation_sha256 == _sha256(failure)
                    and context.namespace_digest == source.namespace.digest
                    and context.source_composition_id == source.composition_id
                    and context.source_artifact_id == source.artifact_revision_id
                    and context.slot_id == locus.slot_id
                    and context.locator_path == source_factor.locator.path
                    and context.from_revision_id == source_factor.revision_id
                    and context.safe_failure_code == opportunity.safe_failure_code
                    and context.failure_artifact_sha256 == source.artifact_sha256
                    and context.runtime_version == source.namespace.runtime_version
                ):
                    raise ValueError("persisted generation context closure is invalid")
                if self._proposal_generation_context_verifier is None:
                    raise RuntimeError(
                        "persisted generation context requires its trusted verifier"
                    )
                try:
                    context_verified = bool(
                        self._proposal_generation_context_verifier(
                            context,
                            opportunity,
                            receipt,
                            source,
                            source_factor,
                            state,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted generation-context verification failed"
                    ) from exc
                if not context_verified:
                    raise ValueError("persisted generation context was rejected")
            expected_counter_delta = (
                receipt.projected_counter_delta
                if decision.selected_branch == "reuse"
                else None
            )
            if decision.committed_counter_delta != expected_counter_delta:
                raise ValueError("proposal decision counter delta does not replay")
            replayed_proposal_counters = _apply_proposal_counter_delta(
                replayed_proposal_counters,
                expected_counter_delta,
                max_rows=(
                    state.capacity_policy.max_proposal_lifetime_counters
                ),
            )
            if decision.proposal_counter_state_after_sha256 != (
                _proposal_lifetime_counter_root(
                    replayed_proposal_counters,
                    cell_sha256=cell.scheduler_key_sha256,
                )
            ):
                raise ValueError("proposal decision counter successor is invalid")
            if decision.cursor_committed:
                cursor_by_cell[
                    cell.scheduler_key_sha256
                ] = receipt.projected_cursor
            selected_target_by_decision[decision.decision_id] = selected_target

        if replayed_proposal_counters != state.proposal_lifetime_counters:
            raise ValueError("proposal lifetime-counter state does not replay")

        assignments_by_opportunity: set[str] = set()
        counts_by_namespace: dict[str, dict[ScientificBranch, int]] = {}
        for assignment in sorted(
            state.branch_assignments,
            key=lambda item: (item.created_seq, item.assignment_id),
        ):
            opportunity = repair_opportunities.get(assignment.repair_opportunity_id)
            if opportunity is None:
                raise ValueError("branch assignment repair opportunity is missing")
            if assignment.repair_opportunity_id in assignments_by_opportunity:
                raise ValueError("repair opportunity owns multiple branch assignments")
            assignments_by_opportunity.add(assignment.repair_opportunity_id)
            counts = counts_by_namespace.setdefault(
                opportunity.namespace_digest,
                {branch: 0 for branch in ("reuse", "mutate", "fresh")},
            )
            expected_counts = tuple(
                (branch, counts[branch])
                for branch in ("reuse", "mutate", "fresh")
            )
            decision = (
                decisions_by_id.get(assignment.proposal_decision_id)
                if assignment.proposal_decision_id is not None
                else None
            )
            if assignment.proposal_decision_id is not None and decision is None:
                raise ValueError("branch assignment proposal decision is missing")
            feasible = (
                decision.effective_feasible_branches
                if decision is not None
                else opportunity.feasible_branches
            )
            candidates: list[tuple[float, str, ScientificBranch]] = []
            total = sum(counts.values())
            for branch in feasible:
                deficit = (total + 1) / 3 - counts[branch]
                tiebreak = (
                    _sha256(
                        {
                            "seed": opportunity.public_seed,
                            "opportunity": opportunity.opportunity_id,
                            "branch": branch,
                        }
                    )
                    if decision is None
                    else _proposal_conditioned_branch_tiebreak_sha256(
                        public_seed=opportunity.public_seed,
                        proposal_scheduler_decision_sha256=(
                            decision.proposal_scheduler_decision_sha256
                        ),
                        branch=branch,
                    )
                )
                candidates.append((deficit, tiebreak, branch))
            _deficit, expected_tiebreak, expected_branch = max(candidates)
            id_body = {
                "opportunity": opportunity.opportunity_id,
                "namespace_ordinal": total,
                "branch": expected_branch,
            }
            if decision is not None:
                id_body["proposal_decision"] = decision.digest
            expected_id = _opaque_id("ba", id_body)
            proposal_join = (
                assignment.proposal_decision_id is None
                and assignment.proposal_decision_sha256 is None
                and assignment.effective_feasible_branches is None
                and assignment.selector_policy_sha256
                == _BRANCH_SELECTOR_POLICY_SHA256
                if decision is None
                else (
                    assignment.proposal_decision_id == decision.decision_id
                    and assignment.proposal_decision_sha256 == decision.digest
                    and assignment.effective_feasible_branches == feasible
                    and assignment.selector_policy_sha256
                    == _PROPOSAL_CONDITIONED_BRANCH_POLICY_SHA256
                    and decision.selected_branch == assignment.branch
                    and decision.created_seq == assignment.created_seq
                )
            )
            if not (
                assignment.assignment_id == expected_id
                and assignment.repair_opportunity_sha256 == opportunity.digest
                and assignment.namespace_digest == opportunity.namespace_digest
                and assignment.source_composition_id
                == opportunity.source_composition_id
                and assignment.branch == expected_branch
                and assignment.branch in feasible
                and assignment.assigned_counts_before == expected_counts
                and proposal_join
                and assignment.public_tiebreak_sha256 == expected_tiebreak
                and opportunity.created_seq < assignment.created_seq
                <= opportunity.expiry_seq
                and assignment.created_seq <= state.event_seq
            ):
                raise ValueError("branch assignment is not a reproducible one-shot decision")
            counts[assignment.branch] += 1
        for decision in state.proposal_decisions:
            assignments = [
                item
                for item in state.branch_assignments
                if item.proposal_decision_id == decision.decision_id
            ]
            if decision.effective_feasible_branches:
                if len(assignments) != 1:
                    raise ValueError(
                        "proposal decision lacks one exact branch assignment"
                    )
            elif assignments:
                raise ValueError(
                    "branch-exhausted proposal decision cannot own an assignment"
                )
        assignments_by_id = {
            item.assignment_id: item for item in state.branch_assignments
        }
        carrier_reservations_by_action = {
            item.action_id: item
            for item in state.proposal_carrier_reservations
        }
        generated_action_ids = {
            item.action_id
            for item in state.proposal_actions
            if item.branch in {"mutate", "fresh"}
        }
        if set(carrier_reservations_by_action) != generated_action_ids:
            raise ValueError(
                "generated proposal actions and carrier reservations differ"
            )
        actions_by_assignment: dict[str, ProposalActionV2] = {}
        for action in state.proposal_actions:
            assignment = assignments_by_id.get(action.assignment_id)
            decision = decisions_by_id.get(action.proposal_decision_id)
            if assignment is None or decision is None:
                raise ValueError("proposal action assignment/decision is missing")
            if action.assignment_id in actions_by_assignment:
                raise ValueError("branch assignment owns multiple proposal actions")
            actions_by_assignment[action.assignment_id] = action
            target = selected_target_by_decision.get(decision.decision_id)
            source = compositions.get(action.source_composition_id)
            source_factor = factors.get(action.from_revision_id)
            if source is None or source_factor is None:
                raise ValueError("proposal action source is missing")
            receipt = decision.proposal_receipt
            if not (
                assignment.branch == action.branch
                and assignment.proposal_decision_id == decision.decision_id
                and action.assignment_sha256 == _sha256(assignment)
                and action.proposal_decision_sha256 == decision.digest
                and action.proposal_receipt_sha256
                == decision.proposal_receipt_sha256
                and action.proposal_policy_sha256 == receipt.policy_sha256
                and action.proposal_cursor_before_sha256
                == receipt.cursor_before_sha256
                and action.proposal_candidate_manifest_sha256
                == receipt.candidate_manifest_sha256
                and action.proposal_projected_history_sha256
                == receipt.projected_history_sha256
                and action.namespace_digest == source.namespace.digest
                and action.source_artifact_id == source.artifact_revision_id
                and action.slot_id == receipt.request.cell.locus.slot_id
                and action.locator_path == source_factor.locator.path
                and action.from_revision_id == source_factor.revision_id
                and action.from_content_sha256 == source_factor.content_sha256
                and action.generation_context == decision.generation_context
                and action.prepared_seq == assignment.created_seq
                and action.updated_seq <= state.event_seq
            ):
                raise ValueError("proposal action immutable closure is invalid")
            if action.branch == "reuse":
                if target is None or not (
                    action.selected_target_revision_id == target.revision_id
                    and action.selected_target_content_sha256
                    == target.content_sha256
                ):
                    raise ValueError("reuse action selected target closure is invalid")
            elif action.selected_target_revision_id is not None:
                raise ValueError("generated action cannot own a selected reuse target")

            prepared = action.model_copy(
                update={
                    "state": "prepared",
                    "generation_lease": None,
                    "generation_terminal_sha256": None,
                    "resolved_to_revision_id": None,
                    "resolved_target_content_sha256": None,
                    "phase_terminal_sha256": None,
                    "transition_id": None,
                    "binding_proof_id": None,
                    "abort_receipt": None,
                    "fencing_generation": 1,
                    "updated_seq": action.prepared_seq,
                }
            )
            lease = action.generation_lease
            if lease is not None:
                if action.generation_request is None or not (
                    lease.action_id == action.action_id
                    and lease.generation_request_sha256
                    == action.generation_request.digest
                    and lease.expected_prepared_action_sha256 == prepared.digest
                    and lease.started_seq is not None
                    and action.prepared_seq < lease.started_seq <= state.event_seq
                ):
                    raise ValueError("proposal generation lease closure is invalid")
                if self._proposal_generation_lease_verifier is None:
                    raise RuntimeError(
                        "persisted generation lease requires its trusted verifier"
                    )
                try:
                    lease_verified = bool(
                        self._proposal_generation_lease_verifier(
                            lease,
                            prepared,
                            state,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted generation-lease verification failed"
                    ) from exc
                if not lease_verified:
                    raise ValueError("persisted generation lease was rejected")
            matching_transitions = [
                transition
                for transition in state.direct_transitions
                if transition.origin_branch == action.branch
                and transition.proposal_action_id == action.action_id
                and transition.proposal_action_intent_sha256
                == action.action_intent_sha256
                and transition.namespace.digest == action.namespace_digest
                and transition.source_composition_id
                == action.source_composition_id
                and transition.slot_id == action.slot_id
                and transition.from_revision_id == action.from_revision_id
            ]
            if len(matching_transitions) > 1:
                raise ValueError("proposal action owns multiple local edges")
            carrier_reservation = carrier_reservations_by_action.get(
                action.action_id
            )
            if action.branch == "reuse":
                if carrier_reservation is not None:
                    raise ValueError("reuse action cannot reserve generated carrier capacity")
            else:
                assert carrier_reservation is not None
                policy = state.capacity_policy
                if not (
                    action.carrier_capacity_reservation_id
                    == carrier_reservation.reservation_id
                    and
                    carrier_reservation.namespace_digest
                    == action.namespace_digest
                    and carrier_reservation.capacity_policy_sha256
                    == policy.digest
                    and carrier_reservation.created_seq == action.prepared_seq
                    and carrier_reservation.reserved_hot_metadata_bytes
                    == policy.max_generated_target_metadata_bytes
                    and carrier_reservation.reserved_artifact_bytes
                    == policy.max_generated_target_artifact_bytes
                    and carrier_reservation.reserved_prompt_summary_tokens
                    == policy.max_generated_target_prompt_summary_tokens
                    and carrier_reservation.reserved_structural_bytes
                    == policy.max_generated_carrier_structural_bytes
                    and carrier_reservation.reserved_transition_bytes
                    == policy.max_generated_transition_bytes
                    and carrier_reservation.reserved_admission_bytes
                    == policy.max_generated_admission_bytes
                    and carrier_reservation.reserved_owner_slab_bytes
                    == policy.max_generated_owner_slab_bytes
                ):
                    raise ValueError(
                        "proposal carrier reservation policy/action join is invalid"
                    )
                action_admission = next(
                    (
                        item
                        for item in state.proposal_carrier_admissions
                        if item.action_id == action.action_id
                    ),
                    None,
                )
                if (
                    action.state == "aborted"
                    and action.abort_receipt is not None
                    and action.abort_receipt.cleanup_admission_id is not None
                    and action_admission is None
                ):
                    raise ValueError(
                        "proposal cleanup receipt lacks its quarantined admission"
                    )
                if action.state == "prepared":
                    expected_reservation_state = "reserved"
                    expected_materialized_seq = None
                    expected_terminal_seq = None
                elif action.state == "executing":
                    expected_reservation_state = (
                        "materialized" if matching_transitions else "reserved"
                    )
                    expected_materialized_seq = (
                        matching_transitions[0].created_seq
                        if matching_transitions
                        else None
                    )
                    expected_terminal_seq = None
                elif action.state == "committed":
                    if not matching_transitions:
                        raise ValueError(
                            "committed carrier reservation lacks its edge"
                        )
                    expected_reservation_state = "consumed"
                    expected_materialized_seq = matching_transitions[0].created_seq
                    expected_terminal_seq = action.updated_seq
                elif action_admission is not None:
                    expected_reservation_state = "consumed"
                    expected_materialized_seq = action_admission.created_seq
                    expected_terminal_seq = action.updated_seq
                else:
                    expected_reservation_state = "released"
                    expected_materialized_seq = None
                    expected_terminal_seq = action.updated_seq
                terminal_seq = (
                    carrier_reservation.consumed_seq
                    if expected_reservation_state == "consumed"
                    else carrier_reservation.released_seq
                )
                if not (
                    carrier_reservation.state == expected_reservation_state
                    and carrier_reservation.materialized_seq
                    == expected_materialized_seq
                    and terminal_seq == expected_terminal_seq
                ):
                    raise ValueError(
                        "proposal carrier reservation lifecycle is invalid"
                    )
                if action_admission is not None:
                    target_factor = factors.get(
                        action_admission.target_factor_revision_id
                    )
                    target_composition = compositions.get(
                        action_admission.target_composition_id
                    )
                    if target_factor is None or target_composition is None:
                        raise ValueError(
                            "materialized carrier reservation target is missing"
                        )
                    self._assert_carrier_closure_fits_reservation(
                        carrier_reservation,
                        action=action,
                        factor=target_factor,
                        composition=target_composition,
                        transition=(
                            matching_transitions[0]
                            if matching_transitions
                            else None
                        ),
                        admission=action_admission,
                    )
            if action.state == "committed":
                if len(matching_transitions) != 1:
                    raise ValueError("committed proposal action lacks its local edge")
                transition = matching_transitions[0]
                if not (
                    action.transition_id == transition.transition_id
                    and action.binding_proof_id == transition.binding_proof_id
                    and action.phase_terminal_sha256
                    == transition.binding_proof_sha256
                    and action.updated_seq > action.prepared_seq
                    and transition.proposal_action_committed_seq
                    == action.updated_seq
                    and action.resolved_to_revision_id
                    == transition.to_revision_id
                    and action.resolved_target_content_sha256
                    == factors[transition.to_revision_id].content_sha256
                ):
                    raise ValueError("proposal action terminal edge join is invalid")
                if self._proposal_action_terminal_verifier is None:
                    raise RuntimeError(
                        "persisted proposal action requires its terminal verifier"
                    )
                try:
                    terminal_verified = bool(
                        self._proposal_action_terminal_verifier(
                            action,
                            transition,
                            state,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted proposal-action terminal verification failed"
                    ) from exc
                if not terminal_verified:
                    raise ValueError(
                        "persisted proposal-action terminal was rejected"
                    )
            elif action.state == "prepared":
                if matching_transitions:
                    if action.branch != "reuse":
                        raise ValueError(
                            "prepared generated action cannot own a local edge"
                        )
                    transition = matching_transitions[0]
                    if not (
                        transition.proposal_action_committed_seq is None
                        and transition.created_seq > action.prepared_seq
                        and not any(
                            plan.transition_id == transition.transition_id
                            for plan in state.plans
                        )
                    ):
                        raise ValueError(
                            "prepared proposal action edge is not inert"
                        )
            elif action.state == "executing":
                if action.branch == "reuse" or lease is None:
                    raise ValueError("executing action lacks generated lease authority")
                if matching_transitions:
                    transition = matching_transitions[0]
                    if not (
                        transition.proposal_action_committed_seq is None
                        and lease.started_seq is not None
                        and transition.created_seq > lease.started_seq
                        and not any(
                            plan.transition_id == transition.transition_id
                            for plan in state.plans
                        )
                    ):
                        raise ValueError(
                            "executing proposal action edge is not inert"
                        )
            elif action.state == "aborted":
                if matching_transitions:
                    raise ValueError("aborted proposal action cannot own a Bank edge")
                assert action.abort_receipt is not None
                predecessor = (
                    prepared
                    if action.abort_receipt.predecessor_state == "prepared"
                    else prepared.model_copy(
                        update={
                            "state": "executing",
                            "generation_lease": lease,
                            "updated_seq": (
                                lease.started_seq if lease is not None else None
                            ),
                        }
                    )
                )
                if not (
                    action.abort_receipt.action_id == action.action_id
                    and action.abort_receipt.expected_action_sha256
                    == predecessor.digest
                    and action.abort_receipt.emitted_seq == action.updated_seq
                    and action.updated_seq > action.prepared_seq
                ):
                    raise ValueError("proposal action abort fence is invalid")
                cleanup_transition_id = (
                    action.abort_receipt.cleanup_transition_id
                )
                if cleanup_transition_id is not None:
                    generated_cleanup = (
                        action.branch in {"mutate", "fresh"}
                        and action.abort_receipt.predecessor_state == "executing"
                        and action.abort_receipt.reason.startswith("generation_")
                        and lease is not None
                    )
                    reuse_cleanup = (
                        action.branch == "reuse"
                        and action.abort_receipt.predecessor_state == "prepared"
                        and action.abort_receipt.reason == "phase_rejected"
                        and action.abort_receipt.phase_terminal_sha256 is not None
                    )
                    if not (
                        (generated_cleanup or reuse_cleanup)
                        and action.abort_receipt.cleanup_action_intent_sha256
                        == action.action_intent_sha256
                        and cleanup_transition_id not in transitions
                        and action.abort_receipt.cleanup_admission_id is not None
                        and action.abort_receipt.cleanup_admission_sha256 is not None
                    ):
                        raise ValueError(
                            "proposal action cleanup receipt does not close its inert edge"
                        )
                if self._proposal_abort_verifier is None:
                    raise RuntimeError(
                        "persisted proposal abort requires its trusted verifier"
                    )
                try:
                    verified = bool(
                        self._proposal_abort_verifier(
                            action.abort_receipt,
                            predecessor,
                            state,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "persisted proposal abort verification failed"
                    ) from exc
                if not verified:
                    raise ValueError("persisted proposal abort was rejected")
        actions_by_id = {item.action_id: item for item in state.proposal_actions}
        for admission in state.proposal_carrier_admissions:
            action = actions_by_id.get(admission.action_id)
            source = compositions.get(admission.source_composition_id)
            target = compositions.get(admission.target_composition_id)
            factor = factors.get(admission.target_factor_revision_id)
            transition = direct.get(admission.transition_id)
            if action is None or source is None or target is None or factor is None:
                raise ValueError("proposal carrier admission closure is missing")
            expected_factor_before = (
                self._row_was_independently_eligible_before_action_edge(
                    state,
                    row_kind="factor",
                    row_id=factor.revision_id,
                    action=action,
                    edge_created_seq=admission.created_seq,
                )
            )
            expected_composition_before = (
                self._row_was_independently_eligible_before_action_edge(
                    state,
                    row_kind="composition",
                    row_id=target.composition_id,
                    action=action,
                    edge_created_seq=admission.created_seq,
                )
            )
            if not (
                admission.action_intent_sha256 == action.action_intent_sha256
                and admission.namespace_digest == action.namespace_digest
                == source.namespace.digest
                == target.namespace.digest
                and admission.source_composition_id
                == action.source_composition_id
                and target.binding_map.get(action.slot_id)
                == factor.revision_id
                and admission.target_composition_sha256
                == _sha256(self._projected_carrier_row(target))
                and admission.target_composition_carrier_key_sha256
                == self._composition_carrier_key_sha256(state, target)
                and admission.target_factor_sha256
                == _sha256(self._projected_carrier_row(factor))
                and admission.target_factor_carrier_key_sha256
                == self._factor_carrier_key_sha256(factor)
                and admission.independent_authority_cutoff_seq
                == action.prepared_seq
                and admission.factor_independently_eligible_before
                == expected_factor_before
                and admission.composition_independently_eligible_before
                == expected_composition_before
                and admission.created_seq > action.prepared_seq
                and admission.created_seq <= state.event_seq
            ):
                raise ValueError(
                    "proposal carrier admission immutable closure is invalid"
                )
            if admission.state in {"staged", "admitted"}:
                if transition is None or not (
                    transition.proposal_action_id == action.action_id
                    and transition.proposal_action_intent_sha256
                    == action.action_intent_sha256
                    and transition.transition_id == admission.transition_id
                    and transition.source_composition_id
                    == admission.source_composition_id
                    and transition.target_composition_id
                    == admission.target_composition_id
                    and transition.to_revision_id
                    == admission.target_factor_revision_id
                    and transition.created_seq == admission.created_seq
                    and admission.projected_transition_sha256
                    == _sha256(self._projected_action_transition(transition))
                ):
                    raise ValueError(
                        "proposal carrier admission edge closure is invalid"
                    )
            if admission.state == "staged":
                expected_action_state = (
                    "prepared" if action.branch == "reuse" else "executing"
                )
                if not (
                    action.state == expected_action_state
                    and transition is not None
                    and transition.proposal_action_committed_seq is None
                ):
                    raise ValueError(
                        "staged carrier admission is not an inert action edge"
                    )
            elif admission.state == "admitted":
                if transition is None or not (
                    action.state == "committed"
                    and transition.proposal_action_committed_seq
                    == action.updated_seq
                    == admission.terminal_seq
                    and admission.terminal_sha256
                    == self._admission_terminal_sha256(
                        disposition="admitted",
                        action=action,
                        projected_transition_sha256=(
                            admission.projected_transition_sha256
                        ),
                        committed_transition=transition,
                    )
                ):
                    raise ValueError(
                        "admitted carrier admission lacks its action terminal"
                    )
            else:
                abort = action.abort_receipt
                if abort is None:
                    raise ValueError(
                        "quarantined carrier admission lacks an abort receipt"
                    )
                staged = admission.model_copy(
                    update={
                        "state": "staged",
                        "terminal_seq": None,
                        "terminal_sha256": None,
                    }
                )
                if not (
                    action.state == "aborted"
                    and transition is None
                    and abort.cleanup_transition_id == admission.transition_id
                    and abort.cleanup_transition_sha256
                    == admission.projected_transition_sha256
                    and abort.cleanup_action_intent_sha256
                    == admission.action_intent_sha256
                    and abort.cleanup_admission_id == admission.admission_id
                    and abort.cleanup_admission_sha256 == staged.digest
                    and admission.terminal_seq == action.updated_seq
                    == abort.emitted_seq
                    and admission.terminal_sha256
                    == self._admission_terminal_sha256(
                        disposition="quarantined",
                        action=action,
                        projected_transition_sha256=(
                            admission.projected_transition_sha256
                        ),
                        abort_receipt=abort,
                    )
                ):
                    raise ValueError(
                        "quarantined carrier admission lacks its exact cleanup"
                    )
        admissions_by_id = {
            item.admission_id: item
            for item in state.proposal_carrier_admissions
        }
        for action in state.proposal_actions:
            abort = action.abort_receipt
            if abort is None or abort.cleanup_admission_id is None:
                continue
            admission = admissions_by_id.get(abort.cleanup_admission_id)
            if admission is None or not (
                admission.action_id == action.action_id
                and admission.state == "quarantined"
            ):
                raise ValueError(
                    "proposal cleanup receipt lacks its quarantined admission"
                )
        action_ids = set(actions_by_id)
        if any(
            transition.proposal_action_id not in action_ids
            for transition in state.direct_transitions
            if transition.proposal_action_id is not None
        ):
            raise ValueError("action-bound transition lacks its proposal action")
        for transition in state.direct_transitions:
            if transition.proposal_action_id is None:
                continue
            action = actions_by_id[transition.proposal_action_id]
            admission = self._admission_for_transition(
                state,
                transition.transition_id,
            )
            if not (
                admission is not None
                and admission.action_id == action.action_id
                and transition.origin_branch == action.branch
                and transition.proposal_action_intent_sha256
                == action.action_intent_sha256
                and transition.namespace.digest == action.namespace_digest
                and transition.source_composition_id
                == action.source_composition_id
                and transition.slot_id == action.slot_id
                and transition.from_revision_id == action.from_revision_id
                and (
                    action.branch != "reuse"
                    or transition.to_revision_id
                    == action.selected_target_revision_id
                )
                and (
                    action.state != "committed"
                    or transition.to_revision_id
                    == action.resolved_to_revision_id
                )
                and (
                    action.branch != "mutate"
                    or factors[transition.to_revision_id].parent_revision_id
                    == action.from_revision_id
                )
                and (
                    action.branch != "fresh"
                    or factors[transition.to_revision_id].parent_revision_id is None
                )
            ):
                raise ValueError("action-bound transition branch/intent join is invalid")
        for assignment in state.branch_assignments:
            if assignment.proposal_decision_id is None:
                continue
            action = actions_by_assignment.get(assignment.assignment_id)
            if action is None or action.branch != assignment.branch:
                raise ValueError(
                    "proposal-conditioned assignment lacks its exact action"
                )
        if len(state.exposures) > state.capacity_policy.max_exposures:
            raise ValueError("persisted exposures exceed capacity")
        if len(state.tombstones) > state.capacity_policy.max_recent_tombstones:
            raise ValueError("persisted tombstones exceed capacity")
        if len(state.used_roots) > state.capacity_policy.max_consumed_root_ids:
            raise ValueError("persisted consumed physical roots exceed capacity")
        if len(state.used_receipts) > (
            state.capacity_policy.max_consumed_receipt_ids
        ):
            raise ValueError("persisted consumed receipt ids exceed capacity")
        for tombstone in state.tombstones:
            transition = transitions.get(tombstone.subject_id)
            if transition is None or not (
                tombstone.namespace_digest == transition.namespace.digest
                and tombstone.portable_pair_sha256
                == self._portable_pair_sha256_from_factors(transition, factors)
                and tombstone.background_sha256
                == self._transition_background_sha256(transition)
                and tombstone.artifact_sha256
                == compositions[transition.target_composition_id].artifact_sha256
            ):
                raise ValueError("negative tombstone transition closure is invalid")
        if len(state.checkpoints) > state.capacity_policy.max_checkpoints:
            raise ValueError("persisted checkpoints exceed capacity")
        checkpoint_subject_rows = [
            subject_id
            for checkpoint in state.checkpoints
            for subject_id in checkpoint.subject_ids
        ]
        if len(checkpoint_subject_rows) != len(set(checkpoint_subject_rows)):
            raise ValueError("checkpoint subjects overlap")
        checkpoint_edge_owner: dict[str, str] = {}
        for checkpoint in state.checkpoints:
            if checkpoint.capacity_policy_sha256 != state.capacity_policy.digest:
                raise ValueError("cold checkpoint capacity policy is stale")
            if checkpoint.merkle_root_sha256 != _sha256(
                checkpoint.archive_root_body
            ):
                raise ValueError("cold checkpoint exact manifest root is stale")
            if checkpoint.created_seq != checkpoint.epoch_end_seq + 1:
                raise ValueError("cold checkpoint event boundary is not contiguous")
            subject_transitions = [
                transitions.get(subject_id) for subject_id in checkpoint.subject_ids
            ]
            if any(item is None for item in subject_transitions):
                raise ValueError("cold checkpoint subject transition is missing")
            exact_subject_transitions = cast(
                list[ScientificTransitionV2],
                subject_transitions,
            )
            if checkpoint.epoch_start_seq != min(
                item.created_seq for item in exact_subject_transitions
            ):
                raise ValueError("cold checkpoint epoch start is not reproducible")
            if any(
                item.structural_state == "live"
                or item.created_seq > checkpoint.epoch_end_seq
                or item.namespace.digest != checkpoint.namespace_digest
                for item in exact_subject_transitions
            ):
                raise ValueError("cold checkpoint subject closure is invalid")
            checkpoint_subject_set = set(checkpoint.subject_ids)
            checkpoint_edge_keys = {
                self._canonical_scientific_edge_sha256(state, item)
                for item in exact_subject_transitions
            }
            expected_group_subjects = {
                member.transition_id
                for edge_key in checkpoint_edge_keys
                for member in canonical_groups[edge_key]
            }
            if checkpoint_subject_set != expected_group_subjects:
                raise ValueError(
                    "cold checkpoint does not own complete canonical groups"
                )
            for edge_key in checkpoint_edge_keys:
                prior_checkpoint_id = checkpoint_edge_owner.setdefault(
                    edge_key,
                    checkpoint.checkpoint_id,
                )
                if prior_checkpoint_id != checkpoint.checkpoint_id:
                    raise ValueError("checkpoint canonical groups overlap")
            for manifest in checkpoint.archived_epoch_manifests:
                transition = transitions.get(manifest.exact_transition_id)
                if transition is None or not (
                    manifest.exact_transition_id in checkpoint_subject_set
                    and manifest.exact_transition_id
                    == manifest.credit_owner_transition_id
                    and manifest.canonical_scientific_edge_key_sha256
                    in checkpoint_edge_keys
                    and self._canonical_scientific_edge_sha256(state, transition)
                    == manifest.canonical_scientific_edge_key_sha256
                    and self._credit_owner_transition_id(state, transition)
                    == manifest.credit_owner_transition_id
                ):
                    raise ValueError(
                        "archived epoch manifest transition/owner closure is invalid"
                    )
            if self._archive_verifier is None:
                raise RuntimeError("persisted checkpoint requires trusted archive verifier")
            try:
                valid = bool(
                    self._archive_verifier(
                        checkpoint.merkle_root_sha256,
                        checkpoint.archive_attestation_sha256,
                    )
                )
            except Exception as exc:
                raise RuntimeError("persisted archive checkpoint verification failed") from exc
            if not valid:
                raise ValueError("persisted archive checkpoint was rejected")
        if len(state.portable_evidence_leaves) > (
            state.capacity_policy.max_portable_evidence_leaves
        ):
            raise ValueError("persisted portable evidence leaves exceed capacity")
        checkpoints = {
            item.checkpoint_id: item for item in state.checkpoints
        }
        for leaf in state.portable_evidence_leaves:
            transition = direct.get(leaf.transition_id)
            checkpoint = checkpoints.get(leaf.checkpoint_id)
            expected_id = _opaque_id("pel", leaf.attestation_body)
            expected_attestation = _mac(
                self._key,
                "portable-evidence-leaf-v1",
                leaf.attestation_body,
            )
            if transition is None or checkpoint is None or not (
                transition.transition_id in checkpoint.subject_ids
                and transition.structural_state != "live"
                and leaf.namespace_digest == transition.namespace.digest
                and leaf.portable_pair_sha256
                == self._portable_pair_sha256_from_factors(
                    transition,
                    factors,
                )
                and leaf.background_sha256
                == transition.fixed_background_sha256
                and leaf.checkpoint_merkle_root_sha256
                == checkpoint.merkle_root_sha256
                and leaf.created_seq == checkpoint.created_seq
                and leaf.source_revision_seq < leaf.created_seq
                and leaf.leaf_id == expected_id
                and hmac.compare_digest(
                    leaf.bank_attestation_sha256,
                    expected_attestation,
                )
            ):
                raise ValueError("portable evidence leaf closure is invalid")
        policy = state.capacity_policy
        if len(state.factors) > policy.max_factor_records:
            raise ValueError("persisted factors exceed record capacity")
        if len(state.compositions) > policy.max_composition_records:
            raise ValueError("persisted compositions exceed record capacity")
        if len(state.direct_transitions) + len(state.whole_transitions) > (
            policy.max_transition_records
        ):
            raise ValueError("persisted transitions exceed record capacity")
        if len(state.plans) > policy.max_plan_records:
            raise ValueError("persisted plans exceed record capacity")
        if len(state.gate_receipts) > policy.max_gate_receipts:
            raise ValueError("persisted gate receipts exceed record capacity")
        if len(state.deployment_heads) > policy.max_deployment_slots:
            raise ValueError("persisted deployment slots exceed record capacity")
        namespace_digests = {item.namespace.digest for item in state.compositions}
        for namespace_digest in namespace_digests:
            scoped_live = [
                item
                for item in state.compositions
                if item.namespace.digest == namespace_digest
                and item.structural_state == "live"
            ]
            if len(scoped_live) > (
                policy.max_hot_compositions_per_namespace
                + policy.unknown_structural_reserve
            ):
                raise ValueError("persisted hot compositions exceed namespace capacity")
            if sum(item.canonical_metadata_bytes for item in scoped_live) > (
                policy.max_hot_metadata_bytes
            ):
                raise ValueError("persisted hot metadata bytes exceed capacity")
            if sum(item.artifact_bytes for item in scoped_live) > (
                policy.max_hot_artifact_bytes_per_namespace
            ):
                raise ValueError("persisted hot artifact bytes exceed capacity")
            if sum(item.prompt_summary_tokens for item in scoped_live) > (
                policy.max_prompt_summary_tokens_per_namespace
            ):
                raise ValueError("persisted prompt-summary tokens exceed capacity")
        cold_bytes = sum(
            item.canonical_metadata_bytes + item.artifact_bytes
            for item in state.compositions
            if item.structural_state == "cold"
        )
        if cold_bytes > policy.max_cold_metadata_bytes:
            raise ValueError("persisted cold composition bytes exceed capacity")
        if base_receipts and not state.deployment_heads:
            raise ValueError("base receipts exist without deployment heads")

    @_linearized_bank_read
    def to_state(self) -> FactorBankStateV2:
        self._validate_state(self._state)
        return self._state.model_copy(deep=True)

    @property
    @_linearized_bank_read
    def scientific_state_sha256(self) -> str:
        return self.to_state().digest

    @_linearized_bank_read
    def read_only_snapshot(self) -> "ReadOnlyFactorBankV2":
        """Freeze the terminal TEST view with no writer capability attached."""

        return ReadOnlyFactorBankV2(self.to_state())

    def save(self, path: Path | str) -> None:
        """Durably publish one snapshot at the mutation linearization point.

        Public saves share the instance's re-entrant mutation lock.  Without
        this fence a caller could capture an old immutable state, wait while a
        mutation durably publishes a newer one, and then pass file CAS using
        the instance hash updated by that mutation.  The lock is re-entrant so
        the automatic save at outer transaction commit cannot deadlock.
        """

        with self._mutation_lock:
            self._save_locked(path)

    def _save_locked(self, path: Path | str) -> None:
        target = Path(path).resolve()
        if self._persisted_path is not None and target != self._persisted_path:
            raise RuntimeError("an authoritative SFT Bank cannot change its state path")
        target.parent.mkdir(parents=True, exist_ok=True)
        state = self.to_state()
        state_sha = state.digest
        envelope = StateEnvelopeV2(
            state=state,
            state_sha256=state_sha,
            state_hmac_sha256=_mac(self._key, "sft-bank-state-v14", state),
        )
        payload = (
            json.dumps(
                envelope.model_dump(mode="json"),
                ensure_ascii=True,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        envelope_sha = hashlib.sha256(payload).hexdigest()
        lock_path = target.with_suffix(target.suffix + ".lock")
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if target.exists():
                current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
                if self._persisted_envelope_sha256 is None:
                    raise RuntimeError("refusing to overwrite an unowned SFT state file")
                if current_sha != self._persisted_envelope_sha256:
                    raise RuntimeError("SFT state changed concurrently; compare-and-swap failed")
            elif self._persisted_envelope_sha256 is not None:
                raise RuntimeError("persisted SFT state disappeared before compare-and-swap")
            temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
            with temporary.open("wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    # File fsync + atomic replace already published the state;
                    # do not roll the object back if directory fsync is absent.
                    pass
            finally:
                os.close(directory_fd)
            self._persisted_path = target
            self._persisted_envelope_sha256 = envelope_sha
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        state_key: bytes,
        **capabilities: Any,
    ) -> "FactorBankV2":
        target = Path(path).resolve()
        raw_bytes = target.read_bytes()
        raw = json.loads(raw_bytes)
        if isinstance(raw, dict) and raw.get("schema_version") == "pif_shadow_v1":
            raise LegacyStateRejected(
                "pif_shadow_v1 cannot be causally upgraded; import structure explicitly"
            )
        serialized_schema = (
            raw.get("state", {}).get("schema_version")
            if isinstance(raw, dict) and isinstance(raw.get("state"), dict)
            else None
        )
        if serialized_schema != SFT_BANK_SCHEMA_VERSION:
            raise LegacyStateRejected(
                "unsupported or legacy FactorBank schema; explicit migration required"
            )
        envelope = StateEnvelopeV2.model_validate(raw)
        if envelope.state_sha256 != envelope.state.digest:
            raise ValueError("SFT state digest mismatch")
        expected_mac = _mac(state_key, "sft-bank-state-v14", envelope.state)
        if not hmac.compare_digest(envelope.state_hmac_sha256, expected_mac):
            raise ValueError("SFT state HMAC mismatch")
        bank = cls(envelope.state, state_key=state_key, **capabilities)
        bank._persisted_path = target
        bank._persisted_envelope_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return bank


class ReadOnlyFactorBankV2:
    """Terminal TEST facade: no writer capability or mutation method exists."""

    def __init__(self, state: FactorBankStateV2) -> None:
        self._state = FactorBankStateV2.model_validate(
            state.model_dump(mode="python")
        )
        self._digest = self._state.digest

    @property
    def scientific_state_sha256(self) -> str:
        if self._state.digest != self._digest:
            raise RuntimeError("read-only SFT state was corrupted")
        return self._digest

    def retrieve(
        self,
        namespace: ExecutionNamespace,
        *,
        limit: int = 3,
    ) -> list[CompositionRevisionV2]:
        if self._state.digest != self._digest:
            raise RuntimeError("read-only SFT state was corrupted")
        if limit < 0:
            raise ValueError("retrieval limit must be non-negative")
        compositions = {item.composition_id: item for item in self._state.compositions}
        heads = [
            item for item in self._state.deployment_heads
            if item.namespace_digest == namespace.digest and item.state == "active"
        ]
        heads.sort(key=lambda item: (-item.generation, item.deployment_slot_id))
        return [
            compositions[item.active_composition_id]
            for item in heads[:limit]
            if item.active_composition_id is not None
        ]


def make_proposal_generation_context_v1(
    *,
    opportunity: RepairOpportunityV2,
    failure: FailureObservationV2,
    proposal_receipt: ProposalReceiptV1,
    source: CompositionRevisionV2,
    source_factor: FactorRevisionV2,
    source_manifest_sha256: str,
    train_update_source_catalog_sha256: str,
    train_update_policy_sha256: str,
    generation_policy_sha256: str,
    prompt_template_sha256: str,
    scalar_output_schema_sha256: str,
    budget: ExecutionBudget,
    verifier_epoch: str,
    attestation_sha256: str,
) -> ProposalGenerationContextV1:
    """Build the closed context that a concrete Phase verifier must resolve."""

    budget = ExecutionBudget.model_validate(budget.model_dump(mode="python"))
    body = {
        "context_version": "sft_proposal_generation_context_v1",
        "proposal_receipt_sha256": proposal_receipt.digest,
        "repair_opportunity_id": opportunity.opportunity_id,
        "repair_opportunity_sha256": opportunity.digest,
        "failure_observation_sha256": _sha256(failure),
        "namespace_digest": source.namespace.digest,
        "source_composition_id": source.composition_id,
        "source_artifact_id": source.artifact_revision_id,
        "slot_id": proposal_receipt.request.cell.locus.slot_id,
        "locator_path": source_factor.locator.path,
        "from_revision_id": source_factor.revision_id,
        "source_manifest_sha256": source_manifest_sha256,
        "train_update_source_catalog_sha256": train_update_source_catalog_sha256,
        "train_update_policy_sha256": train_update_policy_sha256,
        "safe_failure_code": opportunity.safe_failure_code,
        "failure_artifact_sha256": source.artifact_sha256,
        "generation_policy_sha256": generation_policy_sha256,
        "prompt_template_sha256": prompt_template_sha256,
        "scalar_output_schema_sha256": scalar_output_schema_sha256,
        "model_name": "gpt-4o-mini",
        "runtime_version": source.namespace.runtime_version,
        "budget": budget,
        "budget_sha256": budget.digest,
        "verifier_epoch": verifier_epoch,
        "attestation_sha256": attestation_sha256,
    }
    return ProposalGenerationContextV1(
        context_id=_opaque_id("pgc", body),
        **body,
    )


def make_proposal_generation_lease_v1(
    *,
    action: ProposalActionV2,
    runner_session_id: str,
    runner_lease_token_sha256: str,
    journal_anchor_sha256: str,
    verifier_epoch: str,
    attestation_sha256: str,
) -> ProposalGenerationLeaseV1:
    if action.state != "prepared" or action.generation_request is None:
        raise ValueError("generation lease requires a prepared generated action")
    body = {
        "lease_version": "sft_proposal_generation_lease_v1",
        "action_id": action.action_id,
        "generation_request_sha256": action.generation_request.digest,
        "expected_prepared_action_sha256": action.digest,
        "runner_session_id": runner_session_id,
        "runner_lease_token_sha256": runner_lease_token_sha256,
        "fencing_generation": 1,
        "journal_anchor_sha256": journal_anchor_sha256,
        "verifier_epoch": verifier_epoch,
        "attestation_sha256": attestation_sha256,
    }
    return ProposalGenerationLeaseV1(
        lease_id=_opaque_id("pgl", body),
        **body,
    )


def make_proposal_action_abort_receipt_v2(
    *,
    action: ProposalActionV2,
    reason: Literal[
        "phase_noop", "phase_rejected", "lease_expired", "runner_fenced",
        "carrier_capacity", "generation_invalid_output",
        "generation_budget_exceeded", "generation_runner_crash",
        "generation_terminal_rejected",
    ],
    safe_failure_code: str,
    verifier_epoch: str,
    attestation_sha256: str,
    phase_terminal_sha256: str | None = None,
    cleanup_transition: DirectFactorTransitionV2 | None = None,
    cleanup_admission: ProposalCarrierAdmissionV1 | None = None,
) -> ProposalActionAbortReceiptV2:
    if action.state not in {"prepared", "executing"}:
        raise ValueError("abort receipt requires a nonterminal proposal action")
    body = {
        "receipt_version": "sft_proposal_action_abort_v2",
        "action_id": action.action_id,
        "predecessor_state": action.state,
        "expected_action_sha256": action.digest,
        "reason": reason,
        "phase_terminal_sha256": phase_terminal_sha256,
        "expected_fencing_generation": 1,
        "next_fencing_generation": 2,
        "safe_failure_code": safe_failure_code,
        "verifier_epoch": verifier_epoch,
        "attestation_sha256": attestation_sha256,
    }
    if (cleanup_transition is None) != (cleanup_admission is None):
        raise ValueError(
            "cleanup receipt requires both transition and staged admission"
        )
    if cleanup_transition is not None:
        assert cleanup_admission is not None
        generated_cleanup = action.state == "executing" and action.branch in {
            "mutate", "fresh",
        }
        reuse_cleanup = (
            action.state == "prepared"
            and action.branch == "reuse"
            and reason == "phase_rejected"
            and phase_terminal_sha256 is not None
        )
        if not (generated_cleanup or reuse_cleanup) or not (
            cleanup_transition.proposal_action_id == action.action_id
            and cleanup_transition.proposal_action_intent_sha256
            == action.action_intent_sha256
            and cleanup_transition.origin_branch == action.branch
            and cleanup_transition.namespace.digest == action.namespace_digest
            and cleanup_transition.source_composition_id
            == action.source_composition_id
            and cleanup_transition.slot_id == action.slot_id
            and cleanup_transition.from_revision_id == action.from_revision_id
            and cleanup_transition.proposal_action_committed_seq is None
            and (
                phase_terminal_sha256 is None
                or phase_terminal_sha256
                == cleanup_transition.binding_proof_sha256
            )
            and cleanup_admission.action_id == action.action_id
            and cleanup_admission.action_intent_sha256
            == action.action_intent_sha256
            and cleanup_admission.transition_id
            == cleanup_transition.transition_id
            and cleanup_admission.projected_transition_sha256
            == _sha256(
                FactorBankV2._projected_action_transition(cleanup_transition)
            )
            and cleanup_admission.state == "staged"
        ):
            raise ValueError(
                "cleanup receipt requires the action's exact generated inert edge"
            )
        body.update(
            {
                "cleanup_transition_id": cleanup_transition.transition_id,
                "cleanup_transition_sha256": _sha256(cleanup_transition),
                "cleanup_action_intent_sha256": action.action_intent_sha256,
                "cleanup_admission_id": cleanup_admission.admission_id,
                "cleanup_admission_sha256": cleanup_admission.digest,
            }
        )
    return ProposalActionAbortReceiptV2(
        abort_id=_opaque_id("pab", body),
        **body,
    )


def make_assignment_receipt_v2(
    *,
    plan: ProbePlanV2,
    ordinal: int,
    origin_pool_sha256: str,
    producer_epoch: str,
    attestation_sha256: str,
) -> AssignmentReceiptV2:
    unit = plan.units[ordinal]
    return AssignmentReceiptV2(
        assignment_receipt_id=_opaque_id("ar", {"plan": plan.plan_id, "ordinal": ordinal}),
        plan_id=plan.plan_id,
        plan_sha256=plan.digest,
        ordinal=ordinal,
        unit_commitment=unit.unit_commitment,
        arm_order=unit.arm_order,
        origin_pool_sha256=origin_pool_sha256,
        assignment_manifest_sha256=plan.assignment_manifest_sha256,
        without_replacement_index=ordinal,
        producer_epoch=producer_epoch,
        attestation_sha256=attestation_sha256,
    )


def make_runner_lease_grant_v1(
    *,
    plan: ProbePlanV2,
    assignment: AssignmentReceiptV2,
    runner_session_id: str,
    runner_lease_token_sha256: str,
    journal_anchor_sha256: str,
    verifier_epoch: str,
    attestation_sha256: str,
) -> RunnerLeaseGrantV1:
    """Build the public commitment of a host-owned runner lease."""

    attempt_id = _opaque_id(
        "at", {"plan": plan.plan_id, "ordinal": assignment.ordinal}
    )
    body = {
        "lease_version": "runner_lease_v1",
        "attempt_id": attempt_id,
        "plan_id": plan.plan_id,
        "ordinal": assignment.ordinal,
        "assignment_receipt_sha256": _sha256(assignment),
        "scheduled_arm_order": assignment.arm_order,
        "runner_session_id": runner_session_id,
        "runner_lease_token_sha256": runner_lease_token_sha256,
        "fencing_generation": 1,
        "journal_anchor_sha256": journal_anchor_sha256,
        "verifier_epoch": verifier_epoch,
    }
    return RunnerLeaseGrantV1(
        lease_id=_opaque_id("rl", body),
        **body,
        attestation_sha256=attestation_sha256,
    )


def make_pair_execution_receipt_v2(
    *,
    attempt: ProbeAttemptV3,
    source_root_id: str,
    target_root_id: str,
    source_started_seq: int,
    source_finished_seq: int,
    target_started_seq: int,
    target_finished_seq: int,
    verifier_epoch: str,
    attestation_sha256: str,
) -> PairExecutionReceiptV2:
    """Build the outcome-free terminal receipt emitted by a trusted runner."""

    observed_order: Literal["AB", "BA"] = (
        "AB" if source_started_seq < target_started_seq else "BA"
    )
    event_identity = {
        "attempt": attempt.attempt_id,
        "assignment": _sha256(attempt.assignment),
        "source_root": source_root_id,
        "target_root": target_root_id,
        "runner_lease": attempt.runner_lease.digest,
    }
    schedule_event_id = _opaque_id("pe", {**event_identity, "event": "schedule"})
    source_start_id = _opaque_id("pe", {**event_identity, "event": "source_start"})
    target_start_id = _opaque_id("pe", {**event_identity, "event": "target_start"})
    source_finish_id = _opaque_id("pe", {**event_identity, "event": "source_finish"})
    target_finish_id = _opaque_id("pe", {**event_identity, "event": "target_finish"})
    terminal_event_id = _opaque_id("pe", {**event_identity, "event": "pair_complete"})
    schedule_seq = min(source_started_seq, target_started_seq) - 1
    terminal_seq = max(source_finished_seq, target_finished_seq) + 1
    schedule = runner_schedule_commitment_v1(
        expected_open_attempt_sha256=_sha256(attempt),
        assignment_receipt_sha256=_sha256(attempt.assignment),
        plan_id=attempt.plan_id,
        ordinal=attempt.ordinal,
        scheduled_arm_order=attempt.assignment.arm_order,
        runner_session_id=attempt.runner_lease.runner_session_id,
        runner_lease_token_sha256=attempt.runner_lease.runner_lease_token_sha256,
        fencing_generation=attempt.runner_lease.fencing_generation,
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        prestart_schedule_event_id=schedule_event_id,
        prestart_schedule_event_seq=schedule_seq,
    )
    event_root = pair_event_root_v1(
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        schedule_commitment_sha256=schedule,
        observed_arm_order=observed_order,
        source_root_id=source_root_id,
        target_root_id=target_root_id,
        source_started_event_id=source_start_id,
        source_started_seq=source_started_seq,
        source_finished_event_id=source_finish_id,
        source_finished_seq=source_finished_seq,
        target_started_event_id=target_start_id,
        target_started_seq=target_started_seq,
        target_finished_event_id=target_finish_id,
        target_finished_seq=target_finished_seq,
        terminal_event_id=terminal_event_id,
        terminal_event_seq=terminal_seq,
        runner_lease_token_sha256=attempt.runner_lease.runner_lease_token_sha256,
        fencing_generation=attempt.runner_lease.fencing_generation,
    )
    return PairExecutionReceiptV2(
        pair_receipt_id=_opaque_id(
            "px",
            {
                "attempt": _sha256(attempt),
                "runner_lease": attempt.runner_lease.digest,
                "terminal_event_root": event_root,
            },
        ),
        plan_id=attempt.plan_id,
        ordinal=attempt.ordinal,
        assignment_receipt_sha256=_sha256(attempt.assignment),
        expected_open_attempt_sha256=_sha256(attempt),
        scheduled_arm_order=attempt.assignment.arm_order,
        runner_lease_sha256=attempt.runner_lease.digest,
        runner_lease_token_sha256=attempt.runner_lease.runner_lease_token_sha256,
        fencing_generation=attempt.runner_lease.fencing_generation,
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        source_root_id=source_root_id,
        target_root_id=target_root_id,
        prestart_schedule_event_id=schedule_event_id,
        prestart_schedule_event_seq=schedule_seq,
        schedule_commitment_sha256=schedule,
        source_started_event_id=source_start_id,
        target_started_event_id=target_start_id,
        source_finished_event_id=source_finish_id,
        target_finished_event_id=target_finish_id,
        source_started_seq=source_started_seq,
        target_started_seq=target_started_seq,
        source_finished_seq=source_finished_seq,
        target_finished_seq=target_finished_seq,
        terminal_event_id=terminal_event_id,
        terminal_event_seq=terminal_seq,
        observed_arm_order=observed_order,
        runner_session_id=attempt.runner_lease.runner_session_id,
        runner_event_root_sha256=event_root,
        verifier_epoch=verifier_epoch,
        attestation_sha256=attestation_sha256,
    )


def paired_execution_root_v2(
    *,
    assignment: AssignmentReceiptV2,
    pair_receipt: PairExecutionReceiptV2,
) -> str:
    """Commit one frozen assignment to independently observed physical order.

    The runner receipt derives order from non-overlapping start/finish spans;
    assignment order is only the predeclared schedule to be compliance-joined.
    """

    assignment = AssignmentReceiptV2.model_validate(
        assignment.model_dump(mode="python")
    )
    pair_receipt = PairExecutionReceiptV2.model_validate(
        pair_receipt.model_dump(mode="python")
    )
    ordered_roots = (
        (pair_receipt.source_root_id, pair_receipt.target_root_id)
        if pair_receipt.observed_arm_order == "AB"
        else (pair_receipt.target_root_id, pair_receipt.source_root_id)
    )
    return _sha256(
        {
            "protocol": "sft-paired-execution-root-v2",
            "assignment_receipt_sha256": _sha256(assignment),
            "pair_execution_receipt_sha256": pair_receipt.digest,
            "observed_arm_order": pair_receipt.observed_arm_order,
            "ordered_arm_roots": ordered_roots,
        }
    )


def make_arm_receipt_v2(
    *,
    plan: ProbePlanV2,
    attempt: ProbeAttemptV3,
    composition: CompositionRevisionV2,
    transition: ScientificTransitionV2,
    arm: Literal["source", "target"],
    root_id: str,
    paired_arm_root_id: str,
    pair_execution_receipt: PairExecutionReceiptV2,
    runtime_profile_id: str,
    materialization_event_id: str,
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
    expected_artifact = (
        plan.source_artifact_sha256 if arm == "source" else plan.target_artifact_sha256
    )
    activated = (
        (
            transition.from_revision_id if arm == "source" else transition.to_revision_id,
        )
        if isinstance(transition, DirectFactorTransitionV2)
        else ()
    )
    support_id = (
        transition.binding_proof_id
        if isinstance(transition, DirectFactorTransitionV2)
        else transition.transition_id
    )
    pair_execution_receipt = PairExecutionReceiptV2.model_validate(
        pair_execution_receipt.model_dump(mode="python")
    )
    observed_order = pair_execution_receipt.observed_arm_order
    arm_position: Literal[0, 1] = (
        0
        if (
            (observed_order == "AB" and arm == "source")
            or (observed_order == "BA" and arm == "target")
        )
        else 1
    )
    source_root_id = root_id if arm == "source" else paired_arm_root_id
    target_root_id = paired_arm_root_id if arm == "source" else root_id
    if (
        source_root_id != pair_execution_receipt.source_root_id
        or target_root_id != pair_execution_receipt.target_root_id
    ):
        raise ValueError("arm receipt roots differ from terminal pair receipt")
    pair_root = paired_execution_root_v2(
        assignment=attempt.assignment,
        pair_receipt=pair_execution_receipt,
    )
    return ArmReceiptV2(
        receipt_id=_opaque_id(
            "rc", {"attempt": attempt.attempt_id, "arm": arm, "root": root_id}
        ),
        plan_id=plan.plan_id,
        ordinal=attempt.ordinal,
        arm=arm,
        root_id=root_id,
        observed_arm_order=observed_order,
        arm_position=arm_position,
        paired_execution_root_sha256=pair_root,
        pair_execution_receipt_sha256=pair_execution_receipt.digest,
        assignment_receipt_sha256=_sha256(attempt.assignment),
        unit_commitment=attempt.assignment.unit_commitment,
        namespace_digest=plan.namespace_digest,
        composition_id=composition.composition_id,
        assigned_artifact_sha256=expected_artifact,
        materialized_artifact_sha256=expected_artifact,
        selected_artifact_sha256=expected_artifact,
        loaded_artifact_sha256=expected_artifact,
        loaded_binding_ids=tuple(sorted(composition.binding_map.values())),
        activated_direct_factor_revision_ids=activated,
        activation_trace_root=activation_trace_root,
        runtime_profile_id=runtime_profile_id,
        materialization_event_id=materialization_event_id,
        binding_proof_id=support_id,
        model_name=plan.model_name,
        runtime_version=plan.runtime_version,
        budget_sha256=plan.budget_sha256,
        usage=usage,
        execution_class=execution_class,
        outcome=outcome,
        safe_failure_code=safe_failure_code,
        failed_stage_rank=failed_stage_rank,
        producer_epoch=producer_epoch,
        attestation_sha256=attestation_sha256,
    )


# Import-only aliases keep sibling adapters importable during the atomic v9
# rollout.  Proposal aliases expose the current class to Phase adapters; they
# do not accept or migrate older serialized authority.
PairExecutionReceiptV1 = PairExecutionReceiptV2
ProbeAttemptV2 = ProbeAttemptV3
make_pair_execution_receipt_v1 = make_pair_execution_receipt_v2
ProposalActionV1 = ProposalActionV2
ProposalActionAbortReceiptV1 = ProposalActionAbortReceiptV2


__all__ = [
    "AggregatePolicyV1",
    "ArchivedEpochManifestV1",
    "ArmReceiptV2",
    "AssignmentReceiptV2",
    "AttemptCancellationReceiptV3",
    "BaseSnapshotReceiptV2",
    "BranchAssignmentV2",
    "CapacityPolicyV1",
    "CompositionRevisionV2",
    "DirectFactorTransitionV2",
    "EdgeAssessmentV2",
    "FactorBankStateV2",
    "FactorBankV2",
    "FactorRevisionV2",
    "FailureObservationV2",
    "GateOpportunityV2",
    "GateReceiptV2",
    "LegacyStateRejected",
    "MAX_PROPOSAL_DECISION_BYTES",
    "PairExecutionReceiptV2",
    "ProbeAttemptV3",
    "ProbePlanV2",
    "ProbeUnitV2",
    "ProposalActionAbortReceiptV1",
    "ProposalActionAbortReceiptV2",
    "ProposalActionV1",
    "ProposalActionV2",
    "ProposalCarrierCapacityReservationV1",
    "ProposalCarrierAdmissionV1",
    "ProposalDecisionV1",
    "ProposalGenerationContextV1",
    "ProposalGenerationLeaseV1",
    "ProposalGenerationRequestV1",
    "ProposalLifetimeCounterV1",
    "PortableEvidenceLeafV1",
    "ReadOnlyFactorBankV2",
    "RepairOpportunityV2",
    "RollbackRecordV2",
    "RollbackTriggerV2",
    "SFT_BANK_SCHEMA_VERSION",
    "StateEnvelopeV2",
    "RunnerLeaseGrantV1",
    "StartedArmJournalWitnessV2",
    "WholeCompositionTransitionV2",
    "classify_attempt_vote",
    "cancellation_event_root_v3",
    "pair_event_root_v1",
    "runner_schedule_commitment_v1",
    "make_arm_receipt_v2",
    "make_assignment_receipt_v2",
    "make_pair_execution_receipt_v2",
    "make_proposal_action_abort_receipt_v2",
    "make_proposal_generation_context_v1",
    "make_proposal_generation_lease_v1",
    "make_runner_lease_grant_v1",
    "paired_execution_root_v2",
    "next_allowed_ordinal",
    "recompute_assessment",
]
