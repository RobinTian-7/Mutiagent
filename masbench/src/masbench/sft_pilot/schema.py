"""Closed control-plane schemas for the default-off SFT pilot.

The pilot store deliberately persists commitments and bounded counters, not
task/model content.  These shapes are narrower than the eventual Phase/Factor
adapter: they freeze one exact protocol namespace and provide enough authority
for a single-host, single-writer, no-retry execution fence.

The marker checks below are a conservative ingress barrier, not a semantic
privacy oracle.  The future runner must still keep private scoring data and
TEST capabilities physically outside this package.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from exp_graph.mas.factor_bank import (
    ExecutionNamespace,
    assert_bank_safe_public_value,
)


PILOT_SCHEMA_VERSION = "sft_phase_single_writer_protocol_v1"
PILOT_APPLICATION_ID = 0x53465431
PILOT_USER_VERSION = 4

PilotMethodArm = Literal[
    "current",
    "whole_artifact_receipt",
    "ect_whole_transaction",
    "sft_unified",
    "sft_shadow",
    "sft_shuffled_edge",
    "sft_uniform_target",
    "sft_no_failure_memory",
    "sft_no_diversity_eviction",
]
PilotPhase = Literal["TRAIN_UPDATE", "PROBE", "FINAL_VAL"]
PilotSplit = Literal["TRAIN_UPDATE", "FINAL_VAL"]
PilotCallState = Literal[
    "reserved",
    "request_started",
    "completed",
    "failed_before_start",
    "indeterminate",
]
PilotOperationKind = Literal[
    "proposal_generation",
    "source_probe",
    "target_probe",
    "final_val",
    "control_execution",
]
PilotComponentCheckpointKind = Literal[
    "action_prepared",
    "generation_start_authorized",
    "probe_attempt_open",
    "probe_terminal",
    "gate_terminal",
]


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_EXPLICIT_PRIVATE_SPLITS = frozenset(
    {"test", "final_test", "heldout_test", "private_test", "validation_test"}
)
_RAW_FIELD_MARKERS = frozenset(
    {
        "answer",
        "answer_key",
        "expected",
        "expected_output",
        "final_answer",
        "ground_truth",
        "judge_rationale",
        "private",
        "private_prompt",
        "prompt",
        "raw",
        "raw_prompt",
        "raw_response",
        "response",
        "submission",
        "test",
    }
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return the only JSON representation admitted by the pilot store."""

    return json.dumps(
        _jsonable(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def pilot_hmac_sha256(key: bytes, *, domain: str, value: Any) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("pilot HMAC key must contain at least 32 bytes")
    payload = domain.encode("ascii") + b"\0" + canonical_json(value).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def require_sha256(value: str, *, field_name: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def require_opaque_id(value: str, *, field_name: str) -> str:
    if not _OPAQUE_ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a short opaque identifier")
    return value


def _reject_raw_or_private_fields(value: Any) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            words = frozenset(filter(None, normalized.split("_")))
            if normalized in _RAW_FIELD_MARKERS or {
                "ground",
                "truth",
            }.issubset(words):
                raise ValueError(f"raw/private pilot field is forbidden: {key}")
            _reject_raw_or_private_fields(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_raw_or_private_fields(item)
        return
    if isinstance(value, str):
        normalized = value.strip().casefold().replace("-", "_")
        if normalized in _EXPLICIT_PRIVATE_SPLITS:
            raise ValueError("TEST/private split labels are forbidden in the pilot")


def assert_pilot_safe_value(value: Any) -> None:
    """Reject obvious TEST/private/raw content before hashing or persistence."""

    assert_bank_safe_public_value(value)
    _reject_raw_or_private_fields(value)


class ClosedPilotModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def reject_unsafe_values(self) -> "ClosedPilotModel":
        assert_pilot_safe_value(self.model_dump(mode="python"))
        return self


class PilotSourceManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_source_manifest_v1"] = (
        "sft_pilot_source_manifest_v1"
    )
    split: Literal["PUBLIC", "TRAIN_UPDATE"]
    source_catalog_sha256: str
    source_policy_sha256: str

    @field_validator("source_catalog_sha256", "source_policy_sha256")
    @classmethod
    def validate_digests(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)


class AuthorizedPhaseBudgetV1(ClosedPilotModel):
    phase: PilotPhase
    method_arm: PilotMethodArm
    executions: int = Field(ge=0, le=10_000)
    call_slots: int = Field(ge=0, le=1_000_000)
    input_tokens: int = Field(ge=0, le=1_000_000_000)
    output_tokens: int = Field(ge=0, le=1_000_000_000)


class PilotCapacityPolicyV1(ClosedPilotModel):
    policy_version: Literal["sft_pilot_capacity_v1"] = "sft_pilot_capacity_v1"
    max_namespaces: Literal[1] = 1
    max_writer_processes: Literal[1] = 1
    max_parallel_model_calls: Literal[1] = 1
    max_scientific_commits: int = Field(ge=1, le=1_000_000)
    max_execution_leases: int = Field(ge=1, le=1_000_000)
    max_call_receipts: int = Field(ge=1, le=10_000_000)
    max_component_checkpoints: int = Field(default=1_000_000, ge=1, le=10_000_000)
    max_call_slots_per_execution: int = Field(ge=1, le=10_000)
    max_input_tokens_per_call: int = Field(ge=1, le=1_000_000)
    max_output_tokens_per_call: int = Field(ge=1, le=1_000_000)
    max_active_db_bytes: int = Field(ge=65_536, le=1_000_000_000_000)
    max_archive_bytes: int = Field(ge=1_024, le=1_000_000_000_000)
    max_total_stored_scalar_bytes: int = Field(ge=1_024, le=1_000_000_000_000)


class PilotProtocolV1(ClosedPilotModel):
    """Frozen identity for exactly one namespace, method arm, and model."""

    schema_version: Literal[PILOT_SCHEMA_VERSION] = PILOT_SCHEMA_VERSION
    protocol_id: str
    method_arm: PilotMethodArm
    model_name: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    temperature: Literal[0.0] = 0.0
    sdk_max_retries: Literal[0] = 0
    application_max_retries: Literal[0] = 0
    input_admission_policy: Literal[
        "utf8_bytes_plus_fixed_allowance_v1"
    ] = "utf8_bytes_plus_fixed_allowance_v1"
    input_envelope_token_allowance: Literal[256] = 256
    namespace: ExecutionNamespace
    source_manifest: PilotSourceManifestV1
    source_authority_sha256: str
    dataset_split_policy_sha256: str
    candidate_pool_manifest_sha256: str
    runner_config_sha256: str
    model_config_sha256: str
    pair_manifest_sha256: str
    genesis_state_sha256: str
    component_bundle_required: bool = False
    component_checkpoint_saga_required: bool = False
    execution_schedule_sha256: str | None = None
    store_derived_schedule_required: bool = False
    authorized_logical_arms: tuple["PilotLogicalArmCoordinatesV1", ...]
    phase_budgets: tuple[AuthorizedPhaseBudgetV1, ...]
    capacity_policy: PilotCapacityPolicyV1

    @field_validator("protocol_id")
    @classmethod
    def validate_protocol_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="protocol_id")

    @field_validator(
        "source_authority_sha256",
        "dataset_split_policy_sha256",
        "candidate_pool_manifest_sha256",
        "runner_config_sha256",
        "model_config_sha256",
        "pair_manifest_sha256",
        "genesis_state_sha256",
    )
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("execution_schedule_sha256")
    @classmethod
    def validate_optional_execution_schedule_sha(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name="execution_schedule_sha256")

    @model_validator(mode="after")
    def validate_protocol_closure(self) -> "PilotProtocolV1":
        if not self.phase_budgets:
            raise ValueError("protocol requires at least one authorized phase budget")
        if not self.authorized_logical_arms:
            raise ValueError("protocol requires outcome-before logical-arm coordinates")
        seen: set[PilotPhase] = set()
        for budget in self.phase_budgets:
            if budget.method_arm != self.method_arm:
                raise ValueError("every phase budget must use the frozen method arm")
            if budget.phase in seen:
                raise ValueError("phase budgets must be unique")
            seen.add(budget.phase)
        if self.namespace.model_name != self.model_name:
            raise ValueError("namespace model differs from the frozen pilot model")
        if self.component_checkpoint_saga_required and not self.component_bundle_required:
            raise ValueError(
                "component checkpoint saga requires exact component bundles"
            )
        if self.store_derived_schedule_required:
            if self.execution_schedule_sha256 is None:
                raise ValueError(
                    "store-derived schedule authority requires an exact schedule digest"
                )
        elif self.execution_schedule_sha256 is not None:
            raise ValueError(
                "execution schedule digest requires store-derived schedule authority"
            )
        arm_digests = [canonical_sha256(item) for item in self.authorized_logical_arms]
        if len(arm_digests) != len(set(arm_digests)):
            raise ValueError("authorized logical-arm coordinates must be unique")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotCapacityPreflightV1(ClosedPilotModel):
    preflight_version: Literal["sft_pilot_preflight_v1"] = "sft_pilot_preflight_v1"
    planned_scientific_commits: int = Field(ge=0)
    planned_execution_leases: int = Field(ge=0)
    planned_call_receipts: int = Field(ge=0)
    planned_component_checkpoints: int = Field(default=0, ge=0)
    planned_max_calls_per_execution: int = Field(ge=0)
    planned_max_active_db_bytes: int = Field(ge=0)
    planned_archive_bytes: int = Field(ge=0)
    planned_total_stored_scalar_bytes: int = Field(ge=0)
    planned_max_input_tokens_per_call: int = Field(ge=0)
    planned_max_output_tokens_per_call: int = Field(ge=0)
    quarantined_carriers_reserved: int = Field(ge=0)
    indeterminate_call_reserve: int = Field(ge=0)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotLogicalArmCoordinatesV1(ClosedPilotModel):
    """Outcome-before coordinates; process/generation/retry aliases are absent."""

    coordinates_version: Literal["sft_pilot_logical_arm_v1"] = (
        "sft_pilot_logical_arm_v1"
    )
    pair_id: str
    pair_arm: Literal["source", "target", "control"]
    case_commitment_sha256: str
    unit_commitment: str
    split: PilotSplit
    operation_kind: PilotOperationKind
    execution_ordinal: int = Field(ge=0, le=1_000_000)

    @field_validator("pair_id", "unit_commitment")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("case_commitment_sha256")
    @classmethod
    def validate_case_commitment(cls, value: str) -> str:
        return require_sha256(value, field_name="case_commitment_sha256")

    def derive_logical_arm_key(self, protocol: PilotProtocolV1) -> str:
        digest = canonical_sha256(
            {
                "domain": "sft-pilot-logical-arm-v1",
                "protocol_sha256": protocol.digest,
                "method_arm": protocol.method_arm,
                "pair_manifest_sha256": protocol.pair_manifest_sha256,
                "coordinates": self,
            }
        )
        return f"la:{digest}"


class PilotExecutionLeaseRequestV1(ClosedPilotModel):
    """Caller request before the store derives the authoritative arm key."""

    logical_execution_key: str
    operation_kind: PilotOperationKind
    request_sha256: str
    namespace_sha256: str
    split: PilotSplit
    unit_commitment: str
    action_id: str | None = None
    call_slots_reserved: int = Field(ge=1)
    input_tokens_reserved: int = Field(ge=0)
    output_tokens_reserved: int = Field(ge=0)

    @field_validator("logical_execution_key", "unit_commitment")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("action_id")
    @classmethod
    def validate_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_opaque_id(value, field_name="action_id")

    @field_validator("request_sha256", "namespace_sha256")
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)


class PilotExecutionLeaseV1(ClosedPilotModel):
    logical_execution_key: str
    logical_arm_key: str
    operation_kind: PilotOperationKind
    request_sha256: str
    namespace_sha256: str
    split: PilotSplit
    unit_commitment: str
    action_id: str | None = None
    call_slots_reserved: int = Field(ge=1)
    input_tokens_reserved: int = Field(ge=0)
    output_tokens_reserved: int = Field(ge=0)
    physical_block_ordinal: int | None = Field(default=None, ge=0)
    schedule_entry_sha256: str | None = None
    state: PilotCallState = "reserved"

    @field_validator("logical_execution_key", "logical_arm_key", "unit_commitment")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("action_id")
    @classmethod
    def validate_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_opaque_id(value, field_name="action_id")

    @field_validator("request_sha256", "namespace_sha256")
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("schedule_entry_sha256")
    @classmethod
    def validate_optional_schedule_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name="schedule_entry_sha256")

    @model_validator(mode="after")
    def validate_schedule_projection(self) -> "PilotExecutionLeaseV1":
        if (self.physical_block_ordinal is None) != (
            self.schedule_entry_sha256 is None
        ):
            raise ValueError("schedule-derived execution fields are all-or-none")
        return self


