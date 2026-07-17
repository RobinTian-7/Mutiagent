"""Default-off PIF/FACTS shadow bank for exact factor interventions.

The current :class:`~exp_graph.mas.skill_bank.SkillBank` remains the deployed
bank.  This module is an experimental, import-only shadow implementation of the
minimum PIF transaction: one host-proved factor replacement is simultaneously
the legal local search move, the only owner of matched outcome evidence, and
the lifecycle edge that can put a complete composition on probation.

The implementation intentionally does not decide whether natural-language
content is "the same skill".  A carrier binder must provide stable locators,
canonical artifact hashes, and a final loaded receipt.  Unsupported carriers
remain ``locked_atomic`` and cannot mint factor credit.  TEST data never enters
these schemas; callers receive a read-only snapshot for terminal evaluation.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


FactorCarrier = Literal[
    "named_topology",
    "paper_transport",
    "graph",
    "phase_program",
    "python_source",
    "reasoning_policy",
    "constraint",
    "insight",
]
BindingStatus = Literal["locked_atomic", "proven_factorized"]
OriginBranch = Literal["reuse", "mutate", "fresh", "migration"]
RevisionState = Literal[
    "registered",
    "shadow",
    "probing",
    "probation",
    "active",
    "refuted",
    "archived",
    "quarantine",
]
EdgeState = Literal[
    "registered",
    "probing",
    "probed",
    "candidate",
    "active",
    "refuted",
    "archived",
    "quarantine",
]
BlockState = Literal["sealed", "committed", "incomplete", "quarantine"]
ExecutionClass = Literal[
    "completed",
    "algorithm_failure",
    "infrastructure_failure",
    "harness_failure",
]
ArmName = Literal["source", "target"]
SplitName = Literal["TRAIN_UPDATE", "GATE_DEV", "FINAL_VAL", "ATTRIB_VAL", "TEST"]
PlannerRuntimeMode = Literal[
    "topology_select",
    "operator_compose",
    "graph_generate",
    "program_generate",
    "python_generate",
    "paper_protocol_runtime",
]
PayloadFormat = Literal[
    "named_topology_skill_v1",
    "paper_transport_skill_v1",
    "graph_skill_v1",
    "phase_program_skill_v1",
    "python_skill_v1",
]
WorkerContract = Literal[
    "not_applicable",
    "action_json_v1",
    "message_only_v1",
    "message_only_v2",
]


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_VALUE_MARKERS = (
    "ground_truth",
    "ground truth",
    "expected_output",
    "expected output",
    "private_prompt",
    "private prompt",
    "eval_seed",
    "test_case",
    "test_answer",
    "reference_answer",
    "judge_rationale",
    "final_answer",
    "answer_key",
    "solution_text",
    "verifier_test",
)


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
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_id(value: str, *, field_name: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a short opaque identifier")
    return value


def _require_sha256(value: str, *, field_name: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _reject_forbidden_values(value: Any) -> None:
    """Reject obvious oracle/private-data encodings from Bank-visible strings."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered_key = str(key).lower()
            if any(marker.replace(" ", "_") in lowered_key for marker in _FORBIDDEN_VALUE_MARKERS):
                raise ValueError(f"forbidden Bank-visible field: {key}")
            _reject_forbidden_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _reject_forbidden_values(item)
        return
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _FORBIDDEN_VALUE_MARKERS):
            raise ValueError("forbidden oracle/private-data marker in Bank-visible value")


def assert_bank_safe_public_value(value: Any) -> None:
    """Public ingestion guard for carrier binders and artifact adapters.

    This is a conservative marker barrier, not a semantic privacy oracle.  A
    caller must additionally supply a split/public-source attestation; the
    helper merely makes common answer/TEST/private-prompt encodings fail closed
    before they can be hashed or persisted.
    """

    _reject_forbidden_values(value)


class _ClosedModel(BaseModel):
    # Immutable state objects make an execution receipt or factor revision keep
    # the identity that was validated.  Mutable dictionaries are deliberately
    # absent from the scientific schema.
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def reject_oracle_values(self) -> "_ClosedModel":
        _reject_forbidden_values(self.model_dump(mode="python"))
        return self


class ExecutionNamespace(_ClosedModel):
    """Hard retrieval/evidence namespace; similarity never crosses this key."""

    task_family: str = Field(min_length=1, max_length=80)
    objective: Literal["accuracy_first", "budget_first", "balanced"]
    information_goal: Literal["sink", "all_agents"]
    planner_mode: PlannerRuntimeMode
    payload_format: PayloadFormat
    worker_contract: WorkerContract = "not_applicable"
    n_agents: int = Field(ge=1, le=1024)
    array_size_bucket: str = Field(min_length=1, max_length=80)
    budget_level: Literal["loose", "normal", "tight"]
    model_name: str = Field(min_length=1, max_length=100)
    runtime_version: str = Field(min_length=1, max_length=80)
    binder_version: str = Field(min_length=1, max_length=80)
    compiler_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_mode_contract(self) -> "ExecutionNamespace":
        expected_mode: dict[str, str] = {
            "paper_transport_skill_v1": "paper_protocol_runtime",
            "graph_skill_v1": "graph_generate",
            "phase_program_skill_v1": "program_generate",
            "python_skill_v1": "python_generate",
        }
        required = expected_mode.get(self.payload_format)
        if required is not None and self.planner_mode != required:
            raise ValueError(
                f"{self.payload_format} requires planner/runtime mode {required}"
            )
        if self.payload_format == "python_skill_v1":
            if self.worker_contract == "not_applicable":
                raise ValueError("Python factors require an explicit worker contract")
        elif self.worker_contract != "not_applicable":
            raise ValueError("non-Python factors cannot carry a Python worker contract")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class FactorLocator(_ClosedModel):
    """Host-owned locator; it is never inferred from outcome text."""

    surface: Literal[
        "atomic_artifact",
        "phase_field",
        "python_evolve_block",
        "graph_field",
        "reasoning_policy_field",
        "constraint_field",
        "insight_reference",
    ]
    path: str = Field(min_length=1, max_length=256)
    locator_version: str = Field(min_length=1, max_length=80)


class FactorRevision(_ClosedModel):
    """Immutable factor content identity; efficacy is deliberately absent."""

    revision_id: str
    logical_factor_id: str
    namespace: ExecutionNamespace
    carrier: FactorCarrier
    locator: FactorLocator
    binding_status: BindingStatus
    content_sha256: str
    parent_revision_id: str | None = None
    origin_branch: OriginBranch
    insight_ids: tuple[str, ...] = ()
    failure_hypothesis_ids: tuple[str, ...] = ()
    state: RevisionState = "registered"

    @model_validator(mode="after")
    def validate_identity(self) -> "FactorRevision":
        _require_id(self.revision_id, field_name="revision_id")
        _require_id(self.logical_factor_id, field_name="logical_factor_id")
        _require_sha256(self.content_sha256, field_name="content_sha256")
        if self.parent_revision_id is not None:
            _require_id(self.parent_revision_id, field_name="parent_revision_id")
        for value in (*self.insight_ids, *self.failure_hypothesis_ids):
            _require_id(value, field_name="reference id")
        if self.binding_status == "locked_atomic" and self.locator.surface != "atomic_artifact":
            raise ValueError("locked_atomic revisions must use atomic_artifact locators")
        if self.binding_status == "proven_factorized" and self.locator.surface == "atomic_artifact":
            raise ValueError("factorized revisions require a non-atomic host locator")
        executable_carrier = {
            "named_topology_skill_v1": "named_topology",
            "paper_transport_skill_v1": "paper_transport",
            "graph_skill_v1": "graph",
            "phase_program_skill_v1": "phase_program",
            "python_skill_v1": "python_source",
        }[self.namespace.payload_format]
        if self.carrier in {
            "named_topology",
            "paper_transport",
            "graph",
            "phase_program",
            "python_source",
        } and self.carrier != executable_carrier:
            raise ValueError("executable factor carrier does not match payload namespace")
        return self


