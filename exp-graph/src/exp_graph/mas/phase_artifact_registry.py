"""Trusted PhaseProgram materializer for the default-off factor-transition Bank.

This module is deliberately a host capability, not an LLM-facing schema.  It
owns complete PhaseProgram artifacts and typed scalar values, seals the
``reuse|mutate|fresh`` branch before a target exists, performs one allowlisted
replacement, and mints a binding proof only after independently rebuilding the
two execution images.  The scientific FactorBank sees opaque handles and keyed
commitments; it never stores a raw program or a low-entropy scalar hash.

The implementation uses an HMAC-authenticated, atomically-written JSON state as
the first runnable research backend.  All records are immutable; content
identity is separate from branch/event identity; load verifies a whole-state
MAC and then recomputes every record handle.  A later SQLite backend can keep
the same public contract without changing the scientific state machine.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import fcntl
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.mas.factor_bank import (
    CompositionRevision,
    ExecutionBudget,
    ExecutionNamespace,
    ExecutionUsage,
    FactorLocator,
    FactorRevision,
    assert_bank_safe_public_value,
)
from exp_graph.mas.phase_program import (
    PHASE_PROGRAM_COMPILER_VERSION,
    CompiledPhaseProgram,
    PhaseProgram,
    PhaseProgramLimits,
    compile_phase_program,
)


PHASE_ARTIFACT_REGISTRY_VERSION = "phase-artifact-registry-v8"
PHASE_FACTOR_BINDER_VERSION = "facts-phase-leaf-v2"
PHASE_FULL_FACTOR_BINDER_VERSION = "facts-phase-full-v3"
PHASE_EXECUTION_IMAGE_VERSION = "phase-execution-image-v2"
PHASE_ACTIVATION_VERSION = "phase-activation-v2"
PHASE_MATERIALIZATION_EVENT_DIGEST_VERSION = (
    "sft_phase_materialization_event_digest_v1"
)

_HANDLE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,15}:[0-9a-f]{48}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHENTICATED_RESTORE_TOKEN = object()
SourceSplit = Literal["PUBLIC", "TRAIN_UPDATE"]
Branch = Literal["reuse", "mutate", "fresh"]
ScalarType = Literal["null", "bool", "int", "string"]
GeneratedBranch = Literal["mutate", "fresh"]
PhaseBinderVersion = Literal[
    PHASE_FACTOR_BINDER_VERSION,
    PHASE_FULL_FACTOR_BINDER_VERSION,
]


# ``None`` is a legal generated Phase scalar, so omission cannot use an
# Optional value.  This private sentinel never enters a persisted model.
_MISSING_GENERATED_VALUE = object()


class LegacyPhaseArtifactRegistryRejected(ValueError):
    """An older Phase registry cannot gain v8 action-terminal authority."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
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


