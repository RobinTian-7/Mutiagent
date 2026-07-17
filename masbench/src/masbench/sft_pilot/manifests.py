"""Closed, outcome-before manifests for the executable SFT pilot.

These shapes carry commitments and schedules only.  They intentionally do not
carry benchmark inputs, model text, answers, scoring payloads, or component
state.  Exact manifest bytes are frozen before a scored execution and joined
to child protocols by :func:`validate_experiment_children`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    PilotLogicalArmCoordinatesV1,
    PilotMethodArm,
    PilotProtocolV1,
    canonical_json,
    canonical_sha256,
    require_opaque_id,
    require_sha256,
)


ManifestSplit = Literal["PUBLIC", "TRAIN_UPDATE", "FINAL_VAL"]
ArtifactRole = Literal[
    "proposal_generation",
    "source_artifact",
    "target_artifact",
    "final_deployment",
    "control_artifact",
]
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_ManifestT = TypeVar("_ManifestT", bound=ClosedPilotModel)


def published_manifest_bytes(manifest: ClosedPilotModel) -> bytes:
    """Return the only file encoding admitted for a frozen pilot manifest."""

    return canonical_json(manifest).encode("utf-8")


def load_frozen_manifest(
    path_value: str | Path,
    *,
    model_type: type[_ManifestT],
    expected_sha256: str,
) -> _ManifestT:
    """Open one canonical manifest without following a replaceable symlink."""

    require_sha256(expected_sha256, field_name="expected_sha256")
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("frozen manifest path must be absolute")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("frozen manifest cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError(
                "frozen manifest must be a stable non-symlink regular file"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(_MAX_MANIFEST_BYTES + 1)
    finally:
        os.close(fd)
    if not payload or len(payload) > _MAX_MANIFEST_BYTES:
        raise ValueError("frozen manifest has an invalid byte length")
    try:
        manifest = model_type.model_validate_json(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("frozen manifest does not match its closed schema") from exc
    canonical = published_manifest_bytes(manifest)
    if payload != canonical:
        raise ValueError("frozen manifest file is not canonical exact JSON")
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != expected_sha256:
        raise ValueError("frozen manifest bytes differ from the expected digest")
    return manifest


class PilotCaseEntryV1(ClosedPilotModel):
    case_id: str
    split: ManifestSplit
    unit_commitment: str
    input_commitment_sha256: str

    @field_validator("case_id", "unit_commitment")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("input_commitment_sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        return require_sha256(value, field_name="input_commitment_sha256")


class PilotCaseManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_case_manifest_v1"] = (
        "sft_pilot_case_manifest_v1"
    )
    cases: tuple[PilotCaseEntryV1, ...]

    @model_validator(mode="after")
    def validate_cases(self) -> "PilotCaseManifestV1":
        if not self.cases:
            raise ValueError("case manifest cannot be empty")
        case_ids = tuple(item.case_id for item in self.cases)
        commitments = tuple(item.input_commitment_sha256 for item in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case ids must be unique")
        if len(set(commitments)) != len(commitments):
            raise ValueError("case input commitments must be unique")
        if tuple(sorted(case_ids)) != case_ids:
            raise ValueError("case manifest must use canonical case-id order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotPairEntryV1(ClosedPilotModel):
    pair_id: str
    case_id: str
    unit_commitment: str
    case_commitment_sha256: str
    arm_order: Literal["AB", "BA"]
    execution_ordinal: int = Field(ge=0, le=1_000_000)

    @field_validator("pair_id", "case_id", "unit_commitment")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("case_commitment_sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        return require_sha256(value, field_name="case_commitment_sha256")


class PilotPairManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_pair_manifest_v1"] = (
        "sft_pilot_pair_manifest_v1"
    )
    pairs: tuple[PilotPairEntryV1, ...]

    @model_validator(mode="after")
    def validate_pairs(self) -> "PilotPairManifestV1":
        if not self.pairs:
            raise ValueError("pair manifest cannot be empty")
        ids = tuple(item.pair_id for item in self.pairs)
        units = tuple(item.unit_commitment for item in self.pairs)
        ordinals = tuple(item.execution_ordinal for item in self.pairs)
        if len(set(ids)) != len(ids) or len(set(units)) != len(units):
            raise ValueError("pair ids and unit commitments must be unique")
        if ordinals != tuple(range(len(self.pairs))):
            raise ValueError("pair execution ordinals must be contiguous and ordered")
        n_ab = sum(item.arm_order == "AB" for item in self.pairs)
        n_ba = len(self.pairs) - n_ab
        if abs(n_ab - n_ba) > 1:
            raise ValueError("pair manifest must balance AB and BA order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotCandidateEntryV1(ClosedPilotModel):
    cell_sha256: str
    target_factor_key_sha256: str
    target_content_sha256: str

    @field_validator(
        "cell_sha256", "target_factor_key_sha256", "target_content_sha256"
    )
    @classmethod
    def validate_sha(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)


class PilotCandidateManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_candidate_manifest_v1"] = (
        "sft_pilot_candidate_manifest_v1"
    )
    candidates: tuple[PilotCandidateEntryV1, ...]

    @model_validator(mode="after")
    def validate_candidates(self) -> "PilotCandidateManifestV1":
        if not self.candidates:
            raise ValueError("candidate manifest cannot be empty")
        identities = tuple(
            (item.cell_sha256, item.target_factor_key_sha256)
            for item in self.candidates
        )
        if len(set(identities)) != len(identities):
            raise ValueError("candidate identities must be unique")
        if tuple(sorted(identities)) != identities:
            raise ValueError("candidate manifest must use canonical identity order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotCodeSourceV1(ClosedPilotModel):
    source_id: str
    sha256: str

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="source_id")

    @field_validator("sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        return require_sha256(value, field_name="sha256")


class PilotFailureOwnerV1(ClosedPilotModel):
    safe_failure_code: str
    owner: Literal[
        "factor_algorithm",
        "store_indeterminate",
        "harness_stop",
        "external_final_val",
    ]

    @field_validator("safe_failure_code")
    @classmethod
    def validate_failure_code(cls, value: str) -> str:
        return require_opaque_id(value, field_name="safe_failure_code")


class PilotRunnerManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_runner_manifest_v1"] = (
        "sft_pilot_runner_manifest_v1"
    )
    fixed_git_commit: str
    exact_artifact_runner_version: str
    runtime_version: str
    binder_version: str
    compiler_version: str
    code_sources: tuple[PilotCodeSourceV1, ...]
    failure_owners: tuple[PilotFailureOwnerV1, ...]

    @field_validator("fixed_git_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", value) is None:
            raise ValueError("fixed_git_commit must be a 40- or 64-hex object id")
        return value

    @field_validator(
        "exact_artifact_runner_version",
        "runtime_version",
        "binder_version",
        "compiler_version",
    )
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_sources_and_failures(self) -> "PilotRunnerManifestV1":
        source_ids = tuple(item.source_id for item in self.code_sources)
        failure_codes = tuple(item.safe_failure_code for item in self.failure_owners)
        if not source_ids or len(set(source_ids)) != len(source_ids):
            raise ValueError("runner code sources must be non-empty and unique")
        if not failure_codes or len(set(failure_codes)) != len(failure_codes):
            raise ValueError("failure ownership table must be non-empty and unique")
        if tuple(sorted(source_ids)) != source_ids:
            raise ValueError("runner code sources must use canonical source-id order")
        if tuple(sorted(failure_codes)) != failure_codes:
            raise ValueError("failure owners must use canonical failure-code order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotCallScheduleEntryV1(ClosedPilotModel):
    call_slot: int = Field(ge=0, le=10_000)
    input_tokens_reserved: int = Field(ge=1, le=1_000_000)
    output_tokens_reserved: int = Field(ge=1, le=1_000_000)
    request_envelope_sha256: str
    request_renderer_sha256: str
    prompt_template_sha256: str
    json_mode: bool
    artifact_role: ArtifactRole

    @field_validator(
        "request_envelope_sha256",
        "request_renderer_sha256",
        "prompt_template_sha256",
    )
    @classmethod
    def validate_sha(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotExecutionScheduleEntryV1(ClosedPilotModel):
    logical_arm: PilotLogicalArmCoordinatesV1
    physical_block_ordinal: int = Field(ge=0, le=10_000_000)
    calls: tuple[PilotCallScheduleEntryV1, ...]

    @model_validator(mode="after")
    def validate_call_sequence(self) -> "PilotExecutionScheduleEntryV1":
        if not self.calls:
            raise ValueError("scheduled execution requires at least one call")
        if tuple(item.call_slot for item in self.calls) != tuple(
            range(len(self.calls))
        ):
            raise ValueError("call slots must be contiguous and ordered")
        roles = {item.artifact_role for item in self.calls}
        operation = self.logical_arm.operation_kind
        pair_arm = self.logical_arm.pair_arm
        allowed_roles = {
            "proposal_generation": {"proposal_generation"},
            "source_probe": {"source_artifact"},
            "target_probe": {"target_artifact"},
            "final_val": {"final_deployment"},
            "control_execution": {"control_artifact"},
        }[operation]
        if not roles.issubset(allowed_roles):
            raise ValueError("artifact roles do not match the logical operation")
        if operation == "source_probe" and pair_arm != "source":
            raise ValueError("source probe requires the source logical arm")
        if operation == "target_probe" and pair_arm != "target":
            raise ValueError("target probe requires the target logical arm")
        if operation in {"proposal_generation", "final_val"} and pair_arm != "control":
            raise ValueError("non-probe execution requires a control logical arm")
        if operation in {"proposal_generation", "source_probe", "target_probe"}:
            if self.logical_arm.split != "TRAIN_UPDATE":
                raise ValueError(
                    "training and probe operations require TRAIN_UPDATE split"
                )
        elif operation == "final_val" and self.logical_arm.split != "FINAL_VAL":
            raise ValueError("final_val operation requires FINAL_VAL split")
        return self

    @property
    def coordinates_sha256(self) -> str:
        return canonical_sha256(self.logical_arm)

    @property
    def input_tokens_reserved(self) -> int:
        return sum(item.input_tokens_reserved for item in self.calls)

    @property
    def output_tokens_reserved(self) -> int:
        return sum(item.output_tokens_reserved for item in self.calls)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)

    @property
    def execution_request_sha256(self) -> str:
        """Outcome-before request root derived only from frozen schedule facts."""

        return canonical_sha256(
            {
                "domain": "sft-pilot-scheduled-execution-request-v1",
                "logical_arm": self.logical_arm,
                "physical_block_ordinal": self.physical_block_ordinal,
                "scheduled_calls": self.calls,
            }
        )


class PilotExecutionScheduleV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_execution_schedule_v1"] = (
        "sft_pilot_execution_schedule_v1"
    )
    entries: tuple[PilotExecutionScheduleEntryV1, ...]

    @model_validator(mode="after")
    def validate_entries(self) -> "PilotExecutionScheduleV1":
        if not self.entries:
            raise ValueError("execution schedule cannot be empty")
        blocks = tuple(item.physical_block_ordinal for item in self.entries)
        identities = tuple(item.coordinates_sha256 for item in self.entries)
        if blocks != tuple(range(len(self.entries))):
            raise ValueError("physical block ordinals must be contiguous and ordered")
        if len(set(identities)) != len(identities):
            raise ValueError("logical-arm schedules must be unique")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)

    def entry_for(
        self, logical_arm: PilotLogicalArmCoordinatesV1
    ) -> PilotExecutionScheduleEntryV1:
        digest = canonical_sha256(logical_arm)
        matches = tuple(
            item for item in self.entries if item.coordinates_sha256 == digest
        )
        if len(matches) != 1:
            raise KeyError("logical arm is absent or aliased in the frozen schedule")
        return matches[0]


class PilotProposalPermutationEntryV1(ClosedPilotModel):
    target_factor_key_sha256: str
    permuted_rank: int = Field(ge=0, le=1_000_000)

    @field_validator("target_factor_key_sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        return require_sha256(value, field_name="target_factor_key_sha256")


class PilotProposalPermutationV1(ClosedPilotModel):
    permutation_version: Literal["sft_pilot_proposal_permutation_v1"] = (
        "sft_pilot_proposal_permutation_v1"
    )
    entries: tuple[PilotProposalPermutationEntryV1, ...]

    @model_validator(mode="after")
    def validate_permutation(self) -> "PilotProposalPermutationV1":
        keys = tuple(item.target_factor_key_sha256 for item in self.entries)
        ranks = tuple(item.permuted_rank for item in self.entries)
        if len(set(keys)) != len(keys):
            raise ValueError("permutation target keys must be unique")
        if tuple(sorted(ranks)) != tuple(range(len(self.entries))):
            raise ValueError("permuted ranks must be a complete zero-based permutation")
        if tuple(sorted(keys)) != keys:
            raise ValueError("permutation entries must use canonical target-key order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotExperimentArmV1(ClosedPilotModel):
    method_arm: PilotMethodArm
    child_protocol_sha256: str
    implementation_sha256: str
    state_dir_commitment_sha256: str
    execution_schedule_sha256: str

    @field_validator(
        "child_protocol_sha256",
        "implementation_sha256",
        "state_dir_commitment_sha256",
        "execution_schedule_sha256",
    )
    @classmethod
    def validate_sha(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)


class PilotBlockedArmOrderV1(ClosedPilotModel):
    block_ordinal: int = Field(ge=0, le=10_000_000)
    unit_commitment: str
    arm_order: tuple[PilotMethodArm, ...]

    @field_validator("unit_commitment")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        return require_opaque_id(value, field_name="unit_commitment")


class PilotExperimentManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_pilot_experiment_manifest_v1"] = (
        "sft_pilot_experiment_manifest_v1"
    )
    experiment_id: str
    case_manifest_sha256: str
    pair_manifest_sha256: str
    candidate_manifest_sha256: str
    runner_manifest_sha256: str
    model_config_sha256: str
    execution_schedule_sha256: str
    arms: tuple[PilotExperimentArmV1, ...]
    blocked_arm_orders: tuple[PilotBlockedArmOrderV1, ...]
    shuffled_proposal_permutation: PilotProposalPermutationV1 | None = None
    allowed_child_protocol_differences: tuple[
        Literal[
            "protocol_id",
            "method_arm",
            "genesis_state_sha256",
            "component_bundle_required",
        ],
        ...,
    ] = (
        "component_bundle_required",
        "genesis_state_sha256",
        "method_arm",
        "protocol_id",
    )

    @field_validator("experiment_id")
    @classmethod
    def validate_experiment_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="experiment_id")

    @field_validator(
        "case_manifest_sha256",
        "pair_manifest_sha256",
        "candidate_manifest_sha256",
        "runner_manifest_sha256",
        "model_config_sha256",
        "execution_schedule_sha256",
    )
    @classmethod
    def validate_sha(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_experiment(self) -> "PilotExperimentManifestV1":
        methods = tuple(item.method_arm for item in self.arms)
        if len(methods) < 2 or len(set(methods)) != len(methods):
            raise ValueError("experiment arms must contain unique comparisons")
        if any(
            item.execution_schedule_sha256 != self.execution_schedule_sha256
            for item in self.arms
        ):
            raise ValueError("every arm must bind the shared execution schedule")
        state_roots = tuple(item.state_dir_commitment_sha256 for item in self.arms)
        if len(set(state_roots)) != len(state_roots):
            raise ValueError("every arm requires a distinct state-directory commitment")
        if not self.blocked_arm_orders:
            raise ValueError("cross-arm physical order cannot be empty")
        units = tuple(item.unit_commitment for item in self.blocked_arm_orders)
        blocks = tuple(item.block_ordinal for item in self.blocked_arm_orders)
        if len(set(units)) != len(units):
            raise ValueError("blocked-order units must be unique")
        if blocks != tuple(range(len(self.blocked_arm_orders))):
            raise ValueError("blocked-order ordinals must be contiguous and ordered")
        expected = set(methods)
        for block in self.blocked_arm_orders:
            if len(block.arm_order) != len(methods) or set(block.arm_order) != expected:
                raise ValueError("every blocked order must contain every arm exactly once")
        shuffled_present = "sft_shuffled_edge" in methods
        if shuffled_present != (self.shuffled_proposal_permutation is not None):
            raise ValueError("shuffled arm requires exactly one frozen proposal permutation")
        expected_differences = (
            "component_bundle_required",
            "genesis_state_sha256",
            "method_arm",
            "protocol_id",
        )
        if self.allowed_child_protocol_differences != expected_differences:
            raise ValueError("child protocol difference allowlist is not canonical")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


def validate_schedule_against_protocol(
    schedule: PilotExecutionScheduleV1,
    protocol: PilotProtocolV1,
    *,
    case_manifest: PilotCaseManifestV1 | None = None,
    pair_manifest: PilotPairManifestV1 | None = None,
) -> None:
    """Require exact schedule coverage and protocol-budget closure."""

    scheduled = {canonical_sha256(item.logical_arm): item for item in schedule.entries}
    authorized = {
        canonical_sha256(item): item for item in protocol.authorized_logical_arms
    }
    if scheduled.keys() != authorized.keys():
        raise ValueError("execution schedule differs from protocol logical arms")
    if protocol.store_derived_schedule_required:
        if protocol.execution_schedule_sha256 != schedule.digest:
            raise ValueError("protocol does not bind the exact execution schedule")
    elif protocol.execution_schedule_sha256 is not None:
        raise ValueError("legacy protocol carries an ambiguous schedule digest")
    if (case_manifest is None) != (pair_manifest is None):
        raise ValueError("case and pair manifests must be validated together")
    if case_manifest is not None and pair_manifest is not None:
        cases_by_id = {item.case_id: item for item in case_manifest.cases}
        pairs_by_id = {item.pair_id: item for item in pair_manifest.pairs}
        if len(cases_by_id) != len(case_manifest.cases):
            raise ValueError("case manifest identities are not unique")
        if len(pairs_by_id) != len(pair_manifest.pairs):
            raise ValueError("pair manifest identities are not unique")
        for pair in pair_manifest.pairs:
            case = cases_by_id.get(pair.case_id)
            if case is None or not (
                pair.unit_commitment == case.unit_commitment
                and pair.case_commitment_sha256 == case.input_commitment_sha256
            ):
                raise ValueError("pair manifest is not closed over the exact case")
        if protocol.source_manifest.source_catalog_sha256 != case_manifest.digest:
            raise ValueError("protocol does not bind the exact case manifest")
        if protocol.pair_manifest_sha256 != pair_manifest.digest:
            raise ValueError("protocol does not bind the exact pair manifest")
        for entry in schedule.entries:
            arm = entry.logical_arm
            pair = pairs_by_id.get(arm.pair_id)
            if pair is None:
                raise ValueError("scheduled arm pair_id is absent from pair manifest")
            case = cases_by_id[pair.case_id]
            if not (
                arm.unit_commitment == pair.unit_commitment
                and arm.case_commitment_sha256 == pair.case_commitment_sha256
                and arm.execution_ordinal == pair.execution_ordinal
                and arm.split == case.split
            ):
                raise ValueError(
                    "scheduled arm differs from exact case/pair/split coordinates"
                )
    policy = protocol.capacity_policy
    for entry in schedule.entries:
        if len(entry.calls) > policy.max_call_slots_per_execution:
            raise ValueError("schedule exceeds per-execution call capacity")
        for call in entry.calls:
            if call.input_tokens_reserved > policy.max_input_tokens_per_call:
                raise ValueError("schedule exceeds per-call input capacity")
            if call.output_tokens_reserved > policy.max_output_tokens_per_call:
                raise ValueError("schedule exceeds per-call output capacity")
    for phase_budget in protocol.phase_budgets:
        entries = tuple(
            item
            for item in schedule.entries
            if (
                "FINAL_VAL"
                if item.logical_arm.split == "FINAL_VAL"
                or item.logical_arm.operation_kind == "final_val"
                else (
                    "PROBE"
                    if item.logical_arm.operation_kind
                    in {"source_probe", "target_probe"}
                    else "TRAIN_UPDATE"
                )
            )
            == phase_budget.phase
        )
        if len(entries) > phase_budget.executions:
            raise ValueError(f"schedule exceeds {phase_budget.phase} execution budget")
        if sum(len(item.calls) for item in entries) > phase_budget.call_slots:
            raise ValueError(f"schedule exceeds {phase_budget.phase} call-slot budget")
        if (
            sum(item.input_tokens_reserved for item in entries)
            > phase_budget.input_tokens
        ):
            raise ValueError(f"schedule exceeds {phase_budget.phase} input budget")
        if (
            sum(item.output_tokens_reserved for item in entries)
            > phase_budget.output_tokens
        ):
            raise ValueError(f"schedule exceeds {phase_budget.phase} output budget")


def validate_experiment_children(
    manifest: PilotExperimentManifestV1,
    *,
    protocols: Sequence[PilotProtocolV1],
    case_manifest: PilotCaseManifestV1,
    pair_manifest: PilotPairManifestV1,
    candidate_manifest: PilotCandidateManifestV1,
    runner_manifest: PilotRunnerManifestV1,
    execution_schedule: PilotExecutionScheduleV1,
) -> None:
    """Close child protocols over the exact shared experiment manifests."""

    expected_roots = {
        "case": case_manifest.digest,
        "pair": pair_manifest.digest,
        "candidate": candidate_manifest.digest,
        "runner": runner_manifest.digest,
        "schedule": execution_schedule.digest,
    }
    observed_roots = {
        "case": manifest.case_manifest_sha256,
        "pair": manifest.pair_manifest_sha256,
        "candidate": manifest.candidate_manifest_sha256,
        "runner": manifest.runner_manifest_sha256,
        "schedule": manifest.execution_schedule_sha256,
    }
    if expected_roots != observed_roots:
        raise ValueError("experiment root does not match exact child manifest bytes")
    pair_units = {item.unit_commitment for item in pair_manifest.pairs}
    order_units = {item.unit_commitment for item in manifest.blocked_arm_orders}
    if pair_units != order_units:
        raise ValueError("blocked arm order does not cover the exact pair units")
    if manifest.shuffled_proposal_permutation is not None:
        candidate_keys = {
            item.target_factor_key_sha256 for item in candidate_manifest.candidates
        }
        permutation_keys = {
            item.target_factor_key_sha256
            for item in manifest.shuffled_proposal_permutation.entries
        }
        if candidate_keys != permutation_keys:
            raise ValueError("shuffled permutation differs from the candidate universe")
    by_digest: Mapping[str, PilotProtocolV1] = {
        item.digest: item for item in protocols
    }
    if len(by_digest) != len(protocols):
        raise ValueError("child protocol digests must be unique")
    if set(by_digest) != {item.child_protocol_sha256 for item in manifest.arms}:
        raise ValueError("experiment arms do not cover the exact child protocols")
    reference_projection = None
    allowed = set(manifest.allowed_child_protocol_differences)
    for arm in manifest.arms:
        protocol = by_digest[arm.child_protocol_sha256]
        if protocol.method_arm != arm.method_arm:
            raise ValueError("child protocol method arm differs from experiment arm")
        if protocol.pair_manifest_sha256 != pair_manifest.digest:
            raise ValueError("child protocol pair manifest is not experiment exact")
        if protocol.candidate_pool_manifest_sha256 != candidate_manifest.digest:
            raise ValueError("child protocol candidate manifest is not experiment exact")
        if protocol.runner_config_sha256 != runner_manifest.digest:
            raise ValueError("child protocol runner manifest is not experiment exact")
        if protocol.model_config_sha256 != manifest.model_config_sha256:
            raise ValueError("child protocol model config is not experiment exact")
        if protocol.source_manifest.source_catalog_sha256 != case_manifest.digest:
            raise ValueError("child source catalog is not the frozen case manifest")
        validate_schedule_against_protocol(
            execution_schedule,
            protocol,
            case_manifest=case_manifest,
            pair_manifest=pair_manifest,
        )
        projection = protocol.model_dump(mode="json")
        for field in allowed:
            projection.pop(field, None)
        if "method_arm" in allowed:
            for budget in projection["phase_budgets"]:
                budget.pop("method_arm", None)
        if reference_projection is None:
            reference_projection = projection
        elif projection != reference_projection:
            raise ValueError("child protocols differ outside the explicit allowlist")


__all__ = [
    "PilotBlockedArmOrderV1",
    "PilotCallScheduleEntryV1",
    "PilotCandidateEntryV1",
    "PilotCandidateManifestV1",
    "PilotCaseEntryV1",
    "PilotCaseManifestV1",
    "PilotCodeSourceV1",
    "PilotExecutionScheduleEntryV1",
    "PilotExecutionScheduleV1",
    "PilotExperimentArmV1",
    "PilotExperimentManifestV1",
    "PilotFailureOwnerV1",
    "PilotPairEntryV1",
    "PilotPairManifestV1",
    "PilotProposalPermutationEntryV1",
    "PilotProposalPermutationV1",
    "PilotRunnerManifestV1",
    "load_frozen_manifest",
    "published_manifest_bytes",
    "validate_experiment_children",
    "validate_schedule_against_protocol",
]