class SlotBinding(_ClosedModel):
    slot_id: str
    factor_revision_id: str

    @model_validator(mode="after")
    def validate_ids(self) -> "SlotBinding":
        _require_id(self.slot_id, field_name="slot_id")
        _require_id(self.factor_revision_id, field_name="factor_revision_id")
        return self


class CompositionRevision(_ClosedModel):
    """Complete executable composition; this, not loose factors, is runnable."""

    composition_id: str
    namespace: ExecutionNamespace
    carrier: Literal[
        "named_topology",
        "paper_transport",
        "graph",
        "phase_program",
        "python_source",
    ]
    artifact_revision_id: str
    artifact_sha256: str
    bindings: tuple[SlotBinding, ...]
    origin_branch: OriginBranch
    parent_composition_id: str | None = None
    state: RevisionState = "shadow"
    archive_reason: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "CompositionRevision":
        _require_id(self.composition_id, field_name="composition_id")
        _require_id(self.artifact_revision_id, field_name="artifact_revision_id")
        _require_sha256(self.artifact_sha256, field_name="artifact_sha256")
        if self.parent_composition_id is not None:
            _require_id(self.parent_composition_id, field_name="parent_composition_id")
        slots = [binding.slot_id for binding in self.bindings]
        if not slots or len(slots) != len(set(slots)):
            raise ValueError("composition bindings must contain unique non-empty slots")
        if self.archive_reason is not None:
            _require_id(self.archive_reason, field_name="archive_reason")
        expected_carrier = {
            "named_topology_skill_v1": "named_topology",
            "paper_transport_skill_v1": "paper_transport",
            "graph_skill_v1": "graph",
            "phase_program_skill_v1": "phase_program",
            "python_skill_v1": "python_source",
        }[self.namespace.payload_format]
        if self.carrier != expected_carrier:
            raise ValueError("composition carrier does not match payload namespace")
        return self

    @property
    def binding_map(self) -> dict[str, str]:
        return {binding.slot_id: binding.factor_revision_id for binding in self.bindings}


class ExecutionBudget(_ClosedModel):
    """Six-dimensional hard cap sealed before outcomes."""

    max_messages: int = Field(ge=0)
    max_model_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_wall_time_ms: int = Field(ge=0)
    max_cost_microusd: int = Field(ge=0)

    @property
    def digest(self) -> str:
        return _sha256(self)


class ExecutionUsage(_ClosedModel):
    messages: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    wall_time_ms: int = Field(ge=0)
    cost_microusd: int = Field(ge=0)

    def within(self, budget: ExecutionBudget) -> bool:
        return (
            self.messages <= budget.max_messages
            and self.model_calls <= budget.max_model_calls
            and self.input_tokens <= budget.max_input_tokens
            and self.output_tokens <= budget.max_output_tokens
            and self.wall_time_ms <= budget.max_wall_time_ms
            and self.cost_microusd <= budget.max_cost_microusd
        )


class DenseOutcome(_ClosedModel):
    V: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    K: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    U: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    P: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    S: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    stage_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    C: float = Field(ge=0.0, allow_inf_nan=False)
    D: float = Field(ge=0.0, allow_inf_nan=False)

    def subtract(self, other: "DenseOutcome") -> "DenseDelta":
        return DenseDelta(
            V=self.V - other.V,
            K=self.K - other.K,
            U=self.U - other.U,
            P=self.P - other.P,
            S=self.S - other.S,
            stage_score=self.stage_score - other.stage_score,
            C=self.C - other.C,
            D=self.D - other.D,
        )


class DenseDelta(_ClosedModel):
    V: float = Field(allow_inf_nan=False)
    K: float = Field(allow_inf_nan=False)
    U: float = Field(allow_inf_nan=False)
    P: float = Field(allow_inf_nan=False)
    S: float = Field(allow_inf_nan=False)
    stage_score: float = Field(allow_inf_nan=False)
    C: float = Field(allow_inf_nan=False)
    D: float = Field(allow_inf_nan=False)


class CompletedBlockRef(_ClosedModel):
    block_id: str
    source_root_id: str
    target_root_id: str
    source_outcome: DenseOutcome
    target_outcome: DenseOutcome
    delta: DenseDelta
    source_algorithm_failure: bool
    target_algorithm_failure: bool
    randomized_common_origin_set: bool

    @model_validator(mode="after")
    def validate_ids(self) -> "CompletedBlockRef":
        _require_sha256(self.source_root_id, field_name="source_root_id")
        _require_sha256(self.target_root_id, field_name="target_root_id")
        _require_id(self.block_id, field_name="block_id")
        return self