class PilotCallReceiptV1(ClosedPilotModel):
    call_key: str
    logical_execution_key: str
    call_slot: int = Field(ge=0)
    request_sha256: str
    model_name: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    input_tokens_reserved: int = Field(ge=0)
    output_tokens_reserved: int = Field(ge=1)
    max_completion_tokens: int = Field(ge=1)
    expected_component_recovery_root_sha256: str | None = None
    scheduled_call_sha256: str | None = None
    request_renderer_sha256: str | None = None
    prompt_template_sha256: str | None = None
    json_mode: bool | None = None
    artifact_role: Literal[
        "proposal_generation",
        "source_artifact",
        "target_artifact",
        "final_deployment",
        "control_artifact",
    ] | None = None
    state: PilotCallState = "reserved"
    output_envelope_sha256: str | None = None
    provider_usage_known: bool = False
    input_tokens_used: int | None = Field(default=None, ge=0)
    output_tokens_used: int | None = Field(default=None, ge=0)
    conservative_charged_tokens: int = Field(ge=0)

    @field_validator("call_key", "logical_execution_key")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("request_sha256")
    @classmethod
    def validate_request_sha(cls, value: str) -> str:
        return require_sha256(value, field_name="request_sha256")

    @field_validator("output_envelope_sha256")
    @classmethod
    def validate_optional_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name="output_envelope_sha256")

    @field_validator("expected_component_recovery_root_sha256")
    @classmethod
    def validate_optional_recovery_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_sha256(
            value,
            field_name="expected_component_recovery_root_sha256",
        )

    @field_validator(
        "scheduled_call_sha256",
        "request_renderer_sha256",
        "prompt_template_sha256",
    )
    @classmethod
    def validate_optional_schedule_shas(
        cls, value: str | None, info: Any
    ) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_terminal_usage(self) -> "PilotCallReceiptV1":
        schedule_values = (
            self.scheduled_call_sha256,
            self.request_renderer_sha256,
            self.prompt_template_sha256,
            self.json_mode,
            self.artifact_role,
        )
        if any(value is not None for value in schedule_values) != all(
            value is not None for value in schedule_values
        ):
            raise ValueError("schedule-derived call fields are all-or-none")
        if self.max_completion_tokens != self.output_tokens_reserved:
            raise ValueError("completion cap must equal the frozen output reservation")
        if self.state == "completed":
            if not self.provider_usage_known:
                raise ValueError("completed calls require provider-authoritative usage")
            if self.output_envelope_sha256 is None:
                raise ValueError("completed calls require an output commitment")
            if self.input_tokens_used is None or self.output_tokens_used is None:
                raise ValueError("completed calls require exact token usage")
            if self.input_tokens_used > self.input_tokens_reserved:
                raise ValueError("actual input usage exceeds its call reservation")
            if self.output_tokens_used > self.output_tokens_reserved:
                raise ValueError("actual output usage exceeds its call reservation")
            if self.conservative_charged_tokens != (
                self.input_tokens_used + self.output_tokens_used
            ):
                raise ValueError("completed call charge must equal exact provider usage")
        elif self.output_envelope_sha256 is not None:
            raise ValueError("non-completed calls cannot retain an output commitment")
        if self.state == "indeterminate":
            reservation = self.input_tokens_reserved + self.output_tokens_reserved
            if self.conservative_charged_tokens < reservation:
                raise ValueError(
                    "indeterminate call must charge at least its full reservation"
                )
            if self.provider_usage_known:
                if self.input_tokens_used is None or self.output_tokens_used is None:
                    raise ValueError(
                        "known indeterminate usage requires exact provider counters"
                    )
                if self.conservative_charged_tokens < (
                    self.input_tokens_used + self.output_tokens_used
                ):
                    raise ValueError(
                        "indeterminate call charge cannot understate provider usage"
                    )
            elif self.input_tokens_used is not None or self.output_tokens_used is not None:
                raise ValueError("unknown indeterminate usage cannot carry counters")
        elif self.state != "completed" and (
            self.provider_usage_known
            or self.input_tokens_used is not None
            or self.output_tokens_used is not None
            or self.conservative_charged_tokens != 0
        ):
            raise ValueError("unstarted/nonterminal call cannot carry usage or charge")
        return self


