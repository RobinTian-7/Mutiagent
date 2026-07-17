"""Schema-v2 authenticated runner journal for one exact SFT attempt.

One journal is one bounded Bank attempt: generation is always one and the
complete lifecycle contains at most six events (prepare, two non-overlapping
start/finish pairs, and one terminal).  This makes every accepted lifecycle a
subset of the FactorBank runner language without needing an unbounded log.

Persistence uses two independent authorities.  The JSON file is protected by
HMAC, hash chaining, an OS lock and byte-level compare-and-swap.  A required,
linearizable external checkpoint provider atomically claims every
``current -> proposed`` mutation before the file is replaced.  The provider
keeps that claim pending until an external owner verifies the new file and
acknowledges it.  A pending claim blocks loads and all further mutations.

There is an intentional fail-closed two-phase window: a crash after provider
claim but before file publication leaves a pending claim which requires
external reconciliation.  Silently aborting it would reopen stale-file ABA.

This module records control-plane commitments only.  It neither stores task
content/outcomes nor projects journal terminals into Bank receipts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import fcntl
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exp_graph.mas.factor_bank import (
    ExecutionNamespace,
    PlannerRuntimeMode,
    WorkerContract,
    assert_bank_safe_public_value,
)


SFT_RUNNER_JOURNAL_VERSION = "sft_runner_journal_v2"
SFT_RUNNER_CHECKPOINT_VERSION = "sft_runner_checkpoint_v2"
MAX_JOURNAL_EVENTS = 6

Arm = Literal["source", "target"]
ArmOrder = Literal["AB", "BA"]
SafeFailureCode = Literal[
    "runner_crash",
    "runner_timeout",
    "runner_fenced",
    "executor_unavailable",
    "incomplete_physical_pair",
    "operator_cancelled",
]

_HOST_ID_RE = re.compile(
    r"^(?P<prefix>[a-z]{1,8}):(?:[0-9a-f]{24}|[0-9a-f]{48}|[0-9a-f]{64})$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHENTICATED_RESTORE_TOKEN = object()


class LegacyRunnerJournalRejected(ValueError):
    """A v1 or otherwise unsupported journal cannot gain v2 authority."""


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


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject parser-dependent duplicate object names at every JSON depth."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mac(key: bytes, domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\0" + _canonical_json(value).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


_PUBLIC_FIXED_HMAC_DOMAINS = frozenset(
    {
        "sft-journal-snapshot-reader-v1",
        "sft-scope-manifest-verification-v1",
    }
)


def journal_canonical_sha256_v2(value: Any) -> str:
    """Return the schema-v2 canonical JSON digest used by the journal.

    Adapters use this versioned helper instead of copying the journal's JSON
    normalization rules.  It is a content digest, not an authority proof.
    """

    return _sha256(value)


def journal_fixed_hmac_sha256_v2(
    key: bytes,
    *,
    domain: Literal[
        "sft-journal-snapshot-reader-v1",
        "sft-scope-manifest-verification-v1",
    ],
    value: Any,
) -> str:
    """Authenticate a closed adapter record under one reviewed fixed domain."""

    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("fixed-domain HMAC key must contain at least 32 bytes")
    if domain not in _PUBLIC_FIXED_HMAC_DOMAINS:
        raise ValueError("unreviewed journal adapter HMAC domain")
    return _mac(key, domain, value)


def _require_sha(value: str, name: str) -> None:
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_host_id(
    value: str,
    name: str,
    *,
    allowed_prefixes: tuple[str, ...],
) -> None:
    match = _HOST_ID_RE.fullmatch(value)
    if match is None or match.group("prefix") not in allowed_prefixes:
        expected = "/".join(allowed_prefixes)
        raise ValueError(
            f"{name} must be a host-derived {expected}:<hex> opaque identifier"
        )


def derive_host_opaque_id_v2(prefix: str, commitment_sha256: str) -> str:
    """Derive a semantic-free public ID from an already verified commitment."""

    if not re.fullmatch(r"[a-z]{1,8}", prefix):
        raise ValueError("opaque-id prefix must be one to eight lowercase letters")
    _require_sha(commitment_sha256, "commitment_sha256")
    return f"{prefix}:{_sha256({'domain': 'sft-host-id-v2', 'value': commitment_sha256})[:24]}"


def _reject_explicit_test_label(value: Any) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_explicit_test_label(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_explicit_test_label(item)
        return
    if isinstance(value, str):
        normalized = value.strip().casefold().replace("-", "_")
        if normalized in {"test", "final_test", "heldout_test", "private_test"}:
            raise ValueError("TEST/private split labels are forbidden in the journal")


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def reject_oracle_or_private_values(self) -> "_ClosedModel":
        value = self.model_dump(mode="python")
        assert_bank_safe_public_value(value)
        _reject_explicit_test_label(value)
        return self


class JournalScopeV2(_ClosedModel):
    """Exact execution namespace plus trusted PUBLIC/TRAIN provenance roots."""

    scope_version: Literal["sft_runner_scope_v2"] = "sft_runner_scope_v2"
    namespace: ExecutionNamespace
    namespace_sha256: str
    planner_mode: PlannerRuntimeMode
    information_goal: Literal["sink", "all_agents"]
    worker_contract: WorkerContract
    mode_payload_sha256: str
    mode_payload_source: Literal["PUBLIC", "TRAIN_UPDATE"]
    mode_payload_manifest_sha256: str
    runner_policy_sha256: str

    @model_validator(mode="after")
    def validate_scope(self) -> "JournalScopeV2":
        for name in (
            "namespace_sha256",
            "mode_payload_sha256",
            "mode_payload_manifest_sha256",
            "runner_policy_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.namespace_sha256 != self.namespace.digest:
            raise ValueError("journal namespace digest is not reproducible")
        if self.planner_mode != self.namespace.planner_mode:
            raise ValueError("journal planner mode differs from its namespace")
        if self.information_goal != self.namespace.information_goal:
            raise ValueError("journal information goal differs from its namespace")
        if self.worker_contract != self.namespace.worker_contract:
            raise ValueError("journal worker contract differs from its namespace")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class EventRefV2(_ClosedModel):
    event_id: str
    event_sha256: str

    @model_validator(mode="after")
    def validate_ref(self) -> "EventRefV2":
        _require_host_id(self.event_id, "event_id", allowed_prefixes=("je",))
        _require_sha(self.event_sha256, "event_sha256")
        return self


class PreparePayloadV2(_ClosedModel):
    kind: Literal["prepare"] = "prepare"
    attempt_id: str
    plan_id: str
    ordinal: int = Field(ge=0, le=5)
    assignment_receipt_sha256: str
    expected_open_attempt_sha256: str
    scheduled_arm_order: ArmOrder
    runner_session_id: str
    runner_lease_token_sha256: str
    verifier_epoch_sha256: str
    source_arm_commitment_sha256: str
    target_arm_commitment_sha256: str

    @model_validator(mode="after")
    def validate_prepare(self) -> "PreparePayloadV2":
        _require_host_id(self.attempt_id, "attempt_id", allowed_prefixes=("at",))
        _require_host_id(self.plan_id, "plan_id", allowed_prefixes=("pp", "pl"))
        _require_host_id(
            self.runner_session_id,
            "runner_session_id",
            allowed_prefixes=("rs",),
        )
        for name in (
            "assignment_receipt_sha256",
            "expected_open_attempt_sha256",
            "runner_lease_token_sha256",
            "verifier_epoch_sha256",
            "source_arm_commitment_sha256",
            "target_arm_commitment_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.source_arm_commitment_sha256 == self.target_arm_commitment_sha256:
            raise ValueError("paired arms require distinct input commitments")
        return self


class ArmStartedPayloadV2(_ClosedModel):
    kind: Literal["arm_started"] = "arm_started"
    attempt_id: str
    prepare: EventRefV2
    arm: Arm
    physical_root_id: str
    runner_session_id: str
    runner_lease_token_sha256: str

    @model_validator(mode="after")
    def validate_start(self) -> "ArmStartedPayloadV2":
        _require_host_id(self.attempt_id, "attempt_id", allowed_prefixes=("at",))
        _require_host_id(
            self.runner_session_id,
            "runner_session_id",
            allowed_prefixes=("rs",),
        )
        _require_sha(self.physical_root_id, "physical_root_id")
        _require_sha(self.runner_lease_token_sha256, "runner_lease_token_sha256")
        return self


class ArmFinishedPayloadV2(_ClosedModel):
    kind: Literal["arm_finished"] = "arm_finished"
    attempt_id: str
    prepare: EventRefV2
    arm: Arm
    start: EventRefV2
    physical_root_id: str

    @model_validator(mode="after")
    def validate_finish(self) -> "ArmFinishedPayloadV2":
        _require_host_id(self.attempt_id, "attempt_id", allowed_prefixes=("at",))
        _require_sha(self.physical_root_id, "physical_root_id")
        return self


class PairCompletePayloadV2(_ClosedModel):
    kind: Literal["pair_complete"] = "pair_complete"
    attempt_id: str
    prepare: EventRefV2
    source_started: EventRefV2
    source_finished: EventRefV2
    target_started: EventRefV2
    target_finished: EventRefV2
    source_root_id: str
    target_root_id: str
    observed_arm_order: ArmOrder

    @model_validator(mode="after")
    def validate_complete(self) -> "PairCompletePayloadV2":
        _require_host_id(self.attempt_id, "attempt_id", allowed_prefixes=("at",))
        _require_sha(self.source_root_id, "source_root_id")
        _require_sha(self.target_root_id, "target_root_id")
        if self.source_root_id == self.target_root_id:
            raise ValueError("paired completion requires distinct physical roots")
        refs = (
            self.source_started,
            self.source_finished,
            self.target_started,
            self.target_finished,
        )
        if len({item.event_id for item in refs}) != len(refs):
            raise ValueError("pair completion needs four distinct lifecycle events")
        return self


class AttemptCancelledPayloadV2(_ClosedModel):
    kind: Literal["attempt_cancelled"] = "attempt_cancelled"
    attempt_id: str
    prepare: EventRefV2
    started: tuple[EventRefV2, ...] = Field(default=(), max_length=2)
    finished: tuple[EventRefV2, ...] = Field(default=(), max_length=2)
    safe_failure_code: SafeFailureCode
    terminate_scope: Literal[True] = True

    @model_validator(mode="after")
    def validate_cancel(self) -> "AttemptCancelledPayloadV2":
        _require_host_id(self.attempt_id, "attempt_id", allowed_prefixes=("at",))
        if len({item.event_id for item in self.started}) != len(self.started):
            raise ValueError("cancellation contains duplicate start events")
        if len({item.event_id for item in self.finished}) != len(self.finished):
            raise ValueError("cancellation contains duplicate finish events")
        return self


JournalPayloadV2 = Annotated[
    PreparePayloadV2
    | ArmStartedPayloadV2
    | ArmFinishedPayloadV2
    | PairCompletePayloadV2
    | AttemptCancelledPayloadV2,
    Field(discriminator="kind"),
]


class JournalEventV2(_ClosedModel):
    event_version: Literal["sft_runner_event_v2"] = "sft_runner_event_v2"
    event_id: str
    sequence: int = Field(ge=1, le=MAX_JOURNAL_EVENTS)
    fencing_generation: Literal[1] = 1
    previous_event_sha256: str
    payload: JournalPayloadV2
    event_body_sha256: str
    event_hmac_sha256: str

    @property
    def body(self) -> dict[str, Any]:
        return {
            "event_version": self.event_version,
            "sequence": self.sequence,
            "fencing_generation": self.fencing_generation,
            "previous_event_sha256": self.previous_event_sha256,
            "payload": self.payload,
        }

    @property
    def digest(self) -> str:
        return _sha256(self)

    @property
    def ref(self) -> EventRefV2:
        return EventRefV2(event_id=self.event_id, event_sha256=self.digest)

    @model_validator(mode="after")
    def validate_event(self) -> "JournalEventV2":
        _require_host_id(self.event_id, "event_id", allowed_prefixes=("je",))
        for name in (
            "previous_event_sha256",
            "event_body_sha256",
            "event_hmac_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        expected_body = _sha256(self.body)
        if self.event_body_sha256 != expected_body:
            raise ValueError("runner event body digest is not reproducible")
        if self.event_id != f"je:{expected_body[:24]}":
            raise ValueError("runner event identity is not reproducible")
        return self


class RunnerJournalStateV2(_ClosedModel):
    schema_version: Literal[SFT_RUNNER_JOURNAL_VERSION] = SFT_RUNNER_JOURNAL_VERSION
    journal_id: str
    scope: JournalScopeV2
    sequence: int = Field(default=0, ge=0, le=MAX_JOURNAL_EVENTS)
    fencing_generation: Literal[0, 1] = 0
    genesis_sha256: str
    head_event_sha256: str
    events: tuple[JournalEventV2, ...] = Field(
        default=(),
        max_length=MAX_JOURNAL_EVENTS,
    )

    @model_validator(mode="after")
    def validate_structure(self) -> "RunnerJournalStateV2":
        _require_host_id(self.journal_id, "journal_id", allowed_prefixes=("jr",))
        _require_sha(self.genesis_sha256, "genesis_sha256")
        _require_sha(self.head_event_sha256, "head_event_sha256")
        if self.sequence != len(self.events):
            raise ValueError("runner journal sequence differs from event count")
        if tuple(item.sequence for item in self.events) != tuple(
            range(1, self.sequence + 1)
        ):
            raise ValueError("runner journal event sequence is not contiguous")
        expected_head = self.events[-1].digest if self.events else self.genesis_sha256
        if self.head_event_sha256 != expected_head:
            raise ValueError("runner journal head differs from its event chain")
        n_prepare = sum(item.payload.kind == "prepare" for item in self.events)
        if n_prepare > 1:
            raise ValueError("one runner journal may contain only one attempt")
        if self.events and self.events[0].payload.kind != "prepare":
            raise ValueError("the first runner journal event must prepare its attempt")
        if self.fencing_generation != (1 if n_prepare else 0):
            raise ValueError("single-attempt fencing generation must be exactly one")
        return self

    @property
    def digest(self) -> str:
        return _sha256(self)


class RunnerJournalEnvelopeV2(_ClosedModel):
    state: RunnerJournalStateV2
    state_sha256: str
    state_hmac_sha256: str

    @model_validator(mode="after")
    def validate_envelope(self) -> "RunnerJournalEnvelopeV2":
        _require_sha(self.state_sha256, "state_sha256")
        _require_sha(self.state_hmac_sha256, "state_hmac_sha256")
        if self.state_sha256 != self.state.digest:
            raise ValueError("runner journal state digest mismatch")
        return self


class JournalCheckpointV2(_ClosedModel):
    checkpoint_version: Literal[SFT_RUNNER_CHECKPOINT_VERSION] = (
        SFT_RUNNER_CHECKPOINT_VERSION
    )
    journal_id: str
    scope_sha256: str
    sequence: int = Field(ge=0, le=MAX_JOURNAL_EVENTS)
    fencing_generation: Literal[0, 1]
    head_event_sha256: str
    state_sha256: str
    checkpoint_hmac_sha256: str

    @property
    def body(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"checkpoint_hmac_sha256"})

    @property
    def digest(self) -> str:
        return _sha256(self)

    @model_validator(mode="after")
    def validate_checkpoint(self) -> "JournalCheckpointV2":
        _require_host_id(self.journal_id, "journal_id", allowed_prefixes=("jr",))
        for name in (
            "scope_sha256",
            "head_event_sha256",
            "state_sha256",
            "checkpoint_hmac_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self


class CheckpointUpdateClaimV2(_ClosedModel):
    claim_version: Literal["sft_checkpoint_claim_v2"] = "sft_checkpoint_claim_v2"
    claim_token_sha256: str
    journal_id: str
    expected_checkpoint: JournalCheckpointV2
    proposed_checkpoint: JournalCheckpointV2
    provider_epoch_sha256: str

    @model_validator(mode="after")
    def validate_claim(self) -> "CheckpointUpdateClaimV2":
        _require_sha(self.claim_token_sha256, "claim_token_sha256")
        _require_host_id(self.journal_id, "journal_id", allowed_prefixes=("jr",))
        _require_sha(self.provider_epoch_sha256, "provider_epoch_sha256")
        if not (
            self.expected_checkpoint.journal_id == self.journal_id
            and self.proposed_checkpoint.journal_id == self.journal_id
        ):
            raise ValueError("checkpoint claim crosses journal identities")
        if self.proposed_checkpoint.sequence <= self.expected_checkpoint.sequence:
            raise ValueError("checkpoint claim must advance the journal")
        return self


class CheckpointProviderSnapshotV2(_ClosedModel):
    snapshot_version: Literal["sft_checkpoint_provider_snapshot_v2"] = (
        "sft_checkpoint_provider_snapshot_v2"
    )
    journal_id: str
    provider_epoch_sha256: str
    latest_checkpoint: JournalCheckpointV2 | None
    pending_claim: CheckpointUpdateClaimV2 | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> "CheckpointProviderSnapshotV2":
        _require_host_id(self.journal_id, "journal_id", allowed_prefixes=("jr",))
        _require_sha(self.provider_epoch_sha256, "provider_epoch_sha256")
        if self.latest_checkpoint is not None and (
            self.latest_checkpoint.journal_id != self.journal_id
        ):
            raise ValueError("provider latest checkpoint crosses journal identities")
        if self.pending_claim is not None and (
            self.pending_claim.journal_id != self.journal_id
            or self.latest_checkpoint is None
            or self.pending_claim.expected_checkpoint != self.latest_checkpoint
        ):
            raise ValueError("provider pending claim is not based on its latest checkpoint")
        return self


class LatestCheckpointProviderV2(Protocol):
    """Trusted linearizable authority; acknowledgement is external to journal."""

    def inspect(self, journal_id: str) -> CheckpointProviderSnapshotV2:
        ...

    def claim_update(
        self,
        *,
        journal_id: str,
        expected_checkpoint: JournalCheckpointV2,
        proposed_checkpoint: JournalCheckpointV2,
    ) -> CheckpointUpdateClaimV2:
        ...


def _event_ref(event: JournalEventV2) -> EventRefV2:
    return event.ref


def _verify_runner_state_v2(
    state: RunnerJournalStateV2,
    *,
    journal_key: bytes,
) -> None:
    """Verify the complete authenticated single-attempt lifecycle."""

    state = RunnerJournalStateV2.model_validate(state.model_dump(mode="python"))
    expected_genesis = _mac(
        journal_key,
        "sft-runner-journal-v2-genesis",
        {"journal_id": state.journal_id, "scope": state.scope},
    )
    if not hmac.compare_digest(state.genesis_sha256, expected_genesis):
        raise ValueError("runner journal genesis HMAC mismatch")
    previous = state.genesis_sha256
    seen_ids: set[str] = set()
    prepare_event: JournalEventV2 | None = None
    starts: dict[Arm, JournalEventV2] = {}
    finishes: dict[Arm, JournalEventV2] = {}
    started_order: list[Arm] = []
    open_arm: Arm | None = None
    terminal: JournalEventV2 | None = None
    for event in state.events:
        if event.event_id in seen_ids:
            raise ValueError("runner journal contains a duplicate event identity")
        seen_ids.add(event.event_id)
        if event.previous_event_sha256 != previous:
            raise ValueError("runner journal event chain was reordered or truncated")
        expected_event_mac = _mac(journal_key, "sft-runner-v2-event", event.body)
        if not hmac.compare_digest(event.event_hmac_sha256, expected_event_mac):
            raise ValueError("runner journal event HMAC mismatch")
        payload = event.payload
        if payload.kind == "prepare":
            if prepare_event is not None or event.sequence != 1:
                raise ValueError("one journal admits one first-event prepare")
            prepare_event = event
        else:
            if prepare_event is None:
                raise ValueError("runner lifecycle event precedes its prepare")
            prepare = prepare_event.payload
            assert isinstance(prepare, PreparePayloadV2)
            if payload.attempt_id != prepare.attempt_id:
                raise ValueError("runner lifecycle crossed attempt identities")
            if payload.prepare != _event_ref(prepare_event):
                raise ValueError("runner lifecycle does not join its exact prepare")
            if terminal is not None:
                raise ValueError("runner lifecycle continued after its terminal")
            scheduled: tuple[Arm, Arm] = (
                ("source", "target")
                if prepare.scheduled_arm_order == "AB"
                else ("target", "source")
            )
            if payload.kind == "arm_started":
                expected_index = len(started_order)
                if expected_index >= 2 or payload.arm != scheduled[expected_index]:
                    raise ValueError("arm start is outside the scheduled prefix")
                if open_arm is not None:
                    raise ValueError("paired physical arms may not overlap")
                if not (
                    payload.runner_session_id == prepare.runner_session_id
                    and payload.runner_lease_token_sha256
                    == prepare.runner_lease_token_sha256
                ):
                    raise ValueError("arm start differs from its prepared lease")
                if any(
                    item.payload.physical_root_id == payload.physical_root_id
                    for item in starts.values()
                ):
                    raise ValueError("source and target cannot share a physical root")
                starts[payload.arm] = event
                started_order.append(payload.arm)
                open_arm = payload.arm
            elif payload.kind == "arm_finished":
                start_event = starts.get(payload.arm)
                if start_event is None or open_arm != payload.arm:
                    raise ValueError("arm finish is outside the active scheduled prefix")
                start = start_event.payload
                assert isinstance(start, ArmStartedPayloadV2)
                if (
                    payload.start != _event_ref(start_event)
                    or payload.physical_root_id != start.physical_root_id
                ):
                    raise ValueError("arm finish differs from its exact start/root")
                if payload.arm in finishes:
                    raise ValueError("one physical arm was finished more than once")
                finishes[payload.arm] = event
                open_arm = None
            elif payload.kind == "pair_complete":
                if started_order != list(scheduled) or open_arm is not None:
                    raise ValueError("pair terminal lacks a non-overlapping schedule")
                if set(finishes) != {"source", "target"}:
                    raise ValueError("pair completion requires both exact finishes")
                source_start = starts["source"]
                target_start = starts["target"]
                source_finish = finishes["source"]
                target_finish = finishes["target"]
                source = source_start.payload
                target = target_start.payload
                assert isinstance(source, ArmStartedPayloadV2)
                assert isinstance(target, ArmStartedPayloadV2)
                if not (
                    payload.source_started == _event_ref(source_start)
                    and payload.source_finished == _event_ref(source_finish)
                    and payload.target_started == _event_ref(target_start)
                    and payload.target_finished == _event_ref(target_finish)
                    and payload.source_root_id == source.physical_root_id
                    and payload.target_root_id == target.physical_root_id
                    and payload.observed_arm_order == prepare.scheduled_arm_order
                ):
                    raise ValueError("pair terminal does not close its exact schedule")
                terminal = event
            elif payload.kind == "attempt_cancelled":
                expected_started = tuple(
                    _event_ref(starts[arm]) for arm in started_order
                )
                expected_finished = tuple(
                    _event_ref(finishes[arm])
                    for arm in started_order
                    if arm in finishes
                )
                if (
                    tuple(started_order) != scheduled[: len(started_order)]
                    or payload.started != expected_started
                    or payload.finished != expected_finished
                ):
                    raise ValueError("cancellation is not the exact scheduled prefix")
                terminal = event
            else:  # pragma: no cover - discriminated union is exhaustive
                raise AssertionError(payload.kind)
        previous = event.digest


def _checkpoint_for_state_v2(
    state: RunnerJournalStateV2,
    *,
    journal_key: bytes,
) -> JournalCheckpointV2:
    body = {
        "checkpoint_version": SFT_RUNNER_CHECKPOINT_VERSION,
        "journal_id": state.journal_id,
        "scope_sha256": state.scope.digest,
        "sequence": state.sequence,
        "fencing_generation": state.fencing_generation,
        "head_event_sha256": state.head_event_sha256,
        "state_sha256": state.digest,
    }
    return JournalCheckpointV2(
        **body,
        checkpoint_hmac_sha256=_mac(
            journal_key,
            "sft-runner-v2-checkpoint",
            body,
        ),
    )


def verify_runner_journal_envelope_bytes_v2(
    raw_bytes: bytes,
    *,
    journal_key: bytes,
    expected_journal_id: str,
    expected_scope: JournalScopeV2,
) -> tuple[RunnerJournalEnvelopeV2, JournalCheckpointV2]:
    """Authenticate one exact envelope without constructing a writer.

    The expected journal identity and scope are mandatory host inputs.  This
    function therefore cannot turn a detached state plus an arbitrary key into
    authority; external checkpoint and manifest authority remain the caller's
    separate responsibility.
    """

    if not isinstance(raw_bytes, bytes):
        raise TypeError("raw_bytes must be exact journal envelope bytes")
    if not isinstance(journal_key, bytes) or len(journal_key) < 32:
        raise ValueError("journal_key must contain at least 32 bytes")
    _require_host_id(
        expected_journal_id,
        "expected_journal_id",
        allowed_prefixes=("jr",),
    )
    raw = json.loads(raw_bytes, object_pairs_hook=_reject_duplicate_json_pairs)
    version = (
        raw.get("state", {}).get("schema_version")
        if isinstance(raw, dict) and isinstance(raw.get("state"), dict)
        else None
    )
    if version != SFT_RUNNER_JOURNAL_VERSION:
        raise LegacyRunnerJournalRejected(
            "unsupported/v1 runner journal cannot gain schema-v2 authority"
        )
    envelope = RunnerJournalEnvelopeV2.model_validate(raw)
    if envelope.state.journal_id != expected_journal_id:
        raise ValueError("runner journal persisted identity differs from expected")
    if envelope.state.scope != expected_scope:
        raise ValueError("runner journal persisted scope differs from expected scope")
    expected_state_mac = _mac(
        journal_key,
        "sft-runner-v2-state",
        envelope.state,
    )
    if not hmac.compare_digest(envelope.state_hmac_sha256, expected_state_mac):
        raise ValueError("runner journal state HMAC mismatch")
    _verify_runner_state_v2(envelope.state, journal_key=journal_key)
    checkpoint = _checkpoint_for_state_v2(
        envelope.state,
        journal_key=journal_key,
    )
    return envelope, checkpoint


class SFTRunnerJournal:
    """Bounded one-attempt runner journal with externally fenced persistence."""

    def __init__(
        self,
        *,
        journal_key: bytes,
        journal_id: str,
        scope: JournalScopeV2 | None,
        checkpoint_provider: LatestCheckpointProviderV2,
        scope_manifest_verifier: Callable[[JournalScopeV2], bool],
        _state: RunnerJournalStateV2 | None = None,
        _restore_token: object | None = None,
    ) -> None:
        if not isinstance(journal_key, bytes) or len(journal_key) < 32:
            raise ValueError("journal_key must contain at least 32 bytes")
        _require_host_id(journal_id, "journal_id", allowed_prefixes=("jr",))
        if checkpoint_provider is None:
            raise ValueError("a trusted latest-checkpoint provider is required")
        if scope_manifest_verifier is None:
            raise ValueError("a trusted scope manifest verifier is required")
        if _state is not None and _restore_token is not _AUTHENTICATED_RESTORE_TOKEN:
            raise ValueError("detached runner journal state is not authoritative")
        if _state is None and scope is None:
            raise ValueError("a new runner journal requires its immutable scope")
        if _state is not None and scope is not None and _state.scope != scope:
            raise ValueError("restored runner journal scope differs from caller scope")
        self._key = bytes(journal_key)
        self._checkpoint_provider = checkpoint_provider
        self._scope_manifest_verifier = scope_manifest_verifier
        if _state is None:
            assert scope is not None
            genesis = _mac(
                self._key,
                "sft-runner-journal-v2-genesis",
                {"journal_id": journal_id, "scope": scope},
            )
            _state = RunnerJournalStateV2(
                journal_id=journal_id,
                scope=scope,
                genesis_sha256=genesis,
                head_event_sha256=genesis,
            )
        if _state.journal_id != journal_id:
            raise ValueError("restored runner journal identity mismatch")
        self._state = RunnerJournalStateV2.model_validate(
            _state.model_dump(mode="python")
        )
        self._mutation_lock = threading.RLock()
        self._persisted_path: Path | None = None
        self._persisted_envelope_sha256: str | None = None
        self._verify_scope_manifest()
        self._verify_state()

    @property
    def state(self) -> RunnerJournalStateV2:
        return self._state.model_copy(deep=True)

    @property
    def scientific_state_sha256(self) -> str:
        return self._state.digest

    @property
    def head_event_sha256(self) -> str:
        return self._state.head_event_sha256

    def _verify_scope_manifest(self) -> None:
        try:
            accepted = bool(self._scope_manifest_verifier(self._state.scope))
        except Exception as exc:
            raise RuntimeError("trusted scope manifest verification failed") from exc
        if not accepted:
            raise ValueError("scope PUBLIC/TRAIN manifest was rejected")

    def _event_by_kind(self, kind: str) -> list[JournalEventV2]:
        return [item for item in self._state.events if item.payload.kind == kind]

    def _prepare_event(self) -> JournalEventV2 | None:
        items = self._event_by_kind("prepare")
        return items[0] if items else None

    def terminal_for_attempt(self, attempt_id: str) -> JournalEventV2 | None:
        _require_host_id(attempt_id, "attempt_id", allowed_prefixes=("at",))
        return next(
            (
                item
                for item in self._state.events
                if item.payload.kind in {"pair_complete", "attempt_cancelled"}
                and item.payload.attempt_id == attempt_id
            ),
            None,
        )

    def get_event(self, event_id: str) -> JournalEventV2:
        _require_host_id(event_id, "event_id", allowed_prefixes=("je",))
        event = next(
            (item for item in self._state.events if item.event_id == event_id),
            None,
        )
        if event is None:
            raise KeyError(event_id)
        return JournalEventV2.model_validate(event.model_dump(mode="python"))

    @staticmethod
    def _scheduled_arms(order: ArmOrder) -> tuple[Arm, Arm]:
        return ("source", "target") if order == "AB" else ("target", "source")

    def _verify_state(self) -> None:
        _verify_runner_state_v2(self._state, journal_key=self._key)

    def checkpoint(self) -> JournalCheckpointV2:
        return _checkpoint_for_state_v2(self._state, journal_key=self._key)

    def _validate_checkpoint(self, checkpoint: JournalCheckpointV2) -> None:
        checkpoint = JournalCheckpointV2.model_validate(
            checkpoint.model_dump(mode="python")
        )
        expected = _mac(
            self._key,
            "sft-runner-v2-checkpoint",
            checkpoint.body,
        )
        if not hmac.compare_digest(checkpoint.checkpoint_hmac_sha256, expected):
            raise ValueError("runner journal checkpoint HMAC mismatch")

    def _provider_snapshot(self) -> CheckpointProviderSnapshotV2:
        try:
            raw = self._checkpoint_provider.inspect(self._state.journal_id)
        except Exception as exc:
            raise RuntimeError("latest-checkpoint provider inspection failed") from exc
        snapshot = CheckpointProviderSnapshotV2.model_validate(
            raw.model_dump(mode="python") if isinstance(raw, BaseModel) else raw
        )
        if snapshot.journal_id != self._state.journal_id:
            raise ValueError("checkpoint provider returned the wrong journal")
        if snapshot.latest_checkpoint is not None:
            self._validate_checkpoint(snapshot.latest_checkpoint)
        if snapshot.pending_claim is not None:
            self._validate_checkpoint(snapshot.pending_claim.expected_checkpoint)
            self._validate_checkpoint(snapshot.pending_claim.proposed_checkpoint)
        return snapshot

    def _require_provider_current(self, expected: JournalCheckpointV2) -> None:
        self._validate_checkpoint(expected)
        snapshot = self._provider_snapshot()
        if snapshot.pending_claim is not None:
            raise RuntimeError(
                "external checkpoint update awaits owner acknowledgement"
            )
        if snapshot.latest_checkpoint != expected:
            raise RuntimeError(
                "external latest checkpoint differs from the exact journal state"
            )

    def _claim_update(
        self,
        *,
        expected: JournalCheckpointV2,
        proposed: JournalCheckpointV2,
    ) -> CheckpointUpdateClaimV2:
        try:
            raw = self._checkpoint_provider.claim_update(
                journal_id=self._state.journal_id,
                expected_checkpoint=expected,
                proposed_checkpoint=proposed,
            )
        except Exception as exc:
            raise RuntimeError("external checkpoint update claim failed") from exc
        claim = CheckpointUpdateClaimV2.model_validate(
            raw.model_dump(mode="python") if isinstance(raw, BaseModel) else raw
        )
        if not (
            claim.journal_id == self._state.journal_id
            and claim.expected_checkpoint == expected
            and claim.proposed_checkpoint == proposed
        ):
            raise ValueError("checkpoint provider claim differs from requested update")
        return claim

    def _append(self, payload: JournalPayloadV2) -> JournalEventV2:
        if self._state.sequence >= MAX_JOURNAL_EVENTS:
            raise RuntimeError("single-attempt journal event capacity is exhausted")
        sequence = self._state.sequence + 1
        body = {
            "event_version": "sft_runner_event_v2",
            "sequence": sequence,
            "fencing_generation": 1,
            "previous_event_sha256": self._state.head_event_sha256,
            "payload": payload,
        }
        body_sha = _sha256(body)
        event = JournalEventV2(
            event_id=f"je:{body_sha[:24]}",
            **body,
            event_body_sha256=body_sha,
            event_hmac_sha256=_mac(self._key, "sft-runner-v2-event", body),
        )
        self._state = RunnerJournalStateV2(
            journal_id=self._state.journal_id,
            scope=self._state.scope,
            sequence=sequence,
            fencing_generation=1,
            genesis_sha256=self._state.genesis_sha256,
            head_event_sha256=event.digest,
            events=(*self._state.events, event),
        )
        return event

    def _commit_new_event(
        self,
        *,
        resolve_existing: Callable[[], JournalEventV2 | None],
        build_payload: Callable[[], JournalPayloadV2],
    ) -> JournalEventV2:
        with self._mutation_lock:
            existing = resolve_existing()
            if existing is not None:
                return existing
            if self._persisted_path is None:
                raise RuntimeError(
                    "runner journal must persist its empty checkpoint before mutation"
                )
            self._verify_scope_manifest()
            current = self.checkpoint()
            self._require_provider_current(current)
            snapshot = (
                self._state,
                self._persisted_path,
                self._persisted_envelope_sha256,
            )
            try:
                payload = build_payload()
                event = self._append(payload)
                self._verify_state()
                proposed = self.checkpoint()
                self._claim_update(expected=current, proposed=proposed)
                assert self._persisted_path is not None
                self._save_owned_state(self._persisted_path)
                return event
            except Exception:
                (
                    self._state,
                    self._persisted_path,
                    self._persisted_envelope_sha256,
                ) = snapshot
                # A provider claim may now be pending even if file publication
                # failed.  Leaving it pending is the fail-closed 2PC outcome.
                raise

    def prepare_attempt(self, intent: PreparePayloadV2) -> JournalEventV2:
        intent = PreparePayloadV2.model_validate(intent.model_dump(mode="python"))

        def existing() -> JournalEventV2 | None:
            prepared = self._prepare_event()
            if prepared is None:
                return None
            if prepared.payload == intent:
                return prepared
            raise ValueError("one journal cannot prepare a second or different attempt")

        return self._commit_new_event(
            resolve_existing=existing,
            build_payload=lambda: intent,
        )

    def start_arm(
        self,
        attempt_id: str,
        *,
        arm: Arm,
        physical_root_id: str,
    ) -> JournalEventV2:
        _require_host_id(attempt_id, "attempt_id", allowed_prefixes=("at",))
        _require_sha(physical_root_id, "physical_root_id")

        def existing() -> JournalEventV2 | None:
            prior = next(
                (
                    item
                    for item in self._event_by_kind("arm_started")
                    if item.payload.arm == arm
                ),
                None,
            )
            if prior is None:
                return None
            if prior.payload.attempt_id != attempt_id:
                raise ValueError("arm start idempotence crossed attempt identities")
            if prior.payload.physical_root_id == physical_root_id:
                return prior
            raise ValueError("physical arm already started under a different root")

        def build() -> JournalPayloadV2:
            prepare_event = self._prepare_event()
            if prepare_event is None:
                raise ValueError("arm start requires the exact prepared attempt")
            prepare = prepare_event.payload
            assert isinstance(prepare, PreparePayloadV2)
            if prepare.attempt_id != attempt_id:
                raise ValueError("arm start crossed attempt identities")
            if self.terminal_for_attempt(attempt_id) is not None:
                raise ValueError("terminal attempt cannot start another arm")
            starts = self._event_by_kind("arm_started")
            finishes = self._event_by_kind("arm_finished")
            scheduled = self._scheduled_arms(prepare.scheduled_arm_order)
            if len(starts) >= 2 or arm != scheduled[len(starts)]:
                raise ValueError("arm start is outside the scheduled prefix")
            if starts and len(finishes) != len(starts):
                raise ValueError("second arm cannot start before the first arm finishes")
            if any(item.payload.physical_root_id == physical_root_id for item in starts):
                raise ValueError("source and target cannot share a physical root")
            return ArmStartedPayloadV2(
                attempt_id=attempt_id,
                prepare=_event_ref(prepare_event),
                arm=arm,
                physical_root_id=physical_root_id,
                runner_session_id=prepare.runner_session_id,
                runner_lease_token_sha256=prepare.runner_lease_token_sha256,
            )

        return self._commit_new_event(
            resolve_existing=existing,
            build_payload=build,
        )

    def finish_arm(self, attempt_id: str, *, arm: Arm) -> JournalEventV2:
        _require_host_id(attempt_id, "attempt_id", allowed_prefixes=("at",))

        def existing() -> JournalEventV2 | None:
            prior = next(
                (
                    item
                    for item in self._event_by_kind("arm_finished")
                    if item.payload.arm == arm
                ),
                None,
            )
            if prior is not None and prior.payload.attempt_id != attempt_id:
                raise ValueError("arm finish idempotence crossed attempt identities")
            return prior

        def build() -> JournalPayloadV2:
            prepare_event = self._prepare_event()
            if prepare_event is None:
                raise ValueError("arm finish requires the exact prepared attempt")
            prepare = prepare_event.payload
            assert isinstance(prepare, PreparePayloadV2)
            if prepare.attempt_id != attempt_id:
                raise ValueError("arm finish crossed attempt identities")
            if self.terminal_for_attempt(attempt_id) is not None:
                raise ValueError("terminal attempt cannot finish another arm")
            start = next(
                (
                    item
                    for item in self._event_by_kind("arm_started")
                    if item.payload.arm == arm
                ),
                None,
            )
            if start is None:
                raise ValueError("arm finish requires its exact scheduled start")
            starts = self._event_by_kind("arm_started")
            finishes = self._event_by_kind("arm_finished")
            if starts[-1] != start or len(finishes) != len(starts) - 1:
                raise ValueError("arm finish is outside the active non-overlapping prefix")
            start_payload = start.payload
            assert isinstance(start_payload, ArmStartedPayloadV2)
            return ArmFinishedPayloadV2(
                attempt_id=attempt_id,
                prepare=_event_ref(prepare_event),
                arm=arm,
                start=_event_ref(start),
                physical_root_id=start_payload.physical_root_id,
            )

        return self._commit_new_event(
            resolve_existing=existing,
            build_payload=build,
        )

    def complete_pair(self, attempt_id: str) -> JournalEventV2:
        _require_host_id(attempt_id, "attempt_id", allowed_prefixes=("at",))

        def existing() -> JournalEventV2 | None:
            terminal = self.terminal_for_attempt(attempt_id)
            if terminal is None:
                return None
            if terminal.payload.kind == "pair_complete":
                return terminal
            raise ValueError("cancelled attempt cannot complete")

        def build() -> JournalPayloadV2:
            prepare_event = self._prepare_event()
            if prepare_event is None:
                raise ValueError("pair completion requires the exact prepared attempt")
            prepare = prepare_event.payload
            assert isinstance(prepare, PreparePayloadV2)
            if prepare.attempt_id != attempt_id:
                raise ValueError("pair completion crossed attempt identities")
            starts = {
                item.payload.arm: item for item in self._event_by_kind("arm_started")
            }
            finishes = {
                item.payload.arm: item for item in self._event_by_kind("arm_finished")
            }
            if set(starts) != {"source", "target"} or set(finishes) != {
                "source",
                "target",
            }:
                raise ValueError("pair completion requires two exact finished arms")
            source = starts["source"].payload
            target = starts["target"].payload
            assert isinstance(source, ArmStartedPayloadV2)
            assert isinstance(target, ArmStartedPayloadV2)
            return PairCompletePayloadV2(
                attempt_id=attempt_id,
                prepare=_event_ref(prepare_event),
                source_started=_event_ref(starts["source"]),
                source_finished=_event_ref(finishes["source"]),
                target_started=_event_ref(starts["target"]),
                target_finished=_event_ref(finishes["target"]),
                source_root_id=source.physical_root_id,
                target_root_id=target.physical_root_id,
                observed_arm_order=prepare.scheduled_arm_order,
            )

        return self._commit_new_event(
            resolve_existing=existing,
            build_payload=build,
        )

    def cancel_attempt(
        self,
        attempt_id: str,
        *,
        safe_failure_code: SafeFailureCode,
    ) -> JournalEventV2:
        _require_host_id(attempt_id, "attempt_id", allowed_prefixes=("at",))

        def existing() -> JournalEventV2 | None:
            terminal = self.terminal_for_attempt(attempt_id)
            if terminal is None:
                return None
            if (
                terminal.payload.kind == "attempt_cancelled"
                and terminal.payload.safe_failure_code == safe_failure_code
            ):
                return terminal
            raise ValueError("attempt already owns a different terminal")

        def build() -> JournalPayloadV2:
            prepare_event = self._prepare_event()
            if prepare_event is None:
                raise ValueError("cancellation requires the exact prepared attempt")
            prepare = prepare_event.payload
            assert isinstance(prepare, PreparePayloadV2)
            if prepare.attempt_id != attempt_id:
                raise ValueError("cancellation crossed attempt identities")
            starts = self._event_by_kind("arm_started")
            finishes = self._event_by_kind("arm_finished")
            scheduled = self._scheduled_arms(prepare.scheduled_arm_order)
            observed = tuple(item.payload.arm for item in starts)
            if observed != scheduled[: len(observed)]:
                raise ValueError("cancellation is outside the scheduled prefix")
            return AttemptCancelledPayloadV2(
                attempt_id=attempt_id,
                prepare=_event_ref(prepare_event),
                started=tuple(_event_ref(item) for item in starts),
                finished=tuple(_event_ref(item) for item in finishes),
                safe_failure_code=safe_failure_code,
            )

        return self._commit_new_event(
            resolve_existing=existing,
            build_payload=build,
        )

    def _serialized_envelope(self) -> bytes:
        state = self._state.model_copy(deep=True)
        envelope = RunnerJournalEnvelopeV2(
            state=state,
            state_sha256=state.digest,
            state_hmac_sha256=_mac(self._key, "sft-runner-v2-state", state),
        )
        return (
            json.dumps(
                envelope.model_dump(mode="json"),
                ensure_ascii=True,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def _save_owned_state(self, target: Path) -> None:
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
                    raise RuntimeError("refusing to overwrite an unowned journal file")
                if current_sha != self._persisted_envelope_sha256:
                    raise RuntimeError(
                        "runner journal changed concurrently; file CAS failed"
                    )
            elif self._persisted_envelope_sha256 is not None:
                raise RuntimeError("persisted runner journal disappeared before file CAS")
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
                    pass
            finally:
                os.close(directory_fd)
            self._persisted_path = target
            self._persisted_envelope_sha256 = envelope_sha
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def save(self, path: Path | str) -> None:
        target = Path(path).resolve()
        if self._persisted_path is not None and target != self._persisted_path:
            raise RuntimeError("an authoritative runner journal cannot change its path")
        with self._mutation_lock:
            self._verify_scope_manifest()
            self._verify_state()
            self._require_provider_current(self.checkpoint())
            self._save_owned_state(target)

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        journal_key: bytes,
        expected_scope: JournalScopeV2,
        checkpoint_provider: LatestCheckpointProviderV2,
        scope_manifest_verifier: Callable[[JournalScopeV2], bool],
    ) -> "SFTRunnerJournal":
        target = Path(path).resolve()
        raw_bytes = target.read_bytes()
        raw = json.loads(
            raw_bytes,
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
        version = (
            raw.get("state", {}).get("schema_version")
            if isinstance(raw, dict) and isinstance(raw.get("state"), dict)
            else None
        )
        if version != SFT_RUNNER_JOURNAL_VERSION:
            raise LegacyRunnerJournalRejected(
                "unsupported/v1 runner journal cannot gain schema-v2 authority"
            )
        envelope = RunnerJournalEnvelopeV2.model_validate(raw)
        expected_state_mac = _mac(
            journal_key,
            "sft-runner-v2-state",
            envelope.state,
        )
        if not hmac.compare_digest(
            envelope.state_hmac_sha256,
            expected_state_mac,
        ):
            raise ValueError("runner journal state HMAC mismatch")
        if envelope.state.scope != expected_scope:
            raise ValueError("runner journal persisted scope differs from expected scope")
        journal = cls(
            journal_key=journal_key,
            journal_id=envelope.state.journal_id,
            scope=expected_scope,
            checkpoint_provider=checkpoint_provider,
            scope_manifest_verifier=scope_manifest_verifier,
            _state=envelope.state,
            _restore_token=_AUTHENTICATED_RESTORE_TOKEN,
        )
        journal._require_provider_current(journal.checkpoint())
        journal._persisted_path = target
        journal._persisted_envelope_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return journal


__all__ = [
    "ArmFinishedPayloadV2",
    "ArmStartedPayloadV2",
    "AttemptCancelledPayloadV2",
    "CheckpointProviderSnapshotV2",
    "CheckpointUpdateClaimV2",
    "EventRefV2",
    "JournalCheckpointV2",
    "JournalEventV2",
    "JournalScopeV2",
    "LatestCheckpointProviderV2",
    "LegacyRunnerJournalRejected",
    "MAX_JOURNAL_EVENTS",
    "PairCompletePayloadV2",
    "PreparePayloadV2",
    "RunnerJournalStateV2",
    "SFTRunnerJournal",
    "SFT_RUNNER_CHECKPOINT_VERSION",
    "SFT_RUNNER_JOURNAL_VERSION",
    "derive_host_opaque_id_v2",
    "journal_canonical_sha256_v2",
    "journal_fixed_hmac_sha256_v2",
    "verify_runner_journal_envelope_bytes_v2",
]