def _mac(key: bytes, domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\0" + _canonical_json(value).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _handle_id(key: bytes, prefix: str, identity: Any) -> str:
    return f"{prefix}:{_mac(key, 'handle:' + prefix, identity)[:48]}"


def _atomic_registry_update(method: Callable[..., Any]) -> Callable[..., Any]:
    """Make one public registry mutation a fail-closed state transaction.

    The JSON backend is deliberately bounded and in-memory, so immutable record
    objects plus shallow dictionary snapshots are sufficient for rollback.  A
    loaded/saved registry also compare-and-swaps its owned file before the
    method may return authority to its caller.
    """

    @wraps(method)
    def wrapped(self: "PhaseArtifactRegistry", *args: Any, **kwargs: Any) -> Any:
        with self._atomic_update():
            return method(self, *args, **kwargs)

    return wrapped


def _registry_instance_lock(method: Callable[..., Any]) -> Callable[..., Any]:
    """Linearize one public read/verification against registry mutations.

    Resolver memoization is deliberately instance-scoped for one complete
    verification operation.  The same reentrant lock used by writers keeps
    that cache from being shared or cleared by another thread while also
    allowing nested resolver calls in the owning thread.
    """

    @wraps(method)
    def wrapped(self: "PhaseArtifactRegistry", *args: Any, **kwargs: Any) -> Any:
        with self._mutation_lock:
            return method(self, *args, **kwargs)

    return wrapped


def _registry_verification_scope(method: Callable[..., Any]) -> Callable[..., Any]:
    """Share one resolver cache across a complete verification operation."""

    @wraps(method)
    def wrapped(self: "PhaseArtifactRegistry", *args: Any, **kwargs: Any) -> Any:
        outermost = self._verification_cache is None
        if outermost:
            self._verification_cache = {}
            self._verification_visiting = set()
        try:
            return method(self, *args, **kwargs)
        finally:
            if outermost:
                self._verification_cache = None
                self._verification_visiting = None

    return wrapped


def _memoized_registry_resolver(
    kind: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Memoize immutable record resolution and reject recursive cycles.

    The key includes the complete caller handle, rather than only its public
    identifier, so a malformed handle cannot reuse another handle's success.
    """

    def decorate(method: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(method)
        def wrapped(
            self: "PhaseArtifactRegistry", handle: Any, *args: Any, **kwargs: Any
        ) -> Any:
            outermost = self._verification_cache is None
            if outermost:
                self._verification_cache = {}
                self._verification_visiting = set()
            assert self._verification_cache is not None
            assert self._verification_visiting is not None
            key = (kind, _canonical_json(handle))
            if key in self._verification_cache:
                return self._verification_cache[key]
            if key in self._verification_visiting:
                raise ValueError(f"{kind} provenance contains a cycle")
            self._verification_visiting.add(key)
            try:
                result = method(self, handle, *args, **kwargs)
                self._verification_cache[key] = result
                return result
            finally:
                self._verification_visiting.discard(key)
                if outermost:
                    self._verification_cache = None
                    self._verification_visiting = None

        return wrapped

    return decorate


def _require_sha(value: str, name: str) -> None:
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_handle(value: str, name: str) -> None:
    if not _HANDLE_RE.fullmatch(value):
        raise ValueError(f"{name} must be an opaque registry handle")


def _validated_program(value: PhaseProgram | Mapping[str, Any]) -> PhaseProgram:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    parsed = PhaseProgram.model_validate(raw)
    return PhaseProgram.model_validate(parsed.model_dump(mode="python"))


def _validated_limits(
    value: PhaseProgramLimits | Mapping[str, Any],
) -> PhaseProgramLimits:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    parsed = PhaseProgramLimits.model_validate(raw)
    result = PhaseProgramLimits.model_validate(parsed.model_dump(mode="python"))
    if result.max_steps > 16:
        raise ValueError("factor profile max_steps cannot exceed 16")
    if result.max_messages > 128:
        raise ValueError("factor profile max_messages cannot exceed 128")
    if result.max_receiver_fan_in > 4:
        raise ValueError("factor profile max_receiver_fan_in cannot exceed 4")
    return result


def _decode_pointer(path: str) -> list[str]:
    if not path.startswith("/") or path == "/":
        raise ValueError("factor locator must be a non-root JSON Pointer")
    raw_tokens = path[1:].split("/")
    if any(re.fullmatch(r"(?:[^~]|~[01])*", token) is None for token in raw_tokens):
        raise ValueError("factor locator contains a non-canonical JSON Pointer escape")
    tokens = [part.replace("~1", "/").replace("~0", "~") for part in raw_tokens]
    # PhaseProgram list positions use canonical RFC-6901 decimal indices.  A
    # caller must not be able to seal `/phases/00/...` and later collide with
    # the materializer's canonical `/phases/0/...` proof path.
    if any(token.isdigit() and len(token) > 1 and token.startswith("0") for token in tokens):
        raise ValueError("factor locator list index must use canonical decimal form")
    if _pointer(tokens) != path:
        raise ValueError("factor locator must use canonical JSON Pointer encoding")
    return tokens


def _read_pointer(payload: Any, path: str) -> Any:
    current = payload
    for token in _decode_pointer(path):
        if isinstance(current, list):
            if not token.isdigit():
                raise ValueError("list JSON Pointer token must be a non-negative integer")
            index = int(token)
            if index >= len(current):
                raise ValueError("factor locator list index is out of range")
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                raise ValueError("factor locator key does not exist")
            current = current[token]
        else:
            raise ValueError("factor locator descends through a scalar")
    return current


def _replace_pointer(payload: Any, path: str, value: Any) -> Any:
    copied = json.loads(_canonical_json(payload))
    tokens = _decode_pointer(path)
    current = copied
    for token in tokens[:-1]:
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ValueError("factor locator list index is out of range")
            current = current[int(token)]
        elif isinstance(current, dict):
            if token not in current:
                raise ValueError("factor locator key does not exist")
            current = current[token]
        else:
            raise ValueError("factor locator descends through a scalar")
    final = tokens[-1]
    if isinstance(current, list):
        if not final.isdigit() or int(final) >= len(current):
            raise ValueError("factor locator list index is out of range")
        index = int(final)
        if isinstance(current[index], (dict, list)):
            raise ValueError("structural values remain locked_atomic")
        current[index] = value
    elif isinstance(current, dict):
        if final not in current:
            raise ValueError("factor locator key does not exist")
        if isinstance(current[final], (dict, list)):
            raise ValueError("structural values remain locked_atomic")
        current[final] = value
    else:
        raise ValueError("factor locator parent is a scalar")
    return copied


def _leaf_differences(
    source: Any,
    target: Any,
    *,
    path: tuple[str | int, ...] = (),
) -> list[tuple[tuple[str | int, ...], Any, Any]]:
    if type(source) is not type(target):
        return [(path, source, target)]
    if isinstance(source, dict):
        if set(source) != set(target):
            return [(path, source, target)]
        result: list[tuple[tuple[str | int, ...], Any, Any]] = []
        for key in sorted(source):
            result.extend(_leaf_differences(source[key], target[key], path=(*path, key)))
        return result
    if isinstance(source, list):
        if len(source) != len(target):
            return [(path, source, target)]
        result = []
        for index, (left, right) in enumerate(zip(source, target)):
            result.extend(_leaf_differences(left, right, path=(*path, index)))
        return result
    return [] if source == target else [(path, source, target)]


def _pointer(tokens: Sequence[str | int]) -> str:
    escaped = [str(item).replace("~", "~0").replace("/", "~1") for item in tokens]
    return "/" + "/".join(escaped)


def _scalar_type(value: Any) -> ScalarType:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "string"
    raise ValueError("PhaseProgram factors support only null/bool/int/string scalars")


def phase_generated_scalar_sha256(value: Any) -> str:
    """Commit one parsed scalar with its exact JSON/Python scalar type."""

    scalar_type = _scalar_type(value)
    assert_bank_safe_public_value(value)
    return _sha256({"scalar_type": scalar_type, "value": value})


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class RegistryHandle(_ClosedModel):
    registry_version: Literal[PHASE_ARTIFACT_REGISTRY_VERSION] = (
        PHASE_ARTIFACT_REGISTRY_VERSION
    )
    kind: str
    handle_id: str
    record_mac: str

    @model_validator(mode="after")
    def validate_handle(self) -> "RegistryHandle":
        _require_handle(self.handle_id, "handle_id")
        _require_sha(self.record_mac, "record_mac")
        return self


class RuntimeProfileHandle(RegistryHandle):
    kind: Literal["runtime_profile"] = "runtime_profile"


class PhaseArtifactHandle(RegistryHandle):
    kind: Literal["phase_artifact"] = "phase_artifact"


class PhaseValueHandle(RegistryHandle):
    kind: Literal["phase_value"] = "phase_value"
    scalar_type: ScalarType
    slot_schema_commitment: str


class ValueAttestationHandle(RegistryHandle):
    kind: Literal["value_attestation"] = "value_attestation"


class FactorContentHandle(RegistryHandle):
    kind: Literal["factor_content"] = "factor_content"


class BranchReceiptHandle(RegistryHandle):
    kind: Literal["branch_receipt"] = "branch_receipt"


class OperationSealHandle(RegistryHandle):
    kind: Literal["operation_seal"] = "operation_seal"


class MaterializationEventHandle(RegistryHandle):
    kind: Literal["materialization_event"] = "materialization_event"


class PhaseBindingProofHandle(RegistryHandle):
    kind: Literal["phase_binding_proof"] = "phase_binding_proof"
    proof_sha256: str

    @model_validator(mode="after")
    def validate_proof_digest(self) -> "PhaseBindingProofHandle":
        _require_sha(self.proof_sha256, "proof_sha256")
        return self


class SourceManifest(_ClosedModel):
    """Host-authenticated source universe; TEST/VAL/private has no enum value."""

    manifest_sha256: str
    split: SourceSplit
    source_catalog_sha256: str
    policy_sha256: str
    producer_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_hashes(self) -> "SourceManifest":
        for name in ("manifest_sha256", "source_catalog_sha256", "policy_sha256"):
            _require_sha(str(getattr(self, name)), name)
        return self


class RegistryCapacity(_ClosedModel):
    max_profiles: int = Field(default=64, ge=1, le=1024)
    max_artifacts: int = Field(default=4096, ge=1, le=100_000)
    max_values: int = Field(default=4096, ge=1, le=100_000)
    max_attestations: int = Field(default=8192, ge=1, le=200_000)
    max_factors: int = Field(default=4096, ge=1, le=100_000)
    max_branch_receipts: int = Field(default=8192, ge=1, le=200_000)
    max_seals: int = Field(default=8192, ge=1, le=200_000)
    max_events: int = Field(default=8192, ge=1, le=200_000)
    max_proofs: int = Field(default=8192, ge=1, le=200_000)
    max_lineage_depth: int = Field(default=64, ge=1, le=256)


class PhaseRuntimeProfileRecord(_ClosedModel):
    handle: RuntimeProfileHandle
    namespace: ExecutionNamespace
    limits: PhaseProgramLimits
    limits_commitment: str
    binder_version: PhaseBinderVersion = PHASE_FACTOR_BINDER_VERSION
    compiler_version: Literal[PHASE_PROGRAM_COMPILER_VERSION] = (
        PHASE_PROGRAM_COMPILER_VERSION
    )
    execution_image_version: Literal[PHASE_EXECUTION_IMAGE_VERSION] = (
        PHASE_EXECUTION_IMAGE_VERSION
    )
    activation_version: Literal[PHASE_ACTIVATION_VERSION] = PHASE_ACTIVATION_VERSION
    # ProgramGeneratePlanner and PhaseProgramGeneration both install this
    # exact runner override.  Instruction changes are operational only in this
    # profile; another runtime contract needs a different profile/version.
    enable_step_instructions: Literal[True] = True


class PhaseExecutionStepImage(_ClosedModel):
    step_index: int = Field(ge=0)
    phase_index: int = Field(ge=0)
    phase_kind: str
    transmissions: tuple[tuple[int, int], ...]
    operator: str
    instruction: str | None


class PhaseExecutionImage(_ClosedModel):
    image_version: Literal[PHASE_EXECUTION_IMAGE_VERSION] = PHASE_EXECUTION_IMAGE_VERSION
    runtime_profile_id: str
    selected_primary: int = Field(ge=0)
    information_goal: Literal["sink", "all_agents"]
    state_retention: str
    allow_no_send: bool
    enable_step_instructions: Literal[True] = True
    steps: tuple[PhaseExecutionStepImage, ...]


class PhaseSlotDescriptor(_ClosedModel):
    locator: FactorLocator
    program_schema_commitment: str
    slot_schema_commitment: str
    allowed_scalar_types: tuple[ScalarType, ...]
    phase_kind: Literal[
        "program", "gather", "broadcast", "pairwise_exchange", "consensus"
    ]
    phase_index: int | None = Field(default=None, ge=0)
    field_name: str
    activation_kind: Literal[
        "execution_image_load", "phase_step_executed", "submission_event"
    ]
    enum_values: tuple[str, ...] = ()
    int_min: int | None = None
    int_max: int | None = None
    max_length: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_descriptor(self) -> "PhaseSlotDescriptor":
        for name in ("program_schema_commitment", "slot_schema_commitment"):
            _require_sha(str(getattr(self, name)), name)
        if not self.allowed_scalar_types:
            raise ValueError("slot descriptor needs at least one scalar type")
        if len(self.allowed_scalar_types) != len(set(self.allowed_scalar_types)):
            raise ValueError("slot scalar types must be unique")
        return self


class PhaseProgramArtifactRecord(_ClosedModel):
    handle: PhaseArtifactHandle
    runtime_profile: RuntimeProfileHandle
    source_manifest_sha256: str
    split: SourceSplit
    program: PhaseProgram
    program_commitment: str
    execution_image: PhaseExecutionImage
    execution_image_commitment: str
    parent_artifact_id: str | None = None
    derivation_operation_seal_id: str | None = None
    derivation_target_factor_id: str | None = None
    created_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_derivation_shape(self) -> "PhaseProgramArtifactRecord":
        lineage = (
            self.parent_artifact_id,
            self.derivation_operation_seal_id,
            self.derivation_target_factor_id,
        )
        if any(item is None for item in lineage) and any(item is not None for item in lineage):
            raise ValueError("materialized artifact derivation must be complete or absent")
        for item in lineage:
            if item is not None:
                _require_handle(item, "artifact derivation reference")
        return self


class PhaseValueContentRecord(_ClosedModel):
    handle: PhaseValueHandle
    runtime_profile: RuntimeProfileHandle
    descriptor: PhaseSlotDescriptor
    value: Any
    keyed_content_commitment: str
    first_seen_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_scalar(self) -> "PhaseValueContentRecord":
        actual = _scalar_type(self.value)
        if actual != self.handle.scalar_type:
            raise ValueError("factor scalar type does not match its handle")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("factor scalar must be finite")
        assert_bank_safe_public_value(self.value)
        return self


class PhaseValueAttestationRecord(_ClosedModel):
    handle: ValueAttestationHandle
    value: PhaseValueHandle
    source_manifest_sha256: str
    split: SourceSplit
    source_artifact_id: str | None = None
    operation_seal_id: str | None = None
    created_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_provenance_owner(self) -> "PhaseValueAttestationRecord":
        if (self.source_artifact_id is None) == (self.operation_seal_id is None):
            raise ValueError(
                "value attestation requires exactly one artifact or generation owner"
            )
        for item in (self.source_artifact_id, self.operation_seal_id):
            if item is not None:
                _require_handle(item, "value attestation provenance owner")
        return self


class PhaseFactorContentRecord(_ClosedModel):
    handle: FactorContentHandle
    runtime_profile: RuntimeProfileHandle
    namespace: ExecutionNamespace
    descriptor: PhaseSlotDescriptor
    value: PhaseValueHandle
    factor_content_commitment: str


class PhaseGenerationTerminalV1(_ClosedModel):
    """Answer-free host terminal for one already-fenced generated action.

    The registry never accepts a raw prompt, model response, expected answer,
    score, or ground truth.  It persists only closed request/lease/action
    joins, bounded usage, and commitments.  The parsed scalar is validated
    separately against the typed Phase slot and stored by the existing value
    registry, never copied into this terminal.
    """

    terminal_version: Literal["sft_phase_generation_terminal_v1"] = (
        "sft_phase_generation_terminal_v1"
    )
    terminal_id: str
    action_transaction_id: str
    action_intent_sha256: str
    branch: GeneratedBranch
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    generation_request_id: str
    generation_request_sha256: str
    generation_lease_id: str
    generation_lease_sha256: str
    runner_lease_token_sha256: str
    fencing_generation: Literal[1] = 1
    generation_lease_started_sequence: int = Field(ge=1)
    model_name: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    runtime_version: str
    budget: ExecutionBudget
    budget_sha256: str
    usage: ExecutionUsage
    generated_scalar_sha256: str
    response_envelope_sha256: str
    terminal_event_id: str
    terminal_event_sequence: int = Field(ge=1)
    verifier_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_terminal(self) -> "PhaseGenerationTerminalV1":
        for name in (
            "terminal_id",
            "action_transaction_id",
            "generation_request_id",
            "generation_lease_id",
            "runtime_version",
            "terminal_event_id",
            "verifier_epoch",
        ):
            if not _ID_RE.fullmatch(str(getattr(self, name))):
                raise ValueError(f"{name} must be an opaque host identifier")
        for name in (
            "action_intent_sha256",
            "generation_request_sha256",
            "generation_lease_sha256",
            "runner_lease_token_sha256",
            "budget_sha256",
            "generated_scalar_sha256",
            "response_envelope_sha256",
            "attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.budget_sha256 != self.budget.digest:
            raise ValueError("generation terminal budget commitment is not reproducible")
        if self.usage.model_calls != 1:
            raise ValueError("generation terminal must attest exactly one model call")
        if not self.usage.within(self.budget):
            raise ValueError("generation terminal usage exceeds its sealed budget")
        if self.terminal_event_sequence <= self.generation_lease_started_sequence:
            raise ValueError("generation terminal must follow its persisted lease start")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class PhaseBranchReceiptBody(_ClosedModel):
    """Host-attested, closure-bound choice of one scientific branch."""

    branch: Branch
    source_artifact: PhaseArtifactHandle
    runtime_profile: RuntimeProfileHandle
    descriptor: PhaseSlotDescriptor
    source_factor: FactorContentHandle
    retrieved_target_factor: FactorContentHandle | None = None
    retrieved_target_attestation: ValueAttestationHandle | None = None
    mutation_parent_factor: FactorContentHandle | None = None
    dependency_factor_ids: tuple[str, ...] = ()
    source_manifest_sha256: str
    input_root_commitments: tuple[str, ...]
    provenance_closure_sha256: str
    action_transaction_id: str | None = None
    action_intent_sha256: str | None = None
    generation_terminal: PhaseGenerationTerminalV1 | None = None
    producer_epoch: str
    attestation_sha256: str

    @model_validator(mode="after")
    def validate_branch_body(self) -> "PhaseBranchReceiptBody":
        _require_sha(self.source_manifest_sha256, "source_manifest_sha256")
        _require_sha(self.provenance_closure_sha256, "provenance_closure_sha256")
        _require_sha(self.attestation_sha256, "attestation_sha256")
        if not _ID_RE.fullmatch(self.producer_epoch):
            raise ValueError("producer_epoch must be an opaque host identifier")
        if (self.action_transaction_id is None) != (
            self.action_intent_sha256 is None
        ):
            raise ValueError(
                "branch action transaction id and intent digest are inseparable"
            )
        if self.action_transaction_id is not None:
            if not _ID_RE.fullmatch(self.action_transaction_id):
                raise ValueError("action_transaction_id must be an opaque identifier")
            assert self.action_intent_sha256 is not None
            _require_sha(self.action_intent_sha256, "action_intent_sha256")
            if self.action_intent_sha256 not in self.input_root_commitments:
                raise ValueError("action intent must be in its input-root closure")
        if len(self.dependency_factor_ids) != len(set(self.dependency_factor_ids)):
            raise ValueError("branch dependency factors must be unique")
        for factor_id in self.dependency_factor_ids:
            _require_handle(factor_id, "dependency_factor_id")
        if not self.input_root_commitments or self.input_root_commitments != tuple(
            sorted(set(self.input_root_commitments))
        ):
            raise ValueError("branch input-root closure must be non-empty and canonical")
        for root in self.input_root_commitments:
            _require_sha(root, "input_root_commitment")
        if self.branch == "reuse":
            if (
                self.retrieved_target_factor is None
                or self.retrieved_target_attestation is None
                or self.mutation_parent_factor is not None
            ):
                raise ValueError("reuse receipt requires only a retrieved target")
            if self.dependency_factor_ids != (self.retrieved_target_factor.handle_id,):
                raise ValueError("reuse closure must name exactly its selected target")
            if self.generation_terminal is not None:
                raise ValueError("reuse receipt cannot carry a generation terminal")
        elif self.branch == "mutate":
            if (
                self.mutation_parent_factor is None
                or self.retrieved_target_factor is not None
                or self.retrieved_target_attestation is not None
            ):
                raise ValueError("mutate receipt requires only its exact parent")
            if self.dependency_factor_ids != (self.mutation_parent_factor.handle_id,):
                raise ValueError("mutate closure must name exactly its parent")
        elif (
            self.retrieved_target_factor is not None
            or self.retrieved_target_attestation is not None
            or self.mutation_parent_factor is not None
        ):
            raise ValueError("fresh receipt cannot carry a Bank factor dependency")
        elif self.dependency_factor_ids:
            raise ValueError("fresh receipt must have an empty Bank dependency closure")
        if self.branch in {"mutate", "fresh"}:
            if self.action_transaction_id is None:
                if self.generation_terminal is not None:
                    raise ValueError(
                        "non-action generation cannot carry an action terminal"
                    )
            else:
                terminal = self.generation_terminal
                if terminal is None:
                    raise ValueError(
                        "action-bound generated receipt requires its exact terminal"
                    )
                assert self.action_intent_sha256 is not None
                if not (
                    terminal.branch == self.branch
                    and terminal.action_transaction_id == self.action_transaction_id
                    and terminal.action_intent_sha256 == self.action_intent_sha256
                ):
                    raise ValueError(
                        "generation terminal differs from its action/branch intent"
                    )
                terminal_roots = {
                    terminal.generation_request_sha256,
                    terminal.generation_lease_sha256,
                    terminal.digest,
                }
                if not terminal_roots.issubset(self.input_root_commitments):
                    raise ValueError(
                        "generated action input closure omits terminal commitments"
                    )
        return self


class PhaseBranchReceiptRecord(_ClosedModel):
    handle: BranchReceiptHandle
    body: PhaseBranchReceiptBody
    created_sequence: int = Field(ge=1)
    expiry_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_expiry(self) -> "PhaseBranchReceiptRecord":
        if self.expiry_sequence < self.created_sequence:
            raise ValueError("branch receipt expiry precedes creation")
        return self


class PhaseOperationSealRecord(_ClosedModel):
    handle: OperationSealHandle
    branch_receipt: BranchReceiptHandle
    branch: Branch
    source_artifact: PhaseArtifactHandle
    descriptor: PhaseSlotDescriptor
    source_factor: FactorContentHandle
    retrieved_target_factor: FactorContentHandle | None = None
    retrieved_target_attestation: ValueAttestationHandle | None = None
    mutation_parent_factor: FactorContentHandle | None = None
    sequence_at_seal: int = Field(ge=1)
    nonce_commitment: str

    @model_validator(mode="after")
    def validate_branch_shape(self) -> "PhaseOperationSealRecord":
        if self.branch == "reuse":
            if (
                self.retrieved_target_factor is None
                or self.retrieved_target_attestation is None
            ):
                raise ValueError("reuse requires a sealed target and provenance owner")
            if self.mutation_parent_factor is not None:
                raise ValueError("reuse cannot carry generation dependencies")
        elif self.branch == "mutate":
            if self.mutation_parent_factor is None:
                raise ValueError("mutate requires its attested parent factor")
            if (
                self.retrieved_target_factor is not None
                or self.retrieved_target_attestation is not None
            ):
                raise ValueError("mutate cannot carry a retrieved target")
        else:
            if any(
                item is not None
                for item in (
                    self.retrieved_target_factor,
                    self.retrieved_target_attestation,
                    self.mutation_parent_factor,
                )
            ):
                raise ValueError("fresh cannot carry Bank factor dependencies")
        _require_sha(self.nonce_commitment, "nonce_commitment")
        return self


class ActivationRequirement(_ClosedModel):
    arm: Literal["source", "target"]
    factor_content_id: str
    artifact_id: str
    runtime_profile_id: str
    mode: Literal["image_loaded", "trusted_trace_event"]
    activation_kind: Literal[
        "execution_image_load", "phase_step_executed", "submission_event"
    ]

    @model_validator(mode="after")
    def validate_requirement(self) -> "ActivationRequirement":
        for name in ("factor_content_id", "artifact_id", "runtime_profile_id"):
            _require_handle(str(getattr(self, name)), name)
        if (self.mode == "image_loaded") != (
            self.activation_kind == "execution_image_load"
        ):
            raise ValueError("activation mode must match its host-observable event kind")
        return self


class PhaseMaterializationEventRecord(_ClosedModel):
    handle: MaterializationEventHandle
    operation_seal: OperationSealHandle
    source_artifact: PhaseArtifactHandle
    target_artifact: PhaseArtifactHandle | None
    source_factor: FactorContentHandle
    target_factor: FactorContentHandle | None
    target_attestation: ValueAttestationHandle
    status: Literal[
        "verified_delta",
        "same_value_noop",
        "operational_noop",
        "duplicate_existing",
    ]
    reason_code: str
    created_sequence: int = Field(ge=1)


def phase_materialization_event_sha256_v1(
    event: PhaseMaterializationEventRecord,
) -> str:
    """Public commitment for one fully revalidated materialization terminal.

    The explicit domain/version prevents this cross-store terminal from being
    confused with a naked model digest or another record's canonical hash.
    Registry methods resolve the record authority before callers receive it;
    this pure helper revalidates the closed shape before committing it.
    """

    checked = PhaseMaterializationEventRecord.model_validate(
        event.model_dump(mode="python")
    )
    return _sha256(
        {
            "digest_version": PHASE_MATERIALIZATION_EVENT_DIGEST_VERSION,
            "event": checked,
        }
    )


class PhaseMaterializationProofRecord(_ClosedModel):
    handle: PhaseBindingProofHandle
    event: MaterializationEventHandle
    operation_seal: OperationSealHandle
    branch: Branch
    namespace: ExecutionNamespace
    runtime_profile: RuntimeProfileHandle
    source_manifest_sha256: str
    source_artifact: PhaseArtifactHandle
    target_artifact: PhaseArtifactHandle
    descriptor: PhaseSlotDescriptor
    source_value: PhaseValueHandle
    target_value: PhaseValueHandle
    source_factor: FactorContentHandle
    target_factor: FactorContentHandle
    masked_background_commitment: str
    source_execution_image_commitment: str
    target_execution_image_commitment: str
    source_activation: ActivationRequirement
    target_activation: ActivationRequirement


class PhaseExtractedFactor(_ClosedModel):
    descriptor: PhaseSlotDescriptor
    value: PhaseValueHandle
    attestation: ValueAttestationHandle
    factor: FactorContentHandle


class NoOpMaterialization(_ClosedModel):
    event: MaterializationEventHandle
    reason: Literal["same_value", "same_execution_image", "duplicate_existing"]


class PhaseArtifactRegistryState(_ClosedModel):
    schema_version: Literal[PHASE_ARTIFACT_REGISTRY_VERSION] = (
        PHASE_ARTIFACT_REGISTRY_VERSION
    )
    sequence: int = Field(default=0, ge=0)
    capacity: RegistryCapacity = Field(default_factory=RegistryCapacity)
    manifests: tuple[SourceManifest, ...] = ()
    profiles: tuple[PhaseRuntimeProfileRecord, ...] = ()
    artifacts: tuple[PhaseProgramArtifactRecord, ...] = ()
    values: tuple[PhaseValueContentRecord, ...] = ()
    attestations: tuple[PhaseValueAttestationRecord, ...] = ()
    factors: tuple[PhaseFactorContentRecord, ...] = ()
    branch_receipts: tuple[PhaseBranchReceiptRecord, ...] = ()
    seals: tuple[PhaseOperationSealRecord, ...] = ()
    events: tuple[PhaseMaterializationEventRecord, ...] = ()
    proofs: tuple[PhaseMaterializationProofRecord, ...] = ()


class _IngressCapability:
    __slots__ = ("_registry_token", "manifest_sha256")

    def __init__(self, registry_token: object, manifest_sha256: str) -> None:
        self._registry_token = registry_token
        self.manifest_sha256 = manifest_sha256


class VerifiedPhaseBinding:
    """Ephemeral proof capability; callers cannot construct a valid instance."""

    __slots__ = ("_registry_token", "proof")

    def __init__(self, registry_token: object, proof: PhaseMaterializationProofRecord):
        self._registry_token = registry_token
        self.proof = proof


def _record_body(record: BaseModel) -> dict[str, Any]:
    return record.model_dump(mode="json", exclude={"handle"})


def _program_schema_commitment() -> str:
    return _sha256(
        {
            "format": "phase_program_v1",
            "mutable": {
                "selected_primary": "bounded_int",
                "instruction": ["null", "string<=500"],
                "send_mode": ["full_state", "delta_or_no_send"],
                "hub": "0<=int<n_agents",
                "pattern": "phase-kind enum",
                "max_rounds": "1..64",
                "stop_when": [
                    "fixed_rounds",
                    "sink_full_information",
                    "all_agents_full_information",
                ],
            },
            "locked": ["format", "information_goal", "phase.kind", "containers"],
        }
    )


_PROGRAM_SCHEMA_COMMITMENT = _program_schema_commitment()


def phase_mutable_factor_paths_v3(
    program: PhaseProgram | Mapping[str, Any],
) -> tuple[str, ...]:
    """Enumerate the complete carrier-owned mutable scalar domain.

    This is intentionally a PhaseProgram-specific allowlist, not a generic
    JSON walker.  The caller cannot omit or reorder fields: profile-v3 full
    factorization always consumes this exact tuple and separately commits the
    remaining structural skeleton.
    """

    checked = _validated_program(program)
    paths = ["/selected_primary"]
    for index, phase in enumerate(checked.phases):
        prefix = f"/phases/{index}"
        paths.extend((f"{prefix}/instruction", f"{prefix}/send_mode"))
        if phase.kind in {"gather", "broadcast"}:
            paths.extend((f"{prefix}/hub", f"{prefix}/pattern"))
        else:
            paths.extend(
                (
                    f"{prefix}/pattern",
                    f"{prefix}/max_rounds",
                    f"{prefix}/stop_when",
                )
            )
    if len(paths) != len(set(paths)):
        raise RuntimeError("canonical Phase factor enumeration contains duplicates")
    return tuple(paths)


def _descriptor(program: PhaseProgram, profile: PhaseRuntimeProfileRecord, path: str) -> PhaseSlotDescriptor:
    tokens = _decode_pointer(path)
    phase_kind: str = "program"
    phase_index: int | None = None
    enum_values: tuple[str, ...] = ()
    int_min: int | None = None
    int_max: int | None = None
    max_length: int | None = None
    activation: Literal["execution_image_load", "phase_step_executed", "submission_event"]

    if tokens == ["selected_primary"]:
        field_name = "selected_primary"
        allowed: tuple[ScalarType, ...] = ("int",)
        int_min, int_max = 0, profile.namespace.n_agents - 1
        activation = "submission_event"
    elif len(tokens) == 3 and tokens[0] == "phases" and tokens[1].isdigit():
        phase_index = int(tokens[1])
        if phase_index >= len(program.phases):
            raise ValueError("phase factor locator index is out of range")
        phase = program.phases[phase_index]
        phase_kind = phase.kind
        field_name = tokens[2]
        if field_name == "instruction":
            allowed = ("null", "string")
            max_length = 500
            activation = "phase_step_executed"
        elif field_name == "send_mode":
            allowed = ("string",)
            enum_values = ("full_state", "delta_or_no_send")
            activation = "phase_step_executed"
        elif field_name == "hub" and phase_kind in {"gather", "broadcast"}:
            allowed = ("int",)
            int_min, int_max = 0, profile.namespace.n_agents - 1
            activation = "execution_image_load"
        elif field_name == "pattern":
            allowed = ("string",)
            patterns = {
                "gather": ("star", "tree"),
                "broadcast": ("star", "tree"),
                "pairwise_exchange": ("ring", "bidirectional_ring", "rotating"),
                "consensus": ("all_to_all", "rotating"),
            }
            enum_values = patterns[phase_kind]
            activation = "execution_image_load"
        elif field_name == "max_rounds" and phase_kind in {
            "pairwise_exchange",
            "consensus",
        }:
            allowed = ("int",)
            int_min, int_max = 1, 64
            activation = "execution_image_load"
        elif field_name == "stop_when" and phase_kind in {
            "pairwise_exchange",
            "consensus",
        }:
            allowed = ("string",)
            enum_values = (
                "fixed_rounds",
                "sink_full_information",
                "all_agents_full_information",
            )
            activation = "execution_image_load"
        else:
            raise ValueError("PhaseProgram field is structural or not allowlisted")
    else:
        raise ValueError("PhaseProgram field is structural or not allowlisted")

    locator = FactorLocator(
        surface="phase_field",
        path=path,
        locator_version=profile.binder_version,
    )
    schema_body = {
        "program_schema": _PROGRAM_SCHEMA_COMMITMENT,
        "locator": locator,
        "allowed": allowed,
        "phase_kind": phase_kind,
        "phase_index": phase_index,
        "field": field_name,
        "activation": activation,
        "enum": enum_values,
        "int_min": int_min,
        "int_max": int_max,
        "max_length": max_length,
    }
    return PhaseSlotDescriptor(
        locator=locator,
        program_schema_commitment=_PROGRAM_SCHEMA_COMMITMENT,
        slot_schema_commitment=_sha256(schema_body),
        allowed_scalar_types=allowed,
        phase_kind=phase_kind,
        phase_index=phase_index,
        field_name=field_name,
        activation_kind=activation,
        enum_values=enum_values,
        int_min=int_min,
        int_max=int_max,
        max_length=max_length,
    )


def _validate_scalar(value: Any, descriptor: PhaseSlotDescriptor) -> ScalarType:
    actual = _scalar_type(value)
    if actual not in descriptor.allowed_scalar_types:
        raise ValueError("factor scalar type does not match the slot schema")
    if descriptor.enum_values and value not in descriptor.enum_values:
        raise ValueError("factor scalar is outside the slot enum")
    if actual == "int":
        if descriptor.int_min is not None and value < descriptor.int_min:
            raise ValueError("factor integer is below the slot bound")
        if descriptor.int_max is not None and value > descriptor.int_max:
            raise ValueError("factor integer is above the slot bound")
    if actual == "string" and descriptor.max_length is not None:
        if len(value) > descriptor.max_length:
            raise ValueError("factor string exceeds the slot bound")
    assert_bank_safe_public_value(value)
    return actual


def _build_execution_image(
    program: PhaseProgram,
    compiled: CompiledPhaseProgram,
    profile_id: str,
) -> PhaseExecutionImage:
    return PhaseExecutionImage(
        runtime_profile_id=profile_id,
        selected_primary=compiled.selected_primary,
        information_goal=program.information_goal,
        state_retention=program.state_retention,
        allow_no_send=program.allow_no_send,
        enable_step_instructions=True,
        steps=tuple(
            PhaseExecutionStepImage(
                step_index=index,
                phase_index=step.phase_index,
                phase_kind=step.phase_kind,
                transmissions=tuple(tuple(edge) for edge in step.transmissions),
                operator=f"phase:{step.phase_kind}",
                instruction=step.instruction,
            )
            for index, step in enumerate(compiled.steps)
        ),
    )


class PhaseArtifactRegistry:
    """Host-owned, bounded, HMAC-authenticated PhaseProgram registry."""

    def __init__(
        self,
        *,
        registry_key: bytes,
        manifests: Sequence[SourceManifest] = (),
        state: PhaseArtifactRegistryState | None = None,
        manifest_verifier: Callable[[SourceManifest], bool] | None,
        branch_receipt_verifier: Callable[[PhaseBranchReceiptBody], bool] | None = None,
        capacity: RegistryCapacity | None = None,
        _restore_token: object | None = None,
    ) -> None:
        if not isinstance(registry_key, bytes) or len(registry_key) < 32:
            raise ValueError("registry_key must contain at least 32 bytes")
        if state is not None and manifests:
            raise ValueError("supply manifests or persisted state, not both")
        if state is not None and capacity is not None:
            raise ValueError("persisted state owns its capacity policy")
        if state is not None and _restore_token is not _AUTHENTICATED_RESTORE_TOKEN:
            # Check duplicate collapse first so malformed recovery input still
            # receives a precise diagnosis, then reject detached state clones.
            self._assert_unique_state_records(state)
            raise ValueError(
                "detached Phase registry state is not authoritative; use authenticated load"
            )
        self._key = bytes(registry_key)
        self._mutation_lock = threading.RLock()
        self._token = object()
        self._manifest_verifier = manifest_verifier
        self._branch_receipt_verifier = branch_receipt_verifier
        if state is None:
            checked = tuple(
                SourceManifest.model_validate(item.model_dump(mode="python"))
                for item in manifests
            )
            state = PhaseArtifactRegistryState(
                manifests=checked,
                capacity=capacity or RegistryCapacity(),
            )
        else:
            state = PhaseArtifactRegistryState.model_validate(
                state.model_dump(mode="python")
            )
        self._assert_unique_state_records(state)
        self._sequence = state.sequence
        self.capacity = state.capacity
        self._manifests = {item.manifest_sha256: item for item in state.manifests}
        self._profiles = {item.handle.handle_id: item for item in state.profiles}
        self._artifacts = {item.handle.handle_id: item for item in state.artifacts}
        self._values = {item.handle.handle_id: item for item in state.values}
        self._attestations = {
            item.handle.handle_id: item for item in state.attestations
        }
        self._factors = {item.handle.handle_id: item for item in state.factors}
        self._branch_receipts = {
            item.handle.handle_id: item for item in state.branch_receipts
        }
        self._seals = {item.handle.handle_id: item for item in state.seals}
        self._events = {item.handle.handle_id: item for item in state.events}
        self._proofs = {item.handle.handle_id: item for item in state.proofs}
        self._transaction_depth = 0
        self._verification_cache: dict[tuple[str, str], Any] | None = None
        self._verification_visiting: set[tuple[str, str]] | None = None
        self._persisted_path: Path | None = None
        self._persisted_envelope_sha256: str | None = None
        self._verify_state()

    @staticmethod
    def _assert_unique_state_records(state: PhaseArtifactRegistryState) -> None:
        collections = (
            ("manifest", [item.manifest_sha256 for item in state.manifests]),
            ("profile", [item.handle.handle_id for item in state.profiles]),
            ("artifact", [item.handle.handle_id for item in state.artifacts]),
            ("value", [item.handle.handle_id for item in state.values]),
            ("attestation", [item.handle.handle_id for item in state.attestations]),
            ("factor", [item.handle.handle_id for item in state.factors]),
            (
                "branch receipt",
                [item.handle.handle_id for item in state.branch_receipts],
            ),
            ("seal", [item.handle.handle_id for item in state.seals]),
            ("event", [item.handle.handle_id for item in state.events]),
            ("proof", [item.handle.handle_id for item in state.proofs]),
        )
        for label, identifiers in collections:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate persisted Phase registry {label} identifier")

    @contextmanager
    def _atomic_update(self):
        """Stage nested record writes and publish them as one verified update."""

        # The lock covers owner selection, snapshot, every nested mutation,
        # verification, publication, and rollback.  Locking only the depth
        # counter would still let another thread masquerade as a nested call.
        with self._mutation_lock:
            outermost = self._transaction_depth == 0
            snapshot: tuple[Any, ...] | None = None
            if outermost:
                snapshot = (
                    self._sequence,
                    dict(self._profiles),
                    dict(self._artifacts),
                    dict(self._values),
                    dict(self._attestations),
                    dict(self._factors),
                    dict(self._branch_receipts),
                    dict(self._seals),
                    dict(self._events),
                    dict(self._proofs),
                    self._persisted_path,
                    self._persisted_envelope_sha256,
                )
            self._transaction_depth += 1
            try:
                yield
                if outermost:
                    self._verify_state()
                    if self._persisted_path is not None:
                        self._save_owned_state(self._persisted_path)
            except Exception:
                if outermost and snapshot is not None:
                    (
                        self._sequence,
                        self._profiles,
                        self._artifacts,
                        self._values,
                        self._attestations,
                        self._factors,
                        self._branch_receipts,
                        self._seals,
                        self._events,
                        self._proofs,
                        self._persisted_path,
                        self._persisted_envelope_sha256,
                    ) = snapshot
                raise
            finally:
                self._transaction_depth -= 1

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _verify_manifest(self, manifest: SourceManifest) -> None:
        if self._manifest_verifier is None:
            raise RuntimeError("no trusted PUBLIC/TRAIN manifest verifier is installed")
        try:
            valid = bool(self._manifest_verifier(manifest))
        except Exception as exc:
            raise RuntimeError("source manifest verification failed") from exc
        if not valid:
            raise ValueError("source manifest is not authorized for Bank ingestion")

    def issue_ingress(self, manifest_sha256: str) -> _IngressCapability:
        manifest = self._manifests.get(manifest_sha256)
        if manifest is None:
            raise ValueError("source manifest is not registered")
        self._verify_manifest(manifest)
        return _IngressCapability(self._token, manifest_sha256)

    def _manifest_from_ingress(self, ingress: _IngressCapability) -> SourceManifest:
        if not isinstance(ingress, _IngressCapability) or ingress._registry_token is not self._token:
            raise ValueError("ingress capability is not owned by this registry")
        manifest = self._manifests.get(ingress.manifest_sha256)
        if manifest is None:
            raise ValueError("ingress capability names an unknown manifest")
        self._verify_manifest(manifest)
        return manifest

    def _new_handle(
        self,
        handle_type: type[RegistryHandle],
        *,
        prefix: str,
        kind: str,
        identity: Any,
        body: Any,
        **extra: Any,
    ) -> RegistryHandle:
        return handle_type(
            kind=kind,
            handle_id=_handle_id(self._key, prefix, identity),
            record_mac=_mac(self._key, "record:" + kind, body),
            **extra,
        )

    def _verify_record(
        self,
        record: BaseModel,
        *,
        prefix: str,
        kind: str,
        identity: Any,
    ) -> None:
        handle = record.handle
        expected_id = _handle_id(self._key, prefix, identity)
        expected_mac = _mac(self._key, "record:" + kind, _record_body(record))
        if handle.kind != kind or not hmac.compare_digest(handle.handle_id, expected_id):
            raise ValueError(f"{kind} handle identity mismatch")
        if not hmac.compare_digest(handle.record_mac, expected_mac):
            raise ValueError(f"{kind} record MAC mismatch")

    def _check_capacity(self, collection: Mapping[str, Any], maximum: int, label: str) -> None:
        if len(collection) >= maximum:
            raise RuntimeError(f"Phase artifact registry {label} capacity is exhausted")

    def _artifact_lineage_depth(
        self,
        artifact: PhaseProgramArtifactRecord,
    ) -> int:
        """Return canonical parent depth with a bounded, non-recursive walk."""

        cursor = artifact
        seen = {cursor.handle.handle_id}
        depth = 0
        while cursor.parent_artifact_id is not None:
            depth += 1
            if depth > self.capacity.max_lineage_depth:
                raise ValueError(
                    "PhaseProgram artifact lineage exceeds its hard depth cap"
                )
            parent_id = cursor.parent_artifact_id
            if parent_id in seen:
                raise ValueError("PhaseProgram artifact lineage contains a cycle")
            seen.add(parent_id)
            parent = self._artifacts.get(parent_id)
            if parent is None:
                raise ValueError("materialized artifact parent is missing")
            cursor = parent
        return depth

    def _assert_branch_lineage_preflight(
        self,
        *,
        branch: Branch,
        source: PhaseProgramArtifactRecord,
        descriptor: PhaseSlotDescriptor,
        retrieved_target: PhaseFactorContentRecord | None,
        decision_sequence: int,
    ) -> None:
        """Reject a novel child beyond the cap before branch state is written.

        Generated targets do not exist when ``mutate`` or ``fresh`` is sealed,
        so those branches conservatively stop at the cap.  ``reuse`` already
        names its exact typed value: it may continue only when the replacement
        is an operational no-op or resolves to a complete artifact that
        existed before the branch decision.  This is a content-addressed host
        check, not a rebase or an LLM/oracle decision.
        """

        if self._artifact_lineage_depth(source) < self.capacity.max_lineage_depth:
            return
        if branch != "reuse":
            raise ValueError(
                "branch lineage depth preflight would exceed the hard cap"
            )
        if retrieved_target is None:
            raise ValueError("reuse lineage preflight requires its exact target")
        profile = self._resolve_profile(source.runtime_profile)
        expected_descriptor = _descriptor(
            source.program,
            profile,
            descriptor.locator.path,
        )
        if (
            descriptor != expected_descriptor
            or retrieved_target.runtime_profile != profile.handle
            or retrieved_target.descriptor != descriptor
        ):
            raise ValueError("reuse lineage preflight crosses its typed slot/profile")
        target_value = self._resolve_value(retrieved_target.value)
        source_value = _read_pointer(
            source.program.model_dump(mode="json"),
            descriptor.locator.path,
        )
        if source_value == target_value.value and type(source_value) is type(
            target_value.value
        ):
            raise ValueError("reuse target must differ from the source factor")
        raw = _replace_pointer(
            source.program.model_dump(mode="json"),
            descriptor.locator.path,
            target_value.value,
        )
        target_program = _validated_program(raw)
        compiled = compile_phase_program(
            target_program,
            n_agents=profile.namespace.n_agents,
            limits=profile.limits,
        )
        target_image = _build_execution_image(
            target_program,
            compiled,
            profile.handle.handle_id,
        )
        if target_image == source.execution_image:
            return
        identity = {
            "profile": source.runtime_profile.handle_id,
            "manifest": source.source_manifest_sha256,
            "program": target_program,
        }
        target_id = _handle_id(self._key, "pa", identity)
        existing = self._artifacts.get(target_id)
        if existing is None or existing.created_sequence > decision_sequence:
            raise ValueError(
                "reuse lineage depth preflight would create an over-cap artifact"
            )
        self._resolve_artifact(existing.handle)

    @_atomic_registry_update
    def register_runtime_profile(
        self,
        *,
        namespace: ExecutionNamespace,
        limits: PhaseProgramLimits | Mapping[str, Any],
    ) -> RuntimeProfileHandle:
        namespace = ExecutionNamespace.model_validate(namespace.model_dump(mode="python"))
        limits = _validated_limits(limits)
        if namespace.payload_format != "phase_program_skill_v1":
            raise ValueError("PhaseProgram profile requires phase_program_skill_v1")
        if namespace.planner_mode != "program_generate" or namespace.worker_contract != "not_applicable":
            raise ValueError("PhaseProgram profile crosses its planner/worker contract")
        if namespace.binder_version not in {
            PHASE_FACTOR_BINDER_VERSION,
            PHASE_FULL_FACTOR_BINDER_VERSION,
        }:
            raise ValueError("execution namespace names a different factor binder")
        if namespace.compiler_version != PHASE_PROGRAM_COMPILER_VERSION:
            raise ValueError("execution namespace names a different compiler")
        identity = {
            "namespace": namespace,
            "limits": limits,
            "binder": namespace.binder_version,
            "compiler": PHASE_PROGRAM_COMPILER_VERSION,
            "image": PHASE_EXECUTION_IMAGE_VERSION,
            "activation": PHASE_ACTIVATION_VERSION,
            "enable_step_instructions": True,
        }
        provisional_body = {
            "namespace": namespace,
            "limits": limits,
            "limits_commitment": _mac(self._key, "limits", limits),
            "binder_version": namespace.binder_version,
            "compiler_version": PHASE_PROGRAM_COMPILER_VERSION,
            "execution_image_version": PHASE_EXECUTION_IMAGE_VERSION,
            "activation_version": PHASE_ACTIVATION_VERSION,
            "enable_step_instructions": True,
        }
        handle = self._new_handle(
            RuntimeProfileHandle,
            prefix="rp",
            kind="runtime_profile",
            identity=identity,
            body=provisional_body,
        )
        record = PhaseRuntimeProfileRecord(handle=handle, **provisional_body)
        existing = self._profiles.get(handle.handle_id)
        if existing is not None:
            self._resolve_profile(handle)
            return existing.handle
        self._check_capacity(self._profiles, self.capacity.max_profiles, "profile")
        self._profiles[handle.handle_id] = record
        return handle

    @_atomic_registry_update
    def ingest_program(
        self,
        program: PhaseProgram | Mapping[str, Any],
        *,
        runtime_profile: RuntimeProfileHandle,
        ingress: _IngressCapability,
    ) -> PhaseArtifactHandle:
        profile = self._resolve_profile(runtime_profile)
        manifest = self._manifest_from_ingress(ingress)
        program = _validated_program(program)
        assert_bank_safe_public_value(program.model_dump(mode="json"))
        if program.information_goal != profile.namespace.information_goal:
            raise ValueError("program information_goal crosses the runtime profile")
        compiled = compile_phase_program(
            program,
            n_agents=profile.namespace.n_agents,
            limits=profile.limits,
        )
        image = _build_execution_image(program, compiled, profile.handle.handle_id)
        identity = {
            "profile": profile.handle.handle_id,
            "manifest": manifest.manifest_sha256,
            "program": program,
        }
        sequence = self._sequence + 1
        body = {
            "runtime_profile": profile.handle,
            "source_manifest_sha256": manifest.manifest_sha256,
            "split": manifest.split,
            "program": program,
            "program_commitment": _mac(self._key, "program", program),
            "execution_image": image,
            "execution_image_commitment": _mac(self._key, "execution-image", image),
            "parent_artifact_id": None,
            "derivation_operation_seal_id": None,
            "derivation_target_factor_id": None,
            "created_sequence": sequence,
        }
        handle = self._new_handle(
            PhaseArtifactHandle,
            prefix="pa",
            kind="phase_artifact",
            identity=identity,
            body=body,
        )
        existing = self._artifacts.get(handle.handle_id)
        if existing is not None:
            self._resolve_artifact(existing.handle)
            return existing.handle
        self._check_capacity(self._artifacts, self.capacity.max_artifacts, "artifact")
        body["created_sequence"] = self._next_sequence()
        # sequence is not content identity but is MAC-protected record metadata.
        handle = self._new_handle(
            PhaseArtifactHandle,
            prefix="pa",
            kind="phase_artifact",
            identity=identity,
            body=body,
        )
        record = PhaseProgramArtifactRecord(handle=handle, **body)
        self._artifacts[handle.handle_id] = record
        return handle

    @_atomic_registry_update
    def extract_factor(
        self,
        artifact: PhaseArtifactHandle,
        *,
        locator: str,
    ) -> PhaseExtractedFactor:
        artifact_record = self._resolve_artifact(artifact)
        profile = self._resolve_profile(artifact_record.runtime_profile)
        descriptor = _descriptor(artifact_record.program, profile, locator)
        value = _read_pointer(artifact_record.program.model_dump(mode="json"), locator)
        value_record = self._ensure_value(profile, descriptor, value)
        attestation = self._ensure_attestation(
            value_record,
            manifest_sha256=artifact_record.source_manifest_sha256,
            split=artifact_record.split,
            source_artifact_id=artifact_record.handle.handle_id,
            operation_seal_id=None,
        )
        factor = self._ensure_factor(profile, descriptor, value_record)
        return PhaseExtractedFactor(
            descriptor=descriptor,
            value=value_record.handle,
            attestation=attestation.handle,
            factor=factor.handle,
        )

    @_atomic_registry_update
    def extract_full_factorizations_v3(
        self,
        artifacts: Sequence[PhaseArtifactHandle],
    ) -> tuple[tuple[PhaseExtractedFactor, ...], ...]:
        """Atomically materialize complete full-v3 factor records.

        The exact artifact handles are caller inputs, but the scalar domain is
        not.  All values, artifact-owned attestations, and factor handles for
        all supplied artifacts are installed in one registry transaction, so
        capacity failure cannot leave a partial full-factor view.
        """

        handles = tuple(
            PhaseArtifactHandle.model_validate(item.model_dump(mode="python"))
            for item in artifacts
        )
        if not handles or len(handles) > 2 or len(set(item.handle_id for item in handles)) != len(handles):
            raise ValueError(
                "full Phase factorization requires one or two distinct artifacts"
            )
        result: list[tuple[PhaseExtractedFactor, ...]] = []
        for handle in handles:
            artifact_record = self._resolve_artifact(handle)
            profile = self._resolve_profile(artifact_record.runtime_profile)
            if profile.binder_version != PHASE_FULL_FACTOR_BINDER_VERSION:
                raise ValueError("full Phase factorization requires the v3 profile")
            extracted: list[PhaseExtractedFactor] = []
            for locator in phase_mutable_factor_paths_v3(artifact_record.program):
                descriptor = _descriptor(artifact_record.program, profile, locator)
                value = _read_pointer(
                    artifact_record.program.model_dump(mode="json"),
                    locator,
                )
                value_record = self._ensure_value(profile, descriptor, value)
                attestation = self._ensure_attestation(
                    value_record,
                    manifest_sha256=artifact_record.source_manifest_sha256,
                    split=artifact_record.split,
                    source_artifact_id=artifact_record.handle.handle_id,
                    operation_seal_id=None,
                )
                factor = self._ensure_factor(profile, descriptor, value_record)
                extracted.append(
                    PhaseExtractedFactor(
                        descriptor=descriptor,
                        value=value_record.handle,
                        attestation=attestation.handle,
                        factor=factor.handle,
                    )
                )
            result.append(tuple(extracted))
        return tuple(result)

    def _value_identity(
        self,
        profile: PhaseRuntimeProfileRecord,
        descriptor: PhaseSlotDescriptor,
        value: Any,
    ) -> dict[str, Any]:
        return {
            "namespace": profile.namespace.digest,
            "profile": profile.handle.handle_id,
            "slot_schema": descriptor.slot_schema_commitment,
            "locator": descriptor.locator,
            "scalar_type": _scalar_type(value),
            "value_commitment": _mac(self._key, "scalar", value),
        }

    def _ensure_value(
        self,
        profile: PhaseRuntimeProfileRecord,
        descriptor: PhaseSlotDescriptor,
        value: Any,
        *,
        require_new_after: int | None = None,
    ) -> PhaseValueContentRecord:
        scalar_type = _validate_scalar(value, descriptor)
        identity = self._value_identity(profile, descriptor, value)
        handle_id = _handle_id(self._key, "pv", identity)
        existing = self._values.get(handle_id)
        if existing is not None:
            self._resolve_value(existing.handle)
            if require_new_after is not None:
                raise ValueError("generated value already existed before the sealed operation")
            return existing
        self._check_capacity(self._values, self.capacity.max_values, "value")
        sequence = self._next_sequence()
        body = {
            "runtime_profile": profile.handle,
            "descriptor": descriptor,
            "value": value,
            "keyed_content_commitment": identity["value_commitment"],
            "first_seen_sequence": sequence,
        }
        handle = self._new_handle(
            PhaseValueHandle,
            prefix="pv",
            kind="phase_value",
            identity=identity,
            body=body,
            scalar_type=scalar_type,
            slot_schema_commitment=descriptor.slot_schema_commitment,
        )
        record = PhaseValueContentRecord(handle=handle, **body)
        if require_new_after is not None and record.first_seen_sequence <= require_new_after:
            raise RuntimeError("generated value did not occur after its operation seal")
        self._values[handle.handle_id] = record
        return record

    def _ensure_attestation(
        self,
        value: PhaseValueContentRecord,
        *,
        manifest_sha256: str,
        split: SourceSplit,
        source_artifact_id: str | None,
        operation_seal_id: str | None,
    ) -> PhaseValueAttestationRecord:
        identity = {
            "value": value.handle.handle_id,
            "manifest": manifest_sha256,
            "source_artifact": source_artifact_id,
            "operation_seal": operation_seal_id,
        }
        handle_id = _handle_id(self._key, "va", identity)
        existing = self._attestations.get(handle_id)
        if existing is not None:
            self._resolve_attestation(existing.handle)
            return existing
        self._check_capacity(
            self._attestations,
            self.capacity.max_attestations,
            "attestation",
        )
        body = {
            "value": value.handle,
            "source_manifest_sha256": manifest_sha256,
            "split": split,
            "source_artifact_id": source_artifact_id,
            "operation_seal_id": operation_seal_id,
            "created_sequence": self._next_sequence(),
        }
        handle = self._new_handle(
            ValueAttestationHandle,
            prefix="va",
            kind="value_attestation",
            identity=identity,
            body=body,
        )
        record = PhaseValueAttestationRecord(handle=handle, **body)
        self._attestations[handle.handle_id] = record
        return record

    def _ensure_factor(
        self,
        profile: PhaseRuntimeProfileRecord,
        descriptor: PhaseSlotDescriptor,
        value: PhaseValueContentRecord,
    ) -> PhaseFactorContentRecord:
        identity = {
            "namespace": profile.namespace.digest,
            "profile": profile.handle.handle_id,
            "locator": descriptor.locator,
            "slot_schema": descriptor.slot_schema_commitment,
            "value": value.handle.handle_id,
        }
        handle_id = _handle_id(self._key, "fc", identity)
        existing = self._factors.get(handle_id)
        if existing is not None:
            self._resolve_factor(existing.handle)
            return existing
        self._check_capacity(self._factors, self.capacity.max_factors, "factor")
        body = {
            "runtime_profile": profile.handle,
            "namespace": profile.namespace,
            "descriptor": descriptor,
            "value": value.handle,
            "factor_content_commitment": _mac(self._key, "factor-content", identity),
        }
        handle = self._new_handle(
            FactorContentHandle,
            prefix="fc",
            kind="factor_content",
            identity=identity,
            body=body,
        )
        record = PhaseFactorContentRecord(handle=handle, **body)
        self._factors[handle.handle_id] = record
        return record

    @_atomic_registry_update
    def register_branch_receipt(
        self,
        *,
        branch: Branch,
        source_artifact: PhaseArtifactHandle,
        locator: str,
        retrieved_target_factor: FactorContentHandle | None = None,
        mutation_parent_factor: FactorContentHandle | None = None,
        additional_input_root_commitments: Sequence[str] = (),
        action_transaction_id: str | None = None,
        action_intent_sha256: str | None = None,
        generation_terminal: PhaseGenerationTerminalV1 | None = None,
        producer_epoch: str,
        attestation_sha256: str,
        ttl_events: int = 64,
    ) -> BranchReceiptHandle:
        """Register one host-attested retrieval/generation decision.

        The trusted host verifier owns the complete model/retrieval input
        closure and must reject any TEST/private dependency before this method
        is called.  The scientific registry persists only its safe commitment.
        """

        if branch not in {"reuse", "mutate", "fresh"}:
            raise ValueError("branch must be reuse, mutate, or fresh")
        if (action_transaction_id is None) != (action_intent_sha256 is None):
            raise ValueError(
                "action transaction id and intent digest must be supplied together"
            )
        if action_transaction_id is not None:
            if not _ID_RE.fullmatch(action_transaction_id):
                raise ValueError("action_transaction_id must be an opaque identifier")
            assert action_intent_sha256 is not None
            _require_sha(action_intent_sha256, "action_intent_sha256")
        terminal = (
            PhaseGenerationTerminalV1.model_validate(
                generation_terminal.model_dump(mode="python")
            )
            if generation_terminal is not None
            else None
        )
        if branch == "reuse" and terminal is not None:
            raise ValueError("reuse receipt cannot carry a generation terminal")
        if branch in {"mutate", "fresh"} and action_transaction_id is not None:
            if terminal is None:
                raise ValueError(
                    "action-bound generated receipt requires its exact terminal"
                )
            assert action_intent_sha256 is not None
            if not (
                terminal.branch == branch
                and terminal.action_transaction_id == action_transaction_id
                and terminal.action_intent_sha256 == action_intent_sha256
            ):
                raise ValueError(
                    "generation terminal differs from its action/branch intent"
                )
        elif terminal is not None:
            raise ValueError("generation terminal requires an action-bound generated branch")
        if ttl_events < 1 or ttl_events > 4096:
            raise ValueError("branch receipt ttl is outside the bounded range")
        source = self._resolve_artifact(source_artifact)
        if terminal is not None and source.split != "TRAIN_UPDATE":
            raise ValueError("generated action source must be TRAIN_UPDATE")
        profile = self._resolve_profile(source.runtime_profile)
        descriptor = _descriptor(source.program, profile, locator)
        target_record = (
            self._resolve_factor(retrieved_target_factor)
            if retrieved_target_factor is not None
            else None
        )
        parent_record = (
            self._resolve_factor(mutation_parent_factor)
            if mutation_parent_factor is not None
            else None
        )
        if target_record is not None and target_record.descriptor != descriptor:
            raise ValueError("retrieved factor belongs to another typed slot")
        self._assert_branch_lineage_preflight(
            branch=branch,
            source=source,
            descriptor=descriptor,
            retrieved_target=target_record,
            decision_sequence=self._sequence,
        )
        # This nested call may create the source value/attestation/factor.  It
        # deliberately follows the no-write depth preflight above.
        extracted = self.extract_factor(source.handle, locator=locator)
        source_factor = self._resolve_factor(extracted.factor)
        if target_record is not None:
            if target_record.handle == source_factor.handle:
                raise ValueError("reuse target must differ from the source factor")
        if branch == "mutate" and (
            parent_record is None or parent_record.handle != source_factor.handle
        ):
            raise ValueError("mutation parent must be the exact source factor")
        dependencies = (
            (target_record.handle.handle_id,)
            if branch == "reuse" and target_record is not None
            else (
                (parent_record.handle.handle_id,)
                if branch == "mutate" and parent_record is not None
                else ()
            )
        )
        manifest = self._manifests[source.source_manifest_sha256]
        target_attestation: PhaseValueAttestationRecord | None = None
        if branch == "reuse":
            assert target_record is not None
            candidates = [
                self._resolve_attestation(item.handle)
                for item in self._attestations.values()
                if item.value == target_record.value
                and item.source_manifest_sha256 == source.source_manifest_sha256
                and item.created_sequence <= self._sequence
            ]
            if not candidates:
                raise ValueError("reuse target lacks an allowed provenance owner")
            target_attestation = min(
                candidates,
                key=lambda item: (item.created_sequence, item.handle.handle_id),
            )
        for root in additional_input_root_commitments:
            _require_sha(root, "additional_input_root_commitment")
        input_roots = tuple(
            sorted(
                {
                    manifest.source_catalog_sha256,
                    manifest.policy_sha256,
                    *additional_input_root_commitments,
                }
            )
        )
        provenance_closure_sha256 = _sha256(
            {
                "source_manifest": source.source_manifest_sha256,
                "input_roots": input_roots,
                "bank_dependencies": dependencies,
                "retrieved_target_attestation": (
                    target_attestation.handle.handle_id
                    if target_attestation is not None
                    else None
                ),
                "branch": branch,
                "source_artifact": source.handle.handle_id,
                "descriptor": extracted.descriptor,
                "action_transaction_id": action_transaction_id,
                "action_intent_sha256": action_intent_sha256,
                "generation_terminal_sha256": (
                    terminal.digest if terminal is not None else None
                ),
            }
        )
        body = PhaseBranchReceiptBody(
            branch=branch,
            source_artifact=source.handle,
            runtime_profile=source.runtime_profile,
            descriptor=extracted.descriptor,
            source_factor=source_factor.handle,
            retrieved_target_factor=target_record.handle if target_record else None,
            retrieved_target_attestation=(
                target_attestation.handle if target_attestation else None
            ),
            mutation_parent_factor=parent_record.handle if parent_record else None,
            dependency_factor_ids=dependencies,
            source_manifest_sha256=source.source_manifest_sha256,
            input_root_commitments=input_roots,
            provenance_closure_sha256=provenance_closure_sha256,
            action_transaction_id=action_transaction_id,
            action_intent_sha256=action_intent_sha256,
            generation_terminal=terminal,
            producer_epoch=producer_epoch,
            attestation_sha256=attestation_sha256,
        )
        if terminal is not None and any(
            existing.body.generation_terminal is not None
            and (
                existing.body.generation_terminal.terminal_id == terminal.terminal_id
                or existing.body.generation_terminal.attestation_sha256
                == terminal.attestation_sha256
                or existing.body.generation_terminal.generation_lease_id
                == terminal.generation_lease_id
            )
            for existing in self._branch_receipts.values()
        ):
            raise ValueError("generation terminal or lease has already been registered")
        if any(
            item.body.attestation_sha256 == body.attestation_sha256
            for item in self._branch_receipts.values()
        ):
            raise ValueError("branch receipt attestation has already been registered")
        if self._branch_receipt_verifier is None:
            raise RuntimeError("no trusted branch/provenance verifier is installed")
        try:
            verified = bool(self._branch_receipt_verifier(body))
        except Exception as exc:
            raise RuntimeError("trusted branch receipt verification failed") from exc
        if not verified:
            raise ValueError("trusted branch/provenance verifier rejected the receipt")
        self._check_capacity(
            self._branch_receipts,
            self.capacity.max_branch_receipts,
            "branch receipt",
        )
        sequence = self._next_sequence()
        identity = {
            "body": body,
            "sequence": sequence,
        }
        record_body = {
            "body": body,
            "created_sequence": sequence,
            "expiry_sequence": sequence + ttl_events,
        }
        handle = self._new_handle(
            BranchReceiptHandle,
            prefix="br",
            kind="branch_receipt",
            identity=identity,
            body=record_body,
        )
        record = PhaseBranchReceiptRecord(handle=handle, **record_body)
        self._branch_receipts[handle.handle_id] = record
        return handle

    @_atomic_registry_update
    def seal_operation(
        self,
        *,
        branch_receipt: BranchReceiptHandle,
    ) -> OperationSealHandle:
        receipt = self._resolve_branch_receipt(branch_receipt)
        if any(
            item.branch_receipt.handle_id == receipt.handle.handle_id
            for item in self._seals.values()
        ):
            raise ValueError("branch receipt has already been consumed")
        if self._sequence > receipt.expiry_sequence:
            raise ValueError("branch receipt has expired")
        body = receipt.body
        branch = body.branch
        source = self._resolve_artifact(body.source_artifact)
        source_factor = self._resolve_factor(body.source_factor)
        target_record = (
            self._resolve_factor(body.retrieved_target_factor)
            if body.retrieved_target_factor is not None
            else None
        )
        target_attestation = (
            self._resolve_attestation(body.retrieved_target_attestation)
            if body.retrieved_target_attestation is not None
            else None
        )
        parent_record = (
            self._resolve_factor(body.mutation_parent_factor)
            if body.mutation_parent_factor is not None
            else None
        )
        nonce = secrets.token_hex(32)
        sequence = self._next_sequence()
        identity = {
            "branch_receipt": receipt.handle.handle_id,
            "branch": branch,
            "source_artifact": source.handle.handle_id,
            "descriptor": body.descriptor,
            "source_factor": source_factor.handle.handle_id,
            "retrieved_target": target_record.handle.handle_id if target_record else None,
            "retrieved_target_attestation": (
                target_attestation.handle.handle_id
                if target_attestation is not None
                else None
            ),
            "mutation_parent": parent_record.handle.handle_id if parent_record else None,
            "sequence": sequence,
            "nonce": _mac(self._key, "nonce", nonce),
        }
        body = {
            "branch_receipt": receipt.handle,
            "branch": branch,
            "source_artifact": source.handle,
            "descriptor": receipt.body.descriptor,
            "source_factor": source_factor.handle,
            "retrieved_target_factor": target_record.handle if target_record else None,
            "retrieved_target_attestation": (
                target_attestation.handle if target_attestation else None
            ),
            "mutation_parent_factor": parent_record.handle if parent_record else None,
            "sequence_at_seal": sequence,
            "nonce_commitment": identity["nonce"],
        }
        handle = self._new_handle(
            OperationSealHandle,
            prefix="os",
            kind="operation_seal",
            identity=identity,
            body=body,
        )
        record = PhaseOperationSealRecord(handle=handle, **body)
        self._check_capacity(self._seals, self.capacity.max_seals, "seal")
        self._seals[handle.handle_id] = record
        return handle

    @_atomic_registry_update
    def register_generated_value(
        self,
        value: Any,
        *,
        operation_seal: OperationSealHandle,
        ingress: _IngressCapability,
    ) -> PhaseExtractedFactor:
        seal = self._resolve_seal(operation_seal)
        if seal.branch == "reuse":
            raise ValueError("reuse cannot register generated factor content")
        if any(item.operation_seal_id == seal.handle.handle_id for item in self._attestations.values()):
            raise ValueError("operation seal already owns a generated value")
        source = self._resolve_artifact(seal.source_artifact)
        manifest = self._manifest_from_ingress(ingress)
        if manifest.manifest_sha256 != source.source_manifest_sha256:
            raise ValueError("generated value provenance crosses the source manifest")
        profile = self._resolve_profile(source.runtime_profile)
        value_record = self._ensure_value(
            profile,
            seal.descriptor,
            value,
            require_new_after=seal.sequence_at_seal,
        )
        attestation = self._ensure_attestation(
            value_record,
            manifest_sha256=manifest.manifest_sha256,
            split=manifest.split,
            source_artifact_id=None,
            operation_seal_id=seal.handle.handle_id,
        )
        factor = self._ensure_factor(profile, seal.descriptor, value_record)
        return PhaseExtractedFactor(
            descriptor=seal.descriptor,
            value=value_record.handle,
            attestation=attestation.handle,
            factor=factor.handle,
        )

    def _register_action_generated_value(
        self,
        value: Any,
        *,
        operation_seal: OperationSealHandle,
        ingress: _IngressCapability,
    ) -> PhaseExtractedFactor:
        """Register an action terminal, including a durable existing-value no-op.

        This capability is intentionally private and reachable only from the
        action-bound all-or-nothing materializer.  The legacy public generated
        value API continues to require genuinely new content.  An existing
        value receives a *new* attestation owned by this exact operation seal;
        an artifact-owned source attestation is never reused as generation
        evidence.
        """

        seal = self._resolve_seal(operation_seal)
        receipt = self._resolve_branch_receipt(seal.branch_receipt)
        terminal = receipt.body.generation_terminal
        if (
            seal.branch not in {"mutate", "fresh"}
            or receipt.body.action_transaction_id is None
            or terminal is None
            or terminal.branch != seal.branch
            or terminal.action_transaction_id
            != receipt.body.action_transaction_id
            or terminal.action_intent_sha256
            != receipt.body.action_intent_sha256
        ):
            raise ValueError(
                "existing generated values require one exact action terminal"
            )
        if any(
            item.operation_seal_id == seal.handle.handle_id
            for item in self._attestations.values()
        ):
            raise ValueError("operation seal already owns a generated value")
        source = self._resolve_artifact(seal.source_artifact)
        manifest = self._manifest_from_ingress(ingress)
        if not (
            source.split == terminal.split == "TRAIN_UPDATE"
            and manifest.split == "TRAIN_UPDATE"
            and manifest.manifest_sha256 == source.source_manifest_sha256
        ):
            raise ValueError(
                "action generated value crosses its TRAIN_UPDATE source manifest"
            )
        profile = self._resolve_profile(source.runtime_profile)
        value_record = self._ensure_value(profile, seal.descriptor, value)
        if terminal.generated_scalar_sha256 != phase_generated_scalar_sha256(
            value_record.value
        ):
            raise ValueError(
                "generation terminal scalar commitment differs from its typed value"
            )
        attestation = self._ensure_attestation(
            value_record,
            manifest_sha256=manifest.manifest_sha256,
            split=manifest.split,
            source_artifact_id=None,
            operation_seal_id=seal.handle.handle_id,
        )
        if not (
            attestation.operation_seal_id == seal.handle.handle_id
            and attestation.source_artifact_id is None
            and attestation.value == value_record.handle
        ):
            raise RuntimeError(
                "action generated value lost its exact seal-owned attestation"
            )
        factor = self._ensure_factor(profile, seal.descriptor, value_record)
        return PhaseExtractedFactor(
            descriptor=seal.descriptor,
            value=value_record.handle,
            attestation=attestation.handle,
            factor=factor.handle,
        )

    @_atomic_registry_update
    def materialize(
        self,
        *,
        operation_seal: OperationSealHandle,
        target_factor: FactorContentHandle | None = None,
    ) -> PhaseBindingProofHandle | NoOpMaterialization:
        seal = self._resolve_seal(operation_seal)
        receipt = self._resolve_branch_receipt(seal.branch_receipt)
        action_bound_generation = bool(
            seal.branch in {"mutate", "fresh"}
            and receipt.body.action_transaction_id is not None
            and receipt.body.generation_terminal is not None
        )
        if any(item.operation_seal.handle_id == seal.handle.handle_id for item in self._events.values()):
            raise ValueError("operation seal has already been consumed")
        source = self._resolve_artifact(seal.source_artifact)
        profile = self._resolve_profile(source.runtime_profile)
        source_factor = self._resolve_factor(seal.source_factor)
        source_value = self._resolve_value(source_factor.value)
        if seal.branch == "reuse":
            if target_factor is not None and target_factor != seal.retrieved_target_factor:
                raise ValueError("reuse target differs from the sealed retrieval")
            assert seal.retrieved_target_factor is not None
            target = self._resolve_factor(seal.retrieved_target_factor)
            if self._resolve_value(target.value).first_seen_sequence > seal.sequence_at_seal:
                raise ValueError("reuse target did not exist when the operation was sealed")
            assert seal.retrieved_target_attestation is not None
            target_attestation = self._resolve_attestation(
                seal.retrieved_target_attestation
            )
            if not (
                target_attestation.value == target.value
                and target_attestation.source_manifest_sha256
                == source.source_manifest_sha256
                and target_attestation.created_sequence <= seal.sequence_at_seal
            ):
                raise ValueError("reuse target provenance differs from its seal")
        else:
            if target_factor is None:
                raise ValueError("generated branch requires its registered target factor")
            target = self._resolve_factor(target_factor)
            attestations = [
                item
                for item in self._attestations.values()
                if item.value.handle_id == target.value.handle_id
                and item.operation_seal_id == seal.handle.handle_id
            ]
            if len(attestations) != 1:
                raise ValueError("generated target lacks one exact seal-bound attestation")
            target_attestation = attestations[0]
            if not (
                target_attestation.operation_seal_id == seal.handle.handle_id
                and target_attestation.source_artifact_id is None
            ):
                raise ValueError(
                    "generated target attestation is not owned by its exact seal"
                )
        if target.descriptor != seal.descriptor or target.runtime_profile != profile.handle:
            raise ValueError("target factor crosses the sealed typed slot/profile")
        target_value = self._resolve_value(target.value)
        if source_value.value == target_value.value and type(source_value.value) is type(target_value.value):
            if seal.branch in {"mutate", "fresh"} and not action_bound_generation:
                raise ValueError(
                    "non-action generated value must be new after its sealed operation"
                )
            return self._record_noop(
                seal,
                source,
                source_factor,
                target,
                target_attestation,
                status="same_value_noop",
                reason="same_value",
            )
        if (
            seal.branch in {"mutate", "fresh"}
            and target_value.first_seen_sequence <= seal.sequence_at_seal
        ):
            if not action_bound_generation:
                raise ValueError(
                    "non-action generated value already existed before its sealed operation"
                )
            return self._record_noop(
                seal,
                source,
                source_factor,
                target,
                target_attestation,
                status="duplicate_existing",
                reason="duplicate_existing",
            )
        raw = _replace_pointer(
            source.program.model_dump(mode="json"),
            seal.descriptor.locator.path,
            target_value.value,
        )
        target_program = _validated_program(raw)
        compiled = compile_phase_program(
            target_program,
            n_agents=profile.namespace.n_agents,
            limits=profile.limits,
        )
        target_image = _build_execution_image(
            target_program,
            compiled,
            profile.handle.handle_id,
        )
        if target_image == source.execution_image:
            return self._record_noop(
                seal,
                source,
                source_factor,
                target,
                target_attestation,
                status="operational_noop",
                reason="same_execution_image",
            )
        target_artifact = self._materialized_artifact(
            source,
            seal,
            target,
            target_program,
            target_image,
        )
        event = self._record_event(
            seal,
            source,
            source_factor,
            target,
            target_attestation,
            status="verified_delta",
            reason_code="exact_typed_factor_delta",
            target_artifact=target_artifact,
        )
        proof = self._record_proof(
            seal=seal,
            event=event,
            source=source,
            target_artifact=target_artifact,
            source_factor=source_factor,
            target_factor=target,
        )
        # Full self-verification is part of the materialization transaction.
        self.verify_phase_materialization_proof(proof.handle)
        return proof.handle

    @_atomic_registry_update
    def materialize_action_idempotent(
        self,
        *,
        action_transaction_id: str,
        action_intent_sha256: str,
        branch: Branch,
        source_artifact: PhaseArtifactHandle,
        locator: str,
        dependency_factor: FactorContentHandle | None,
        exact_additional_input_root_commitments: Sequence[str],
        producer_epoch: str,
        attestation_sha256: str,
        generation_terminal: PhaseGenerationTerminalV1 | None = None,
        generated_value: Any = _MISSING_GENERATED_VALUE,
        ingress: _IngressCapability | None = None,
        ttl_events: int = 64,
    ) -> PhaseBindingProofHandle | NoOpMaterialization:
        """Atomically materialize or replay one exact Bank-prepared action.

        The transaction identity lives in the host-attested branch body.  The
        outer registry update means a persisted file contains either no action
        transaction or its complete branch→seal→event/proof chain.  A retry of
        the same immutable intent returns that terminal.  Generated scalars are
        supplied only after an external, already-fenced call; this method never
        calls a model.  Reusing an id with a different branch, parent, terminal,
        scalar, source, roots, or digest fails closed.
        """

        if branch not in {"reuse", "mutate", "fresh"}:
            raise ValueError("branch must be reuse, mutate, or fresh")
        if not _ID_RE.fullmatch(action_transaction_id):
            raise ValueError("action_transaction_id must be an opaque identifier")
        _require_sha(action_intent_sha256, "action_intent_sha256")
        roots = tuple(exact_additional_input_root_commitments)
        if roots != tuple(sorted(set(roots))) or not roots:
            raise ValueError("action input roots must be a non-empty canonical set")
        for root in roots:
            _require_sha(root, "action input root")
        if action_intent_sha256 not in roots:
            raise ValueError("action intent digest must be in its exact input closure")
        source = self._resolve_artifact(source_artifact)
        profile = self._resolve_profile(source.runtime_profile)
        descriptor = _descriptor(source.program, profile, locator)
        manifest = self._manifests[source.source_manifest_sha256]
        dependency = (
            self._resolve_factor(dependency_factor)
            if dependency_factor is not None
            else None
        )
        terminal = (
            PhaseGenerationTerminalV1.model_validate(
                generation_terminal.model_dump(mode="python")
            )
            if generation_terminal is not None
            else None
        )
        if branch == "reuse":
            if dependency is None:
                raise ValueError("reuse action requires its exact selected target")
            if any(
                item is not None
                for item in (terminal, ingress)
            ) or generated_value is not _MISSING_GENERATED_VALUE:
                raise ValueError("reuse action cannot carry generation inputs")
        else:
            if terminal is None or ingress is None:
                raise ValueError(
                    "generated action requires its terminal and ingress capability"
                )
            if generated_value is _MISSING_GENERATED_VALUE:
                raise ValueError("generated action requires one parsed scalar")
            if source.split != "TRAIN_UPDATE" or terminal.split != "TRAIN_UPDATE":
                raise ValueError("generated action must remain in TRAIN_UPDATE")
            if not (
                terminal.branch == branch
                and terminal.action_transaction_id == action_transaction_id
                and terminal.action_intent_sha256 == action_intent_sha256
            ):
                raise ValueError(
                    "generation terminal differs from its action/branch intent"
                )
            _validate_scalar(generated_value, descriptor)
            if terminal.generated_scalar_sha256 != phase_generated_scalar_sha256(
                generated_value
            ):
                raise ValueError(
                    "generation terminal scalar commitment does not match the parsed value"
                )
            required_terminal_roots = {
                terminal.generation_request_sha256,
                terminal.generation_lease_sha256,
                terminal.digest,
            }
            if not required_terminal_roots.issubset(roots):
                raise ValueError(
                    "generated action roots omit request, lease, or terminal commitment"
                )
            ingress_manifest = self._manifest_from_ingress(ingress)
            if ingress_manifest.manifest_sha256 != source.source_manifest_sha256:
                raise ValueError("generated action ingress crosses the source manifest")
            source_extracted = self.extract_factor(source.handle, locator=locator)
            if branch == "mutate":
                if dependency is None or dependency.handle != source_extracted.factor:
                    raise ValueError("mutation parent must be the exact source factor")
            elif dependency is not None:
                raise ValueError("fresh action must have an empty dependency closure")
        expected_input_roots = tuple(
            sorted({manifest.source_catalog_sha256, manifest.policy_sha256, *roots})
        )
        existing = [
            item
            for item in self._branch_receipts.values()
            if item.body.action_transaction_id == action_transaction_id
        ]
        if len(existing) > 1:
            raise ValueError("action transaction owns multiple branch receipts")
        if existing:
            receipt = self._resolve_branch_receipt(existing[0].handle)
            body = receipt.body
            common_matches = bool(
                body.action_intent_sha256 == action_intent_sha256
                and body.branch == branch
                and body.source_artifact == source.handle
                and body.runtime_profile == source.runtime_profile
                and body.descriptor == descriptor
                and body.input_root_commitments == expected_input_roots
                and body.producer_epoch == producer_epoch
                and body.attestation_sha256 == attestation_sha256
                and body.generation_terminal == terminal
            )
            branch_matches = (
                body.retrieved_target_factor == dependency.handle
                and body.mutation_parent_factor is None
                if branch == "reuse" and dependency is not None
                else (
                    body.mutation_parent_factor == dependency.handle
                    and body.retrieved_target_factor is None
                    if branch == "mutate" and dependency is not None
                    else (
                        body.mutation_parent_factor is None
                        and body.retrieved_target_factor is None
                        if branch == "fresh" and dependency is None
                        else False
                    )
                )
            )
            if not (common_matches and branch_matches):
                raise ValueError(
                    "action transaction id was replayed with a different intent"
                )
            seals = [
                item
                for item in self._seals.values()
                if item.branch_receipt == receipt.handle
            ]
            if len(seals) != 1:
                raise ValueError("persisted action transaction lacks one exact seal")
            events = [
                item
                for item in self._events.values()
                if item.operation_seal == seals[0].handle
            ]
            if len(events) != 1:
                raise ValueError("persisted action transaction lacks one terminal event")
            event = self._resolve_event(events[0].handle)
            if branch != "reuse":
                assert generated_value is not _MISSING_GENERATED_VALUE
                assert event.target_factor is not None
                persisted_target = self._resolve_factor(event.target_factor)
                persisted_value = self._resolve_value(persisted_target.value).value
                if not (
                    persisted_value == generated_value
                    and type(persisted_value) is type(generated_value)
                ):
                    raise ValueError(
                        "action transaction id was replayed with a different scalar"
                    )
            if event.status == "verified_delta":
                proofs = [
                    item
                    for item in self._proofs.values()
                    if item.event == event.handle
                ]
                if len(proofs) != 1:
                    raise ValueError("verified action transaction lacks one proof")
                self.verify_phase_materialization_proof(proofs[0].handle)
                return proofs[0].handle
            reason_by_status = {
                "same_value_noop": "same_value",
                "operational_noop": "same_execution_image",
                "duplicate_existing": "duplicate_existing",
            }
            return NoOpMaterialization(
                event=event.handle,
                reason=reason_by_status[event.status],
            )

        branch_receipt = self.register_branch_receipt(
            branch=branch,
            source_artifact=source.handle,
            locator=locator,
            retrieved_target_factor=(
                dependency.handle if branch == "reuse" and dependency is not None else None
            ),
            mutation_parent_factor=(
                dependency.handle if branch == "mutate" and dependency is not None else None
            ),
            additional_input_root_commitments=roots,
            action_transaction_id=action_transaction_id,
            action_intent_sha256=action_intent_sha256,
            generation_terminal=terminal,
            producer_epoch=producer_epoch,
            attestation_sha256=attestation_sha256,
            ttl_events=ttl_events,
        )
        seal = self.seal_operation(branch_receipt=branch_receipt)
        if branch == "reuse":
            assert dependency is not None
            return self.materialize(
                operation_seal=seal,
                target_factor=dependency.handle,
            )
        assert ingress is not None
        assert generated_value is not _MISSING_GENERATED_VALUE
        generated = self._register_action_generated_value(
            generated_value,
            operation_seal=seal,
            ingress=ingress,
        )
        return self.materialize(
            operation_seal=seal,
            target_factor=generated.factor,
        )

    def materialize_reuse_idempotent(
        self,
        *,
        action_transaction_id: str,
        action_intent_sha256: str,
        source_artifact: PhaseArtifactHandle,
        locator: str,
        retrieved_target_factor: FactorContentHandle,
        exact_additional_input_root_commitments: Sequence[str],
        producer_epoch: str,
        attestation_sha256: str,
        ttl_events: int = 64,
    ) -> PhaseBindingProofHandle | NoOpMaterialization:
        """Compatibility wrapper for the v6 reuse-only call surface."""

        return self.materialize_action_idempotent(
            action_transaction_id=action_transaction_id,
            action_intent_sha256=action_intent_sha256,
            branch="reuse",
            source_artifact=source_artifact,
            locator=locator,
            dependency_factor=retrieved_target_factor,
            exact_additional_input_root_commitments=(
                exact_additional_input_root_commitments
            ),
            producer_epoch=producer_epoch,
            attestation_sha256=attestation_sha256,
            ttl_events=ttl_events,
        )

    def _materialized_artifact(
        self,
        source: PhaseProgramArtifactRecord,
        seal: PhaseOperationSealRecord,
        target_factor: PhaseFactorContentRecord,
        program: PhaseProgram,
        image: PhaseExecutionImage,
    ) -> PhaseProgramArtifactRecord:
        identity = {
            "profile": source.runtime_profile.handle_id,
            "manifest": source.source_manifest_sha256,
            "program": program,
        }
        handle_id = _handle_id(self._key, "pa", identity)
        existing = self._artifacts.get(handle_id)
        if existing is not None:
            return self._resolve_artifact(existing.handle)
        if self._artifact_lineage_depth(source) >= self.capacity.max_lineage_depth:
            # Public branch admission must catch this before it can persist a
            # receipt/seal/value.  Keep the writer fail-closed as a final
            # invariant guard for authenticated legacy or test-only state.
            raise ValueError(
                "materialization would exceed the lineage depth preflight cap"
            )
        self._check_capacity(self._artifacts, self.capacity.max_artifacts, "artifact")
        body = {
            "runtime_profile": source.runtime_profile,
            "source_manifest_sha256": source.source_manifest_sha256,
            "split": source.split,
            "program": program,
            "program_commitment": _mac(self._key, "program", program),
            "execution_image": image,
            "execution_image_commitment": _mac(self._key, "execution-image", image),
            "parent_artifact_id": source.handle.handle_id,
            "derivation_operation_seal_id": seal.handle.handle_id,
            "derivation_target_factor_id": target_factor.handle.handle_id,
            "created_sequence": self._next_sequence(),
        }
        handle = self._new_handle(
            PhaseArtifactHandle,
            prefix="pa",
            kind="phase_artifact",
            identity=identity,
            body=body,
        )
        record = PhaseProgramArtifactRecord(handle=handle, **body)
        self._artifacts[handle.handle_id] = record
        return record

    def _record_noop(
        self,
        seal: PhaseOperationSealRecord,
        source: PhaseProgramArtifactRecord,
        source_factor: PhaseFactorContentRecord,
        target_factor: PhaseFactorContentRecord,
        target_attestation: PhaseValueAttestationRecord,
        *,
        status: Literal["same_value_noop", "operational_noop", "duplicate_existing"],
        reason: Literal["same_value", "same_execution_image", "duplicate_existing"],
    ) -> NoOpMaterialization:
        event = self._record_event(
            seal,
            source,
            source_factor,
            target_factor,
            target_attestation,
            status=status,
            reason_code=reason,
            target_artifact=None,
        )
        return NoOpMaterialization(event=event.handle, reason=reason)

    def _record_event(
        self,
        seal: PhaseOperationSealRecord,
        source: PhaseProgramArtifactRecord,
        source_factor: PhaseFactorContentRecord,
        target_factor: PhaseFactorContentRecord,
        target_attestation: PhaseValueAttestationRecord,
        *,
        status: Literal[
            "verified_delta", "same_value_noop", "operational_noop", "duplicate_existing"
        ],
        reason_code: str,
        target_artifact: PhaseProgramArtifactRecord | None,
    ) -> PhaseMaterializationEventRecord:
        self._check_capacity(self._events, self.capacity.max_events, "event")
        sequence = self._next_sequence()
        identity = {
            "seal": seal.handle.handle_id,
            "source": source.handle.handle_id,
            "target": target_artifact.handle.handle_id if target_artifact else None,
            "source_factor": source_factor.handle.handle_id,
            "target_factor": target_factor.handle.handle_id,
            "status": status,
            "sequence": sequence,
        }
        body = {
            "operation_seal": seal.handle,
            "source_artifact": source.handle,
            "target_artifact": target_artifact.handle if target_artifact else None,
            "source_factor": source_factor.handle,
            "target_factor": target_factor.handle,
            "target_attestation": target_attestation.handle,
            "status": status,
            "reason_code": reason_code,
            "created_sequence": sequence,
        }
        handle = self._new_handle(
            MaterializationEventHandle,
            prefix="me",
            kind="materialization_event",
            identity=identity,
            body=body,
        )
        record = PhaseMaterializationEventRecord(handle=handle, **body)
        self._events[handle.handle_id] = record
        return record

    def _activation_requirement(
        self,
        *,
        arm: Literal["source", "target"],
        factor: PhaseFactorContentRecord,
        artifact: PhaseProgramArtifactRecord,
    ) -> ActivationRequirement:
        descriptor = factor.descriptor
        if descriptor.activation_kind == "execution_image_load":
            mode: Literal["image_loaded", "trusted_trace_event"] = "image_loaded"
        else:
            mode = "trusted_trace_event"
            if descriptor.activation_kind == "phase_step_executed" and not any(
                step.phase_index == descriptor.phase_index
                for step in artifact.execution_image.steps
            ):
                raise ValueError("factorized phase has no executable activation point")
        return ActivationRequirement(
            arm=arm,
            factor_content_id=factor.handle.handle_id,
            artifact_id=artifact.handle.handle_id,
            runtime_profile_id=artifact.runtime_profile.handle_id,
            mode=mode,
            activation_kind=descriptor.activation_kind,
        )

    def _record_proof(
        self,
        *,
        seal: PhaseOperationSealRecord,
        event: PhaseMaterializationEventRecord,
        source: PhaseProgramArtifactRecord,
        target_artifact: PhaseProgramArtifactRecord,
        source_factor: PhaseFactorContentRecord,
        target_factor: PhaseFactorContentRecord,
    ) -> PhaseMaterializationProofRecord:
        self._check_capacity(self._proofs, self.capacity.max_proofs, "proof")
        source_data = source.program.model_dump(mode="json")
        target_data = target_artifact.program.model_dump(mode="json")
        differences = _leaf_differences(source_data, target_data)
        if len(differences) != 1:
            raise RuntimeError("materializer did not produce one exact scalar delta")
        path, _left, _right = differences[0]
        if _pointer(path) != seal.descriptor.locator.path:
            raise RuntimeError("materializer delta differs from the sealed locator")
        masked = _replace_pointer(
            source_data,
            seal.descriptor.locator.path,
            {"__phase_factor_slot__": seal.descriptor.locator.path},
        )
        source_value = self._resolve_value(source_factor.value)
        target_value = self._resolve_value(target_factor.value)
        source_activation = self._activation_requirement(
            arm="source", factor=source_factor, artifact=source
        )
        target_activation = self._activation_requirement(
            arm="target", factor=target_factor, artifact=target_artifact
        )
        body = {
            "event": event.handle,
            "operation_seal": seal.handle,
            "branch": seal.branch,
            "namespace": source_factor.namespace,
            "runtime_profile": source.runtime_profile,
            "source_manifest_sha256": source.source_manifest_sha256,
            "source_artifact": source.handle,
            "target_artifact": target_artifact.handle,
            "descriptor": seal.descriptor,
            "source_value": source_value.handle,
            "target_value": target_value.handle,
            "source_factor": source_factor.handle,
            "target_factor": target_factor.handle,
            "masked_background_commitment": _mac(self._key, "masked-background", masked),
            "source_execution_image_commitment": source.execution_image_commitment,
            "target_execution_image_commitment": target_artifact.execution_image_commitment,
            "source_activation": source_activation,
            "target_activation": target_activation,
        }
        proof_sha256 = _sha256(body)
        identity = {"proof_sha256": proof_sha256, "event": event.handle.handle_id}
        handle = self._new_handle(
            PhaseBindingProofHandle,
            prefix="bp",
            kind="phase_binding_proof",
            identity=identity,
            body=body,
            proof_sha256=proof_sha256,
        )
        record = PhaseMaterializationProofRecord(handle=handle, **body)
        self._proofs[handle.handle_id] = record
        return record

    @_registry_instance_lock
    @_registry_verification_scope
    def verify_phase_materialization_proof(
        self,
        proof: PhaseBindingProofHandle,
        *,
        expected_namespace: ExecutionNamespace | None = None,
        expected_source_artifact_id: str | None = None,
        expected_target_artifact_id: str | None = None,
    ) -> VerifiedPhaseBinding:
        record = self._resolve_proof(proof)
        event = self._resolve_event(record.event)
        seal = self._resolve_seal(record.operation_seal)
        source = self._resolve_artifact(record.source_artifact)
        target = self._resolve_artifact(record.target_artifact)
        profile = self._resolve_profile(record.runtime_profile)
        source_factor = self._resolve_factor(record.source_factor)
        if record.target_factor is None:
            raise ValueError("materialization event lacks its target factor")
        target_factor = self._resolve_factor(record.target_factor)
        source_value = self._resolve_value(record.source_value)
        target_value = self._resolve_value(record.target_value)
        target_attestation = self._resolve_attestation(event.target_attestation)
        if event.status != "verified_delta" or event.operation_seal != seal.handle:
            raise ValueError("proof event is not a verified materialization")
        if not (
            event.source_artifact == source.handle
            and event.target_artifact == target.handle
            and event.source_factor == source_factor.handle
            and event.target_factor == target_factor.handle
            and event.reason_code == "exact_typed_factor_delta"
        ):
            raise ValueError("proof artifact/factor join differs from its event")
        if not (
            seal.source_artifact == source.handle
            and seal.source_factor == source_factor.handle
            and seal.descriptor == record.descriptor
            and record.event == event.handle
        ):
            raise ValueError("proof source/descriptor differs from its sealed operation")
        if target_attestation.value != target_factor.value:
            raise ValueError("proof event target attestation names another value")
        if (
            source.runtime_profile != profile.handle
            or target.runtime_profile != profile.handle
            or source_factor.runtime_profile != profile.handle
            or target_factor.runtime_profile != profile.handle
        ):
            raise ValueError("proof crosses a runtime profile")
        if source_factor.namespace != profile.namespace or target_factor.namespace != profile.namespace:
            raise ValueError("proof crosses an execution namespace")
        if record.namespace != profile.namespace or record.branch != seal.branch:
            raise ValueError("proof namespace/branch differs from its seal")
        if record.source_manifest_sha256 != source.source_manifest_sha256 or (
            target.source_manifest_sha256 != source.source_manifest_sha256
        ):
            raise ValueError("proof crosses a source provenance universe")
        descriptor = _descriptor(source.program, profile, seal.descriptor.locator.path)
        if descriptor != record.descriptor or descriptor != source_factor.descriptor:
            raise ValueError("proof typed slot descriptor is not reproducible")
        if target_factor.descriptor != descriptor:
            raise ValueError("proof target factor belongs to another slot")
        source_data = source.program.model_dump(mode="json")
        target_data = target.program.model_dump(mode="json")
        if _read_pointer(source_data, descriptor.locator.path) != source_value.value:
            raise ValueError("proof source scalar is not loaded by its artifact")
        if _read_pointer(target_data, descriptor.locator.path) != target_value.value:
            raise ValueError("proof target scalar is not loaded by its artifact")
        if _replace_pointer(source_data, descriptor.locator.path, target_value.value) != target_data:
            raise ValueError("proof target is not the exact sealed intervention")
        differences = _leaf_differences(source_data, target_data)
        if len(differences) != 1 or _pointer(differences[0][0]) != descriptor.locator.path:
            raise ValueError("proof is not an exact one-leaf intervention")
        masked = _replace_pointer(
            source_data,
            descriptor.locator.path,
            {"__phase_factor_slot__": descriptor.locator.path},
        )
        if not hmac.compare_digest(
            record.masked_background_commitment,
            _mac(self._key, "masked-background", masked),
        ):
            raise ValueError("proof masked background commitment mismatch")
        source_compiled = compile_phase_program(
            source.program,
            n_agents=profile.namespace.n_agents,
            limits=profile.limits,
        )
        target_compiled = compile_phase_program(
            target.program,
            n_agents=profile.namespace.n_agents,
            limits=profile.limits,
        )
        source_image = _build_execution_image(source.program, source_compiled, profile.handle.handle_id)
        target_image = _build_execution_image(target.program, target_compiled, profile.handle.handle_id)
        if source_image != source.execution_image or target_image != target.execution_image:
            raise ValueError("proof execution image is not reproducible")
        if not (
            record.source_execution_image_commitment
            == source.execution_image_commitment
            and record.target_execution_image_commitment
            == target.execution_image_commitment
        ):
            raise ValueError("proof execution-image commitments differ from its artifacts")
        if source_image == target_image:
            raise ValueError("proof intervention is an operational no-op")
        if record.source_activation != self._activation_requirement(
            arm="source", factor=source_factor, artifact=source
        ) or record.target_activation != self._activation_requirement(
            arm="target", factor=target_factor, artifact=target
        ):
            raise ValueError("proof activation requirements are not reproducible")
        if seal.branch == "reuse":
            if seal.retrieved_target_factor != target_factor.handle:
                raise ValueError("reuse proof differs from sealed retrieval")
            if seal.retrieved_target_attestation != target_attestation.handle:
                raise ValueError("reuse proof differs from sealed target provenance")
            if target_value.first_seen_sequence > seal.sequence_at_seal:
                raise ValueError("reuse proof used future factor content")
            if not (
                target_attestation.source_manifest_sha256
                == source.source_manifest_sha256
                and target_attestation.created_sequence <= seal.sequence_at_seal
            ):
                raise ValueError("reuse proof target attestation was not allowed at seal time")
        else:
            if target_value.first_seen_sequence <= seal.sequence_at_seal:
                raise ValueError("generated proof reused pre-existing factor content")
            attestations = [
                item for item in self._attestations.values()
                if item.value.handle_id == target_value.handle.handle_id
                and item.operation_seal_id == seal.handle.handle_id
            ]
            if len(attestations) != 1:
                raise ValueError("generated proof lacks exact seal-bound provenance")
            if target_attestation != attestations[0]:
                raise ValueError("proof event does not own the generated target attestation")
        if expected_namespace is not None:
            expected = ExecutionNamespace.model_validate(
                expected_namespace.model_dump(mode="python")
            )
            if expected != profile.namespace:
                raise ValueError("proof differs from the expected execution namespace")
        if expected_source_artifact_id is not None and (
            expected_source_artifact_id != source.handle.handle_id
        ):
            raise ValueError("proof differs from the expected source artifact")
        if expected_target_artifact_id is not None and (
            expected_target_artifact_id != target.handle.handle_id
        ):
            raise ValueError("proof differs from the expected target artifact")
        return VerifiedPhaseBinding(self._token, record)

    @_registry_instance_lock
    def factor_bank_binding_verifier(
        self,
        proof_id: str,
        proof_sha256: str,
        source: CompositionRevision,
        target: CompositionRevision,
        source_factor: FactorRevision,
        target_factor: FactorRevision,
        origin_branch: str,
        masked_background_sha256: str,
    ) -> bool:
        record = self._proofs.get(proof_id)
        if record is None or record.handle.proof_sha256 != proof_sha256:
            return False
        try:
            verified = self.verify_phase_materialization_proof(
                record.handle,
                expected_namespace=source.namespace,
                expected_source_artifact_id=source.artifact_revision_id,
                expected_target_artifact_id=target.artifact_revision_id,
            )
        except (ValueError, RuntimeError):
            return False
        proof = verified.proof
        return bool(
            source.namespace == target.namespace == proof.namespace
            and source.artifact_sha256 == proof.source_execution_image_commitment
            and target.artifact_sha256 == proof.target_execution_image_commitment
            and source_factor.revision_id == proof.source_factor.handle_id
            and target_factor.revision_id == proof.target_factor.handle_id
            and source_factor.content_sha256
            == self._resolve_factor(proof.source_factor).factor_content_commitment
            and target_factor.content_sha256
            == self._resolve_factor(proof.target_factor).factor_content_commitment
            and source_factor.locator == target_factor.locator == proof.descriptor.locator
            and origin_branch == proof.branch
            and masked_background_sha256 == proof.masked_background_commitment
        )

    @_registry_instance_lock
    def resolve_proof(self, handle: PhaseBindingProofHandle) -> PhaseMaterializationProofRecord:
        return self._resolve_proof(handle).model_copy(deep=True)

    @_registry_instance_lock
    def resolve_materialization_event(
        self,
        handle: MaterializationEventHandle,
    ) -> PhaseMaterializationEventRecord:
        """Return a deep read-only copy after complete handle/MAC/body checks."""

        return self._resolve_event(handle).model_copy(deep=True)

    @_registry_instance_lock
    def resolve_event(
        self,
        handle: MaterializationEventHandle,
    ) -> PhaseMaterializationEventRecord:
        """Compatibility spelling for the existing binding adapter.

        New cross-store code should use ``resolve_materialization_event`` and
        ``phase_materialization_event_sha256_v1`` explicitly.
        """

        return self._resolve_event(handle).model_copy(deep=True)

    @_registry_instance_lock
    def resolve_artifact(self, handle: PhaseArtifactHandle) -> PhaseProgramArtifactRecord:
        return self._resolve_artifact(handle).model_copy(deep=True)

    @_registry_instance_lock
    def resolve_factor(self, handle: FactorContentHandle) -> PhaseFactorContentRecord:
        return self._resolve_factor(handle).model_copy(deep=True)

    @_memoized_registry_resolver("runtime_profile")
    def _resolve_profile(self, handle: RuntimeProfileHandle) -> PhaseRuntimeProfileRecord:
        handle = RuntimeProfileHandle.model_validate(handle.model_dump(mode="python"))
        record = self._profiles.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("runtime profile handle is not registered")
        identity = {
            "namespace": record.namespace,
            "limits": record.limits,
            "binder": record.binder_version,
            "compiler": record.compiler_version,
            "image": record.execution_image_version,
            "activation": record.activation_version,
            "enable_step_instructions": record.enable_step_instructions,
        }
        self._verify_record(record, prefix="rp", kind="runtime_profile", identity=identity)
        if record.limits_commitment != _mac(self._key, "limits", record.limits):
            raise ValueError("runtime profile limits commitment mismatch")
        _validated_limits(record.limits)
        return record

    @_memoized_registry_resolver("phase_artifact")
    def _resolve_artifact(self, handle: PhaseArtifactHandle) -> PhaseProgramArtifactRecord:
        handle = PhaseArtifactHandle.model_validate(handle.model_dump(mode="python"))
        record = self._artifacts.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("PhaseProgram artifact handle is not registered")
        program = _validated_program(record.program)
        profile = self._resolve_profile(record.runtime_profile)
        identity = {
            "profile": profile.handle.handle_id,
            "manifest": record.source_manifest_sha256,
            "program": program,
        }
        self._verify_record(record, prefix="pa", kind="phase_artifact", identity=identity)
        if record.program_commitment != _mac(self._key, "program", program):
            raise ValueError("PhaseProgram artifact commitment mismatch")
        compiled = compile_phase_program(
            program,
            n_agents=profile.namespace.n_agents,
            limits=profile.limits,
        )
        image = _build_execution_image(program, compiled, profile.handle.handle_id)
        if record.execution_image != image or record.execution_image_commitment != _mac(
            self._key, "execution-image", image
        ):
            raise ValueError("PhaseProgram execution image commitment mismatch")
        manifest = self._manifests.get(record.source_manifest_sha256)
        if manifest is None or manifest.split != record.split:
            raise ValueError("PhaseProgram artifact provenance is not registered")
        self._artifact_lineage_depth(record)
        if record.parent_artifact_id is not None:
            assert record.derivation_operation_seal_id is not None
            assert record.derivation_target_factor_id is not None
            parent_record = self._artifacts.get(record.parent_artifact_id)
            seal_record = self._seals.get(record.derivation_operation_seal_id)
            target_factor_record = self._factors.get(
                record.derivation_target_factor_id
            )
            if parent_record is None or seal_record is None or target_factor_record is None:
                raise ValueError("materialized artifact derivation closure is incomplete")
            # Check the raw monotone order before recursively resolving the
            # lineage.  This makes a forged cycle fail closed instead of
            # recursing indefinitely.
            if not (
                parent_record.created_sequence < seal_record.sequence_at_seal
                < record.created_sequence
            ):
                raise ValueError("materialized artifact derivation order is invalid")
            parent = self._resolve_artifact(parent_record.handle)
            seal = self._resolve_seal(seal_record.handle)
            target_factor = self._resolve_factor(target_factor_record.handle)
            target_value = self._resolve_value(target_factor.value)
            if not (
                seal.source_artifact == parent.handle
                and seal.descriptor == target_factor.descriptor
                and parent.runtime_profile == record.runtime_profile
                and target_factor.runtime_profile == record.runtime_profile
                and parent.source_manifest_sha256 == record.source_manifest_sha256
                and parent.split == record.split
                and target_value.first_seen_sequence < record.created_sequence
            ):
                raise ValueError("materialized artifact derivation joins are invalid")
            parent_descriptor = _descriptor(
                parent.program,
                profile,
                seal.descriptor.locator.path,
            )
            if parent_descriptor != seal.descriptor:
                raise ValueError("materialized artifact source slot is not reproducible")
            expected = _replace_pointer(
                parent.program.model_dump(mode="json"),
                seal.descriptor.locator.path,
                target_value.value,
            )
            if expected != program.model_dump(mode="json"):
                raise ValueError("materialized artifact is not its recorded intervention")
            matching_events = [
                event
                for event in self._events.values()
                if event.status == "verified_delta"
                and event.source_artifact == parent.handle
                and event.target_artifact == record.handle
                and event.operation_seal == seal.handle
                and event.target_factor == target_factor.handle
            ]
            if len(matching_events) != 1:
                raise ValueError(
                    "materialized artifact lacks one exact derivation event"
                )
            event = matching_events[0]
            event_identity = {
                "seal": event.operation_seal.handle_id,
                "source": event.source_artifact.handle_id,
                "target": event.target_artifact.handle_id,
                "source_factor": event.source_factor.handle_id,
                "target_factor": event.target_factor.handle_id,
                "status": event.status,
                "sequence": event.created_sequence,
            }
            self._verify_record(
                event,
                prefix="me",
                kind="materialization_event",
                identity=event_identity,
            )
            attestation = self._resolve_attestation(event.target_attestation)
            if not (
                event.source_factor == seal.source_factor
                and event.reason_code == "exact_typed_factor_delta"
                and event.created_sequence > record.created_sequence
                and attestation.value == target_factor.value
            ):
                raise ValueError(
                    "materialized artifact derivation event joins are invalid"
                )
            matching_proofs = [
                proof
                for proof in self._proofs.values()
                if proof.event == event.handle
                and proof.operation_seal == seal.handle
                and proof.source_artifact == parent.handle
                and proof.target_artifact == record.handle
                and proof.target_factor == target_factor.handle
            ]
            if len(matching_proofs) != 1:
                raise ValueError(
                    "materialized artifact derivation event lacks one exact proof"
                )
            # Resolving the proof authenticates its full immutable body but does
            # not recurse through the event, so the target artifact can safely
            # demand its own transitive receipt closure.
            self._resolve_proof(matching_proofs[0].handle)
        return record

    @_memoized_registry_resolver("phase_value")
    def _resolve_value(self, handle: PhaseValueHandle) -> PhaseValueContentRecord:
        handle = PhaseValueHandle.model_validate(handle.model_dump(mode="python"))
        record = self._values.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("PhaseProgram value handle is not registered")
        profile = self._resolve_profile(record.runtime_profile)
        _validate_scalar(record.value, record.descriptor)
        identity = self._value_identity(profile, record.descriptor, record.value)
        self._verify_record(record, prefix="pv", kind="phase_value", identity=identity)
        if record.keyed_content_commitment != identity["value_commitment"]:
            raise ValueError("PhaseProgram value commitment mismatch")
        return record

    @_memoized_registry_resolver("value_attestation")
    def _resolve_attestation(self, handle: ValueAttestationHandle) -> PhaseValueAttestationRecord:
        handle = ValueAttestationHandle.model_validate(handle.model_dump(mode="python"))
        record = self._attestations.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("value attestation handle is not registered")
        value = self._resolve_value(record.value)
        identity = {
            "value": record.value.handle_id,
            "manifest": record.source_manifest_sha256,
            "source_artifact": record.source_artifact_id,
            "operation_seal": record.operation_seal_id,
        }
        self._verify_record(record, prefix="va", kind="value_attestation", identity=identity)
        manifest = self._manifests.get(record.source_manifest_sha256)
        if manifest is None or manifest.split != record.split:
            raise ValueError("value attestation provenance is not registered")
        if record.source_artifact_id is not None:
            source_record = self._artifacts.get(record.source_artifact_id)
            if source_record is None:
                raise ValueError("value attestation source artifact is missing")
            if source_record.created_sequence >= record.created_sequence:
                raise ValueError("value attestation predates its source artifact")
            source = self._resolve_artifact(source_record.handle)
            profile = self._resolve_profile(source.runtime_profile)
            if not (
                source.source_manifest_sha256 == record.source_manifest_sha256
                and source.split == record.split
                and value.runtime_profile == source.runtime_profile
            ):
                raise ValueError("value attestation crosses artifact provenance")
            descriptor = _descriptor(
                source.program,
                profile,
                value.descriptor.locator.path,
            )
            loaded = _read_pointer(
                source.program.model_dump(mode="json"),
                value.descriptor.locator.path,
            )
            if descriptor != value.descriptor or not (
                loaded == value.value and type(loaded) is type(value.value)
            ):
                raise ValueError("value attestation is not loaded by its source artifact")
        else:
            assert record.operation_seal_id is not None
            seal_record = self._seals.get(record.operation_seal_id)
            if seal_record is None:
                raise ValueError("generated value attestation operation seal is missing")
            if seal_record.sequence_at_seal >= record.created_sequence:
                raise ValueError("generated value attestation predates its operation seal")
            seal = self._resolve_seal(seal_record.handle)
            receipt = self._resolve_branch_receipt(seal.branch_receipt)
            source = self._resolve_artifact(seal.source_artifact)
            common_closure = bool(
                source.source_manifest_sha256 == record.source_manifest_sha256
                and source.split == record.split
                and value.runtime_profile == source.runtime_profile
                and value.descriptor == seal.descriptor
                and value.first_seen_sequence < record.created_sequence
            )
            if not common_closure:
                raise ValueError("generated value attestation closure is invalid")
            if receipt.body.action_transaction_id is None:
                # The public v7-compatible generation capability remains a
                # strict fresh-content ingress.  Only the unified action API
                # below may durably attest a same/pre-existing typed value.
                if not (
                    receipt.body.generation_terminal is None
                    and value.first_seen_sequence > seal.sequence_at_seal
                ):
                    raise ValueError(
                        "non-action generated attestation reused pre-existing content"
                    )
            else:
                terminal = receipt.body.generation_terminal
                if not (
                    terminal is not None
                    and seal.branch in {"mutate", "fresh"}
                    and source.split == record.split == terminal.split == "TRAIN_UPDATE"
                    and terminal.action_transaction_id
                    == receipt.body.action_transaction_id
                    and terminal.action_intent_sha256
                    == receipt.body.action_intent_sha256
                    and terminal.branch == seal.branch
                ):
                    raise ValueError(
                        "action generated attestation lost its exact terminal closure"
                    )
                if terminal.generated_scalar_sha256 != phase_generated_scalar_sha256(
                    value.value
                ):
                    raise ValueError(
                        "generated action terminal scalar commitment differs from its event target"
                    )
        return record

    @_memoized_registry_resolver("factor_content")
    def _resolve_factor(self, handle: FactorContentHandle) -> PhaseFactorContentRecord:
        handle = FactorContentHandle.model_validate(handle.model_dump(mode="python"))
        record = self._factors.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("factor content handle is not registered")
        profile = self._resolve_profile(record.runtime_profile)
        value = self._resolve_value(record.value)
        identity = {
            "namespace": profile.namespace.digest,
            "profile": profile.handle.handle_id,
            "locator": record.descriptor.locator,
            "slot_schema": record.descriptor.slot_schema_commitment,
            "value": value.handle.handle_id,
        }
        self._verify_record(record, prefix="fc", kind="factor_content", identity=identity)
        if record.factor_content_commitment != _mac(self._key, "factor-content", identity):
            raise ValueError("factor content commitment mismatch")
        return record

    @_memoized_registry_resolver("branch_receipt")
    def _resolve_branch_receipt(
        self,
        handle: BranchReceiptHandle,
    ) -> PhaseBranchReceiptRecord:
        handle = BranchReceiptHandle.model_validate(handle.model_dump(mode="python"))
        record = self._branch_receipts.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("branch receipt handle is not registered")
        identity = {
            "body": record.body,
            "sequence": record.created_sequence,
        }
        self._verify_record(
            record,
            prefix="br",
            kind="branch_receipt",
            identity=identity,
        )
        source = self._resolve_artifact(record.body.source_artifact)
        profile = self._resolve_profile(record.body.runtime_profile)
        source_factor = self._resolve_factor(record.body.source_factor)
        if (
            source.runtime_profile != profile.handle
            or source_factor.runtime_profile != profile.handle
            or source.source_manifest_sha256 != record.body.source_manifest_sha256
            or source_factor.descriptor != record.body.descriptor
        ):
            raise ValueError("branch receipt source/profile/descriptor closure is invalid")
        manifest = self._manifests.get(record.body.source_manifest_sha256)
        if manifest is None or not {
            manifest.source_catalog_sha256,
            manifest.policy_sha256,
        }.issubset(record.body.input_root_commitments):
            raise ValueError("branch receipt omits its authenticated source roots")
        expected_closure = _sha256(
            {
                "source_manifest": record.body.source_manifest_sha256,
                "input_roots": record.body.input_root_commitments,
                "bank_dependencies": record.body.dependency_factor_ids,
                "retrieved_target_attestation": (
                    record.body.retrieved_target_attestation.handle_id
                    if record.body.retrieved_target_attestation is not None
                    else None
                ),
                "branch": record.body.branch,
                "source_artifact": record.body.source_artifact.handle_id,
                "descriptor": record.body.descriptor,
                "action_transaction_id": record.body.action_transaction_id,
                "action_intent_sha256": record.body.action_intent_sha256,
                "generation_terminal_sha256": (
                    record.body.generation_terminal.digest
                    if record.body.generation_terminal is not None
                    else None
                ),
            }
        )
        if record.body.provenance_closure_sha256 != expected_closure:
            raise ValueError("branch receipt provenance closure is not reproducible")
        if record.body.generation_terminal is not None and source.split != "TRAIN_UPDATE":
            raise ValueError("generated action receipt crosses a non-TRAIN source")
        target = (
            self._resolve_factor(record.body.retrieved_target_factor)
            if record.body.retrieved_target_factor is not None
            else None
        )
        target_attestation = (
            self._resolve_attestation(record.body.retrieved_target_attestation)
            if record.body.retrieved_target_attestation is not None
            else None
        )
        parent = (
            self._resolve_factor(record.body.mutation_parent_factor)
            if record.body.mutation_parent_factor is not None
            else None
        )
        self._assert_branch_lineage_preflight(
            branch=record.body.branch,
            source=source,
            descriptor=record.body.descriptor,
            retrieved_target=target,
            decision_sequence=record.created_sequence - 1,
        )
        if target is not None and (
            target.runtime_profile != profile.handle
            or target.descriptor != record.body.descriptor
            or target.handle == source_factor.handle
        ):
            raise ValueError("branch receipt retrieved target is not a compatible factor")
        if target is not None and (
            target_attestation is None
            or target_attestation.value != target.value
            or target_attestation.source_manifest_sha256
            != source.source_manifest_sha256
            or target_attestation.created_sequence >= record.created_sequence
        ):
            raise ValueError("branch receipt retrieved provenance closure is invalid")
        if parent is not None and parent.handle != source_factor.handle:
            raise ValueError("branch receipt mutation parent is not the exact source")
        if self._branch_receipt_verifier is None:
            raise RuntimeError("persisted branch receipt requires its trusted verifier")
        try:
            verified = bool(self._branch_receipt_verifier(record.body))
        except Exception as exc:
            raise RuntimeError("persisted branch receipt verification failed") from exc
        if not verified:
            raise ValueError("persisted branch/provenance receipt was rejected")
        return record

    @_memoized_registry_resolver("operation_seal")
    def _resolve_seal(self, handle: OperationSealHandle) -> PhaseOperationSealRecord:
        handle = OperationSealHandle.model_validate(handle.model_dump(mode="python"))
        record = self._seals.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("operation seal handle is not registered")
        receipt = self._resolve_branch_receipt(record.branch_receipt)
        source = self._resolve_artifact(record.source_artifact)
        source_factor = self._resolve_factor(record.source_factor)
        target = self._resolve_factor(record.retrieved_target_factor) if record.retrieved_target_factor else None
        target_attestation = (
            self._resolve_attestation(record.retrieved_target_attestation)
            if record.retrieved_target_attestation
            else None
        )
        parent = self._resolve_factor(record.mutation_parent_factor) if record.mutation_parent_factor else None
        identity = {
            "branch_receipt": receipt.handle.handle_id,
            "branch": record.branch,
            "source_artifact": source.handle.handle_id,
            "descriptor": record.descriptor,
            "source_factor": source_factor.handle.handle_id,
            "retrieved_target": target.handle.handle_id if target else None,
            "retrieved_target_attestation": (
                target_attestation.handle.handle_id if target_attestation else None
            ),
            "mutation_parent": parent.handle.handle_id if parent else None,
            "sequence": record.sequence_at_seal,
            "nonce": record.nonce_commitment,
        }
        self._verify_record(record, prefix="os", kind="operation_seal", identity=identity)
        body = receipt.body
        if not (
            record.branch == body.branch
            and record.source_artifact == body.source_artifact
            and record.descriptor == body.descriptor
            and record.source_factor == body.source_factor
            and record.retrieved_target_factor == body.retrieved_target_factor
            and record.retrieved_target_attestation
            == body.retrieved_target_attestation
            and record.mutation_parent_factor == body.mutation_parent_factor
            and receipt.created_sequence < record.sequence_at_seal
            and record.sequence_at_seal <= receipt.expiry_sequence
        ):
            raise ValueError("operation seal differs from its attested branch receipt")
        return record

    @_memoized_registry_resolver("materialization_event")
    def _resolve_event(self, handle: MaterializationEventHandle) -> PhaseMaterializationEventRecord:
        handle = MaterializationEventHandle.model_validate(handle.model_dump(mode="python"))
        record = self._events.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("materialization event handle is not registered")
        identity = {
            "seal": record.operation_seal.handle_id,
            "source": record.source_artifact.handle_id,
            "target": record.target_artifact.handle_id if record.target_artifact else None,
            "source_factor": record.source_factor.handle_id,
            "target_factor": record.target_factor.handle_id if record.target_factor else None,
            "status": record.status,
            "sequence": record.created_sequence,
        }
        self._verify_record(record, prefix="me", kind="materialization_event", identity=identity)
        seal = self._resolve_seal(record.operation_seal)
        source = self._resolve_artifact(record.source_artifact)
        source_factor = self._resolve_factor(record.source_factor)
        if record.target_factor is None:
            raise ValueError("materialization event lacks its target factor")
        target_factor = self._resolve_factor(record.target_factor)
        attestation = self._resolve_attestation(record.target_attestation)
        receipt = self._resolve_branch_receipt(seal.branch_receipt)
        if (
            seal.source_artifact != source.handle
            or seal.source_factor != source_factor.handle
            or attestation.value != target_factor.value
        ):
            raise ValueError("materialization event cross-record closure is invalid")
        if seal.branch == "reuse" and (
            seal.retrieved_target_attestation != attestation.handle
        ):
            raise ValueError("reuse event differs from sealed target provenance")
        if seal.branch in {"mutate", "fresh"}:
            target_value = self._resolve_value(target_factor.value)
            common_generated_closure = bool(
                attestation.operation_seal_id == seal.handle.handle_id
                and attestation.source_artifact_id is None
                and (
                    receipt.body.dependency_factor_ids
                    == (source_factor.handle.handle_id,)
                    if seal.branch == "mutate"
                    else receipt.body.dependency_factor_ids == ()
                )
            )
            if receipt.body.action_transaction_id is None:
                # Non-action generation keeps the strict v7 contract: the
                # value must have been born after this seal and it cannot carry
                # the v8 action terminal.  It may still terminate as an
                # operational no-op, but never as a same/duplicate action no-op.
                generated_closure = bool(
                    common_generated_closure
                    and receipt.body.generation_terminal is None
                    and target_value.first_seen_sequence > seal.sequence_at_seal
                    and record.status
                    not in {"same_value_noop", "duplicate_existing"}
                )
            else:
                terminal = receipt.body.generation_terminal
                generated_closure = bool(
                    common_generated_closure
                    and terminal is not None
                    and terminal.action_transaction_id
                    == receipt.body.action_transaction_id
                    and terminal.action_intent_sha256
                    == receipt.body.action_intent_sha256
                    and terminal.branch == seal.branch
                    and terminal.generated_scalar_sha256
                    == phase_generated_scalar_sha256(target_value.value)
                )
            if not generated_closure:
                raise ValueError(
                    "generated event lost its action terminal/dependency/seal closure"
                )
        if not (
            source.created_sequence < seal.sequence_at_seal
            < record.created_sequence
            and attestation.created_sequence < record.created_sequence
        ):
            raise ValueError("materialization event chronology is invalid")
        source_value = self._resolve_value(source_factor.value)
        target_value = self._resolve_value(target_factor.value)
        same_typed_value = (
            source_value.value == target_value.value
            and type(source_value.value) is type(target_value.value)
        )
        expected_reason = {
            "verified_delta": "exact_typed_factor_delta",
            "same_value_noop": "same_value",
            "operational_noop": "same_execution_image",
            "duplicate_existing": "duplicate_existing",
        }[record.status]
        if record.reason_code != expected_reason:
            raise ValueError("materialization event reason is not reproducible")
        action_bound_generation = bool(
            seal.branch in {"mutate", "fresh"}
            and receipt.body.action_transaction_id is not None
            and receipt.body.generation_terminal is not None
        )
        if record.status == "same_value_noop" and not (
            action_bound_generation and same_typed_value
        ):
            raise ValueError("same-value event is not an exact generated scalar no-op")
        if record.status == "duplicate_existing" and not (
            action_bound_generation
            and not same_typed_value
            and target_value.first_seen_sequence <= seal.sequence_at_seal
        ):
            raise ValueError("duplicate event target was not pre-existing content")
        if record.status == "operational_noop" and same_typed_value:
            raise ValueError("operational no-op must contain a distinct typed scalar")
        if (
            record.status == "operational_noop"
            and seal.branch in {"mutate", "fresh"}
            and target_value.first_seen_sequence <= seal.sequence_at_seal
        ):
            raise ValueError(
                "generated operational no-op cannot relabel pre-existing content"
            )
        if record.status == "operational_noop":
            raw = _replace_pointer(
                source.program.model_dump(mode="json"),
                seal.descriptor.locator.path,
                target_value.value,
            )
            target_program = _validated_program(raw)
            profile = self._resolve_profile(source.runtime_profile)
            compiled = compile_phase_program(
                target_program,
                n_agents=profile.namespace.n_agents,
                limits=profile.limits,
            )
            target_image = _build_execution_image(
                target_program,
                compiled,
                profile.handle.handle_id,
            )
            if target_image != source.execution_image:
                raise ValueError(
                    "operational no-op does not preserve the execution image"
                )
        if record.status == "verified_delta":
            if record.target_artifact is None:
                raise ValueError("verified materialization event lacks its target artifact")
            target_artifact = self._resolve_artifact(record.target_artifact)
            if target_artifact.created_sequence >= record.created_sequence:
                raise ValueError("materialization event predates its target artifact")
        elif record.target_artifact is not None:
            raise ValueError("no-op materialization event cannot own a target artifact")
        return record

    @_memoized_registry_resolver("binding_proof")
    def _resolve_proof(self, handle: PhaseBindingProofHandle) -> PhaseMaterializationProofRecord:
        handle = PhaseBindingProofHandle.model_validate(handle.model_dump(mode="python"))
        record = self._proofs.get(handle.handle_id)
        if record is None or record.handle != handle:
            raise ValueError("binding proof handle is not registered")
        body = _record_body(record)
        proof_sha256 = _sha256(body)
        identity = {"proof_sha256": proof_sha256, "event": record.event.handle_id}
        self._verify_record(record, prefix="bp", kind="phase_binding_proof", identity=identity)
        if not hmac.compare_digest(handle.proof_sha256, proof_sha256):
            raise ValueError("binding proof public digest mismatch")
        return record

    @_registry_verification_scope
    def _verify_state(self) -> None:
        for manifest in self._manifests.values():
            self._verify_manifest(manifest)
        collections = (
            (self._profiles, self.capacity.max_profiles, "profiles"),
            (self._artifacts, self.capacity.max_artifacts, "artifacts"),
            (self._values, self.capacity.max_values, "values"),
            (self._attestations, self.capacity.max_attestations, "attestations"),
            (self._factors, self.capacity.max_factors, "factors"),
            (
                self._branch_receipts,
                self.capacity.max_branch_receipts,
                "branch receipts",
            ),
            (self._seals, self.capacity.max_seals, "seals"),
            (self._events, self.capacity.max_events, "events"),
            (self._proofs, self.capacity.max_proofs, "proofs"),
        )
        for collection, maximum, label in collections:
            if len(collection) > maximum:
                raise ValueError(f"persisted {label} exceed registry capacity")
        for record in self._profiles.values():
            self._resolve_profile(record.handle)
        for record in self._artifacts.values():
            self._resolve_artifact(record.handle)
        for record in self._values.values():
            self._resolve_value(record.handle)
        for record in self._attestations.values():
            self._resolve_attestation(record.handle)
        for record in self._factors.values():
            self._resolve_factor(record.handle)
        for record in self._branch_receipts.values():
            self._resolve_branch_receipt(record.handle)
        used_branch_receipts: set[str] = set()
        for record in self._seals.values():
            self._resolve_seal(record.handle)
            receipt_id = record.branch_receipt.handle_id
            if receipt_id in used_branch_receipts:
                raise ValueError("one branch receipt has multiple persisted seals")
            used_branch_receipts.add(receipt_id)
        seals_with_events: set[str] = set()
        events_by_target: dict[str, list[PhaseMaterializationEventRecord]] = {}
        for record in self._events.values():
            self._resolve_event(record.handle)
            seal_id = record.operation_seal.handle_id
            if seal_id in seals_with_events:
                raise ValueError("one operation seal has multiple persisted events")
            seals_with_events.add(seal_id)
            if record.target_artifact is not None:
                events_by_target.setdefault(
                    record.target_artifact.handle_id, []
                ).append(record)
        proofs_by_event: dict[str, list[PhaseMaterializationProofRecord]] = {}
        for record in self._proofs.values():
            self.verify_phase_materialization_proof(record.handle)
            proofs_by_event.setdefault(record.event.handle_id, []).append(record)
        action_transactions: dict[str, PhaseBranchReceiptRecord] = {}
        generation_terminal_ids: set[str] = set()
        generation_terminal_attestations: set[str] = set()
        generation_lease_ids: set[str] = set()
        seals_by_receipt: dict[str, list[PhaseOperationSealRecord]] = {}
        for seal in self._seals.values():
            seals_by_receipt.setdefault(
                seal.branch_receipt.handle_id, []
            ).append(seal)
        events_by_seal: dict[str, list[PhaseMaterializationEventRecord]] = {}
        for event in self._events.values():
            events_by_seal.setdefault(
                event.operation_seal.handle_id, []
            ).append(event)
        for receipt in self._branch_receipts.values():
            terminal = receipt.body.generation_terminal
            if terminal is not None:
                if (
                    terminal.terminal_id in generation_terminal_ids
                    or terminal.attestation_sha256
                    in generation_terminal_attestations
                    or terminal.generation_lease_id in generation_lease_ids
                ):
                    raise ValueError(
                        "one generation terminal or lease was replayed across receipts"
                    )
                generation_terminal_ids.add(terminal.terminal_id)
                generation_terminal_attestations.add(terminal.attestation_sha256)
                generation_lease_ids.add(terminal.generation_lease_id)
            transaction_id = receipt.body.action_transaction_id
            if transaction_id is None:
                continue
            if transaction_id in action_transactions:
                raise ValueError(
                    "one action transaction owns multiple branch receipts"
                )
            action_transactions[transaction_id] = receipt
            if receipt.body.action_intent_sha256 not in (
                receipt.body.input_root_commitments
            ):
                raise ValueError(
                    "action transaction omits its intent from the input closure"
                )
            transaction_seals = seals_by_receipt.get(
                receipt.handle.handle_id, []
            )
            if len(transaction_seals) != 1:
                raise ValueError(
                    "persisted action transaction lacks one exact seal"
                )
            transaction_events = events_by_seal.get(
                transaction_seals[0].handle.handle_id, []
            )
            if len(transaction_events) != 1:
                raise ValueError(
                    "persisted action transaction lacks one terminal event"
                )
            transaction_event = transaction_events[0]
            if receipt.body.branch in {"mutate", "fresh"}:
                if terminal is None or not (
                    terminal.action_transaction_id == transaction_id
                    and terminal.action_intent_sha256
                    == receipt.body.action_intent_sha256
                    and terminal.branch == receipt.body.branch
                    and terminal.split == "TRAIN_UPDATE"
                ):
                    raise ValueError(
                        "generated action terminal differs from its unique action chain"
                    )
                if transaction_event.target_factor is None:
                    raise ValueError(
                        "generated action terminal lacks its exact target factor"
                    )
                generated_factor = self._resolve_factor(
                    transaction_event.target_factor
                )
                generated_value = self._resolve_value(generated_factor.value)
                if terminal.generated_scalar_sha256 != phase_generated_scalar_sha256(
                    generated_value.value
                ):
                    raise ValueError(
                        "generated action terminal scalar commitment differs from its event target"
                    )
            elif terminal is not None:
                raise ValueError("reuse action cannot own a generation terminal")
            transaction_proofs = proofs_by_event.get(
                transaction_event.handle.handle_id, []
            )
            if transaction_event.status == "verified_delta":
                if len(transaction_proofs) != 1:
                    raise ValueError(
                        "verified action transaction lacks one exact proof"
                    )
            elif transaction_proofs:
                raise ValueError(
                    "no-op action transaction cannot own a binding proof"
                )
        for artifact in self._artifacts.values():
            if artifact.parent_artifact_id is None:
                continue
            matching_events = [
                event
                for event in events_by_target.get(artifact.handle.handle_id, [])
                if event.status == "verified_delta"
                and event.source_artifact.handle_id == artifact.parent_artifact_id
                and event.operation_seal.handle_id
                == artifact.derivation_operation_seal_id
                and event.target_factor is not None
                and event.target_factor.handle_id
                == artifact.derivation_target_factor_id
            ]
            if len(matching_events) != 1:
                raise ValueError(
                    "materialized artifact lacks one exact derivation event"
                )
        for event in self._events.values():
            if event.status == "verified_delta" and len(
                proofs_by_event.get(event.handle.handle_id, [])
            ) != 1:
                raise ValueError("verified materialization event lacks one exact proof")
        sequences = [
            *(item.created_sequence for item in self._artifacts.values()),
            *(item.first_seen_sequence for item in self._values.values()),
            *(item.created_sequence for item in self._attestations.values()),
            *(item.created_sequence for item in self._branch_receipts.values()),
            *(item.sequence_at_seal for item in self._seals.values()),
            *(item.created_sequence for item in self._events.values()),
        ]
        if sequences and max(sequences) > self._sequence:
            raise ValueError("persisted registry sequence is behind its records")

    @_registry_instance_lock
    def to_state(self) -> PhaseArtifactRegistryState:
        state = PhaseArtifactRegistryState(
            sequence=self._sequence,
            capacity=self.capacity,
            manifests=tuple(sorted(self._manifests.values(), key=lambda item: item.manifest_sha256)),
            profiles=tuple(sorted(self._profiles.values(), key=lambda item: item.handle.handle_id)),
            artifacts=tuple(sorted(self._artifacts.values(), key=lambda item: item.handle.handle_id)),
            values=tuple(sorted(self._values.values(), key=lambda item: item.handle.handle_id)),
            attestations=tuple(sorted(self._attestations.values(), key=lambda item: item.handle.handle_id)),
            factors=tuple(sorted(self._factors.values(), key=lambda item: item.handle.handle_id)),
            branch_receipts=tuple(
                sorted(
                    self._branch_receipts.values(),
                    key=lambda item: item.handle.handle_id,
                )
            ),
            seals=tuple(sorted(self._seals.values(), key=lambda item: item.handle.handle_id)),
            events=tuple(sorted(self._events.values(), key=lambda item: item.handle.handle_id)),
            proofs=tuple(sorted(self._proofs.values(), key=lambda item: item.handle.handle_id)),
        )
        # Several upstream PhaseProgram fields are lists.  A frozen Pydantic
        # wrapper does not make those nested containers immutable, so never
        # expose aliases into the authoritative record dictionaries.
        return PhaseArtifactRegistryState.model_validate(
            state.model_dump(mode="python")
        )

    @property
    def scientific_state_sha256(self) -> str:
        return _sha256(self.to_state())

    def _serialized_envelope(self) -> bytes:
        state = self.to_state().model_dump(mode="json")
        envelope = {
            "state": state,
            "state_hmac_sha256": _mac(self._key, "registry-state", state),
        }
        return (
            json.dumps(
                envelope,
                ensure_ascii=True,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def _save_owned_state(self, target: Path) -> None:
        """Persist under an exclusive lock and compare-and-swap ownership."""

        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialized_envelope()
        envelope_sha = hashlib.sha256(payload).hexdigest()
        lock_path = target.with_suffix(target.suffix + ".lock")
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if target.exists():
                current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
                if self._persisted_envelope_sha256 is None:
                    raise RuntimeError(
                        "refusing to overwrite an unowned Phase registry state file"
                    )
                if current_sha != self._persisted_envelope_sha256:
                    raise RuntimeError(
                        "Phase registry changed concurrently; compare-and-swap failed"
                    )
            elif self._persisted_envelope_sha256 is not None:
                raise RuntimeError(
                    "persisted Phase registry disappeared before compare-and-swap"
                )
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
                    # The file body was fsync'd and atomically published.  Some
                    # filesystems do not support directory fsync; raising here
                    # would make the object roll back after the file committed.
                    pass
            finally:
                os.close(directory_fd)
            self._persisted_path = target
            self._persisted_envelope_sha256 = envelope_sha
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @_registry_instance_lock
    def save(self, path: Path | str) -> None:
        target = Path(path).resolve()
        if self._persisted_path is not None and target != self._persisted_path:
            raise RuntimeError("an authoritative Phase registry cannot change its state path")
        self._verify_state()
        self._save_owned_state(target)

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        registry_key: bytes,
        manifest_verifier: Callable[[SourceManifest], bool] | None,
        branch_receipt_verifier: Callable[[PhaseBranchReceiptBody], bool] | None = None,
    ) -> "PhaseArtifactRegistry":
        target = Path(path).resolve()
        raw_bytes = target.read_bytes()
        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict) or set(raw) != {"state", "state_hmac_sha256"}:
            raise ValueError("invalid Phase artifact registry envelope")
        expected = _mac(registry_key, "registry-state", raw["state"])
        if not isinstance(raw["state_hmac_sha256"], str) or not hmac.compare_digest(
            raw["state_hmac_sha256"], expected
        ):
            raise ValueError("Phase artifact registry state MAC mismatch")
        serialized_schema = (
            raw["state"].get("schema_version")
            if isinstance(raw.get("state"), dict)
            else None
        )
        if serialized_schema != PHASE_ARTIFACT_REGISTRY_VERSION:
            raise LegacyPhaseArtifactRegistryRejected(
                "unsupported or legacy Phase artifact registry schema; "
                "explicit migration is required"
            )
        state = PhaseArtifactRegistryState.model_validate(raw["state"])
        registry = cls(
            registry_key=registry_key,
            state=state,
            manifest_verifier=manifest_verifier,
            branch_receipt_verifier=branch_receipt_verifier,
            _restore_token=_AUTHENTICATED_RESTORE_TOKEN,
        )
        registry._persisted_path = target
        registry._persisted_envelope_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return registry


__all__ = [
    "ActivationRequirement",
    "FactorContentHandle",
    "LegacyPhaseArtifactRegistryRejected",
    "MaterializationEventHandle",
    "NoOpMaterialization",
    "OperationSealHandle",
    "PHASE_ACTIVATION_VERSION",
    "PHASE_ARTIFACT_REGISTRY_VERSION",
    "PHASE_EXECUTION_IMAGE_VERSION",
    "PHASE_FACTOR_BINDER_VERSION",
    "PHASE_FULL_FACTOR_BINDER_VERSION",
    "PHASE_MATERIALIZATION_EVENT_DIGEST_VERSION",
    "PhaseArtifactHandle",
    "PhaseArtifactRegistry",
    "PhaseArtifactRegistryState",
    "PhaseBindingProofHandle",
    "PhaseExtractedFactor",
    "PhaseFactorContentRecord",
    "PhaseGenerationTerminalV1",
    "PhaseMaterializationEventRecord",
    "PhaseMaterializationProofRecord",
    "PhaseProgramArtifactRecord",
    "PhaseRuntimeProfileRecord",
    "PhaseSlotDescriptor",
    "PhaseValueHandle",
    "RegistryCapacity",
    "RuntimeProfileHandle",
    "SourceManifest",
    "SourceSplit",
    "ValueAttestationHandle",
    "VerifiedPhaseBinding",
    "phase_generated_scalar_sha256",
    "phase_mutable_factor_paths_v3",
    "phase_materialization_event_sha256_v1",
]