class PilotCallStartAuthorizationV1(ClosedPilotModel):
    """Only ``newly_authorized`` permits crossing the external SDK boundary."""

    disposition: Literal["newly_authorized", "already_started"]
    receipt: PilotCallReceiptV1

    @property
    def may_invoke_sdk(self) -> bool:
        return self.disposition == "newly_authorized"


class PilotScientificCommitV1(ClosedPilotModel):
    commit_ordinal: int = Field(ge=1)
    operation_id: str
    owner_logical_execution_key: str
    owner_action_id: str
    owner_split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    request_sha256: str
    before_state_sha256: str
    after_state_sha256: str
    previous_commit_sha256: str
    commit_sha256: str
    commit_hmac_sha256: str

    @field_validator("operation_id", "owner_logical_execution_key", "owner_action_id")
    @classmethod
    def validate_operation_id(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator(
        "request_sha256",
        "before_state_sha256",
        "after_state_sha256",
        "previous_commit_sha256",
        "commit_sha256",
        "commit_hmac_sha256",
    )
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)


class PilotComponentBundleV1(ClosedPilotModel):
    """Authenticated metadata for one exact pair of component envelopes.

    The envelope bytes live in SQLite BLOB columns and are returned through
    :class:`PilotComponentBundleSnapshotV1`.  Keeping them out of this
    canonical metadata shape prevents accidental JSON/base64 rewrites from
    changing the recovery bytes.
    """

    bundle_version: Literal["sft_pilot_component_bundle_v1"] = (
        "sft_pilot_component_bundle_v1"
    )
    generation: int = Field(ge=0)
    scientific_commit_ordinal: int | None = Field(default=None, ge=1)
    phase_registry_envelope_sha256: str
    factor_bank_envelope_sha256: str
    previous_bundle_sha256: str
    bundle_sha256: str
    bundle_hmac_sha256: str

    @field_validator(
        "phase_registry_envelope_sha256",
        "factor_bank_envelope_sha256",
        "previous_bundle_sha256",
        "bundle_sha256",
        "bundle_hmac_sha256",
    )
    @classmethod
    def validate_bundle_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_generation_join(self) -> "PilotComponentBundleV1":
        if self.generation == 0:
            if self.scientific_commit_ordinal is not None:
                raise ValueError("genesis component bundle cannot own a scientific commit")
        elif self.scientific_commit_ordinal != self.generation:
            raise ValueError(
                "component bundle generation must equal its scientific commit ordinal"
            )
        return self