class FactorTransition(_ClosedModel):
    """Comparator-conditioned directed edge and sole factor efficacy owner."""

    transition_id: str
    namespace: ExecutionNamespace
    source_composition_id: str
    target_composition_id: str
    slot_id: str
    from_revision_id: str
    to_revision_id: str
    fixed_background_sha256: str
    binding_proof_id: str
    binding_proof_sha256: str
    masked_background_sha256: str
    origin_branch: OriginBranch
    state: EdgeState = "registered"
    evidence_blocks: tuple[CompletedBlockRef, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> "FactorTransition":
        for name in (
            "transition_id",
            "source_composition_id",
            "target_composition_id",
            "slot_id",
            "from_revision_id",
            "to_revision_id",
            "binding_proof_id",
        ):
            _require_id(str(getattr(self, name)), field_name=name)
        _require_sha256(
            self.fixed_background_sha256,
            field_name="fixed_background_sha256",
        )
        _require_sha256(self.binding_proof_sha256, field_name="binding_proof_sha256")
        _require_sha256(
            self.masked_background_sha256,
            field_name="masked_background_sha256",
        )
        if self.from_revision_id == self.to_revision_id:
            raise ValueError("factor transition must change a revision")
        return self

    @property
    def mean_stage_delta(self) -> float:
        confirmatory = [
            block
            for block in self.evidence_blocks
            if block.randomized_common_origin_set
        ]
        if not confirmatory:
            return float("-inf")
        return sum(block.delta.stage_score for block in confirmatory) / len(
            confirmatory
        )

    @property
    def confirmatory_evidence_count(self) -> int:
        return sum(
            1 for block in self.evidence_blocks if block.randomized_common_origin_set
        )


class SealedProbeBlock(_ClosedModel):
    """Outcome-before manifest for one complete matched source/target block."""

    block_id: str
    transition_id: str
    namespace: ExecutionNamespace
    split: SplitName = "TRAIN_UPDATE"
    unit_commitment: str
    source_assignment_id: str
    target_assignment_id: str
    source_composition_id: str
    target_composition_id: str
    source_artifact_sha256: str
    target_artifact_sha256: str
    fixed_background_sha256: str
    arm_order: Literal["AB", "BA"]
    model_name: str
    runtime_version: str
    budget: ExecutionBudget
    randomized_common_origin_set: bool = False
    state: BlockState = "sealed"
    disposition_reason: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "SealedProbeBlock":
        for name in (
            "block_id",
            "transition_id",
            "source_composition_id",
            "target_composition_id",
        ):
            _require_id(str(getattr(self, name)), field_name=name)
        for name in (
            "unit_commitment",
            "source_assignment_id",
            "target_assignment_id",
            "source_artifact_sha256",
            "target_artifact_sha256",
            "fixed_background_sha256",
        ):
            _require_sha256(str(getattr(self, name)), field_name=name)
        if self.split != "TRAIN_UPDATE":
            raise ValueError("factor efficacy blocks are TRAIN_UPDATE-only")
        if self.disposition_reason is not None:
            _require_id(self.disposition_reason, field_name="disposition_reason")
        return self


class LoadedExecutionReceipt(_ClosedModel):
    """Runner-authored proof of the artifact actually loaded in one arm."""

    receipt_id: str
    block_id: str
    arm: ArmName
    split: SplitName
    root_id: str
    assignment_id: str
    unit_commitment: str
    namespace: ExecutionNamespace
    composition_id: str
    assigned_artifact_sha256: str
    materialized_artifact_sha256: str
    selected_artifact_sha256: str
    loaded_artifact_sha256: str
    activated_factor_revision_ids: tuple[str, ...]
    model_name: str
    runtime_version: str
    budget_digest: str
    usage: ExecutionUsage
    execution_class: ExecutionClass
    outcome: DenseOutcome | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "LoadedExecutionReceipt":
        for name in ("receipt_id", "block_id", "composition_id"):
            _require_id(str(getattr(self, name)), field_name=name)
        for name in (
            "root_id",
            "assignment_id",
            "unit_commitment",
            "assigned_artifact_sha256",
            "materialized_artifact_sha256",
            "selected_artifact_sha256",
            "loaded_artifact_sha256",
            "budget_digest",
        ):
            _require_sha256(str(getattr(self, name)), field_name=name)
        for revision_id in self.activated_factor_revision_ids:
            _require_id(revision_id, field_name="activated_factor_revision_id")
        needs_outcome = self.execution_class in {"completed", "algorithm_failure"}
        if needs_outcome != (self.outcome is not None):
            raise ValueError(
                "completed/algorithm failure receipts require outcomes; "
                "infrastructure/harness failures forbid them"
            )
        return self


class FailureObservation(_ClosedModel):
    """Answer-free failure information; hypotheses never become causal credit."""

    failure_id: str
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    failure_class: Literal["algorithm", "infrastructure", "harness"]
    stage: str = Field(min_length=1, max_length=80)
    failure_code: str
    composition_id: str
    transition_id: str | None = None
    artifact_sha256: str

    @model_validator(mode="after")
    def validate_identity(self) -> "FailureObservation":
        for name in ("failure_id", "failure_code", "composition_id"):
            _require_id(str(getattr(self, name)), field_name=name)
        if self.transition_id is not None:
            _require_id(self.transition_id, field_name="transition_id")
        _require_sha256(self.artifact_sha256, field_name="artifact_sha256")
        return self


class GateDecision(_ClosedModel):
    """Whole-Bank gate receipt; it contains no per-case or answer data."""

    decision_id: str
    composition_id: str
    transition_id: str
    split: Literal["FINAL_VAL"] = "FINAL_VAL"
    accepted: bool
    incumbent_snapshot_sha256: str
    candidate_snapshot_sha256: str
    gate_config_sha256: str
    verification_receipt_sha256: str

    @model_validator(mode="after")
    def validate_identity(self) -> "GateDecision":
        for name in ("decision_id", "composition_id", "transition_id"):
            _require_id(str(getattr(self, name)), field_name=name)
        for name in (
            "incumbent_snapshot_sha256",
            "candidate_snapshot_sha256",
            "gate_config_sha256",
            "verification_receipt_sha256",
        ):
            _require_sha256(str(getattr(self, name)), field_name=name)
        return self


class FactorBankState(_ClosedModel):
    schema_version: Literal["pif_shadow_v1"] = "pif_shadow_v1"
    factors: tuple[FactorRevision, ...] = ()
    compositions: tuple[CompositionRevision, ...] = ()
    transitions: tuple[FactorTransition, ...] = ()
    blocks: tuple[SealedProbeBlock, ...] = ()
    failures: tuple[FailureObservation, ...] = ()
    gate_decisions: tuple[GateDecision, ...] = ()
    used_roots: tuple[tuple[str, str], ...] = ()
    used_receipts: tuple[tuple[str, str], ...] = ()
    exposures: tuple[tuple[str, int], ...] = ()

    @model_validator(mode="after")
    def validate_unique_roots(self) -> "FactorBankState":
        roots = [root for root, _block in self.used_roots]
        if len(roots) != len(set(roots)):
            raise ValueError("physical roots must be globally unique")
        for root in roots:
            _require_sha256(root, field_name="used_root")
        receipt_ids = [receipt_id for receipt_id, _block in self.used_receipts]
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("execution receipt identifiers must be globally unique")
        for receipt_id in receipt_ids:
            _require_id(receipt_id, field_name="used_receipt")
        collections = (
            ("factor revision", [item.revision_id for item in self.factors]),
            ("composition", [item.composition_id for item in self.compositions]),
            ("transition", [item.transition_id for item in self.transitions]),
            ("probe block", [item.block_id for item in self.blocks]),
            ("failure", [item.failure_id for item in self.failures]),
            ("gate decision", [item.decision_id for item in self.gate_decisions]),
        )
        for label, identifiers in collections:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} identifier")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class ReadOnlyFactorBank:
    """Terminal-evaluation facade with no mutation methods."""

    def __init__(self, state: FactorBankState):
        self._state = state.model_copy(deep=True)
        self._digest = state.digest

    @property
    def scientific_state_sha256(self) -> str:
        self._assert_integrity()
        return self._digest

    def _assert_integrity(self) -> None:
        if self._state.digest != self._digest:
            raise RuntimeError("read-only Bank state was replaced or corrupted")

    def retrieve(
        self,
        namespace: ExecutionNamespace,
        *,
        limit: int = 3,
    ) -> list[CompositionRevision]:
        self._assert_integrity()
        return [
            item.model_copy(deep=True)
            for item in _retrieve_from_state(self._state, namespace, limit=limit)
        ]

    def model_dump(self) -> dict[str, Any]:
        self._assert_integrity()
        return self._state.model_dump(mode="json")


def _retrieve_from_state(
    state: FactorBankState,
    namespace: ExecutionNamespace,
    *,
    limit: int,
) -> list[CompositionRevision]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    active = [
        composition
        for composition in state.compositions
        if composition.state == "active" and composition.namespace == namespace
    ]
    edge_by_target = {
        transition.target_composition_id: transition
        for transition in state.transitions
        if transition.state == "active"
    }
    def score(composition: CompositionRevision) -> float:
        transition = edge_by_target.get(composition.composition_id)
        return transition.mean_stage_delta if transition is not None else float("-inf")

    active.sort(key=lambda composition: (-score(composition), composition.composition_id))
    return active[:limit]