class PilotComponentBundleSnapshotV1(ClosedPilotModel):
    """Exact recovery bytes plus their authenticated SQLite metadata."""

    metadata: PilotComponentBundleV1
    phase_registry_envelope_bytes: bytes
    factor_bank_envelope_bytes: bytes


class PilotCheckpointSemanticWitnessV1(ClosedPilotModel):
    """Host-derived proof of one exact Phase/Factor lifecycle transition.

    This shape intentionally contains commitments and bounded coordinates only.
    The native component envelopes remain the authority for the underlying
    records; the witness makes the particular before/after facts used by the
    checkpoint law explicit and authenticated by the SQLite checkpoint HMAC.
    """

    witness_version: Literal["sft_pilot_checkpoint_semantics_v1"] = (
        "sft_pilot_checkpoint_semantics_v1"
    )
    checkpoint_kind: PilotComponentCheckpointKind
    protocol_sha256: str
    action_id: str
    action_branch: Literal["reuse", "mutate", "fresh"]
    action_producer_epoch: str
    action_intent_sha256: str
    phase_state_before_sha256: str
    phase_state_after_sha256: str
    phase_sequence_before: int = Field(ge=0)
    phase_sequence_after: int = Field(ge=0)
    factor_state_before_sha256: str
    factor_state_after_sha256: str
    factor_event_seq_before: int = Field(ge=0)
    factor_event_seq_after: int = Field(ge=1)
    proposal_action_before_sha256: str | None = None
    proposal_action_after_sha256: str
    proposal_action_before_state: Literal[
        "prepared", "executing", "committed", "aborted"
    ] | None = None
    proposal_action_after_state: Literal[
        "prepared", "executing", "committed", "aborted"
    ]
    proposal_generation_lease_sha256: str | None = None
    plan_id: str | None = None
    plan_sha256: str | None = None
    plan_epoch_id: str | None = None
    attempt_id: str | None = None
    attempt_sha256: str | None = None
    attempt_state: Literal[
        "open", "complete", "incomplete", "quarantine", "cancelled"
    ] | None = None
    attempt_ordinal: int | None = Field(default=None, ge=0, le=5)
    probe_pair_id: str | None = None
    probe_source_logical_arm_key: str | None = None
    probe_target_logical_arm_key: str | None = None
    terminal_execution_receipt_sha256: str | None = None
    assessment_id: str | None = None
    assessment_sha256: str | None = None
    gate_opportunity_id: str | None = None
    gate_opportunity_sha256: str | None = None
    gate_receipt_id: str | None = None
    gate_receipt_sha256: str | None = None
    expected_stage_operation_kind: Literal[
        "proposal_generation", "source_probe", "target_probe"
    ]
    expected_stage_pair_arm: Literal["source", "target"] | None = None
    expected_stage_execution_ordinal: int | None = Field(
        default=None, ge=0, le=5
    )

    @field_validator(
        "action_id",
        "action_producer_epoch",
        "plan_id",
        "plan_epoch_id",
        "attempt_id",
        "probe_pair_id",
        "probe_source_logical_arm_key",
        "probe_target_logical_arm_key",
        "assessment_id",
        "gate_opportunity_id",
        "gate_receipt_id",
    )
    @classmethod
    def validate_optional_ids(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator(
        "protocol_sha256",
        "action_intent_sha256",
        "phase_state_before_sha256",
        "phase_state_after_sha256",
        "factor_state_before_sha256",
        "factor_state_after_sha256",
        "proposal_action_before_sha256",
        "proposal_action_after_sha256",
        "proposal_generation_lease_sha256",
        "plan_sha256",
        "attempt_sha256",
        "terminal_execution_receipt_sha256",
        "assessment_sha256",
        "gate_opportunity_sha256",
        "gate_receipt_sha256",
    )
    @classmethod
    def validate_optional_shas(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "PilotCheckpointSemanticWitnessV1":
        if self.factor_event_seq_after <= self.factor_event_seq_before:
            raise ValueError("checkpoint semantics require a new Factor event")
        if self.phase_sequence_after < self.phase_sequence_before:
            raise ValueError("checkpoint semantics cannot rewind Phase sequence")
        if self.factor_state_before_sha256 == self.factor_state_after_sha256:
            raise ValueError("checkpoint semantics require changed Factor state")

        plan_values = (self.plan_id, self.plan_sha256, self.plan_epoch_id)
        attempt_values = (
            self.attempt_id,
            self.attempt_sha256,
            self.attempt_state,
            self.attempt_ordinal,
        )
        probe_binding_values = (
            self.probe_pair_id,
            self.probe_source_logical_arm_key,
            self.probe_target_logical_arm_key,
        )
        assessment_values = (self.assessment_id, self.assessment_sha256)
        opportunity_values = (
            self.gate_opportunity_id,
            self.gate_opportunity_sha256,
        )
        gate_values = (self.gate_receipt_id, self.gate_receipt_sha256)
        for label, values in (
            ("plan", plan_values),
            ("attempt", attempt_values),
            ("probe binding", probe_binding_values),
            ("assessment", assessment_values),
            ("gate opportunity", opportunity_values),
            ("gate receipt", gate_values),
        ):
            if any(value is not None for value in values) != all(
                value is not None for value in values
            ):
                raise ValueError(f"checkpoint {label} commitment is all-or-none")
        if all(value is None for value in attempt_values) != all(
            value is None for value in probe_binding_values
        ):
            raise ValueError("attempt and frozen probe-arm binding are inseparable")

        is_probe = self.expected_stage_operation_kind in {
            "source_probe", "target_probe"
        }
        if is_probe != (
            self.expected_stage_pair_arm is not None
            and self.expected_stage_execution_ordinal is not None
        ):
            raise ValueError("probe stage requires exact arm and ordinal coordinates")
        if is_probe and self.expected_stage_operation_kind != (
            "source_probe"
            if self.expected_stage_pair_arm == "source"
            else "target_probe"
        ):
            raise ValueError("probe arm differs from its operation kind")

        kind = self.checkpoint_kind
        no_probe = not any(value is not None for value in (*plan_values, *attempt_values))
        no_gate = not any(
            value is not None
            for value in (*assessment_values, *opportunity_values, *gate_values)
        )
        if kind == "action_prepared":
            if not (
                self.proposal_action_before_sha256 is None
                and self.proposal_action_before_state is None
                and self.proposal_action_after_state == "prepared"
                and self.proposal_generation_lease_sha256 is None
                and self.expected_stage_operation_kind == "proposal_generation"
                and no_probe
                and no_gate
                and self.terminal_execution_receipt_sha256 is None
            ):
                raise ValueError("action_prepared semantic witness has extra state")
        elif kind == "generation_start_authorized":
            generated = (
                self.action_branch in {"mutate", "fresh"}
                and self.proposal_action_before_state == "prepared"
                and self.proposal_action_after_state == "executing"
                and self.proposal_generation_lease_sha256 is not None
            )
            reused = (
                self.action_branch == "reuse"
                and self.proposal_action_before_state == "prepared"
                and self.proposal_action_after_state == "committed"
                and self.proposal_generation_lease_sha256 is None
            )
            if not (
                self.proposal_action_before_sha256 is not None
                and (generated or reused)
                and self.expected_stage_operation_kind == "proposal_generation"
                and no_probe
                and no_gate
                and self.terminal_execution_receipt_sha256 is None
            ):
                raise ValueError("generation checkpoint lacks its exact action delta")
        elif kind == "probe_attempt_open":
            if not (
                self.proposal_action_before_sha256 is not None
                and self.proposal_action_after_state == "committed"
                and all(value is not None for value in (*plan_values, *attempt_values))
                and self.attempt_state == "open"
                and is_probe
                and no_gate
                and self.terminal_execution_receipt_sha256 is None
            ):
                raise ValueError("probe open checkpoint lacks one open attempt")
        elif kind == "probe_terminal":
            if not (
                self.proposal_action_before_sha256 is not None
                and self.proposal_action_before_state == "committed"
                and self.proposal_action_after_state == "committed"
                and all(value is not None for value in (*plan_values, *attempt_values))
                and self.attempt_state in {
                    "complete", "incomplete", "quarantine", "cancelled"
                }
                and self.terminal_execution_receipt_sha256 is not None
                and is_probe
                and not any(value is not None for value in (*opportunity_values, *gate_values))
            ):
                raise ValueError("probe terminal checkpoint lacks trusted evidence")
        else:
            if not (
                self.proposal_action_before_sha256 is not None
                and self.proposal_action_before_state == "committed"
                and self.proposal_action_after_state == "committed"
                and all(
                    value is not None
                    for value in (
                        *plan_values,
                        *attempt_values,
                        *assessment_values,
                        *opportunity_values,
                        *gate_values,
                    )
                )
                and self.attempt_state
                in {"complete", "incomplete", "quarantine", "cancelled"}
                and self.expected_stage_operation_kind == "proposal_generation"
                and self.terminal_execution_receipt_sha256 is not None
            ):
                raise ValueError("gate checkpoint lacks settled assessment and receipt")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotComponentCheckpointV1(ClosedPilotModel):
    """Authenticated metadata for one non-scientific recovery checkpoint."""

    checkpoint_version: Literal["sft_pilot_component_checkpoint_v2"] = (
        "sft_pilot_component_checkpoint_v2"
    )
    checkpoint_ordinal: int = Field(ge=1)
    operation_id: str
    checkpoint_kind: PilotComponentCheckpointKind
    protocol_sha256: str
    action_id: str
    action_owner_logical_execution_key: str
    action_owner_logical_arm_key: str
    logical_execution_key: str
    logical_arm_key: str
    owner_split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    settled: bool
    semantic_witness: PilotCheckpointSemanticWitnessV1
    semantic_witness_sha256: str
    owner_terminal_call_ledger_sha256: str | None = None
    phase_registry_envelope_sha256: str
    factor_bank_envelope_sha256: str
    previous_recovery_root_sha256: str
    checkpoint_sha256: str
    checkpoint_hmac_sha256: str

    @field_validator(
        "operation_id",
        "action_id",
        "action_owner_logical_execution_key",
        "action_owner_logical_arm_key",
        "logical_execution_key",
        "logical_arm_key",
    )
    @classmethod
    def validate_checkpoint_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator(
        "protocol_sha256",
        "phase_registry_envelope_sha256",
        "factor_bank_envelope_sha256",
        "previous_recovery_root_sha256",
        "semantic_witness_sha256",
        "checkpoint_sha256",
        "checkpoint_hmac_sha256",
    )
    @classmethod
    def validate_checkpoint_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_settlement(self) -> "PilotComponentCheckpointV1":
        if self.settled != (self.checkpoint_kind == "gate_terminal"):
            raise ValueError("only gate_terminal component checkpoints are settled")
        if not (
            self.semantic_witness.checkpoint_kind == self.checkpoint_kind
            and self.semantic_witness.action_id == self.action_id
            and self.semantic_witness.protocol_sha256 == self.protocol_sha256
            and self.semantic_witness.digest == self.semantic_witness_sha256
        ):
            raise ValueError("checkpoint differs from its semantic witness")
        if (self.owner_terminal_call_ledger_sha256 is not None) != self.settled:
            raise ValueError("only settled checkpoints bind a terminal call ledger")
        if self.owner_terminal_call_ledger_sha256 is not None:
            require_sha256(
                self.owner_terminal_call_ledger_sha256,
                field_name="owner_terminal_call_ledger_sha256",
            )
        return self


class PilotComponentCheckpointSnapshotV1(ClosedPilotModel):
    """Exact Phase/Factor bytes owned by an authenticated checkpoint."""

    metadata: PilotComponentCheckpointV1
    phase_registry_envelope_bytes: bytes
    factor_bank_envelope_bytes: bytes


class PilotComponentRecoverySnapshotV1(ClosedPilotModel):
    """Exact bytes selected by the scientific/checkpoint recovery-head law."""

    recovery_version: Literal["sft_pilot_component_recovery_v1"] = (
        "sft_pilot_component_recovery_v1"
    )
    origin: Literal["scientific_bundle", "checkpoint"]
    recovery_root_sha256: str
    phase_registry_envelope_bytes: bytes
    factor_bank_envelope_bytes: bytes
    scientific_bundle: PilotComponentBundleV1 | None = None
    checkpoint: PilotComponentCheckpointV1 | None = None

    @field_validator("recovery_root_sha256")
    @classmethod
    def validate_recovery_root(cls, value: str) -> str:
        return require_sha256(value, field_name="recovery_root_sha256")

    @model_validator(mode="after")
    def validate_origin_join(self) -> "PilotComponentRecoverySnapshotV1":
        if self.origin == "scientific_bundle":
            if self.scientific_bundle is None or self.checkpoint is not None:
                raise ValueError("scientific recovery requires exactly one bundle")
            if self.recovery_root_sha256 != self.scientific_bundle.bundle_sha256:
                raise ValueError("scientific recovery root differs from its bundle")
        else:
            if self.checkpoint is None or self.scientific_bundle is not None:
                raise ValueError("checkpoint recovery requires exactly one checkpoint")
            if self.recovery_root_sha256 != self.checkpoint.checkpoint_sha256:
                raise ValueError("checkpoint recovery root differs from its checkpoint")
        return self


class PilotArchivePayloadV1(ClosedPilotModel):
    archive_version: Literal["sft_pilot_archive_v1"] = "sft_pilot_archive_v1"
    archive_id: str
    protocol_sha256: str
    terminal_generation: int = Field(ge=0)
    terminal_state_sha256: str
    commit_chain_head_sha256: str
    budget_ledger_root_sha256: str
    operation_ledger_root_sha256: str
    pair_manifest_sha256: str
    disposition_counts: tuple[tuple[str, int], ...]

    @field_validator("archive_id")
    @classmethod
    def validate_archive_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="archive_id")

    @field_validator(
        "protocol_sha256",
        "terminal_state_sha256",
        "commit_chain_head_sha256",
        "budget_ledger_root_sha256",
        "operation_ledger_root_sha256",
        "pair_manifest_sha256",
    )
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_dispositions(self) -> "PilotArchivePayloadV1":
        names: set[str] = set()
        for name, count in self.disposition_counts:
            require_opaque_id(name, field_name="disposition name")
            if name in names:
                raise ValueError("archive disposition names must be unique")
            if count < 0:
                raise ValueError("archive disposition counts cannot be negative")
            names.add(name)
        return self


class PilotArchiveEpochV1(ClosedPilotModel):
    payload: PilotArchivePayloadV1
    archive_sha256: str
    archive_hmac_sha256: str

    @field_validator("archive_sha256", "archive_hmac_sha256")
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)


PilotProtocolV1.model_rebuild()