class FactorBank:
    """Mutable TRAIN-side shadow Bank. Existing QueenBee paths do not call it."""

    BRANCH_CYCLE: tuple[OriginBranch, ...] = (
        "fresh",
        "mutate",
        "reuse",
        "fresh",
        "reuse",
        "mutate",
    )

    def __init__(
        self,
        state: FactorBankState | None = None,
        *,
        gate_verifier: Callable[[GateDecision, FactorBankState], bool] | None = None,
        binding_verifier: Callable[
            [
                str,
                str,
                CompositionRevision,
                CompositionRevision,
                FactorRevision,
                FactorRevision,
                OriginBranch,
                str,
            ],
            bool,
        ]
        | None = None,
        execution_receipt_verifier: Callable[
            [SealedProbeBlock, LoadedExecutionReceipt, LoadedExecutionReceipt],
            bool,
        ]
        | None = None,
    ):
        state = state or FactorBankState()
        # Revalidate at the mutable boundary.  Pydantic's model_copy(update=...)
        # intentionally does not validate updates, so accepting an already-built
        # object without this round trip would make schema checks bypassable.
        state = FactorBankState.model_validate(state.model_dump(mode="python"))
        self.factors = {item.revision_id: item for item in state.factors}
        self.compositions = {
            item.composition_id: item for item in state.compositions
        }
        self.transitions = {
            item.transition_id: item for item in state.transitions
        }
        self.blocks = {item.block_id: item for item in state.blocks}
        self.failures = {item.failure_id: item for item in state.failures}
        self.gate_decisions = {
            item.decision_id: item for item in state.gate_decisions
        }
        self.used_roots = dict(state.used_roots)
        self.used_receipts = dict(state.used_receipts)
        self.exposures = dict(state.exposures)
        # Deployment is fail-closed unless the host integration supplies the
        # current strict gate verifier.  The Bank never treats a caller-provided
        # ``accepted=True`` bit as evidence by itself.
        self._gate_verifier = gate_verifier
        self._binding_verifier = binding_verifier
        self._execution_receipt_verifier = execution_receipt_verifier
        self._validate_references()

    def _validate_references(self) -> None:
        for composition in self.compositions.values():
            for factor_id in composition.binding_map.values():
                if factor_id not in self.factors:
                    raise ValueError(
                        f"composition {composition.composition_id} references unknown factor {factor_id}"
                    )
        for transition in self.transitions.values():
            source = self.compositions.get(transition.source_composition_id)
            if source is None:
                raise ValueError("transition source composition is missing")
            target = self.compositions.get(transition.target_composition_id)
            if target is None:
                raise ValueError("transition target composition is missing")
            if source.namespace != transition.namespace or target.namespace != transition.namespace:
                raise ValueError("persisted transition crosses its execution namespace")
            source_map = source.binding_map
            target_map = target.binding_map
            if set(source_map) != set(target_map) or transition.slot_id not in source_map:
                raise ValueError("persisted transition has an invalid factor-slot domain")
            changed = [
                slot for slot in source_map if source_map[slot] != target_map[slot]
            ]
            if changed != [transition.slot_id]:
                raise ValueError("persisted transition is not an exact one-slot replacement")
            if source_map[transition.slot_id] != transition.from_revision_id:
                raise ValueError("persisted transition from-revision does not match source")
            if target_map[transition.slot_id] != transition.to_revision_id:
                raise ValueError("persisted transition to-revision does not match target")
            background = [
                (slot, source_map[slot])
                for slot in sorted(source_map)
                if slot != transition.slot_id
            ]
            if _sha256(background) != transition.fixed_background_sha256:
                raise ValueError("persisted transition fixed background is invalid")
            if self.factors[transition.from_revision_id].content_sha256 == self.factors[
                transition.to_revision_id
            ].content_sha256:
                raise ValueError("persisted transition does not change factor content")
            if self._binding_verifier is None:
                raise RuntimeError(
                    "a trusted carrier binding verifier is required for persisted transitions"
                )
            if not self._binding_verifier(
                transition.binding_proof_id,
                transition.binding_proof_sha256,
                source,
                target,
                self.factors[transition.from_revision_id],
                self.factors[transition.to_revision_id],
                transition.origin_branch,
                transition.masked_background_sha256,
            ):
                raise ValueError("persisted transition binding proof was rejected")

        for block in self.blocks.values():
            transition = self.transitions.get(block.transition_id)
            if transition is None:
                raise ValueError("probe block transition is missing")
            source = self.compositions[transition.source_composition_id]
            target = self.compositions[transition.target_composition_id]
            if (
                block.namespace != transition.namespace
                or block.source_composition_id != source.composition_id
                or block.target_composition_id != target.composition_id
                or block.source_artifact_sha256 != source.artifact_sha256
                or block.target_artifact_sha256 != target.artifact_sha256
                or block.fixed_background_sha256 != transition.fixed_background_sha256
                or block.model_name != transition.namespace.model_name
                or block.runtime_version != transition.namespace.runtime_version
            ):
                raise ValueError("persisted probe block is not bound to its transition")

        completed_by_block: dict[str, str] = {}
        for transition in self.transitions.values():
            for evidence in transition.evidence_blocks:
                block = self.blocks.get(evidence.block_id)
                if block is None or block.state != "committed":
                    raise ValueError("transition evidence does not name a committed block")
                if block.transition_id != transition.transition_id:
                    raise ValueError("committed block evidence is owned by the wrong transition")
                if evidence.block_id in completed_by_block:
                    raise ValueError("one committed block cannot credit multiple transitions")
                completed_by_block[evidence.block_id] = transition.transition_id
                if self.used_roots.get(evidence.source_root_id) != evidence.block_id:
                    raise ValueError("source evidence root is not owned by its block")
                if self.used_roots.get(evidence.target_root_id) != evidence.block_id:
                    raise ValueError("target evidence root is not owned by its block")
        for block in self.blocks.values():
            if block.state == "committed" and block.block_id not in completed_by_block:
                raise ValueError("committed block is missing its sole evidence owner")

        for root_id, block_id in self.used_roots.items():
            if block_id not in self.blocks:
                raise ValueError(f"physical root {root_id} names an unknown block")
        for receipt_id, block_id in self.used_receipts.items():
            if block_id not in self.blocks:
                raise ValueError(f"execution receipt {receipt_id} names an unknown block")

        for failure in self.failures.values():
            composition = self.compositions.get(failure.composition_id)
            if composition is None or composition.artifact_sha256 != failure.artifact_sha256:
                raise ValueError("persisted failure is not bound to its composition")
            if failure.transition_id is not None:
                transition = self.transitions.get(failure.transition_id)
                if transition is None or transition.target_composition_id != failure.composition_id:
                    raise ValueError("persisted failure is not bound to its transition")

        accepted_targets: set[tuple[str, str]] = set()
        rejected_targets: set[tuple[str, str]] = set()
        for decision in self.gate_decisions.values():
            transition = self.transitions.get(decision.transition_id)
            composition = self.compositions.get(decision.composition_id)
            if transition is None or composition is None:
                raise ValueError("persisted gate decision references missing state")
            if transition.target_composition_id != composition.composition_id:
                raise ValueError("persisted gate decision names the wrong target")
            pair = (transition.transition_id, composition.composition_id)
            (accepted_targets if decision.accepted else rejected_targets).add(pair)
        if accepted_targets & rejected_targets:
            raise ValueError("one transition target has conflicting gate decisions")

        for transition in self.transitions.values():
            target = self.compositions[transition.target_composition_id]
            pair = (transition.transition_id, target.composition_id)
            to_factor = self.factors[transition.to_revision_id]
            if transition.state == "active":
                if pair not in accepted_targets or target.state != "active":
                    raise ValueError("active transition lacks an accepted gate target")
                if to_factor.state != "active":
                    raise ValueError("active transition target factor is not active")
            if pair in accepted_targets and (
                transition.state != "active" or target.state != "active"
            ):
                raise ValueError("accepted gate decision is inconsistent with lifecycle state")
            if pair in rejected_targets and (
                transition.state != "refuted" or target.state != "archived"
            ):
                raise ValueError("rejected gate decision is inconsistent with lifecycle state")
        for composition in self.compositions.values():
            if composition.state == "active" and not any(
                transition.state == "active"
                and transition.target_composition_id == composition.composition_id
                for transition in self.transitions.values()
            ):
                raise ValueError("active composition was not admitted by an active transition")

    @staticmethod
    def choose_branch(
        opportunity_index: int,
        feasible: Iterable[OriginBranch],
    ) -> OriginBranch:
        """Closed exploration schedule; no branch label receives efficacy."""

        feasible_set = {branch for branch in feasible if branch != "migration"}
        if not feasible_set:
            raise ValueError("at least one reuse/mutate/fresh branch must be feasible")
        start = opportunity_index % len(FactorBank.BRANCH_CYCLE)
        for offset in range(len(FactorBank.BRANCH_CYCLE)):
            candidate = FactorBank.BRANCH_CYCLE[
                (start + offset) % len(FactorBank.BRANCH_CYCLE)
            ]
            if candidate in feasible_set:
                return candidate
        raise AssertionError("branch cycle did not cover the feasible set")

    def add_factor(self, factor: FactorRevision) -> None:
        factor = FactorRevision.model_validate(factor.model_dump(mode="python"))
        if factor.revision_id in self.factors:
            raise ValueError(f"factor revision already exists: {factor.revision_id}")
        if factor.state != "registered":
            raise ValueError("new factor revisions must start registered with zero efficacy")
        if factor.parent_revision_id is not None:
            parent = self.factors.get(factor.parent_revision_id)
            if parent is None:
                raise ValueError("factor parent revision does not exist")
            if parent.logical_factor_id != factor.logical_factor_id:
                raise ValueError("factor parent must share the logical factor id")
            if parent.namespace != factor.namespace:
                raise ValueError("factor parent cannot cross namespaces")
        self.factors[factor.revision_id] = factor

    def add_composition(self, composition: CompositionRevision) -> None:
        composition = CompositionRevision.model_validate(
            composition.model_dump(mode="python")
        )
        if composition.composition_id in self.compositions:
            raise ValueError(
                f"composition revision already exists: {composition.composition_id}"
            )
        if composition.state != "shadow":
            raise ValueError("new compositions must start shadow with zero outcome evidence")
        if composition.parent_composition_id is not None:
            parent = self.compositions.get(composition.parent_composition_id)
            if parent is None:
                raise ValueError("composition parent revision does not exist")
            if parent.namespace != composition.namespace:
                raise ValueError("composition parent cannot cross namespaces")
        for factor_id in composition.binding_map.values():
            factor = self.factors.get(factor_id)
            if factor is None:
                raise ValueError(f"unknown factor revision: {factor_id}")
            if factor.namespace != composition.namespace:
                raise ValueError("composition factor cannot cross namespaces")
        self.compositions[composition.composition_id] = composition

    def register_transition(
        self,
        *,
        source_composition_id: str,
        target_composition_id: str,
        slot_id: str,
        binding_proof_id: str,
        binding_proof_sha256: str,
        masked_background_sha256: str,
        origin_branch: Literal["reuse", "mutate", "fresh"],
    ) -> FactorTransition:
        _require_id(binding_proof_id, field_name="binding_proof_id")
        _require_sha256(binding_proof_sha256, field_name="binding_proof_sha256")
        _require_sha256(
            masked_background_sha256,
            field_name="masked_background_sha256",
        )
        if origin_branch not in {"reuse", "mutate", "fresh"}:
            raise ValueError("direct transition origin must be reuse, mutate, or fresh")
        source = self.compositions[source_composition_id]
        target = self.compositions[target_composition_id]
        if source.namespace != target.namespace:
            raise ValueError("factor transition cannot cross namespaces")
        if source.artifact_sha256 == target.artifact_sha256:
            raise ValueError("changed factor bindings require a distinct materialized artifact")
        source_map = source.binding_map
        target_map = target.binding_map
        if set(source_map) != set(target_map) or slot_id not in source_map:
            raise ValueError("source/target must expose the same declared factor slots")
        changed = [slot for slot in source_map if source_map[slot] != target_map[slot]]
        if changed != [slot_id]:
            raise ValueError("direct factor transition must change exactly one slot")
        old = self.factors[source_map[slot_id]]
        new = self.factors[target_map[slot_id]]
        if old.binding_status != "proven_factorized" or new.binding_status != "proven_factorized":
            raise ValueError("locked/unsupported artifacts cannot mint factor credit")
        if old.logical_factor_id != new.logical_factor_id:
            raise ValueError("same-slot replacement must preserve logical factor identity")
        if old.content_sha256 == new.content_sha256:
            raise ValueError("direct factor transition must change canonical factor content")
        if old.locator != new.locator or old.carrier != new.carrier:
            raise ValueError("same-slot replacement requires the same host locator and carrier")
        if self._binding_verifier is None:
            raise RuntimeError("no trusted carrier binding verifier is installed")
        if not self._binding_verifier(
            binding_proof_id,
            binding_proof_sha256,
            source,
            target,
            old,
            new,
            origin_branch,
            masked_background_sha256,
        ):
            raise ValueError("trusted carrier binding verifier rejected the proof")

        background = [(slot, source_map[slot]) for slot in sorted(source_map) if slot != slot_id]
        background_sha256 = _sha256(background)
        transition_id = "tr:" + _sha256(
            {
                "namespace": source.namespace,
                "source": source.composition_id,
                "target": target.composition_id,
                "slot": slot_id,
                "from": old.revision_id,
                "to": new.revision_id,
                "background": background_sha256,
                "binding_proof": binding_proof_sha256,
            }
        )[:24]
        if transition_id in self.transitions:
            raise ValueError("factor transition already exists")
        transition = FactorTransition(
            transition_id=transition_id,
            namespace=source.namespace,
            source_composition_id=source.composition_id,
            target_composition_id=target.composition_id,
            slot_id=slot_id,
            from_revision_id=old.revision_id,
            to_revision_id=new.revision_id,
            fixed_background_sha256=background_sha256,
            binding_proof_id=binding_proof_id,
            binding_proof_sha256=binding_proof_sha256,
            masked_background_sha256=masked_background_sha256,
            origin_branch=origin_branch,
            state="registered",
        )
        self.transitions[transition_id] = transition
        # The comparator revision may already be active in another composition;
        # registering a challenger must not demote it globally.  The directed
        # edge owns comparator-conditioned efficacy, while only a previously
        # unadmitted target revision enters the probing lifecycle here.
        if new.state not in {"active", "probation"}:
            self.factors[new.revision_id] = new.model_copy(update={"state": "probing"})
        return transition

    def seal_direct_block(
        self,
        transition_id: str,
        *,
        unit_commitment: str,
        arm_order: Literal["AB", "BA"],
        budget: ExecutionBudget,
        randomized_common_origin_set: bool = False,
    ) -> SealedProbeBlock:
        _require_sha256(unit_commitment, field_name="unit_commitment")
        budget = ExecutionBudget.model_validate(budget.model_dump(mode="python"))
        transition = self.transitions[transition_id]
        if transition.state in {"active", "refuted", "archived", "quarantine"}:
            raise ValueError("cannot probe a closed transition")
        source = self.compositions[transition.source_composition_id]
        target = self.compositions[transition.target_composition_id]
        block_payload = {
            "transition": transition_id,
            "unit": unit_commitment,
            "source": source.composition_id,
            "target": target.composition_id,
            "order": arm_order,
            "budget": budget.digest,
            "ordinal": len(self.blocks),
        }
        block_id = "pb:" + _sha256(block_payload)[:24]
        source_assignment = _sha256({**block_payload, "arm": "source"})
        target_assignment = _sha256({**block_payload, "arm": "target"})
        block = SealedProbeBlock(
            block_id=block_id,
            transition_id=transition_id,
            namespace=transition.namespace,
            split="TRAIN_UPDATE",
            unit_commitment=unit_commitment,
            source_assignment_id=source_assignment,
            target_assignment_id=target_assignment,
            source_composition_id=source.composition_id,
            target_composition_id=target.composition_id,
            source_artifact_sha256=source.artifact_sha256,
            target_artifact_sha256=target.artifact_sha256,
            fixed_background_sha256=transition.fixed_background_sha256,
            arm_order=arm_order,
            model_name=transition.namespace.model_name,
            runtime_version=transition.namespace.runtime_version,
            budget=budget,
            randomized_common_origin_set=randomized_common_origin_set,
        )
        if block.block_id in self.blocks:
            raise ValueError("probe block already exists")
        self.blocks[block.block_id] = block
        self.transitions[transition_id] = transition.model_copy(
            update={"state": "probing"}
        )
        return block

    def _quarantine_block(self, block: SealedProbeBlock, reason: str) -> None:
        self.blocks[block.block_id] = block.model_copy(
            update={"state": "quarantine", "disposition_reason": reason}
        )

    def _validate_receipt(
        self,
        block: SealedProbeBlock,
        receipt: LoadedExecutionReceipt,
        *,
        arm: ArmName,
    ) -> str | None:
        composition_id = (
            block.source_composition_id if arm == "source" else block.target_composition_id
        )
        artifact_sha256 = (
            block.source_artifact_sha256 if arm == "source" else block.target_artifact_sha256
        )
        assignment_id = (
            block.source_assignment_id if arm == "source" else block.target_assignment_id
        )
        composition = self.compositions[composition_id]
        checks = (
            (receipt.block_id == block.block_id, "receipt_block_mismatch"),
            (receipt.arm == arm, "receipt_arm_mismatch"),
            (receipt.split == "TRAIN_UPDATE", "receipt_split_mismatch"),
            (receipt.unit_commitment == block.unit_commitment, "unit_mismatch"),
            (receipt.namespace == block.namespace, "namespace_mismatch"),
            (receipt.composition_id == composition_id, "composition_mismatch"),
            (receipt.assignment_id == assignment_id, "assignment_mismatch"),
            (receipt.assigned_artifact_sha256 == artifact_sha256, "assigned_hash_mismatch"),
            (receipt.materialized_artifact_sha256 == artifact_sha256, "materialized_hash_mismatch"),
            (receipt.selected_artifact_sha256 == artifact_sha256, "selected_hash_mismatch"),
            (receipt.loaded_artifact_sha256 == artifact_sha256, "loaded_hash_mismatch"),
            (
                tuple(sorted(receipt.activated_factor_revision_ids))
                == tuple(sorted(composition.binding_map.values())),
                "activated_factor_mismatch",
            ),
            (receipt.model_name == block.model_name, "model_mismatch"),
            (receipt.runtime_version == block.runtime_version, "runtime_mismatch"),
            (receipt.budget_digest == block.budget.digest, "budget_digest_mismatch"),
            (receipt.usage.within(block.budget), "budget_violation"),
        )
        for passed, reason in checks:
            if not passed:
                return reason
        return None

    def commit_complete_block(
        self,
        block_id: str,
        source_receipt: LoadedExecutionReceipt,
        target_receipt: LoadedExecutionReceipt,
    ) -> CompletedBlockRef | None:
        """Atomically attribute one complete block or fail closed.

        Infrastructure/harness failures consume their physical roots and leave
        the block incomplete, but write no positive or negative factor evidence.
        Algorithm failures are valid outcomes and may refute the directed edge.
        """

        source_receipt = LoadedExecutionReceipt.model_validate(
            source_receipt.model_dump(mode="python")
        )
        target_receipt = LoadedExecutionReceipt.model_validate(
            target_receipt.model_dump(mode="python")
        )
        block = self.blocks[block_id]
        if block.state != "sealed":
            raise ValueError("probe block is not open")
        receipts = (source_receipt, target_receipt)
        if source_receipt.receipt_id == target_receipt.receipt_id:
            self._quarantine_block(block, "duplicate_receipt_id")
            return None
        if any(receipt.receipt_id in self.used_receipts for receipt in receipts):
            self._quarantine_block(block, "reused_receipt_id")
            return None
        roots = [receipt.root_id for receipt in receipts]
        if roots[0] == roots[1]:
            self._quarantine_block(block, "same_physical_root")
            return None
        if any(root in self.used_roots for root in roots):
            self._quarantine_block(block, "reused_physical_root")
            return None

        # Once presented, roots are attempt-owned even when delivery is invalid.
        for root in roots:
            self.used_roots[root] = block.block_id
        for receipt in receipts:
            self.used_receipts[receipt.receipt_id] = block.block_id

        if self._execution_receipt_verifier is None:
            self._quarantine_block(block, "missing_trusted_receipt_verifier")
            return None
        try:
            receipts_verified = bool(
                self._execution_receipt_verifier(
                    block,
                    source_receipt,
                    target_receipt,
                )
            )
        except Exception:
            receipts_verified = False
        if not receipts_verified:
            self._quarantine_block(block, "untrusted_execution_receipt")
            return None

        for arm, receipt in (("source", source_receipt), ("target", target_receipt)):
            reason = self._validate_receipt(block, receipt, arm=arm)
            if reason is not None:
                self._quarantine_block(block, reason)
                return None

        if any(
            receipt.execution_class
            in {"infrastructure_failure", "harness_failure"}
            for receipt in receipts
        ):
            self.blocks[block.block_id] = block.model_copy(
                update={"state": "incomplete", "disposition_reason": "non_algorithm_failure"}
            )
            return None

        assert source_receipt.outcome is not None
        assert target_receipt.outcome is not None
        delta = target_receipt.outcome.subtract(source_receipt.outcome)
        completed = CompletedBlockRef(
            block_id=block.block_id,
            source_root_id=source_receipt.root_id,
            target_root_id=target_receipt.root_id,
            source_outcome=source_receipt.outcome,
            target_outcome=target_receipt.outcome,
            delta=delta,
            source_algorithm_failure=source_receipt.execution_class
            == "algorithm_failure",
            target_algorithm_failure=target_receipt.execution_class
            == "algorithm_failure",
            randomized_common_origin_set=block.randomized_common_origin_set,
        )
        transition = self.transitions[block.transition_id]
        evidence = (*transition.evidence_blocks, completed)

        confirmatory_blocks = [
            item for item in evidence if item.randomized_common_origin_set
        ]
        aggregate_delta = {
            field: (
                sum(float(getattr(item.delta, field)) for item in confirmatory_blocks)
                / len(confirmatory_blocks)
            )
            if confirmatory_blocks
            else 0.0
            for field in ("V", "K", "U", "P", "S", "stage_score", "C", "D")
        }
        source_failure_rate = (
            sum(float(item.source_algorithm_failure) for item in confirmatory_blocks)
            / len(confirmatory_blocks)
            if confirmatory_blocks
            else 0.0
        )
        target_failure_rate = (
            sum(float(item.target_algorithm_failure) for item in confirmatory_blocks)
            / len(confirmatory_blocks)
            if confirmatory_blocks
            else 0.0
        )
        mean_target_stage = (
            sum(item.target_outcome.stage_score for item in confirmatory_blocks)
            / len(confirmatory_blocks)
            if confirmatory_blocks
            else 0.0
        )
        target_failed = target_failure_rate > source_failure_rate
        hard_regression = any(
            aggregate_delta[field] < 0 for field in ("V", "K", "U", "P", "S")
        )
        candidate_eligible = bool(
            confirmatory_blocks
            and not target_failed
            and mean_target_stage > 0
            and aggregate_delta["stage_score"] > 0
            and not hard_regression
        )
        target = self.compositions[transition.target_composition_id]
        to_factor = self.factors[transition.to_revision_id]
        if confirmatory_blocks and (
            target_failed or hard_regression or aggregate_delta["stage_score"] < 0
        ):
            edge_state: EdgeState = "refuted"
            self.compositions[target.composition_id] = target.model_copy(
                update={"state": "refuted"}
            )
            if to_factor.state != "active":
                self.factors[to_factor.revision_id] = to_factor.model_copy(
                    update={"state": "refuted"}
                )
        elif candidate_eligible:
            edge_state = "candidate"
            self.compositions[target.composition_id] = target.model_copy(
                update={"state": "probation"}
            )
            if to_factor.state != "active":
                self.factors[to_factor.revision_id] = to_factor.model_copy(
                    update={"state": "probation"}
                )
        else:
            edge_state = "probed"
            self.compositions[target.composition_id] = target.model_copy(
                update={"state": "shadow"}
            )
            if to_factor.state != "active":
                self.factors[to_factor.revision_id] = to_factor.model_copy(
                    update={"state": "probing"}
                )
        self.transitions[transition.transition_id] = transition.model_copy(
            update={"state": edge_state, "evidence_blocks": evidence}
        )
        self.blocks[block.block_id] = block.model_copy(
            update={"state": "committed", "disposition_reason": "complete"}
        )
        return completed

    def apply_gate(self, decision: GateDecision) -> None:
        decision = GateDecision.model_validate(decision.model_dump(mode="python"))
        if decision.decision_id in self.gate_decisions:
            raise ValueError("gate decision already exists")
        transition = self.transitions[decision.transition_id]
        composition = self.compositions[decision.composition_id]
        if transition.target_composition_id != composition.composition_id:
            raise ValueError("gate decision does not name the transition target")
        if transition.state != "candidate" or composition.state != "probation":
            raise ValueError("only a locally eligible probation candidate can be gated")
        if decision.candidate_snapshot_sha256 != self.scientific_state_sha256:
            raise ValueError("gate decision is not bound to the current candidate snapshot")
        if self._gate_verifier is None:
            raise RuntimeError("no trusted strict gate verifier is installed")
        state_before_gate = self.to_state()
        try:
            verified = bool(self._gate_verifier(decision, state_before_gate))
        except Exception as exc:
            raise RuntimeError("trusted strict gate verification failed") from exc
        if not verified:
            raise ValueError("trusted strict gate verifier rejected the decision receipt")
        to_factor = self.factors[transition.to_revision_id]
        if decision.accepted:
            self.transitions[transition.transition_id] = transition.model_copy(
                update={"state": "active"}
            )
            self.compositions[composition.composition_id] = composition.model_copy(
                update={"state": "active"}
            )
            self.factors[to_factor.revision_id] = to_factor.model_copy(
                update={"state": "active"}
            )
        else:
            self.transitions[transition.transition_id] = transition.model_copy(
                update={"state": "refuted"}
            )
            self.compositions[composition.composition_id] = composition.model_copy(
                update={"state": "archived", "archive_reason": "final_gate_rejected"}
            )
            if to_factor.state != "active":
                self.factors[to_factor.revision_id] = to_factor.model_copy(
                    update={"state": "refuted"}
                )
        self.gate_decisions[decision.decision_id] = decision

    def record_exposure(self, subject_id: str) -> None:
        _require_id(subject_id, field_name="subject_id")
        self.exposures[subject_id] = self.exposures.get(subject_id, 0) + 1

    def record_failure(self, observation: FailureObservation) -> None:
        observation = FailureObservation.model_validate(
            observation.model_dump(mode="python")
        )
        if observation.failure_id in self.failures:
            raise ValueError("failure observation already exists")
        composition = self.compositions.get(observation.composition_id)
        if composition is None:
            raise ValueError("failure composition does not exist")
        if observation.artifact_sha256 != composition.artifact_sha256:
            raise ValueError("failure artifact does not match the composition")
        if observation.transition_id is not None:
            transition = self.transitions.get(observation.transition_id)
            if transition is None or transition.target_composition_id != composition.composition_id:
                raise ValueError("failure transition does not match the composition")
        self.failures[observation.failure_id] = observation

    def archive_composition(self, composition_id: str, *, reason: str) -> None:
        _require_id(reason, field_name="archive reason")
        composition = self.compositions[composition_id]
        if composition.state == "active":
            raise ValueError("active composition requires a replacement gate before archive")
        self.compositions[composition_id] = composition.model_copy(
            update={"state": "archived", "archive_reason": reason}
        )
        for transition_id, transition in list(self.transitions.items()):
            if transition.target_composition_id == composition_id and transition.state != "active":
                self.transitions[transition_id] = transition.model_copy(
                    update={"state": "archived"}
                )

    def enforce_capacity(
        self,
        namespace: ExecutionNamespace,
        *,
        max_active: int,
        max_probation: int,
        max_shadow: int,
    ) -> list[str]:
        """Deterministically bound the prompt-visible working set.

        Active deployments are never silently evicted.  A caller must first
        install a replacement through the whole-Bank gate.  Open probe subjects
        are protected; excess probation/shadow revisions become reversible cold
        tombstones in deterministic evidence/identifier order.
        """

        if min(max_active, max_probation, max_shadow) < 0:
            raise ValueError("capacity limits must be non-negative")
        scoped = [
            item for item in self.compositions.values() if item.namespace == namespace
        ]
        active = [item for item in scoped if item.state == "active"]
        if len(active) > max_active:
            raise RuntimeError(
                "active capacity exceeded; install a gated replacement before archive"
            )
        protected = {
            composition_id
            for block in self.blocks.values()
            if block.state == "sealed"
            for composition_id in (
                block.source_composition_id,
                block.target_composition_id,
            )
        }
        transition_by_target: dict[str, FactorTransition] = {}
        for transition in self.transitions.values():
            current = transition_by_target.get(transition.target_composition_id)
            if current is None or transition.mean_stage_delta > current.mean_stage_delta:
                transition_by_target[transition.target_composition_id] = transition

        archived: list[str] = []
        for state, cap, reason in (
            ("probation", max_probation, "capacity_probation"),
            ("shadow", max_shadow, "capacity_shadow"),
        ):
            candidates = [
                item
                for item in scoped
                if item.state == state and item.composition_id not in protected
            ]
            candidates.sort(
                key=lambda item: (
                    -transition_by_target.get(item.composition_id).mean_stage_delta
                    if item.composition_id in transition_by_target
                    else float("inf"),
                    -len(
                        transition_by_target.get(item.composition_id).evidence_blocks
                    )
                    if item.composition_id in transition_by_target
                    else 0,
                    item.composition_id,
                )
            )
            keep_unprotected = max(0, cap - sum(
                1
                for item in scoped
                if item.state == state and item.composition_id in protected
            ))
            for item in candidates[keep_unprotected:]:
                self.archive_composition(item.composition_id, reason=reason)
                archived.append(item.composition_id)
        return archived

    def candidate_neighbors(
        self,
        source_composition_id: str,
        *,
        limit: int = 3,
    ) -> list[CompositionRevision]:
        """Deterministically rank only evidence-backed one-hop candidates."""

        if limit < 0:
            raise ValueError("limit must be non-negative")
        source = self.compositions[source_composition_id]
        edges = [
            transition
            for transition in self.transitions.values()
            if transition.source_composition_id == source.composition_id
            and transition.namespace == source.namespace
            and transition.state in {"candidate", "active"}
        ]
        edges.sort(
            key=lambda transition: (
                -transition.mean_stage_delta,
                -len(transition.evidence_blocks),
                transition.transition_id,
            )
        )
        return [
            self.compositions[edge.target_composition_id] for edge in edges[:limit]
        ]

    def retrieve(
        self,
        namespace: ExecutionNamespace,
        *,
        limit: int = 3,
    ) -> list[CompositionRevision]:
        return _retrieve_from_state(self.to_state(), namespace, limit=limit)

    def to_state(self) -> FactorBankState:
        return FactorBankState(
            factors=tuple(sorted(self.factors.values(), key=lambda item: item.revision_id)),
            compositions=tuple(
                sorted(self.compositions.values(), key=lambda item: item.composition_id)
            ),
            transitions=tuple(
                sorted(self.transitions.values(), key=lambda item: item.transition_id)
            ),
            blocks=tuple(sorted(self.blocks.values(), key=lambda item: item.block_id)),
            failures=tuple(
                sorted(self.failures.values(), key=lambda item: item.failure_id)
            ),
            gate_decisions=tuple(
                sorted(self.gate_decisions.values(), key=lambda item: item.decision_id)
            ),
            used_roots=tuple(sorted(self.used_roots.items())),
            used_receipts=tuple(sorted(self.used_receipts.items())),
            exposures=tuple(sorted(self.exposures.items())),
        )

    @property
    def scientific_state_sha256(self) -> str:
        return self.to_state().digest

    def read_only_snapshot(self) -> ReadOnlyFactorBank:
        return ReadOnlyFactorBank(self.to_state())

    def assert_scientific_state_unchanged(self, before_sha256: str) -> None:
        _require_sha256(before_sha256, field_name="before_sha256")
        if self.scientific_state_sha256 != before_sha256:
            raise RuntimeError("scientific state changed across the read-only boundary")

    def save(self, path: Path | str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            self.to_state().model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ) + "\n"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        gate_verifier: Callable[[GateDecision, FactorBankState], bool] | None = None,
        binding_verifier: Callable[
            [
                str,
                str,
                CompositionRevision,
                CompositionRevision,
                FactorRevision,
                FactorRevision,
            ],
            bool,
        ]
        | None = None,
        execution_receipt_verifier: Callable[
            [SealedProbeBlock, LoadedExecutionReceipt, LoadedExecutionReceipt],
            bool,
        ]
        | None = None,
    ) -> "FactorBank":
        state = FactorBankState.model_validate_json(Path(path).read_text(encoding="utf-8"))
        return cls(
            state,
            gate_verifier=gate_verifier,
            binding_verifier=binding_verifier,
            execution_receipt_verifier=execution_receipt_verifier,
        )


def make_receipt(
    *,
    block: SealedProbeBlock,
    composition: CompositionRevision,
    arm: ArmName,
    root_id: str,
    usage: ExecutionUsage,
    execution_class: ExecutionClass,
    outcome: DenseOutcome | None,
    loaded_artifact_sha256: str | None = None,
) -> LoadedExecutionReceipt:
    """Test/runner helper that still requires host-supplied root and outcome."""

    assignment = (
        block.source_assignment_id if arm == "source" else block.target_assignment_id
    )
    expected_artifact = (
        block.source_artifact_sha256 if arm == "source" else block.target_artifact_sha256
    )
    receipt_id = f"rc:{arm}:{block.block_id.split(':', 1)[-1]}"
    return LoadedExecutionReceipt(
        receipt_id=receipt_id,
        block_id=block.block_id,
        arm=arm,
        split=block.split,
        root_id=root_id,
        assignment_id=assignment,
        unit_commitment=block.unit_commitment,
        namespace=block.namespace,
        composition_id=composition.composition_id,
        assigned_artifact_sha256=expected_artifact,
        materialized_artifact_sha256=expected_artifact,
        selected_artifact_sha256=expected_artifact,
        loaded_artifact_sha256=loaded_artifact_sha256 or expected_artifact,
        activated_factor_revision_ids=tuple(
            sorted(composition.binding_map.values())
        ),
        model_name=block.model_name,
        runtime_version=block.runtime_version,
        budget_digest=block.budget.digest,
        usage=usage,
        execution_class=execution_class,
        outcome=outcome,
    )


__all__ = [
    "BindingStatus",
    "CompositionRevision",
    "DenseDelta",
    "DenseOutcome",
    "ExecutionBudget",
    "ExecutionNamespace",
    "ExecutionUsage",
    "FactorBank",
    "FactorBankState",
    "FactorCarrier",
    "FactorLocator",
    "FactorRevision",
    "FactorTransition",
    "FailureObservation",
    "GateDecision",
    "LoadedExecutionReceipt",
    "ReadOnlyFactorBank",
    "SealedProbeBlock",
    "SlotBinding",
    "assert_bank_safe_public_value",
    "make_receipt",
]
