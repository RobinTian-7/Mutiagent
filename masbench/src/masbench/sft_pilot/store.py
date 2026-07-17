"""Single-host, single-writer SQLite authority for the default-off SFT pilot.

This is intentionally a control/recovery store, not a second SkillBank.  It
persists a frozen protocol, execution/call fences, immutable scientific
records, and (only when explicitly required) exact Phase/Factor envelope
bytes.  It never interprets or mutates component state and no method calls an
LLM.

The guarantees are deliberately narrow: local filesystem, one process, one
long-held ``flock``, WAL + ``synchronous=FULL``, and no retry after a committed
``request_started`` state.  HMAC/hash chains detect local discontinuity but do
not detect rollback of the entire database together with its head.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import threading
from typing import Any, Iterator, Literal

from exp_graph.mas.factor_bank_v2 import SFT_BANK_SCHEMA_VERSION
from exp_graph.mas.phase_artifact_registry import PHASE_ARTIFACT_REGISTRY_VERSION

from masbench.sft_pilot.manifests import (
    PilotCallScheduleEntryV1,
    PilotExecutionScheduleEntryV1,
    PilotExecutionScheduleV1,
    validate_schedule_against_protocol,
)

from masbench.sft_pilot.schema import (
    PILOT_APPLICATION_ID,
    PILOT_USER_VERSION,
    PilotArchiveEpochV1,
    PilotArchivePayloadV1,
    PilotCallReceiptV1,
    PilotCallStartAuthorizationV1,
    PilotCapacityPreflightV1,
    PilotComponentBundleSnapshotV1,
    PilotComponentBundleV1,
    PilotComponentCheckpointKind,
    PilotComponentCheckpointSnapshotV1,
    PilotComponentCheckpointV1,
    PilotComponentRecoverySnapshotV1,
    PilotCheckpointSemanticWitnessV1,
    PilotExecutionLeaseV1,
    PilotExecutionLeaseRequestV1,
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    PilotScientificCommitV1,
    assert_pilot_safe_value,
    canonical_json,
    canonical_sha256,
    pilot_hmac_sha256,
    require_opaque_id,
    require_sha256,
)


ZERO_SHA256 = "0" * 64
DATABASE_FILENAME = "pilot.sqlite3"
LOCK_FILENAME = "pilot.writer.lock"


def _published_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _require_json_sha256(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return require_sha256(value, field_name=field_name)


def _validate_component_envelope_bytes(
    value: bytes,
    *,
    component: Literal["phase_registry", "factor_bank"],
) -> str:
    """Validate the closed persisted envelope shape without owning its key.

    The Phase/Factor loaders remain the authorities for their inner HMACs.
    This layer accepts only their exact published JSON encoding, rejects
    obvious private/TEST carriers, and then authenticates the exact bytes in
    the SQLite bundle HMAC.
    """

    if type(value) is not bytes or not value:
        raise ValueError(f"{component} envelope must be non-empty exact bytes")
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{component} envelope must be valid UTF-8 JSON") from exc
    if _published_json_bytes(decoded) != value:
        raise ValueError(
            f"{component} envelope bytes are not the component's canonical publication"
        )
    if not isinstance(decoded, dict):
        raise ValueError(f"{component} envelope must be a JSON object")
    assert_pilot_safe_value(decoded)
    if component == "phase_registry":
        if set(decoded) != {"state", "state_hmac_sha256"}:
            raise ValueError("invalid Phase registry envelope fields")
        state = decoded.get("state")
        if (
            not isinstance(state, dict)
            or state.get("schema_version") != PHASE_ARTIFACT_REGISTRY_VERSION
        ):
            raise ValueError("unsupported Phase registry envelope schema")
        _require_json_sha256(
            decoded.get("state_hmac_sha256"),
            field_name="phase registry state_hmac_sha256",
        )
    else:
        if set(decoded) != {
            "envelope_version",
            "state",
            "state_hmac_sha256",
            "state_sha256",
        }:
            raise ValueError("invalid FactorBank envelope fields")
        state = decoded.get("state")
        if (
            decoded.get("envelope_version") != "sft-state-envelope-v2"
            or not isinstance(state, dict)
            or state.get("schema_version") != SFT_BANK_SCHEMA_VERSION
        ):
            raise ValueError("unsupported FactorBank envelope schema")
        state_sha = _require_json_sha256(
            decoded.get("state_sha256"),
            field_name="FactorBank state_sha256",
        )
        if not hmac.compare_digest(state_sha, canonical_sha256(state)):
            raise ValueError("FactorBank envelope state digest mismatch")
        _require_json_sha256(
            decoded.get("state_hmac_sha256"),
            field_name="FactorBank state_hmac_sha256",
        )
    return hashlib.sha256(value).hexdigest()


def _component_bundle_body(
    *,
    generation: int,
    scientific_commit_ordinal: int | None,
    phase_registry_envelope_sha256: str,
    factor_bank_envelope_sha256: str,
    previous_bundle_sha256: str,
) -> dict[str, Any]:
    if generation < 0:
        raise ValueError("component bundle generation cannot be negative")
    if generation == 0:
        if scientific_commit_ordinal is not None:
            raise ValueError("genesis component bundle cannot own a scientific commit")
        if previous_bundle_sha256 != ZERO_SHA256:
            raise ValueError("genesis component bundle must start at the zero hash")
    elif scientific_commit_ordinal != generation:
        raise ValueError(
            "component bundle generation must equal its scientific commit ordinal"
        )
    for name, digest in (
        ("phase_registry_envelope_sha256", phase_registry_envelope_sha256),
        ("factor_bank_envelope_sha256", factor_bank_envelope_sha256),
        ("previous_bundle_sha256", previous_bundle_sha256),
    ):
        require_sha256(digest, field_name=name)
    return {
        "bundle_version": "sft_pilot_component_bundle_v1",
        "generation": generation,
        "scientific_commit_ordinal": scientific_commit_ordinal,
        "phase_registry_envelope_sha256": phase_registry_envelope_sha256,
        "factor_bank_envelope_sha256": factor_bank_envelope_sha256,
        "previous_bundle_sha256": previous_bundle_sha256,
    }


def component_bundle_state_sha256(
    *,
    phase_registry_envelope_bytes: bytes,
    factor_bank_envelope_bytes: bytes,
    generation: int = 0,
    scientific_commit_ordinal: int | None = None,
    previous_bundle_sha256: str = ZERO_SHA256,
) -> str:
    """Derive the scientific state commitment from exact recovery bytes."""

    phase_sha = _validate_component_envelope_bytes(
        phase_registry_envelope_bytes,
        component="phase_registry",
    )
    factor_sha = _validate_component_envelope_bytes(
        factor_bank_envelope_bytes,
        component="factor_bank",
    )
    return canonical_sha256(
        _component_bundle_body(
            generation=generation,
            scientific_commit_ordinal=scientific_commit_ordinal,
            phase_registry_envelope_sha256=phase_sha,
            factor_bank_envelope_sha256=factor_sha,
            previous_bundle_sha256=previous_bundle_sha256,
        )
    )


def component_genesis_sha256_from_envelope_digests(
    *,
    phase_registry_envelope_sha256: str,
    factor_bank_envelope_sha256: str,
) -> str:
    """Derive the generation-zero commitment from already-frozen digests.

    Manifest-level authorities (e.g. the v5 experiment seal) pin envelope
    digests, not raw bytes; this shares the exact bundle body law with
    :func:`component_bundle_state_sha256` so the two derivations can never
    drift.  Byte-level validation still happens wherever real bytes exist.
    """

    return canonical_sha256(
        _component_bundle_body(
            generation=0,
            scientific_commit_ordinal=None,
            phase_registry_envelope_sha256=phase_registry_envelope_sha256,
            factor_bank_envelope_sha256=factor_bank_envelope_sha256,
            previous_bundle_sha256=ZERO_SHA256,
        )
    )


_CHECKPOINT_PREDECESSORS: dict[
    PilotComponentCheckpointKind, frozenset[PilotComponentCheckpointKind]
] = {
    "action_prepared": frozenset(),
    "generation_start_authorized": frozenset({"action_prepared"}),
    "probe_attempt_open": frozenset(
        {"generation_start_authorized", "probe_terminal"}
    ),
    "probe_terminal": frozenset({"probe_attempt_open"}),
    # The additional predecessors are safe failure settlement paths after a
    # crash/indeterminate provider crossing.  They cannot create a new action.
    "gate_terminal": frozenset(
        {
            "action_prepared",
            "generation_start_authorized",
            "probe_attempt_open",
            "probe_terminal",
        }
    ),
}


def _component_checkpoint_body(
    *,
    checkpoint_ordinal: int,
    operation_id: str,
    checkpoint_kind: PilotComponentCheckpointKind,
    protocol_sha256: str,
    action_id: str,
    action_owner_logical_execution_key: str,
    action_owner_logical_arm_key: str,
    logical_execution_key: str,
    logical_arm_key: str,
    semantic_witness: PilotCheckpointSemanticWitnessV1,
    owner_terminal_call_ledger_sha256: str | None,
    phase_registry_envelope_sha256: str,
    factor_bank_envelope_sha256: str,
    previous_recovery_root_sha256: str,
) -> dict[str, Any]:
    return {
        "checkpoint_version": "sft_pilot_component_checkpoint_v2",
        "checkpoint_ordinal": checkpoint_ordinal,
        "operation_id": operation_id,
        "checkpoint_kind": checkpoint_kind,
        "protocol_sha256": protocol_sha256,
        "action_id": action_id,
        "action_owner_logical_execution_key": action_owner_logical_execution_key,
        "action_owner_logical_arm_key": action_owner_logical_arm_key,
        "logical_execution_key": logical_execution_key,
        "logical_arm_key": logical_arm_key,
        "owner_split": "TRAIN_UPDATE",
        "settled": checkpoint_kind == "gate_terminal",
        "semantic_witness": semantic_witness,
        "semantic_witness_sha256": semantic_witness.digest,
        "owner_terminal_call_ledger_sha256": owner_terminal_call_ledger_sha256,
        "phase_registry_envelope_sha256": phase_registry_envelope_sha256,
        "factor_bank_envelope_sha256": factor_bank_envelope_sha256,
        "previous_recovery_root_sha256": previous_recovery_root_sha256,
    }


class PilotStoreError(RuntimeError):
    """Base class for local pilot control-store failures."""


class PilotStoreBusyError(PilotStoreError):
    """Another local writer owns the stable lock."""


class PilotStoreIntegrityError(PilotStoreError):
    """Authenticated state, schema, or stable-lock identity is invalid."""


class PilotIdempotenceConflict(PilotStoreError):
    """An operation/logical key was reused with different committed input."""


class PilotStateTransitionError(PilotStoreError):
    """A call or execution attempted an illegal state transition."""


class PilotCapacityError(PilotStoreError):
    """The frozen preflight or a live count exceeds protocol capacity."""


class PilotProtocolSealedError(PilotStoreError):
    """A writer API was invoked after terminal protocol seal."""


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta(
    only_id INTEGER PRIMARY KEY CHECK(only_id = 1),
    schema_digest TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS protocol(
    only_id INTEGER PRIMARY KEY CHECK(only_id = 1),
    protocol_json TEXT NOT NULL,
    protocol_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('active', 'sealed')),
    protocol_hmac_sha256 TEXT NOT NULL,
    stable_lock_device INTEGER NOT NULL,
    stable_lock_inode INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_schedule(
    only_id INTEGER PRIMARY KEY CHECK(only_id = 1),
    schedule_json TEXT NOT NULL,
    schedule_sha256 TEXT NOT NULL UNIQUE,
    schedule_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capacity_preflight(
    only_id INTEGER PRIMARY KEY CHECK(only_id = 1),
    operation_id TEXT NOT NULL UNIQUE,
    request_sha256 TEXT NOT NULL,
    preflight_json TEXT NOT NULL,
    preflight_sha256 TEXT NOT NULL UNIQUE,
    preflight_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_receipt(
    operation_id TEXT PRIMARY KEY,
    request_sha256 TEXT NOT NULL,
    operation_kind TEXT NOT NULL,
    result_key TEXT NOT NULL,
    result_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scientific_commit(
    commit_ordinal INTEGER PRIMARY KEY CHECK(commit_ordinal >= 1),
    operation_id TEXT NOT NULL UNIQUE,
    owner_logical_execution_key TEXT NOT NULL UNIQUE REFERENCES execution_lease(
        logical_execution_key
    ),
    owner_action_id TEXT NOT NULL,
    owner_split TEXT NOT NULL CHECK(owner_split = 'TRAIN_UPDATE'),
    request_sha256 TEXT NOT NULL,
    before_state_sha256 TEXT NOT NULL,
    after_state_sha256 TEXT NOT NULL,
    previous_commit_sha256 TEXT NOT NULL,
    commit_sha256 TEXT NOT NULL UNIQUE,
    commit_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS component_bundle(
    generation INTEGER PRIMARY KEY CHECK(generation >= 0),
    scientific_commit_ordinal INTEGER UNIQUE REFERENCES scientific_commit(
        commit_ordinal
    ),
    operation_id TEXT NOT NULL UNIQUE,
    phase_registry_envelope BLOB NOT NULL,
    phase_registry_envelope_sha256 TEXT NOT NULL,
    factor_bank_envelope BLOB NOT NULL,
    factor_bank_envelope_sha256 TEXT NOT NULL,
    previous_bundle_sha256 TEXT NOT NULL,
    bundle_sha256 TEXT NOT NULL UNIQUE,
    bundle_hmac_sha256 TEXT NOT NULL,
    CHECK(
        (generation = 0 AND scientific_commit_ordinal IS NULL) OR
        (generation >= 1 AND scientific_commit_ordinal = generation)
    )
);

CREATE TABLE IF NOT EXISTS component_checkpoint(
    checkpoint_ordinal INTEGER PRIMARY KEY CHECK(checkpoint_ordinal >= 1),
    operation_id TEXT NOT NULL UNIQUE,
    checkpoint_kind TEXT NOT NULL CHECK(checkpoint_kind IN (
        'action_prepared', 'generation_start_authorized',
        'probe_attempt_open', 'probe_terminal', 'gate_terminal'
    )),
    protocol_sha256 TEXT NOT NULL,
    action_id TEXT NOT NULL,
    action_owner_logical_execution_key TEXT NOT NULL REFERENCES execution_lease(
        logical_execution_key
    ),
    action_owner_logical_arm_key TEXT NOT NULL,
    logical_execution_key TEXT NOT NULL REFERENCES execution_lease(
        logical_execution_key
    ),
    logical_arm_key TEXT NOT NULL,
    owner_split TEXT NOT NULL CHECK(owner_split = 'TRAIN_UPDATE'),
    settled INTEGER NOT NULL CHECK(settled IN (0, 1)),
    semantic_witness_json TEXT NOT NULL,
    semantic_witness_sha256 TEXT NOT NULL,
    owner_terminal_call_ledger_sha256 TEXT,
    phase_registry_envelope BLOB NOT NULL,
    phase_registry_envelope_sha256 TEXT NOT NULL,
    factor_bank_envelope BLOB NOT NULL,
    factor_bank_envelope_sha256 TEXT NOT NULL,
    previous_recovery_root_sha256 TEXT NOT NULL,
    checkpoint_sha256 TEXT NOT NULL UNIQUE,
    checkpoint_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS component_checkpoint_promotion(
    checkpoint_sha256 TEXT PRIMARY KEY REFERENCES component_checkpoint(
        checkpoint_sha256
    ),
    commit_ordinal INTEGER NOT NULL UNIQUE REFERENCES scientific_commit(
        commit_ordinal
    ),
    promotion_sha256 TEXT NOT NULL UNIQUE,
    promotion_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_lease(
    logical_execution_key TEXT PRIMARY KEY,
    logical_arm_key TEXT NOT NULL UNIQUE,
    operation_kind TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    namespace_sha256 TEXT NOT NULL,
    split TEXT NOT NULL CHECK(split IN ('TRAIN_UPDATE', 'FINAL_VAL')),
    unit_commitment TEXT NOT NULL,
    action_id TEXT,
    call_slots_reserved INTEGER NOT NULL CHECK(call_slots_reserved >= 1),
    input_tokens_reserved INTEGER NOT NULL CHECK(input_tokens_reserved >= 0),
    output_tokens_reserved INTEGER NOT NULL CHECK(output_tokens_reserved >= 0),
    physical_block_ordinal INTEGER CHECK(
        physical_block_ordinal IS NULL OR physical_block_ordinal >= 0
    ),
    schedule_entry_sha256 TEXT,
    state TEXT NOT NULL CHECK(state IN (
        'reserved', 'request_started', 'completed',
        'failed_before_start', 'indeterminate'
    ))
);

CREATE TABLE IF NOT EXISTS call_receipt(
    call_key TEXT PRIMARY KEY,
    logical_execution_key TEXT NOT NULL REFERENCES execution_lease(
        logical_execution_key
    ),
    call_slot INTEGER NOT NULL CHECK(call_slot >= 0),
    request_sha256 TEXT NOT NULL,
    model_name TEXT NOT NULL CHECK(model_name = 'gpt-4o-mini'),
    input_tokens_reserved INTEGER NOT NULL CHECK(input_tokens_reserved >= 0),
    output_tokens_reserved INTEGER NOT NULL CHECK(output_tokens_reserved >= 1),
    max_completion_tokens INTEGER NOT NULL CHECK(max_completion_tokens >= 1),
    expected_component_recovery_root_sha256 TEXT,
    scheduled_call_sha256 TEXT,
    request_renderer_sha256 TEXT,
    prompt_template_sha256 TEXT,
    json_mode INTEGER CHECK(json_mode IS NULL OR json_mode IN (0, 1)),
    artifact_role TEXT CHECK(artifact_role IS NULL OR artifact_role IN (
        'proposal_generation', 'source_artifact', 'target_artifact',
        'final_deployment', 'control_artifact'
    )),
    state TEXT NOT NULL CHECK(state IN (
        'reserved', 'request_started', 'completed',
        'failed_before_start', 'indeterminate'
    )),
    output_envelope_sha256 TEXT,
    provider_usage_known INTEGER NOT NULL CHECK(provider_usage_known IN (0, 1)),
    input_tokens_used INTEGER CHECK(input_tokens_used IS NULL OR input_tokens_used >= 0),
    output_tokens_used INTEGER CHECK(output_tokens_used IS NULL OR output_tokens_used >= 0),
    conservative_charged_tokens INTEGER NOT NULL CHECK(
        conservative_charged_tokens >= 0
    ),
    UNIQUE(logical_execution_key, call_slot)
);

CREATE TABLE IF NOT EXISTS archive_epoch(
    archive_id TEXT PRIMARY KEY,
    seal_operation_id TEXT NOT NULL UNIQUE,
    seal_request_sha256 TEXT NOT NULL,
    archive_json TEXT NOT NULL,
    archive_sha256 TEXT NOT NULL UNIQUE,
    archive_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS violation_event(
    event_id TEXT PRIMARY KEY,
    safe_code TEXT NOT NULL,
    object_sha256 TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS schema_meta_no_update
BEFORE UPDATE ON schema_meta BEGIN
    SELECT RAISE(ABORT, 'schema metadata is immutable');
END;
CREATE TRIGGER IF NOT EXISTS schema_meta_no_delete
BEFORE DELETE ON schema_meta BEGIN
    SELECT RAISE(ABORT, 'schema metadata is immutable');
END;
CREATE TRIGGER IF NOT EXISTS protocol_no_delete
BEFORE DELETE ON protocol BEGIN
    SELECT RAISE(ABORT, 'protocol is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_schedule_no_update
BEFORE UPDATE ON execution_schedule BEGIN
    SELECT RAISE(ABORT, 'execution schedule is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_schedule_no_delete
BEFORE DELETE ON execution_schedule BEGIN
    SELECT RAISE(ABORT, 'execution schedule is immutable');
END;
CREATE TRIGGER IF NOT EXISTS protocol_sealed_no_update
BEFORE UPDATE ON protocol WHEN OLD.status = 'sealed' BEGIN
    SELECT RAISE(ABORT, 'sealed protocol is immutable');
END;
CREATE TRIGGER IF NOT EXISTS protocol_active_frozen_update
BEFORE UPDATE ON protocol WHEN OLD.status = 'active' AND (
    NEW.only_id != OLD.only_id OR
    NEW.protocol_json != OLD.protocol_json OR
    NEW.protocol_sha256 != OLD.protocol_sha256 OR
    NEW.stable_lock_device != OLD.stable_lock_device OR
    NEW.stable_lock_inode != OLD.stable_lock_inode OR
    NEW.status != 'sealed'
) BEGIN
    SELECT RAISE(ABORT, 'active protocol identity is frozen');
END;
CREATE TRIGGER IF NOT EXISTS capacity_preflight_no_update
BEFORE UPDATE ON capacity_preflight BEGIN
    SELECT RAISE(ABORT, 'capacity preflight is immutable');
END;
CREATE TRIGGER IF NOT EXISTS capacity_preflight_no_delete
BEFORE DELETE ON capacity_preflight BEGIN
    SELECT RAISE(ABORT, 'capacity preflight is immutable');
END;
CREATE TRIGGER IF NOT EXISTS operation_receipt_no_update
BEFORE UPDATE ON operation_receipt BEGIN
    SELECT RAISE(ABORT, 'operation receipt is immutable');
END;
CREATE TRIGGER IF NOT EXISTS operation_receipt_no_delete
BEFORE DELETE ON operation_receipt BEGIN
    SELECT RAISE(ABORT, 'operation receipt is immutable');
END;
CREATE TRIGGER IF NOT EXISTS scientific_commit_no_update
BEFORE UPDATE ON scientific_commit BEGIN
    SELECT RAISE(ABORT, 'scientific commit is immutable');
END;
CREATE TRIGGER IF NOT EXISTS scientific_commit_no_delete
BEFORE DELETE ON scientific_commit BEGIN
    SELECT RAISE(ABORT, 'scientific commit is immutable');
END;
CREATE TRIGGER IF NOT EXISTS component_bundle_no_update
BEFORE UPDATE ON component_bundle BEGIN
    SELECT RAISE(ABORT, 'component bundle is immutable');
END;
CREATE TRIGGER IF NOT EXISTS component_bundle_no_delete
BEFORE DELETE ON component_bundle BEGIN
    SELECT RAISE(ABORT, 'component bundle is immutable');
END;
CREATE TRIGGER IF NOT EXISTS component_checkpoint_no_update
BEFORE UPDATE ON component_checkpoint BEGIN
    SELECT RAISE(ABORT, 'component checkpoint is immutable');
END;
CREATE TRIGGER IF NOT EXISTS component_checkpoint_no_delete
BEFORE DELETE ON component_checkpoint BEGIN
    SELECT RAISE(ABORT, 'component checkpoint is immutable');
END;
CREATE TRIGGER IF NOT EXISTS component_checkpoint_promotion_no_update
BEFORE UPDATE ON component_checkpoint_promotion BEGIN
    SELECT RAISE(ABORT, 'component checkpoint promotion is immutable');
END;
CREATE TRIGGER IF NOT EXISTS component_checkpoint_promotion_no_delete
BEFORE DELETE ON component_checkpoint_promotion BEGIN
    SELECT RAISE(ABORT, 'component checkpoint promotion is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_terminal_no_update
BEFORE UPDATE ON execution_lease
WHEN OLD.state IN ('completed', 'failed_before_start', 'indeterminate') BEGIN
    SELECT RAISE(ABORT, 'terminal execution lease is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_lease_no_delete
BEFORE DELETE ON execution_lease BEGIN
    SELECT RAISE(ABORT, 'execution lease is immutable');
END;
CREATE TRIGGER IF NOT EXISTS call_terminal_no_update
BEFORE UPDATE ON call_receipt
WHEN OLD.state IN ('completed', 'failed_before_start', 'indeterminate') BEGIN
    SELECT RAISE(ABORT, 'terminal call receipt is immutable');
END;
CREATE TRIGGER IF NOT EXISTS call_receipt_no_delete
BEFORE DELETE ON call_receipt BEGIN
    SELECT RAISE(ABORT, 'call receipt is immutable');
END;
CREATE TRIGGER IF NOT EXISTS archive_epoch_no_update
BEFORE UPDATE ON archive_epoch BEGIN
    SELECT RAISE(ABORT, 'archive epoch is immutable');
END;
CREATE TRIGGER IF NOT EXISTS archive_epoch_no_delete
BEFORE DELETE ON archive_epoch BEGIN
    SELECT RAISE(ABORT, 'archive epoch is immutable');
END;
CREATE TRIGGER IF NOT EXISTS violation_event_no_update
BEFORE UPDATE ON violation_event BEGIN
    SELECT RAISE(ABORT, 'violation event is immutable');
END;
CREATE TRIGGER IF NOT EXISTS violation_event_no_delete
BEFORE DELETE ON violation_event BEGIN
    SELECT RAISE(ABORT, 'violation event is immutable');
END;
"""


def _schema_objects(connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    return [tuple(str(item) for item in row) for row in rows]


def _expected_schema_digest() -> str:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        connection.executescript(_SCHEMA_SQL)
        return canonical_sha256(_schema_objects(connection))
    finally:
        connection.close()


EXPECTED_SCHEMA_DIGEST = _expected_schema_digest()


class SingleWriterPilotStore:
    """One long-held local writer lock plus one authoritative SQLite file."""

    def __init__(
        self,
        *,
        state_dir: Path,
        protocol: PilotProtocolV1,
        hmac_key: bytes,
        lock_fd: int,
        connection: sqlite3.Connection,
        execution_schedule: PilotExecutionScheduleV1 | None,
    ) -> None:
        self.state_dir = state_dir
        self.database_path = state_dir / DATABASE_FILENAME
        self.lock_path = state_dir / LOCK_FILENAME
        self.protocol = protocol
        self.execution_schedule = execution_schedule
        self._hmac_key = hmac_key
        self._lock_fd = lock_fd
        self._connection = connection
        self._pid = os.getpid()
        self._thread_id = threading.get_ident()
        self._closed = False
        lock_stat = os.fstat(lock_fd)
        self._lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
        database_stat = os.stat(self.database_path)
        self._database_identity = (database_stat.st_dev, database_stat.st_ino)
        self.recovered_indeterminate_count = 0

    @classmethod
    def open(
        cls,
        state_dir: str | Path,
        *,
        protocol: PilotProtocolV1,
        hmac_key: bytes,
        execution_schedule: PilotExecutionScheduleV1 | None = None,
    ) -> "SingleWriterPilotStore":
        if not isinstance(protocol, PilotProtocolV1):
            protocol = PilotProtocolV1.model_validate(protocol)
        if execution_schedule is not None and not isinstance(
            execution_schedule, PilotExecutionScheduleV1
        ):
            execution_schedule = PilotExecutionScheduleV1.model_validate(
                execution_schedule
            )
        if protocol.store_derived_schedule_required:
            if execution_schedule is None:
                raise PilotStoreIntegrityError(
                    "store-derived protocol requires its exact execution schedule"
                )
            try:
                validate_schedule_against_protocol(execution_schedule, protocol)
            except ValueError as exc:
                raise PilotStoreIntegrityError(
                    "execution schedule does not close the frozen protocol"
                ) from exc
        elif execution_schedule is not None:
            raise PilotStoreIntegrityError(
                "legacy protocol cannot open with schedule-derived authority"
            )
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("pilot HMAC key must contain at least 32 bytes")

        directory = Path(state_dir)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = directory.stat()
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise PilotStoreIntegrityError("pilot state path is not a directory")
        if directory_stat.st_mode & 0o077:
            raise PilotStoreIntegrityError("pilot state directory must be mode 0700")

        lock_path = directory / LOCK_FILENAME
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            lock_fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise PilotStoreIntegrityError("stable writer lock cannot be opened") from exc
        connection: sqlite3.Connection | None = None
        try:
            os.fchmod(lock_fd, 0o600)
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise PilotStoreIntegrityError("stable writer lock must be a regular file")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PilotStoreBusyError("another pilot writer owns the stable lock") from exc

            path_stat = os.lstat(lock_path)
            if (path_stat.st_dev, path_stat.st_ino) != (
                lock_stat.st_dev,
                lock_stat.st_ino,
            ):
                raise PilotStoreIntegrityError("stable writer lock path was replaced")

            database_path = directory / DATABASE_FILENAME
            if database_path.exists():
                database_stat = os.lstat(database_path)
                if not stat.S_ISREG(database_stat.st_mode):
                    raise PilotStoreIntegrityError(
                        "pilot database must be a non-symlink regular file"
                    )
            connection = sqlite3.connect(
                database_path,
                isolation_level=None,
                timeout=0.0,
                check_same_thread=True,
            )
            connection.row_factory = sqlite3.Row
            cls._configure_connection(connection)
            os.chmod(database_path, 0o600)
            cls._initialize_or_verify_schema(connection)

            store = cls(
                state_dir=directory,
                protocol=protocol,
                hmac_key=hmac_key,
                lock_fd=lock_fd,
                connection=connection,
                execution_schedule=execution_schedule,
            )
            store._initialize_or_verify_protocol()
            store._initialize_or_verify_execution_schedule()
            store._verify_scientific_chain()
            store._verify_component_bundles()
            store._verify_component_checkpoints()
            store._verify_preflight()
            store._verify_archive()
            store._verify_schedule_ledger()
            store.recovered_indeterminate_count = store._recover_started_calls()
            return store
        except BaseException:
            if connection is not None:
                connection.close()
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
            raise

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        journal_mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        if journal_mode.casefold() != "wal":
            raise PilotStoreIntegrityError("pilot SQLite journal mode must be WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=0")
        connection.execute("PRAGMA trusted_schema=OFF")
        if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            raise PilotStoreIntegrityError("SQLite foreign keys are not active")
        if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
            raise PilotStoreIntegrityError("SQLite synchronous mode is not FULL")
        if int(connection.execute("PRAGMA busy_timeout").fetchone()[0]) != 0:
            raise PilotStoreIntegrityError("SQLite busy timeout must remain zero")

        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        if application_id == 0:
            connection.execute(f"PRAGMA application_id={PILOT_APPLICATION_ID}")
        elif application_id != PILOT_APPLICATION_ID:
            raise PilotStoreIntegrityError("SQLite application_id mismatch")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version == 0:
            connection.execute(f"PRAGMA user_version={PILOT_USER_VERSION}")
        elif user_version != PILOT_USER_VERSION:
            raise PilotStoreIntegrityError("SQLite user_version mismatch")

    @staticmethod
    def _initialize_or_verify_schema(connection: sqlite3.Connection) -> None:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]) != "ok":
            raise PilotStoreIntegrityError("SQLite quick_check failed")
        connection.executescript(_SCHEMA_SQL)
        actual_digest = canonical_sha256(_schema_objects(connection))
        if not hmac.compare_digest(actual_digest, EXPECTED_SCHEMA_DIGEST):
            raise PilotStoreIntegrityError("pilot SQLite schema digest mismatch")
        row = connection.execute(
            "SELECT schema_digest FROM schema_meta WHERE only_id=1"
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO schema_meta(only_id, schema_digest) VALUES(1, ?)",
                (EXPECTED_SCHEMA_DIGEST,),
            )
        elif not hmac.compare_digest(str(row[0]), EXPECTED_SCHEMA_DIGEST):
            raise PilotStoreIntegrityError("persisted schema digest mismatch")

    def _initialize_or_verify_protocol(self) -> None:
        protocol_json = canonical_json(self.protocol)
        protocol_sha256 = self.protocol.digest
        row = self._connection.execute(
            "SELECT protocol_json, protocol_sha256, status, protocol_hmac_sha256, "
            "stable_lock_device, stable_lock_inode "
            "FROM protocol WHERE only_id=1"
        ).fetchone()
        if row is None:
            status = "active"
            lock_device, lock_inode = self._lock_identity
            protocol_hmac = self._protocol_hmac(
                protocol_sha256,
                status,
                lock_device=lock_device,
                lock_inode=lock_inode,
            )
            self._connection.execute(
                """
                INSERT INTO protocol(
                    only_id, protocol_json, protocol_sha256, status,
                    protocol_hmac_sha256, stable_lock_device, stable_lock_inode
                ) VALUES(1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    protocol_json,
                    protocol_sha256,
                    status,
                    protocol_hmac,
                    lock_device,
                    lock_inode,
                ),
            )
            return
        try:
            persisted = PilotProtocolV1.model_validate_json(str(row[0]))
        except (ValueError, TypeError) as exc:
            raise PilotStoreIntegrityError("persisted pilot protocol is invalid") from exc
        persisted_sha = canonical_sha256(persisted)
        if not hmac.compare_digest(str(row[1]), persisted_sha):
            raise PilotStoreIntegrityError("persisted protocol digest is invalid")
        if not hmac.compare_digest(persisted_sha, protocol_sha256):
            raise PilotStoreIntegrityError("state directory belongs to another protocol")
        if canonical_json(persisted) != str(row[0]) or protocol_json != str(row[0]):
            raise PilotStoreIntegrityError("protocol JSON is not canonical/frozen")
        status = str(row[2])
        persisted_lock_identity = (int(row[4]), int(row[5]))
        if persisted_lock_identity != self._lock_identity:
            raise PilotStoreIntegrityError(
                "stable writer lock identity differs from the protocol seal"
            )
        expected_hmac = self._protocol_hmac(
            persisted_sha,
            status,
            lock_device=persisted_lock_identity[0],
            lock_inode=persisted_lock_identity[1],
        )
        if status not in {"active", "sealed"} or not hmac.compare_digest(
            str(row[3]), expected_hmac
        ):
            raise PilotStoreIntegrityError("protocol seal authentication failed")

    def _protocol_hmac(
        self,
        protocol_sha256: str,
        status: str,
        *,
        lock_device: int | None = None,
        lock_inode: int | None = None,
    ) -> str:
        if lock_device is None or lock_inode is None:
            lock_device, lock_inode = self._lock_identity
        return pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-protocol-v1",
            value={
                "protocol_sha256": protocol_sha256,
                "status": status,
                "stable_lock_device": lock_device,
                "stable_lock_inode": lock_inode,
            },
        )

    def _initialize_or_verify_execution_schedule(self) -> None:
        row = self._connection.execute(
            "SELECT schedule_json, schedule_sha256, schedule_hmac_sha256 "
            "FROM execution_schedule WHERE only_id=1"
        ).fetchone()
        schedule = self.execution_schedule
        if not self.protocol.store_derived_schedule_required:
            if row is not None:
                raise PilotStoreIntegrityError(
                    "legacy state directory contains schedule-derived authority"
                )
            return
        if schedule is None:  # Defensive: open() already rejects this.
            raise PilotStoreIntegrityError("required execution schedule is absent")
        schedule_json = canonical_json(schedule)
        schedule_sha = schedule.digest
        if schedule_sha != self.protocol.execution_schedule_sha256:
            raise PilotStoreIntegrityError("execution schedule digest changed")
        schedule_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-execution-schedule-v1",
            value={
                "protocol_sha256": self.protocol.digest,
                "schedule_sha256": schedule_sha,
            },
        )
        if row is None:
            self._connection.execute(
                "INSERT INTO execution_schedule(only_id, schedule_json, "
                "schedule_sha256, schedule_hmac_sha256) VALUES(1, ?, ?, ?)",
                (schedule_json, schedule_sha, schedule_hmac),
            )
            return
        try:
            persisted = PilotExecutionScheduleV1.model_validate_json(str(row[0]))
        except (TypeError, ValueError) as exc:
            raise PilotStoreIntegrityError(
                "persisted execution schedule schema is invalid"
            ) from exc
        if not (
            canonical_json(persisted) == str(row[0]) == schedule_json
            and hmac.compare_digest(str(row[1]), persisted.digest)
            and hmac.compare_digest(str(row[1]), schedule_sha)
            and hmac.compare_digest(str(row[2]), schedule_hmac)
        ):
            raise PilotStoreIntegrityError(
                "persisted execution schedule authentication failed"
            )

    def _ensure_owner(self) -> None:
        if self._closed:
            raise PilotStoreError("pilot store is closed")
        if os.getpid() != self._pid or threading.get_ident() != self._thread_id:
            raise PilotStoreError("pilot store cannot cross process/thread ownership")
        try:
            fd_stat = os.fstat(self._lock_fd)
            path_stat = os.lstat(self.lock_path)
            database_stat = os.lstat(self.database_path)
        except OSError as exc:
            raise PilotStoreIntegrityError("stable pilot authority path disappeared") from exc
        identity = (fd_stat.st_dev, fd_stat.st_ino)
        if identity != self._lock_identity or identity != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise PilotStoreIntegrityError("stable writer lock path was replaced")
        if not stat.S_ISREG(path_stat.st_mode):
            raise PilotStoreIntegrityError("stable writer lock is no longer regular")
        if fd_stat.st_nlink != 1 or path_stat.st_nlink != 1:
            raise PilotStoreIntegrityError("stable writer lock must have one live link")
        if (
            not stat.S_ISREG(database_stat.st_mode)
            or (database_stat.st_dev, database_stat.st_ino)
            != self._database_identity
        ):
            raise PilotStoreIntegrityError("pilot database path was replaced")

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        self._ensure_owner()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield self._connection
            self._enforce_live_capacity(self._connection)
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _enforce_live_capacity(self, connection: sqlite3.Connection) -> None:
        """Enforce the frozen count/byte envelope before every local commit."""

        policy = self.protocol.capacity_policy
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        allocated_bytes = page_count * page_size
        if allocated_bytes > policy.max_active_db_bytes:
            raise PilotCapacityError("active database exceeds frozen byte capacity")

        scalar_columns: dict[str, tuple[str, ...]] = {
            "schema_meta": ("schema_digest",),
            "protocol": (
                "protocol_json",
                "protocol_sha256",
                "status",
                "protocol_hmac_sha256",
            ),
            "execution_schedule": (
                "schedule_json",
                "schedule_sha256",
                "schedule_hmac_sha256",
            ),
            "capacity_preflight": (
                "operation_id",
                "request_sha256",
                "preflight_json",
                "preflight_sha256",
                "preflight_hmac_sha256",
            ),
            "operation_receipt": (
                "operation_id",
                "request_sha256",
                "operation_kind",
                "result_key",
                "result_sha256",
            ),
            "scientific_commit": (
                "operation_id",
                "owner_logical_execution_key",
                "owner_action_id",
                "owner_split",
                "request_sha256",
                "before_state_sha256",
                "after_state_sha256",
                "previous_commit_sha256",
                "commit_sha256",
                "commit_hmac_sha256",
            ),
            "component_bundle": (
                "operation_id",
                "phase_registry_envelope",
                "phase_registry_envelope_sha256",
                "factor_bank_envelope",
                "factor_bank_envelope_sha256",
                "previous_bundle_sha256",
                "bundle_sha256",
                "bundle_hmac_sha256",
            ),
            "component_checkpoint": (
                "operation_id",
                "checkpoint_kind",
                "protocol_sha256",
                "action_id",
                "logical_execution_key",
                "logical_arm_key",
                "owner_split",
                "phase_registry_envelope",
                "phase_registry_envelope_sha256",
                "factor_bank_envelope",
                "factor_bank_envelope_sha256",
                "previous_recovery_root_sha256",
                "checkpoint_sha256",
                "checkpoint_hmac_sha256",
            ),
            "component_checkpoint_promotion": (
                "checkpoint_sha256",
                "promotion_sha256",
                "promotion_hmac_sha256",
            ),
            "execution_lease": (
                "logical_execution_key",
                "logical_arm_key",
                "operation_kind",
                "request_sha256",
                "namespace_sha256",
                "split",
                "unit_commitment",
                "action_id",
                "schedule_entry_sha256",
                "state",
            ),
            "call_receipt": (
                "call_key",
                "logical_execution_key",
                "request_sha256",
                "model_name",
                "expected_component_recovery_root_sha256",
                "scheduled_call_sha256",
                "request_renderer_sha256",
                "prompt_template_sha256",
                "artifact_role",
                "state",
                "output_envelope_sha256",
            ),
            "archive_epoch": (
                "archive_id",
                "seal_operation_id",
                "seal_request_sha256",
                "archive_json",
                "archive_sha256",
                "archive_hmac_sha256",
            ),
            "violation_event": ("event_id", "safe_code", "object_sha256"),
        }
        scalar_bytes = 0
        for table, columns in scalar_columns.items():
            expression = " + ".join(
                f"COALESCE(length({column}), 0)" for column in columns
            )
            scalar_bytes += int(
                connection.execute(
                    f"SELECT COALESCE(SUM({expression}), 0) FROM {table}"
                ).fetchone()[0]
            )
        if scalar_bytes > policy.max_total_stored_scalar_bytes:
            raise PilotCapacityError("persisted scalar commitments exceed capacity")

        preflight_row = connection.execute(
            "SELECT preflight_json FROM capacity_preflight WHERE only_id=1"
        ).fetchone()
        if preflight_row is None:
            return
        preflight = PilotCapacityPreflightV1.model_validate_json(str(preflight_row[0]))
        if allocated_bytes > preflight.planned_max_active_db_bytes:
            raise PilotCapacityError("active database exceeds the frozen preflight")
        if scalar_bytes > preflight.planned_total_stored_scalar_bytes:
            raise PilotCapacityError("stored scalar bytes exceed the frozen preflight")
        live_counts = {
            "scientific commits": int(
                connection.execute("SELECT COUNT(*) FROM scientific_commit").fetchone()[0]
            ),
            "execution leases": int(
                connection.execute("SELECT COUNT(*) FROM execution_lease").fetchone()[0]
            ),
            "call receipts": int(
                connection.execute("SELECT COUNT(*) FROM call_receipt").fetchone()[0]
            ),
            "component checkpoints": int(
                connection.execute(
                    "SELECT COUNT(*) FROM component_checkpoint"
                ).fetchone()[0]
            ),
        }
        planned_counts = {
            "scientific commits": preflight.planned_scientific_commits,
            "execution leases": preflight.planned_execution_leases,
            "call receipts": preflight.planned_call_receipts,
            "component checkpoints": preflight.planned_component_checkpoints,
        }
        for label, live in live_counts.items():
            if live > planned_counts[label]:
                raise PilotCapacityError(f"live {label} exceed the frozen preflight")

    def _require_active(self, connection: sqlite3.Connection) -> None:
        status = str(
            connection.execute("SELECT status FROM protocol WHERE only_id=1").fetchone()[0]
        )
        if status != "active":
            raise PilotProtocolSealedError("pilot protocol is terminally sealed")

    def _require_component_genesis(self, connection: sqlite3.Connection) -> None:
        if self.protocol.component_bundle_required and connection.execute(
            "SELECT 1 FROM component_bundle WHERE generation=0"
        ).fetchone() is None:
            raise PilotStateTransitionError(
                "component-bundle protocol requires explicit genesis before pilot work"
            )

    def _require_preflight(self, connection: sqlite3.Connection) -> None:
        self._require_component_genesis(connection)
        if connection.execute(
            "SELECT 1 FROM capacity_preflight WHERE only_id=1"
        ).fetchone() is None:
            raise PilotCapacityError("capacity preflight must pass before pilot work")

    def _operation_row(
        self, connection: sqlite3.Connection, operation_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT operation_id, request_sha256, operation_kind,
                   result_key, result_sha256
            FROM operation_receipt WHERE operation_id=?
            """,
            (operation_id,),
        ).fetchone()

    def _operation_already_applied(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        request_sha256: str,
        operation_kind: str,
        result_key: str,
        result_sha256: str,
    ) -> bool:
        require_opaque_id(operation_id, field_name="operation_id")
        require_sha256(request_sha256, field_name="request_sha256")
        require_sha256(result_sha256, field_name="result_sha256")
        row = self._operation_row(connection, operation_id)
        if row is None:
            return False
        exact = (
            str(row["request_sha256"]) == request_sha256
            and str(row["operation_kind"]) == operation_kind
            and str(row["result_key"]) == result_key
            and str(row["result_sha256"]) == result_sha256
        )
        if not exact:
            raise PilotIdempotenceConflict(
                "operation_id was reused with a different request or result"
            )
        return True

    @staticmethod
    def _insert_operation(
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        request_sha256: str,
        operation_kind: str,
        result_key: str,
        result_sha256: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO operation_receipt(
                operation_id, request_sha256, operation_kind,
                result_key, result_sha256
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                request_sha256,
                operation_kind,
                result_key,
                result_sha256,
            ),
        )

    @property
    def protocol_status(self) -> Literal["active", "sealed"]:
        self._ensure_owner()
        return str(
            self._connection.execute(
                "SELECT status FROM protocol WHERE only_id=1"
            ).fetchone()[0]
        )  # type: ignore[return-value]

    @property
    def schema_digest(self) -> str:
        self._ensure_owner()
        return str(
            self._connection.execute(
                "SELECT schema_digest FROM schema_meta WHERE only_id=1"
            ).fetchone()[0]
        )

    @property
    def commit_head_sha256(self) -> str:
        self._ensure_owner()
        row = self._connection.execute(
            "SELECT commit_sha256 FROM scientific_commit ORDER BY commit_ordinal DESC LIMIT 1"
        ).fetchone()
        return ZERO_SHA256 if row is None else str(row[0])

    def _component_bundle_metadata(
        self,
        *,
        generation: int,
        scientific_commit_ordinal: int | None,
        phase_registry_envelope_bytes: bytes,
        factor_bank_envelope_bytes: bytes,
        previous_bundle_sha256: str,
    ) -> PilotComponentBundleV1:
        phase_sha = _validate_component_envelope_bytes(
            phase_registry_envelope_bytes,
            component="phase_registry",
        )
        factor_sha = _validate_component_envelope_bytes(
            factor_bank_envelope_bytes,
            component="factor_bank",
        )
        body = _component_bundle_body(
            generation=generation,
            scientific_commit_ordinal=scientific_commit_ordinal,
            phase_registry_envelope_sha256=phase_sha,
            factor_bank_envelope_sha256=factor_sha,
            previous_bundle_sha256=previous_bundle_sha256,
        )
        bundle_sha = canonical_sha256(body)
        bundle_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-component-bundle-v1",
            value={
                "protocol_sha256": self.protocol.digest,
                "body": body,
                "bundle_sha256": bundle_sha,
            },
        )
        return PilotComponentBundleV1(
            **body,
            bundle_sha256=bundle_sha,
            bundle_hmac_sha256=bundle_hmac,
        )

    @staticmethod
    def _insert_component_bundle(
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        metadata: PilotComponentBundleV1,
        phase_registry_envelope_bytes: bytes,
        factor_bank_envelope_bytes: bytes,
    ) -> None:
        connection.execute(
            """
            INSERT INTO component_bundle(
                generation, scientific_commit_ordinal, operation_id,
                phase_registry_envelope, phase_registry_envelope_sha256,
                factor_bank_envelope, factor_bank_envelope_sha256,
                previous_bundle_sha256, bundle_sha256, bundle_hmac_sha256
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.generation,
                metadata.scientific_commit_ordinal,
                operation_id,
                phase_registry_envelope_bytes,
                metadata.phase_registry_envelope_sha256,
                factor_bank_envelope_bytes,
                metadata.factor_bank_envelope_sha256,
                metadata.previous_bundle_sha256,
                metadata.bundle_sha256,
                metadata.bundle_hmac_sha256,
            ),
        )

    @staticmethod
    def _component_snapshot_from_row(
        row: sqlite3.Row,
    ) -> PilotComponentBundleSnapshotV1:
        metadata = PilotComponentBundleV1(
            generation=int(row["generation"]),
            scientific_commit_ordinal=(
                None
                if row["scientific_commit_ordinal"] is None
                else int(row["scientific_commit_ordinal"])
            ),
            phase_registry_envelope_sha256=str(
                row["phase_registry_envelope_sha256"]
            ),
            factor_bank_envelope_sha256=str(row["factor_bank_envelope_sha256"]),
            previous_bundle_sha256=str(row["previous_bundle_sha256"]),
            bundle_sha256=str(row["bundle_sha256"]),
            bundle_hmac_sha256=str(row["bundle_hmac_sha256"]),
        )
        return PilotComponentBundleSnapshotV1(
            metadata=metadata,
            phase_registry_envelope_bytes=bytes(row["phase_registry_envelope"]),
            factor_bank_envelope_bytes=bytes(row["factor_bank_envelope"]),
        )

    def record_genesis_component_bundle(
        self,
        *,
        operation_id: str,
        request_sha256: str,
        phase_registry_envelope_bytes: bytes,
        factor_bank_envelope_bytes: bytes,
    ) -> PilotComponentBundleSnapshotV1:
        """Persist the exact generation-zero recovery source once."""

        require_opaque_id(operation_id, field_name="operation_id")
        require_sha256(request_sha256, field_name="request_sha256")
        if not self.protocol.component_bundle_required:
            raise PilotStateTransitionError(
                "protocol does not authorize component-bundle persistence"
            )
        metadata = self._component_bundle_metadata(
            generation=0,
            scientific_commit_ordinal=None,
            phase_registry_envelope_bytes=phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=factor_bank_envelope_bytes,
            previous_bundle_sha256=ZERO_SHA256,
        )
        if metadata.bundle_sha256 != self.protocol.genesis_state_sha256:
            raise PilotStoreIntegrityError(
                "genesis component bundle differs from the frozen protocol state"
            )
        if (
            len(phase_registry_envelope_bytes) + len(factor_bank_envelope_bytes)
            > self.protocol.capacity_policy.max_total_stored_scalar_bytes
        ):
            raise PilotCapacityError("genesis component envelopes exceed byte capacity")
        with self._write_transaction() as connection:
            self._require_active(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=request_sha256,
                operation_kind="record_genesis_component_bundle",
                result_key="0",
                result_sha256=metadata.bundle_sha256,
            ):
                row = connection.execute(
                    "SELECT * FROM component_bundle WHERE generation=0"
                ).fetchone()
                if row is None:
                    raise PilotStoreIntegrityError(
                        "genesis operation exists without its component bundle"
                    )
                snapshot = self._component_snapshot_from_row(row)
                if (
                    snapshot.metadata != metadata
                    or snapshot.phase_registry_envelope_bytes
                    != phase_registry_envelope_bytes
                    or snapshot.factor_bank_envelope_bytes
                    != factor_bank_envelope_bytes
                ):
                    raise PilotIdempotenceConflict(
                        "genesis operation retry changed exact component bytes"
                    )
                return snapshot
            if connection.execute(
                "SELECT 1 FROM scientific_commit LIMIT 1"
            ).fetchone() is not None:
                raise PilotStoreIntegrityError(
                    "genesis component bundle must precede scientific commits"
                )
            if connection.execute(
                "SELECT 1 FROM component_bundle LIMIT 1"
            ).fetchone() is not None:
                raise PilotIdempotenceConflict(
                    "one protocol can record only one genesis component bundle"
                )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=request_sha256,
                operation_kind="record_genesis_component_bundle",
                result_key="0",
                result_sha256=metadata.bundle_sha256,
            )
            self._insert_component_bundle(
                connection,
                operation_id=operation_id,
                metadata=metadata,
                phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=factor_bank_envelope_bytes,
            )
        return PilotComponentBundleSnapshotV1(
            metadata=metadata,
            phase_registry_envelope_bytes=phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=factor_bank_envelope_bytes,
        )

    def latest_component_bundle(self) -> PilotComponentBundleSnapshotV1:
        """Return byte-for-byte recovery inputs from the authoritative head."""

        self._ensure_owner()
        row = self._connection.execute(
            "SELECT * FROM component_bundle ORDER BY generation DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise PilotStateTransitionError("component-bundle genesis is not recorded")
        snapshot = self._component_snapshot_from_row(row)
        self._verify_component_snapshot(snapshot)
        return snapshot

    def _component_checkpoint_metadata(
        self,
        *,
        checkpoint_ordinal: int,
        operation_id: str,
        checkpoint_kind: PilotComponentCheckpointKind,
        action_id: str,
        action_owner_logical_execution_key: str,
        action_owner_logical_arm_key: str,
        logical_execution_key: str,
        logical_arm_key: str,
        semantic_witness: PilotCheckpointSemanticWitnessV1,
        owner_terminal_call_ledger_sha256: str | None,
        phase_registry_envelope_bytes: bytes,
        factor_bank_envelope_bytes: bytes,
        previous_recovery_root_sha256: str,
    ) -> PilotComponentCheckpointV1:
        phase_sha = _validate_component_envelope_bytes(
            phase_registry_envelope_bytes,
            component="phase_registry",
        )
        factor_sha = _validate_component_envelope_bytes(
            factor_bank_envelope_bytes,
            component="factor_bank",
        )
        body = _component_checkpoint_body(
            checkpoint_ordinal=checkpoint_ordinal,
            operation_id=operation_id,
            checkpoint_kind=checkpoint_kind,
            protocol_sha256=self.protocol.digest,
            action_id=action_id,
            action_owner_logical_execution_key=(
                action_owner_logical_execution_key
            ),
            action_owner_logical_arm_key=action_owner_logical_arm_key,
            logical_execution_key=logical_execution_key,
            logical_arm_key=logical_arm_key,
            semantic_witness=semantic_witness,
            owner_terminal_call_ledger_sha256=(
                owner_terminal_call_ledger_sha256
            ),
            phase_registry_envelope_sha256=phase_sha,
            factor_bank_envelope_sha256=factor_sha,
            previous_recovery_root_sha256=previous_recovery_root_sha256,
        )
        checkpoint_sha = canonical_sha256(body)
        checkpoint_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-component-checkpoint-v2",
            value={
                "body": body,
                "checkpoint_sha256": checkpoint_sha,
            },
        )
        return PilotComponentCheckpointV1(
            **body,
            checkpoint_sha256=checkpoint_sha,
            checkpoint_hmac_sha256=checkpoint_hmac,
        )

    @staticmethod
    def _component_checkpoint_snapshot_from_row(
        row: sqlite3.Row,
    ) -> PilotComponentCheckpointSnapshotV1:
        metadata = PilotComponentCheckpointV1(
            checkpoint_ordinal=int(row["checkpoint_ordinal"]),
            operation_id=str(row["operation_id"]),
            checkpoint_kind=str(row["checkpoint_kind"]),
            protocol_sha256=str(row["protocol_sha256"]),
            action_id=str(row["action_id"]),
            action_owner_logical_execution_key=str(
                row["action_owner_logical_execution_key"]
            ),
            action_owner_logical_arm_key=str(
                row["action_owner_logical_arm_key"]
            ),
            logical_execution_key=str(row["logical_execution_key"]),
            logical_arm_key=str(row["logical_arm_key"]),
            owner_split=str(row["owner_split"]),
            settled=bool(row["settled"]),
            semantic_witness=PilotCheckpointSemanticWitnessV1.model_validate_json(
                str(row["semantic_witness_json"])
            ),
            semantic_witness_sha256=str(row["semantic_witness_sha256"]),
            owner_terminal_call_ledger_sha256=(
                None
                if row["owner_terminal_call_ledger_sha256"] is None
                else str(row["owner_terminal_call_ledger_sha256"])
            ),
            phase_registry_envelope_sha256=str(
                row["phase_registry_envelope_sha256"]
            ),
            factor_bank_envelope_sha256=str(row["factor_bank_envelope_sha256"]),
            previous_recovery_root_sha256=str(
                row["previous_recovery_root_sha256"]
            ),
            checkpoint_sha256=str(row["checkpoint_sha256"]),
            checkpoint_hmac_sha256=str(row["checkpoint_hmac_sha256"]),
        )
        return PilotComponentCheckpointSnapshotV1(
            metadata=metadata,
            phase_registry_envelope_bytes=bytes(row["phase_registry_envelope"]),
            factor_bank_envelope_bytes=bytes(row["factor_bank_envelope"]),
        )

    def _verify_component_checkpoint_snapshot(
        self,
        snapshot: PilotComponentCheckpointSnapshotV1,
    ) -> None:
        metadata = snapshot.metadata
        expected = self._component_checkpoint_metadata(
            checkpoint_ordinal=metadata.checkpoint_ordinal,
            operation_id=metadata.operation_id,
            checkpoint_kind=metadata.checkpoint_kind,
            action_id=metadata.action_id,
            action_owner_logical_execution_key=(
                metadata.action_owner_logical_execution_key
            ),
            action_owner_logical_arm_key=metadata.action_owner_logical_arm_key,
            logical_execution_key=metadata.logical_execution_key,
            logical_arm_key=metadata.logical_arm_key,
            semantic_witness=metadata.semantic_witness,
            owner_terminal_call_ledger_sha256=(
                metadata.owner_terminal_call_ledger_sha256
            ),
            phase_registry_envelope_bytes=snapshot.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=snapshot.factor_bank_envelope_bytes,
            previous_recovery_root_sha256=metadata.previous_recovery_root_sha256,
        )
        if metadata != expected:
            raise PilotStoreIntegrityError(
                "component checkpoint digest or authentication is invalid"
            )
        if metadata.settled:
            owner = self._load_execution(
                self._connection,
                metadata.action_owner_logical_execution_key,
            )
            if not (
                owner.state == "completed"
                and owner.split == "TRAIN_UPDATE"
                and owner.operation_kind == "proposal_generation"
                and owner.action_id == metadata.action_id
                and owner.logical_arm_key
                == metadata.action_owner_logical_arm_key
                and metadata.logical_execution_key
                == owner.logical_execution_key
                and metadata.logical_arm_key == owner.logical_arm_key
                and metadata.owner_terminal_call_ledger_sha256
                == self._execution_call_ledger_sha256(self._connection, owner)
            ):
                raise PilotStoreIntegrityError(
                    "settled checkpoint lost its terminal proposal-owner closure"
                )

    @staticmethod
    def _unpromoted_checkpoint_row(
        connection: sqlite3.Connection,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT checkpoint.* FROM component_checkpoint AS checkpoint
            WHERE checkpoint.checkpoint_ordinal > COALESCE((
                SELECT MAX(promoted.checkpoint_ordinal)
                FROM component_checkpoint AS promoted
                JOIN component_checkpoint_promotion AS promotion
                  ON promotion.checkpoint_sha256 = promoted.checkpoint_sha256
            ), 0)
            ORDER BY checkpoint.checkpoint_ordinal DESC LIMIT 1
            """
        ).fetchone()

    def _latest_component_recovery_snapshot(
        self,
        connection: sqlite3.Connection,
    ) -> PilotComponentRecoverySnapshotV1:
        checkpoint_row = self._unpromoted_checkpoint_row(connection)
        if checkpoint_row is not None:
            checkpoint = self._component_checkpoint_snapshot_from_row(checkpoint_row)
            self._verify_component_checkpoint_snapshot(checkpoint)
            return PilotComponentRecoverySnapshotV1(
                origin="checkpoint",
                recovery_root_sha256=checkpoint.metadata.checkpoint_sha256,
                phase_registry_envelope_bytes=(
                    checkpoint.phase_registry_envelope_bytes
                ),
                factor_bank_envelope_bytes=checkpoint.factor_bank_envelope_bytes,
                checkpoint=checkpoint.metadata,
            )
        bundle_row = connection.execute(
            "SELECT * FROM component_bundle ORDER BY generation DESC LIMIT 1"
        ).fetchone()
        if bundle_row is None:
            raise PilotStateTransitionError(
                "component-bundle genesis is not recorded"
            )
        bundle = self._component_snapshot_from_row(bundle_row)
        self._verify_component_snapshot(bundle)
        return PilotComponentRecoverySnapshotV1(
            origin="scientific_bundle",
            recovery_root_sha256=bundle.metadata.bundle_sha256,
            phase_registry_envelope_bytes=bundle.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=bundle.factor_bank_envelope_bytes,
            scientific_bundle=bundle.metadata,
        )

    def latest_component_recovery_snapshot(
        self,
    ) -> PilotComponentRecoverySnapshotV1:
        """Return exact bytes from the checkpoint head, else scientific head."""

        self._ensure_owner()
        if not self.protocol.component_checkpoint_saga_required:
            raise PilotStateTransitionError(
                "protocol does not authorize component checkpoint recovery"
            )
        return self._latest_component_recovery_snapshot(self._connection)

    def _execution_call_ledger_sha256(
        self,
        connection: sqlite3.Connection,
        execution: PilotExecutionLeaseV1,
    ) -> str:
        calls = tuple(
            self._call_from_row(row)
            for row in connection.execute(
                "SELECT * FROM call_receipt WHERE logical_execution_key=? "
                "ORDER BY call_slot",
                (execution.logical_execution_key,),
            ).fetchall()
        )
        return canonical_sha256(
            {
                "domain": "sft-pilot-terminal-execution-ledger-v1",
                "protocol_sha256": self.protocol.digest,
                "execution": execution,
                "calls": calls,
            }
        )

    def _semantic_checkpoint_leases(
        self,
        connection: sqlite3.Connection,
        witness: PilotCheckpointSemanticWitnessV1,
    ) -> tuple[PilotExecutionLeaseV1, PilotExecutionLeaseV1]:
        if witness.protocol_sha256 != self.protocol.digest:
            raise PilotStoreIntegrityError(
                "checkpoint semantic witness belongs to another protocol"
            )
        owner_rows = connection.execute(
            "SELECT * FROM execution_lease WHERE action_id=? "
            "AND operation_kind='proposal_generation' AND split='TRAIN_UPDATE'",
            (witness.action_id,),
        ).fetchall()
        if len(owner_rows) != 1:
            raise PilotStoreIntegrityError(
                "checkpoint action must have one exact proposal owner"
            )
        owner = self._execution_from_row(owner_rows[0])
        authorized_owner_keys = {
            arm.derive_logical_arm_key(self.protocol)
            for arm in self.protocol.authorized_logical_arms
            if arm.operation_kind == "proposal_generation"
        }
        if owner.logical_arm_key not in authorized_owner_keys:
            raise PilotStoreIntegrityError(
                "checkpoint proposal owner is not in the frozen arm manifest"
            )

        if witness.expected_stage_operation_kind == "proposal_generation":
            stage = owner
        else:
            arm_rows = tuple(
                arm
                for arm in self.protocol.authorized_logical_arms
                if (
                    arm.operation_kind == witness.expected_stage_operation_kind
                    and arm.pair_arm == witness.expected_stage_pair_arm
                    and arm.execution_ordinal
                    == witness.expected_stage_execution_ordinal
                )
            )
            if len(arm_rows) != 1:
                raise PilotStoreIntegrityError(
                    "checkpoint probe coordinates are not unique in the protocol"
                )
            expected_arm_key = arm_rows[0].derive_logical_arm_key(self.protocol)
            witness_arm_key = (
                witness.probe_source_logical_arm_key
                if witness.expected_stage_pair_arm == "source"
                else witness.probe_target_logical_arm_key
            )
            if not (
                arm_rows[0].pair_id == witness.probe_pair_id
                and expected_arm_key == witness_arm_key
            ):
                raise PilotStoreIntegrityError(
                    "checkpoint stage differs from its frozen logical pair"
                )
            stage_rows = connection.execute(
                "SELECT * FROM execution_lease WHERE action_id=? "
                "AND logical_arm_key=? AND split='TRAIN_UPDATE'",
                (witness.action_id, expected_arm_key),
            ).fetchall()
            if len(stage_rows) != 1:
                raise PilotStoreIntegrityError(
                    "checkpoint probe stage lacks its exact logical-arm lease"
                )
            stage = self._execution_from_row(stage_rows[0])
        if stage.operation_kind != witness.expected_stage_operation_kind:
            raise PilotStoreIntegrityError(
                "checkpoint stage operation differs from semantic witness"
            )

        kind = witness.checkpoint_kind
        if kind in {"action_prepared", "generation_start_authorized"}:
            if owner.state != "reserved" or stage != owner:
                raise PilotStateTransitionError(
                    "proposal checkpoint must precede its provider crossing"
                )
        elif kind == "probe_attempt_open":
            if stage.state != "reserved":
                raise PilotStateTransitionError(
                    "probe-open checkpoint requires a reserved first-arm execution"
                )
        elif kind == "probe_terminal":
            # The admissible second-arm lease states depend on how the
            # attempt settled: a complete pair proves both crossings, an
            # incomplete/quarantined pair may carry a permanently
            # indeterminate crossing, and a cancelled pair may legitimately
            # settle before its second crossing ever started (no-retry makes
            # every such lease state terminal for this logical arm).
            attempt_state = witness.attempt_state
            if attempt_state == "complete":
                allowed_states = {"completed"}
            elif attempt_state in {"incomplete", "quarantine"}:
                allowed_states = {"completed", "indeterminate"}
            else:
                allowed_states = {
                    "completed",
                    "indeterminate",
                    "reserved",
                    "failed_before_start",
                }
            if stage.state not in allowed_states:
                raise PilotStateTransitionError(
                    "probe-terminal checkpoint requires a terminal second arm "
                    "consistent with the attempt settlement"
                )
        elif owner.state != "completed" or stage != owner:
            raise PilotStateTransitionError(
                "gate checkpoint requires its completed proposal owner"
            )
        return owner, stage

    def _append_semantically_verified_component_checkpoint(
        self,
        *,
        operation_id: str,
        operation_request_sha256: str,
        semantic_witness: PilotCheckpointSemanticWitnessV1,
        previous_recovery_root_sha256: str,
        phase_registry_envelope_bytes: bytes,
        factor_bank_envelope_bytes: bytes,
    ) -> PilotComponentCheckpointSnapshotV1:
        """Host-internal sink for a coordinator-derived semantic witness.

        Runner code has no public store API for choosing a checkpoint kind or
        constructing a witness; :class:`PilotComponentCoordinator` is the
        sole supported boundary because it owns both native component codecs.
        """

        require_opaque_id(operation_id, field_name="operation_id")
        if not isinstance(semantic_witness, PilotCheckpointSemanticWitnessV1):
            semantic_witness = PilotCheckpointSemanticWitnessV1.model_validate(
                semantic_witness
            )
        checkpoint_kind = semantic_witness.checkpoint_kind
        action_id = semantic_witness.action_id
        require_sha256(
            operation_request_sha256,
            field_name="operation_request_sha256",
        )
        require_sha256(
            previous_recovery_root_sha256,
            field_name="previous_recovery_root_sha256",
        )
        if not self.protocol.component_checkpoint_saga_required:
            raise PilotStateTransitionError(
                "protocol does not authorize component checkpoint persistence"
            )
        if (
            len(phase_registry_envelope_bytes) + len(factor_bank_envelope_bytes)
            > self.protocol.capacity_policy.max_total_stored_scalar_bytes
        ):
            raise PilotCapacityError("component checkpoint exceeds byte capacity")

        with self._write_transaction() as connection:
            self._require_active(connection)
            self._require_preflight(connection)
            owner, stage = self._semantic_checkpoint_leases(
                connection, semantic_witness
            )
            owner_terminal_call_ledger_sha256 = (
                self._execution_call_ledger_sha256(connection, owner)
                if checkpoint_kind == "gate_terminal"
                else None
            )
            existing = connection.execute(
                "SELECT * FROM component_checkpoint WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                snapshot = self._component_checkpoint_snapshot_from_row(existing)
                self._verify_component_checkpoint_snapshot(snapshot)
                metadata = snapshot.metadata
                if any(
                    (
                        metadata.checkpoint_kind != checkpoint_kind,
                        metadata.action_id != action_id,
                        metadata.semantic_witness != semantic_witness,
                        metadata.action_owner_logical_execution_key
                        != owner.logical_execution_key,
                        metadata.action_owner_logical_arm_key
                        != owner.logical_arm_key,
                        metadata.logical_execution_key
                        != stage.logical_execution_key,
                        metadata.logical_arm_key != stage.logical_arm_key,
                        metadata.owner_terminal_call_ledger_sha256
                        != owner_terminal_call_ledger_sha256,
                        metadata.previous_recovery_root_sha256
                        != previous_recovery_root_sha256,
                        snapshot.phase_registry_envelope_bytes
                        != phase_registry_envelope_bytes,
                        snapshot.factor_bank_envelope_bytes
                        != factor_bank_envelope_bytes,
                    )
                ):
                    raise PilotIdempotenceConflict(
                        "component checkpoint retry changed authority or exact bytes"
                    )
                operation = self._operation_row(connection, operation_id)
                if operation is None or any(
                    (
                        str(operation["request_sha256"])
                        != operation_request_sha256,
                        str(operation["operation_kind"])
                        != "component_checkpoint",
                        str(operation["result_key"])
                        != str(metadata.checkpoint_ordinal),
                        str(operation["result_sha256"])
                        != metadata.checkpoint_sha256,
                    )
                ):
                    raise PilotStoreIntegrityError(
                        "component checkpoint operation closure failed"
                    )
                return snapshot

            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM component_checkpoint"
                ).fetchone()[0]
            )
            if count >= self.protocol.capacity_policy.max_component_checkpoints:
                raise PilotCapacityError("component checkpoint capacity is exhausted")

            current = self._latest_component_recovery_snapshot(connection)
            if current.recovery_root_sha256 != previous_recovery_root_sha256:
                raise PilotIdempotenceConflict(
                    "checkpoint does not continue from the exact recovery head"
                )
            if (
                current.phase_registry_envelope_bytes
                == phase_registry_envelope_bytes
                and current.factor_bank_envelope_bytes
                == factor_bank_envelope_bytes
            ):
                raise PilotStateTransitionError(
                    "component checkpoint cannot repeat exact recovery bytes"
                )

            prior_row = self._unpromoted_checkpoint_row(connection)
            if prior_row is None:
                if checkpoint_kind != "action_prepared":
                    raise PilotStateTransitionError(
                        "a checkpoint action must begin with action_prepared"
                    )
            else:
                prior = self._component_checkpoint_snapshot_from_row(prior_row).metadata
                if prior.action_id != action_id:
                    raise PilotStateTransitionError(
                        "a new action cannot bypass settlement and promotion"
                    )
                if prior.checkpoint_kind == "gate_terminal":
                    raise PilotStateTransitionError(
                        "a settled checkpoint must be promoted before further mutation"
                    )
                if prior.checkpoint_kind not in _CHECKPOINT_PREDECESSORS[checkpoint_kind]:
                    raise PilotStateTransitionError(
                        "illegal component checkpoint lifecycle transition"
                    )
                prior_semantics = prior.semantic_witness
                if not (
                    prior_semantics.phase_state_after_sha256
                    == semantic_witness.phase_state_before_sha256
                    and prior_semantics.phase_sequence_after
                    == semantic_witness.phase_sequence_before
                    and prior_semantics.factor_state_after_sha256
                    == semantic_witness.factor_state_before_sha256
                    and prior_semantics.factor_event_seq_after
                    == semantic_witness.factor_event_seq_before
                    and prior_semantics.proposal_action_after_sha256
                    == semantic_witness.proposal_action_before_sha256
                ):
                    raise PilotStoreIntegrityError(
                        "checkpoint semantic witness does not continue its predecessor"
                    )
                if prior.action_owner_logical_execution_key != (
                    owner.logical_execution_key
                ) or prior.action_owner_logical_arm_key != owner.logical_arm_key:
                    raise PilotStoreIntegrityError(
                        "checkpoint changed its exact proposal action owner"
                    )

            ordinal = count + 1
            metadata = self._component_checkpoint_metadata(
                checkpoint_ordinal=ordinal,
                operation_id=operation_id,
                checkpoint_kind=checkpoint_kind,
                action_id=action_id,
                action_owner_logical_execution_key=owner.logical_execution_key,
                action_owner_logical_arm_key=owner.logical_arm_key,
                logical_execution_key=stage.logical_execution_key,
                logical_arm_key=stage.logical_arm_key,
                semantic_witness=semantic_witness,
                owner_terminal_call_ledger_sha256=(
                    owner_terminal_call_ledger_sha256
                ),
                phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=factor_bank_envelope_bytes,
                previous_recovery_root_sha256=previous_recovery_root_sha256,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="component_checkpoint",
                result_key=str(ordinal),
                result_sha256=metadata.checkpoint_sha256,
            )
            connection.execute(
                """
                INSERT INTO component_checkpoint(
                    checkpoint_ordinal, operation_id, checkpoint_kind,
                    protocol_sha256, action_id,
                    action_owner_logical_execution_key,
                    action_owner_logical_arm_key,
                    logical_execution_key, logical_arm_key, owner_split, settled,
                    semantic_witness_json, semantic_witness_sha256,
                    owner_terminal_call_ledger_sha256,
                    phase_registry_envelope,
                    phase_registry_envelope_sha256,
                    factor_bank_envelope,
                    factor_bank_envelope_sha256,
                    previous_recovery_root_sha256, checkpoint_sha256,
                    checkpoint_hmac_sha256
                ) VALUES(
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, 'TRAIN_UPDATE', ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    ordinal,
                    operation_id,
                    checkpoint_kind,
                    self.protocol.digest,
                    action_id,
                    owner.logical_execution_key,
                    owner.logical_arm_key,
                    stage.logical_execution_key,
                    stage.logical_arm_key,
                    int(metadata.settled),
                    canonical_json(semantic_witness),
                    semantic_witness.digest,
                    owner_terminal_call_ledger_sha256,
                    phase_registry_envelope_bytes,
                    metadata.phase_registry_envelope_sha256,
                    factor_bank_envelope_bytes,
                    metadata.factor_bank_envelope_sha256,
                    previous_recovery_root_sha256,
                    metadata.checkpoint_sha256,
                    metadata.checkpoint_hmac_sha256,
                ),
            )
            return PilotComponentCheckpointSnapshotV1(
                metadata=metadata,
                phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=factor_bank_envelope_bytes,
            )

    def record_capacity_preflight(
        self,
        preflight: PilotCapacityPreflightV1,
        *,
        operation_id: str,
        request_sha256: str,
    ) -> PilotCapacityPreflightV1:
        if not isinstance(preflight, PilotCapacityPreflightV1):
            preflight = PilotCapacityPreflightV1.model_validate(preflight)
        result_sha = preflight.digest
        with self._write_transaction() as connection:
            self._require_active(connection)
            self._require_component_genesis(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=request_sha256,
                operation_kind="capacity_preflight",
                result_key="capacity_preflight",
                result_sha256=result_sha,
            ):
                return self._load_preflight(connection)
            existing = connection.execute(
                "SELECT preflight_sha256 FROM capacity_preflight WHERE only_id=1"
            ).fetchone()
            if existing is not None:
                raise PilotIdempotenceConflict(
                    "one frozen protocol can record only one capacity preflight"
                )
            self._validate_preflight_bounds(preflight)
            preflight_hmac = pilot_hmac_sha256(
                self._hmac_key,
                domain="sft-pilot-preflight-v1",
                value={
                    "protocol_sha256": self.protocol.digest,
                    "preflight_sha256": result_sha,
                },
            )
            connection.execute(
                """
                INSERT INTO capacity_preflight(
                    only_id, operation_id, request_sha256, preflight_json,
                    preflight_sha256, preflight_hmac_sha256
                ) VALUES(1, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    request_sha256,
                    canonical_json(preflight),
                    result_sha,
                    preflight_hmac,
                ),
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=request_sha256,
                operation_kind="capacity_preflight",
                result_key="capacity_preflight",
                result_sha256=result_sha,
            )
        return preflight

    def _validate_preflight_bounds(self, preflight: PilotCapacityPreflightV1) -> None:
        policy = self.protocol.capacity_policy
        comparisons = (
            (
                preflight.planned_scientific_commits,
                policy.max_scientific_commits,
                "scientific commits",
            ),
            (
                preflight.planned_execution_leases,
                policy.max_execution_leases,
                "execution leases",
            ),
            (
                preflight.planned_call_receipts,
                policy.max_call_receipts,
                "call receipts",
            ),
            (
                preflight.planned_component_checkpoints,
                policy.max_component_checkpoints,
                "component checkpoints",
            ),
            (
                preflight.planned_max_calls_per_execution,
                policy.max_call_slots_per_execution,
                "calls per execution",
            ),
            (
                preflight.planned_max_active_db_bytes,
                policy.max_active_db_bytes,
                "active database bytes",
            ),
            (
                preflight.planned_archive_bytes,
                policy.max_archive_bytes,
                "archive bytes",
            ),
            (
                preflight.planned_total_stored_scalar_bytes,
                policy.max_total_stored_scalar_bytes,
                "stored scalar bytes",
            ),
            (
                preflight.planned_max_input_tokens_per_call,
                policy.max_input_tokens_per_call,
                "input tokens per call",
            ),
            (
                preflight.planned_max_output_tokens_per_call,
                policy.max_output_tokens_per_call,
                "output tokens per call",
            ),
        )
        for planned, maximum, label in comparisons:
            if planned > maximum:
                raise PilotCapacityError(f"preflight exceeds frozen {label} capacity")
        if (
            preflight.quarantined_carriers_reserved
            + preflight.indeterminate_call_reserve
            > preflight.planned_execution_leases
        ):
            raise PilotCapacityError(
                "failure/quarantine reserves exceed planned execution capacity"
            )
        if self.protocol.store_derived_schedule_required:
            schedule = self.execution_schedule
            if schedule is None:
                raise PilotStoreIntegrityError(
                    "schedule-derived preflight has no immutable schedule"
                )
            expected_schedule_shape = (
                len(schedule.entries),
                sum(len(entry.calls) for entry in schedule.entries),
                max(len(entry.calls) for entry in schedule.entries),
                max(
                    call.input_tokens_reserved
                    for entry in schedule.entries
                    for call in entry.calls
                ),
                max(
                    call.output_tokens_reserved
                    for entry in schedule.entries
                    for call in entry.calls
                ),
            )
            observed_preflight_shape = (
                preflight.planned_execution_leases,
                preflight.planned_call_receipts,
                preflight.planned_max_calls_per_execution,
                preflight.planned_max_input_tokens_per_call,
                preflight.planned_max_output_tokens_per_call,
            )
            if observed_preflight_shape != expected_schedule_shape:
                raise PilotCapacityError(
                    "preflight execution/call shape differs from the exact schedule"
                )

    def _load_preflight(
        self, connection: sqlite3.Connection
    ) -> PilotCapacityPreflightV1:
        row = connection.execute(
            "SELECT preflight_json FROM capacity_preflight WHERE only_id=1"
        ).fetchone()
        if row is None:
            raise PilotCapacityError("capacity preflight has not been recorded")
        return PilotCapacityPreflightV1.model_validate_json(str(row[0]))

    def _verify_preflight(self) -> None:
        row = self._connection.execute(
            """
            SELECT operation_id, request_sha256, preflight_json,
                   preflight_sha256, preflight_hmac_sha256
            FROM capacity_preflight WHERE only_id=1
            """
        ).fetchone()
        if row is None:
            return
        try:
            preflight = PilotCapacityPreflightV1.model_validate_json(
                str(row["preflight_json"])
            )
        except (ValueError, TypeError) as exc:
            raise PilotStoreIntegrityError("capacity preflight schema is invalid") from exc
        digest = preflight.digest
        expected_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-preflight-v1",
            value={
                "protocol_sha256": self.protocol.digest,
                "preflight_sha256": digest,
            },
        )
        if canonical_json(preflight) != str(row["preflight_json"]):
            raise PilotStoreIntegrityError("capacity preflight JSON is not canonical")
        if not hmac.compare_digest(str(row["preflight_sha256"]), digest) or not hmac.compare_digest(
            str(row["preflight_hmac_sha256"]), expected_hmac
        ):
            raise PilotStoreIntegrityError("capacity preflight authentication failed")
        self._validate_preflight_bounds(preflight)
        operation = self._operation_row(self._connection, str(row["operation_id"]))
        if operation is None or any(
            (
                str(operation["request_sha256"]) != str(row["request_sha256"]),
                str(operation["operation_kind"]) != "capacity_preflight",
                str(operation["result_key"]) != "capacity_preflight",
                str(operation["result_sha256"]) != digest,
            )
        ):
            raise PilotStoreIntegrityError("capacity preflight operation closure failed")

    def _verify_schedule_ledger(self) -> None:
        """Re-derive every persisted lease/call from the immutable schedule."""

        execution_rows = self._connection.execute(
            "SELECT * FROM execution_lease ORDER BY physical_block_ordinal"
        ).fetchall()
        if not self.protocol.store_derived_schedule_required:
            for row in execution_rows:
                lease = self._execution_from_row(row)
                if (
                    lease.physical_block_ordinal is not None
                    or lease.schedule_entry_sha256 is not None
                ):
                    raise PilotStoreIntegrityError(
                        "legacy execution ledger contains schedule-derived fields"
                    )
            call_rows = self._connection.execute(
                "SELECT * FROM call_receipt ORDER BY logical_execution_key, call_slot"
            ).fetchall()
            for row in call_rows:
                call = self._call_from_row(row)
                lease = self._load_execution(
                    self._connection, call.logical_execution_key
                )
                self._verify_scheduled_call_projection(lease, call)
            return

        schedule = self.execution_schedule
        if schedule is None:
            raise PilotStoreIntegrityError("required execution schedule is unavailable")
        if any(row["physical_block_ordinal"] is None for row in execution_rows):
            raise PilotStoreIntegrityError(
                "scheduled execution ledger is missing physical block authority"
            )
        ordinals = tuple(int(row["physical_block_ordinal"]) for row in execution_rows)
        if ordinals != tuple(range(len(execution_rows))):
            raise PilotStoreIntegrityError(
                "execution ledger is not a contiguous frozen schedule prefix"
            )
        for index, row in enumerate(execution_rows):
            lease = self._execution_from_row(row)
            entry = schedule.entries[index]
            expected_arm_key = entry.logical_arm.derive_logical_arm_key(self.protocol)
            if not (
                lease.logical_arm_key == expected_arm_key
                and lease.request_sha256 == entry.execution_request_sha256
                and lease.operation_kind == entry.logical_arm.operation_kind
                and lease.split == entry.logical_arm.split
                and lease.unit_commitment == entry.logical_arm.unit_commitment
                and lease.namespace_sha256 == self.protocol.namespace.digest
                and lease.call_slots_reserved == len(entry.calls)
                and lease.input_tokens_reserved == entry.input_tokens_reserved
                and lease.output_tokens_reserved == entry.output_tokens_reserved
                and lease.physical_block_ordinal == entry.physical_block_ordinal
                and lease.schedule_entry_sha256 == entry.digest
            ):
                raise PilotStoreIntegrityError(
                    "execution ledger differs from its immutable schedule row"
                )
            calls = tuple(
                self._call_from_row(call_row)
                for call_row in self._connection.execute(
                    "SELECT * FROM call_receipt WHERE logical_execution_key=? "
                    "ORDER BY call_slot",
                    (lease.logical_execution_key,),
                ).fetchall()
            )
            if tuple(call.call_slot for call in calls) != tuple(range(len(calls))):
                raise PilotStoreIntegrityError(
                    "call ledger is not a contiguous frozen schedule prefix"
                )
            if len(calls) > len(entry.calls):
                raise PilotStoreIntegrityError("call ledger exceeds frozen schedule")
            for call in calls:
                self._verify_scheduled_call_projection(lease, call)
            if lease.state == "completed" and len(calls) != len(entry.calls):
                raise PilotStoreIntegrityError(
                    "completed execution is missing a scheduled call"
                )

    def _scheduled_entry_for_arm(
        self, logical_arm: PilotLogicalArmCoordinatesV1
    ) -> PilotExecutionScheduleEntryV1:
        if self.execution_schedule is None:
            raise PilotStoreIntegrityError("store has no schedule-derived authority")
        try:
            return self.execution_schedule.entry_for(logical_arm)
        except KeyError as exc:
            raise PilotStoreIntegrityError(
                "logical arm is absent from the exact execution schedule"
            ) from exc

    def _scheduled_entry_for_lease(
        self, lease: PilotExecutionLeaseV1
    ) -> PilotExecutionScheduleEntryV1:
        arms = tuple(
            arm
            for arm in self.protocol.authorized_logical_arms
            if arm.derive_logical_arm_key(self.protocol) == lease.logical_arm_key
        )
        if len(arms) != 1:
            raise PilotStoreIntegrityError(
                "execution lease has no unique frozen logical arm"
            )
        return self._scheduled_entry_for_arm(arms[0])

    def _verify_scheduled_call_projection(
        self,
        lease: PilotExecutionLeaseV1,
        receipt: PilotCallReceiptV1,
    ) -> None:
        if not self.protocol.store_derived_schedule_required:
            if any(
                value is not None
                for value in (
                    lease.physical_block_ordinal,
                    lease.schedule_entry_sha256,
                    receipt.scheduled_call_sha256,
                    receipt.request_renderer_sha256,
                    receipt.prompt_template_sha256,
                    receipt.json_mode,
                    receipt.artifact_role,
                )
            ):
                raise PilotStoreIntegrityError(
                    "legacy ledger contains schedule-derived fields"
                )
            return
        scheduled_entry = self._scheduled_entry_for_lease(lease)
        if receipt.call_slot >= len(scheduled_entry.calls):
            raise PilotStoreIntegrityError("persisted call lies outside its schedule")
        scheduled_call = scheduled_entry.calls[receipt.call_slot]
        if not (
            lease.request_sha256 == scheduled_entry.execution_request_sha256
            and lease.operation_kind == scheduled_entry.logical_arm.operation_kind
            and lease.split == scheduled_entry.logical_arm.split
            and lease.unit_commitment == scheduled_entry.logical_arm.unit_commitment
            and lease.call_slots_reserved == len(scheduled_entry.calls)
            and lease.input_tokens_reserved == scheduled_entry.input_tokens_reserved
            and lease.output_tokens_reserved == scheduled_entry.output_tokens_reserved
            and lease.physical_block_ordinal
            == scheduled_entry.physical_block_ordinal
            and lease.schedule_entry_sha256 == scheduled_entry.digest
            and receipt.request_sha256 == scheduled_call.request_envelope_sha256
            and receipt.input_tokens_reserved
            == scheduled_call.input_tokens_reserved
            and receipt.output_tokens_reserved
            == scheduled_call.output_tokens_reserved
            and receipt.max_completion_tokens
            == scheduled_call.output_tokens_reserved
            and receipt.scheduled_call_sha256 == scheduled_call.digest
            and receipt.request_renderer_sha256
            == scheduled_call.request_renderer_sha256
            and receipt.prompt_template_sha256
            == scheduled_call.prompt_template_sha256
            and receipt.json_mode == scheduled_call.json_mode
            and receipt.artifact_role == scheduled_call.artifact_role
        ):
            raise PilotStoreIntegrityError(
                "persisted call differs from its immutable schedule slot"
            )

    @staticmethod
    def _require_schedule_execution_comparison(
        request: PilotExecutionLeaseRequestV1,
        scheduled: PilotExecutionScheduleEntryV1,
    ) -> None:
        arm = scheduled.logical_arm
        expected = (
            scheduled.execution_request_sha256,
            arm.operation_kind,
            arm.split,
            arm.unit_commitment,
            len(scheduled.calls),
            scheduled.input_tokens_reserved,
            scheduled.output_tokens_reserved,
        )
        observed = (
            request.request_sha256,
            request.operation_kind,
            request.split,
            request.unit_commitment,
            request.call_slots_reserved,
            request.input_tokens_reserved,
            request.output_tokens_reserved,
        )
        if observed != expected:
            raise PilotStoreIntegrityError(
                "execution request differs from its store-derived schedule row"
            )

    def reserve_execution(
        self,
        request: PilotExecutionLeaseRequestV1,
        *,
        logical_arm: PilotLogicalArmCoordinatesV1,
        operation_id: str,
        operation_request_sha256: str,
    ) -> PilotExecutionLeaseV1:
        if not isinstance(request, PilotExecutionLeaseRequestV1):
            request = PilotExecutionLeaseRequestV1.model_validate(request)
        if not isinstance(logical_arm, PilotLogicalArmCoordinatesV1):
            logical_arm = PilotLogicalArmCoordinatesV1.model_validate(logical_arm)
        if logical_arm not in self.protocol.authorized_logical_arms:
            raise PilotStoreIntegrityError(
                "logical arm is absent from the frozen protocol manifest"
            )
        if (
            logical_arm.unit_commitment != request.unit_commitment
            or logical_arm.split != request.split
            or logical_arm.operation_kind != request.operation_kind
        ):
            raise PilotStoreIntegrityError(
                "logical-arm coordinates do not close the execution request"
            )
        scheduled: PilotExecutionScheduleEntryV1 | None = None
        if self.protocol.store_derived_schedule_required:
            scheduled = self._scheduled_entry_for_arm(logical_arm)
            self._require_schedule_execution_comparison(request, scheduled)
        lease = PilotExecutionLeaseV1(
            logical_execution_key=request.logical_execution_key,
            logical_arm_key=logical_arm.derive_logical_arm_key(self.protocol),
            operation_kind=request.operation_kind,
            request_sha256=request.request_sha256,
            namespace_sha256=request.namespace_sha256,
            split=request.split,
            unit_commitment=request.unit_commitment,
            action_id=request.action_id,
            call_slots_reserved=request.call_slots_reserved,
            input_tokens_reserved=request.input_tokens_reserved,
            output_tokens_reserved=request.output_tokens_reserved,
            physical_block_ordinal=(
                None if scheduled is None else scheduled.physical_block_ordinal
            ),
            schedule_entry_sha256=None if scheduled is None else scheduled.digest,
            state="reserved",
        )
        if lease.namespace_sha256 != self.protocol.namespace.digest:
            raise PilotStoreIntegrityError("execution lease namespace is not protocol exact")
        policy = self.protocol.capacity_policy
        if lease.call_slots_reserved > policy.max_call_slots_per_execution:
            raise PilotCapacityError("execution call-slot reservation exceeds capacity")
        if (
            lease.input_tokens_reserved
            > lease.call_slots_reserved * policy.max_input_tokens_per_call
        ):
            raise PilotCapacityError("execution input reservation exceeds per-call bounds")
        if (
            lease.output_tokens_reserved
            > lease.call_slots_reserved * policy.max_output_tokens_per_call
        ):
            raise PilotCapacityError("execution output reservation exceeds per-call bounds")
        result_sha = canonical_sha256(lease)
        with self._write_transaction() as connection:
            self._require_active(connection)
            self._require_preflight(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="reserve_execution",
                result_key=lease.logical_execution_key,
                result_sha256=result_sha,
            ):
                return self._load_execution(connection, lease.logical_execution_key)
            if int(
                connection.execute("SELECT COUNT(*) FROM execution_lease").fetchone()[0]
            ) >= policy.max_execution_leases:
                raise PilotCapacityError("execution-lease capacity is exhausted")
            existing_arm = connection.execute(
                "SELECT logical_execution_key FROM execution_lease WHERE logical_arm_key=?",
                (lease.logical_arm_key,),
            ).fetchone()
            if existing_arm is not None:
                raise PilotIdempotenceConflict(
                    "logical_arm_key is permanently consumed independent of generation"
                )
            if scheduled is not None:
                prior_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM execution_lease"
                    ).fetchone()[0]
                )
                if scheduled.physical_block_ordinal != prior_count:
                    raise PilotStateTransitionError(
                        "execution violates the frozen physical block order"
                    )
            self._require_execution_budget(connection, lease)
            connection.execute(
                """
                INSERT INTO execution_lease(
                    logical_execution_key, logical_arm_key, operation_kind,
                    request_sha256, namespace_sha256, split, unit_commitment,
                    action_id, call_slots_reserved, input_tokens_reserved,
                    output_tokens_reserved, physical_block_ordinal,
                    schedule_entry_sha256, state
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.logical_execution_key,
                    lease.logical_arm_key,
                    lease.operation_kind,
                    lease.request_sha256,
                    lease.namespace_sha256,
                    lease.split,
                    lease.unit_commitment,
                    lease.action_id,
                    lease.call_slots_reserved,
                    lease.input_tokens_reserved,
                    lease.output_tokens_reserved,
                    lease.physical_block_ordinal,
                    lease.schedule_entry_sha256,
                    lease.state,
                ),
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="reserve_execution",
                result_key=lease.logical_execution_key,
                result_sha256=result_sha,
            )
        return lease

    @staticmethod
    def _phase_for_lease(lease: PilotExecutionLeaseV1) -> str:
        if lease.split == "FINAL_VAL" or lease.operation_kind == "final_val":
            return "FINAL_VAL"
        if lease.operation_kind in {"source_probe", "target_probe"}:
            return "PROBE"
        return "TRAIN_UPDATE"

    def _require_execution_budget(
        self, connection: sqlite3.Connection, lease: PilotExecutionLeaseV1
    ) -> None:
        phase = self._phase_for_lease(lease)
        budget = next(
            (item for item in self.protocol.phase_budgets if item.phase == phase),
            None,
        )
        if budget is None:
            raise PilotCapacityError(f"phase {phase} has no frozen budget")
        rows = connection.execute(
            "SELECT * FROM execution_lease"
        ).fetchall()
        same_phase = [
            self._execution_from_row(row)
            for row in rows
            if self._phase_for_lease(self._execution_from_row(row)) == phase
        ]
        if len(same_phase) + 1 > budget.executions:
            raise PilotCapacityError(f"phase {phase} execution budget is exhausted")
        if sum(item.call_slots_reserved for item in same_phase) + lease.call_slots_reserved > budget.call_slots:
            raise PilotCapacityError(f"phase {phase} call-slot budget is exhausted")
        if sum(item.input_tokens_reserved for item in same_phase) + lease.input_tokens_reserved > budget.input_tokens:
            raise PilotCapacityError(f"phase {phase} input-token budget is exhausted")
        if sum(item.output_tokens_reserved for item in same_phase) + lease.output_tokens_reserved > budget.output_tokens:
            raise PilotCapacityError(f"phase {phase} output-token budget is exhausted")

    def _require_call_recovery_binding(
        self,
        connection: sqlite3.Connection,
        *,
        lease: PilotExecutionLeaseV1,
        expected_recovery_root_sha256: str | None,
    ) -> None:
        """Close a provider crossing over the exact persisted component head."""

        saga = self.protocol.component_checkpoint_saga_required
        if not saga:
            if expected_recovery_root_sha256 is not None:
                raise PilotStoreIntegrityError(
                    "hash-only/legacy protocols cannot assert checkpoint authority"
                )
            return
        if expected_recovery_root_sha256 is None:
            raise PilotStoreIntegrityError(
                "checkpoint-saga calls require an expected recovery root"
            )
        require_sha256(
            expected_recovery_root_sha256,
            field_name="expected_component_recovery_root_sha256",
        )
        recovery = self._latest_component_recovery_snapshot(connection)
        if recovery.recovery_root_sha256 != expected_recovery_root_sha256:
            raise PilotIdempotenceConflict(
                "provider crossing expected a stale component recovery root"
            )
        if lease.split == "FINAL_VAL" or lease.operation_kind == "final_val":
            if recovery.origin != "scientific_bundle":
                raise PilotStateTransitionError(
                    "FINAL_VAL cannot run with unpromoted component state"
                )
            return
        checkpoint = recovery.checkpoint
        if checkpoint is None:
            raise PilotStateTransitionError(
                "TRAIN_UPDATE provider crossing requires an open checkpoint"
            )
        if checkpoint.action_id != lease.action_id:
            raise PilotStoreIntegrityError(
                "provider crossing checkpoint differs from its action/execution lease"
            )
        expected_kind: PilotComponentCheckpointKind | None = None
        if lease.operation_kind == "proposal_generation":
            expected_kind = "generation_start_authorized"
            exact_stage = (
                checkpoint.logical_execution_key == lease.logical_execution_key
                and checkpoint.logical_arm_key == lease.logical_arm_key
            )
        elif lease.operation_kind in {"source_probe", "target_probe"}:
            expected_kind = "probe_attempt_open"
            witness = checkpoint.semantic_witness
            admitted_arm_keys = {
                witness.probe_source_logical_arm_key,
                witness.probe_target_logical_arm_key,
            }
            exact_stage = lease.logical_arm_key in admitted_arm_keys
        else:
            exact_stage = False
        if (
            expected_kind is None
            or checkpoint.checkpoint_kind != expected_kind
            or not exact_stage
        ):
            raise PilotStateTransitionError(
                "provider crossing is not authorized by its lifecycle checkpoint"
            )

    def reserve_call(
        self,
        *,
        operation_id: str,
        operation_request_sha256: str,
        call_key: str,
        logical_execution_key: str,
        call_slot: int,
        call_request_sha256: str,
        input_tokens_reserved: int,
        output_tokens_reserved: int,
        expected_component_recovery_root_sha256: str | None = None,
        request_renderer_sha256: str | None = None,
        prompt_template_sha256: str | None = None,
        json_mode: bool | None = None,
        artifact_role: str | None = None,
    ) -> PilotCallReceiptV1:
        policy = self.protocol.capacity_policy
        with self._write_transaction() as connection:
            self._require_active(connection)
            self._require_preflight(connection)
            lease = self._load_execution(connection, logical_execution_key)
            scheduled_call: PilotCallScheduleEntryV1 | None = None
            if self.protocol.store_derived_schedule_required:
                scheduled_entry = self._scheduled_entry_for_lease(lease)
                if not (
                    lease.schedule_entry_sha256 == scheduled_entry.digest
                    and lease.physical_block_ordinal
                    == scheduled_entry.physical_block_ordinal
                ):
                    raise PilotStoreIntegrityError(
                        "execution lease differs from its frozen schedule row"
                    )
                if call_slot < 0 or call_slot >= len(scheduled_entry.calls):
                    raise PilotStateTransitionError(
                        "call slot is absent from the frozen execution schedule"
                    )
                scheduled_call = scheduled_entry.calls[call_slot]
                comparisons = (
                    (call_request_sha256, scheduled_call.request_envelope_sha256),
                    (input_tokens_reserved, scheduled_call.input_tokens_reserved),
                    (output_tokens_reserved, scheduled_call.output_tokens_reserved),
                )
                optional_comparisons = (
                    (request_renderer_sha256, scheduled_call.request_renderer_sha256),
                    (prompt_template_sha256, scheduled_call.prompt_template_sha256),
                    (json_mode, scheduled_call.json_mode),
                    (artifact_role, scheduled_call.artifact_role),
                )
                if any(observed != expected for observed, expected in comparisons) or any(
                    observed is not None and observed != expected
                    for observed, expected in optional_comparisons
                ):
                    raise PilotStoreIntegrityError(
                        "call request differs from its store-derived schedule slot"
                    )
                input_tokens_reserved = scheduled_call.input_tokens_reserved
                output_tokens_reserved = scheduled_call.output_tokens_reserved
                call_request_sha256 = scheduled_call.request_envelope_sha256
            elif any(
                value is not None
                for value in (
                    request_renderer_sha256,
                    prompt_template_sha256,
                    json_mode,
                    artifact_role,
                )
            ):
                raise PilotStoreIntegrityError(
                    "legacy calls cannot assert schedule-derived metadata"
                )
            receipt = PilotCallReceiptV1(
                call_key=call_key,
                logical_execution_key=logical_execution_key,
                call_slot=call_slot,
                request_sha256=call_request_sha256,
                input_tokens_reserved=input_tokens_reserved,
                output_tokens_reserved=output_tokens_reserved,
                max_completion_tokens=output_tokens_reserved,
                expected_component_recovery_root_sha256=(
                    expected_component_recovery_root_sha256
                ),
                scheduled_call_sha256=(
                    None if scheduled_call is None else scheduled_call.digest
                ),
                request_renderer_sha256=(
                    None
                    if scheduled_call is None
                    else scheduled_call.request_renderer_sha256
                ),
                prompt_template_sha256=(
                    None
                    if scheduled_call is None
                    else scheduled_call.prompt_template_sha256
                ),
                json_mode=None if scheduled_call is None else scheduled_call.json_mode,
                artifact_role=(
                    None if scheduled_call is None else scheduled_call.artifact_role
                ),
                state="reserved",
                conservative_charged_tokens=0,
            )
            result_sha = canonical_sha256(receipt)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="reserve_call",
                result_key=call_key,
                result_sha256=result_sha,
            ):
                return self._load_call(connection, call_key)
            if input_tokens_reserved > policy.max_input_tokens_per_call:
                raise PilotCapacityError("call input-token reservation exceeds capacity")
            if output_tokens_reserved > policy.max_output_tokens_per_call:
                raise PilotCapacityError("call output-token reservation exceeds capacity")
            if lease.state not in {"reserved", "request_started"}:
                raise PilotStateTransitionError(
                    "calls can only be reserved for an active execution"
                )
            self._require_call_recovery_binding(
                connection,
                lease=lease,
                expected_recovery_root_sha256=(
                    expected_component_recovery_root_sha256
                ),
            )
            if call_slot >= lease.call_slots_reserved:
                raise PilotCapacityError("call slot lies outside the execution reservation")
            total_calls = int(
                connection.execute("SELECT COUNT(*) FROM call_receipt").fetchone()[0]
            )
            if total_calls >= policy.max_call_receipts:
                raise PilotCapacityError("call-receipt capacity is exhausted")
            aggregates = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(input_tokens_reserved), 0),
                       COALESCE(SUM(output_tokens_reserved), 0)
                FROM call_receipt WHERE logical_execution_key=?
                """,
                (logical_execution_key,),
            ).fetchone()
            prior_rows = connection.execute(
                """
                SELECT call_slot, state FROM call_receipt
                WHERE logical_execution_key=? ORDER BY call_slot
                """,
                (logical_execution_key,),
            ).fetchall()
            if call_slot != len(prior_rows) or tuple(
                int(row["call_slot"]) for row in prior_rows
            ) != tuple(range(len(prior_rows))):
                raise PilotStateTransitionError(
                    "call slots must be reserved in contiguous execution order"
                )
            if any(str(row["state"]) != "completed" for row in prior_rows):
                raise PilotStateTransitionError(
                    "a dependent call requires all earlier slots to be completed"
                )
            if int(aggregates[0]) + 1 > lease.call_slots_reserved:
                raise PilotCapacityError("execution call-slot reservation is exhausted")
            if int(aggregates[1]) + input_tokens_reserved > lease.input_tokens_reserved:
                raise PilotCapacityError("execution input-token reservation is exhausted")
            if int(aggregates[2]) + output_tokens_reserved > lease.output_tokens_reserved:
                raise PilotCapacityError("execution output-token reservation is exhausted")
            try:
                connection.execute(
                    """
                    INSERT INTO call_receipt(
                        call_key, logical_execution_key, call_slot, request_sha256,
                        model_name, input_tokens_reserved, output_tokens_reserved,
                        max_completion_tokens,
                        expected_component_recovery_root_sha256,
                        scheduled_call_sha256, request_renderer_sha256,
                        prompt_template_sha256, json_mode, artifact_role,
                        state, output_envelope_sha256,
                        provider_usage_known, input_tokens_used, output_tokens_used,
                        conservative_charged_tokens
                    ) VALUES(
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        NULL, 0, NULL, NULL, 0
                    )
                    """,
                    (
                        call_key,
                        logical_execution_key,
                        call_slot,
                        call_request_sha256,
                        "gpt-4o-mini",
                        input_tokens_reserved,
                        output_tokens_reserved,
                        output_tokens_reserved,
                        expected_component_recovery_root_sha256,
                        receipt.scheduled_call_sha256,
                        receipt.request_renderer_sha256,
                        receipt.prompt_template_sha256,
                        None if receipt.json_mode is None else int(receipt.json_mode),
                        receipt.artifact_role,
                        "reserved",
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PilotIdempotenceConflict(
                    "call key or (logical execution, slot) is already consumed"
                ) from exc
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="reserve_call",
                result_key=call_key,
                result_sha256=result_sha,
            )
        return receipt

    def start_call(
        self,
        call_key: str,
        *,
        operation_id: str,
        operation_request_sha256: str,
        call_request_sha256: str,
        expected_component_recovery_root_sha256: str | None = None,
    ) -> PilotCallStartAuthorizationV1:
        result_sha = canonical_sha256(
            {
                "call_key": call_key,
                "state": "request_started",
                "expected_component_recovery_root_sha256": (
                    expected_component_recovery_root_sha256
                ),
            }
        )
        with self._write_transaction() as connection:
            self._require_active(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="start_call",
                result_key=call_key,
                result_sha256=result_sha,
            ):
                return PilotCallStartAuthorizationV1(
                    disposition="already_started",
                    receipt=self._load_call(connection, call_key),
                )
            receipt = self._load_call(connection, call_key)
            if receipt.request_sha256 != call_request_sha256:
                raise PilotIdempotenceConflict("call request commitment changed at start")
            if receipt.state != "reserved":
                raise PilotStateTransitionError("only a reserved call can start")
            lease = self._load_execution(connection, receipt.logical_execution_key)
            self._verify_scheduled_call_projection(lease, receipt)
            if lease.state not in {"reserved", "request_started"}:
                raise PilotStateTransitionError("execution lease is already terminal")
            if (
                receipt.expected_component_recovery_root_sha256
                != expected_component_recovery_root_sha256
            ):
                raise PilotIdempotenceConflict(
                    "call start changed its expected component recovery root"
                )
            self._require_call_recovery_binding(
                connection,
                lease=lease,
                expected_recovery_root_sha256=(
                    expected_component_recovery_root_sha256
                ),
            )
            other_started = connection.execute(
                """
                SELECT call_key FROM call_receipt
                WHERE state='request_started' AND call_key<>?
                LIMIT 1
                """,
                (call_key,),
            ).fetchone()
            if other_started is not None:
                raise PilotStateTransitionError(
                    "single-call authority already has a request in flight"
                )
            earlier = connection.execute(
                """
                SELECT call_slot, state FROM call_receipt
                WHERE logical_execution_key=? AND call_slot<?
                ORDER BY call_slot
                """,
                (receipt.logical_execution_key, receipt.call_slot),
            ).fetchall()
            if (
                tuple(int(row["call_slot"]) for row in earlier)
                != tuple(range(receipt.call_slot))
                or any(str(row["state"]) != "completed" for row in earlier)
            ):
                raise PilotStateTransitionError(
                    "a call can start only after every earlier slot completed"
                )
            connection.execute(
                "UPDATE call_receipt SET state='request_started' WHERE call_key=?",
                (call_key,),
            )
            if lease.state == "reserved":
                connection.execute(
                    "UPDATE execution_lease SET state='request_started' "
                    "WHERE logical_execution_key=?",
                    (receipt.logical_execution_key,),
                )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="start_call",
                result_key=call_key,
                result_sha256=result_sha,
            )
            return PilotCallStartAuthorizationV1(
                disposition="newly_authorized",
                receipt=self._load_call(connection, call_key),
            )

    def complete_call(
        self,
        call_key: str,
        *,
        operation_id: str,
        operation_request_sha256: str,
        call_request_sha256: str,
        output_envelope_sha256: str,
        provider_usage_known: bool,
        input_tokens_used: int,
        output_tokens_used: int,
    ) -> PilotCallReceiptV1:
        require_sha256(output_envelope_sha256, field_name="output_envelope_sha256")
        desired = {
            "call_key": call_key,
            "state": "completed",
            "output_envelope_sha256": output_envelope_sha256,
            "provider_usage_known": provider_usage_known,
            "input_tokens_used": input_tokens_used,
            "output_tokens_used": output_tokens_used,
        }
        result_sha = canonical_sha256(desired)
        with self._write_transaction() as connection:
            self._require_active(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="complete_call",
                result_key=call_key,
                result_sha256=result_sha,
            ):
                return self._load_call(connection, call_key)
            receipt = self._load_call(connection, call_key)
            if receipt.request_sha256 != call_request_sha256:
                raise PilotIdempotenceConflict("call request commitment changed at completion")
            if receipt.state != "request_started":
                raise PilotStateTransitionError("only a started call can complete")
            if not provider_usage_known:
                raise PilotStateTransitionError(
                    "pilot completion requires provider-authoritative usage"
                )
            if input_tokens_used < 0 or input_tokens_used > receipt.input_tokens_reserved:
                raise PilotCapacityError("call input usage exceeds its reservation")
            if output_tokens_used < 0 or output_tokens_used > receipt.output_tokens_reserved:
                raise PilotCapacityError("call output usage exceeds its reservation")
            connection.execute(
                """
                UPDATE call_receipt
                SET state='completed', output_envelope_sha256=?,
                    provider_usage_known=1, input_tokens_used=?,
                    output_tokens_used=?, conservative_charged_tokens=?
                WHERE call_key=?
                """,
                (
                    output_envelope_sha256,
                    input_tokens_used,
                    output_tokens_used,
                    input_tokens_used + output_tokens_used,
                    call_key,
                ),
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="complete_call",
                result_key=call_key,
                result_sha256=result_sha,
            )
            return self._load_call(connection, call_key)

    def mark_call_indeterminate(
        self,
        call_key: str,
        *,
        operation_id: str,
        operation_request_sha256: str,
        provider_usage_known: bool = False,
        input_tokens_used: int | None = None,
        output_tokens_used: int | None = None,
    ) -> PilotCallReceiptV1:
        if not isinstance(provider_usage_known, bool):
            raise TypeError("provider_usage_known must be boolean")
        if provider_usage_known:
            if (
                isinstance(input_tokens_used, bool)
                or not isinstance(input_tokens_used, int)
                or input_tokens_used < 0
                or isinstance(output_tokens_used, bool)
                or not isinstance(output_tokens_used, int)
                or output_tokens_used < 0
            ):
                raise ValueError(
                    "known provider usage requires non-negative exact counters"
                )
        elif input_tokens_used is not None or output_tokens_used is not None:
            raise ValueError("unknown provider usage cannot carry exact counters")
        result_sha = canonical_sha256(
            {
                "call_key": call_key,
                "state": "indeterminate",
                "provider_usage_known": provider_usage_known,
                "input_tokens_used": input_tokens_used,
                "output_tokens_used": output_tokens_used,
            }
        )
        with self._write_transaction() as connection:
            self._require_active(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="mark_call_indeterminate",
                result_key=call_key,
                result_sha256=result_sha,
            ):
                return self._load_call(connection, call_key)
            receipt = self._load_call(connection, call_key)
            if receipt.state != "request_started":
                raise PilotStateTransitionError(
                    "only a started call can become indeterminate"
                )
            charged_tokens = receipt.input_tokens_reserved + receipt.output_tokens_reserved
            if provider_usage_known:
                assert input_tokens_used is not None
                assert output_tokens_used is not None
                charged_tokens = max(
                    charged_tokens,
                    input_tokens_used + output_tokens_used,
                )
            connection.execute(
                """
                UPDATE call_receipt
                SET state='indeterminate',
                    provider_usage_known=?, input_tokens_used=?, output_tokens_used=?,
                    conservative_charged_tokens=?
                WHERE call_key=?
                """,
                (
                    int(provider_usage_known),
                    input_tokens_used,
                    output_tokens_used,
                    charged_tokens,
                    call_key,
                ),
            )
            connection.execute(
                """
                UPDATE call_receipt SET state='failed_before_start'
                WHERE logical_execution_key=? AND state='reserved'
                """,
                (receipt.logical_execution_key,),
            )
            connection.execute(
                "UPDATE execution_lease SET state='indeterminate' "
                "WHERE logical_execution_key=?",
                (receipt.logical_execution_key,),
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="mark_call_indeterminate",
                result_key=call_key,
                result_sha256=result_sha,
            )
            return self._load_call(connection, call_key)

    def fail_call_before_start(
        self,
        call_key: str,
        *,
        operation_id: str,
        operation_request_sha256: str,
    ) -> PilotCallReceiptV1:
        result_sha = canonical_sha256(
            {"call_key": call_key, "state": "failed_before_start"}
        )
        with self._write_transaction() as connection:
            self._require_active(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="fail_call_before_start",
                result_key=call_key,
                result_sha256=result_sha,
            ):
                return self._load_call(connection, call_key)
            receipt = self._load_call(connection, call_key)
            if receipt.state != "reserved":
                raise PilotStateTransitionError("only a reserved call can fail before start")
            connection.execute(
                "UPDATE call_receipt SET state='failed_before_start' WHERE call_key=?",
                (call_key,),
            )
            remaining = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM call_receipt
                    WHERE logical_execution_key=? AND state IN ('reserved', 'request_started')
                    """,
                    (receipt.logical_execution_key,),
                ).fetchone()[0]
            )
            if remaining == 0:
                completed_calls = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM call_receipt
                        WHERE logical_execution_key=? AND state='completed'
                        """,
                        (receipt.logical_execution_key,),
                    ).fetchone()[0]
                )
                terminal_state = (
                    "indeterminate" if completed_calls else "failed_before_start"
                )
                connection.execute(
                    "UPDATE execution_lease SET state=? "
                    "WHERE logical_execution_key=? "
                    "AND state IN ('reserved', 'request_started')",
                    (terminal_state, receipt.logical_execution_key),
                )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="fail_call_before_start",
                result_key=call_key,
                result_sha256=result_sha,
            )
            return self._load_call(connection, call_key)

    def complete_execution(
        self,
        logical_execution_key: str,
        *,
        operation_id: str,
        operation_request_sha256: str,
    ) -> PilotExecutionLeaseV1:
        result_sha = canonical_sha256(
            {"logical_execution_key": logical_execution_key, "state": "completed"}
        )
        with self._write_transaction() as connection:
            self._require_active(connection)
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="complete_execution",
                result_key=logical_execution_key,
                result_sha256=result_sha,
            ):
                return self._load_execution(connection, logical_execution_key)
            lease = self._load_execution(connection, logical_execution_key)
            if lease.state != "request_started":
                raise PilotStateTransitionError("only a started execution can complete")
            rows = connection.execute(
                "SELECT state FROM call_receipt WHERE logical_execution_key=?",
                (logical_execution_key,),
            ).fetchall()
            if len(rows) != lease.call_slots_reserved or any(
                str(row[0]) != "completed" for row in rows
            ):
                raise PilotStateTransitionError(
                    "execution completion requires all reserved call slots completed"
                )
            connection.execute(
                "UPDATE execution_lease SET state='completed' "
                "WHERE logical_execution_key=?",
                (logical_execution_key,),
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="complete_execution",
                result_key=logical_execution_key,
                result_sha256=result_sha,
            )
            return self._load_execution(connection, logical_execution_key)

    def append_scientific_commit(
        self,
        *,
        operation_id: str,
        owner_logical_execution_key: str,
        request_sha256: str,
        before_state_sha256: str,
        after_state_sha256: str,
    ) -> PilotScientificCommitV1:
        require_opaque_id(operation_id, field_name="operation_id")
        require_opaque_id(
            owner_logical_execution_key,
            field_name="owner_logical_execution_key",
        )
        for name, value in (
            ("request_sha256", request_sha256),
            ("before_state_sha256", before_state_sha256),
            ("after_state_sha256", after_state_sha256),
        ):
            require_sha256(value, field_name=name)
        if self.protocol.component_bundle_required:
            raise PilotStateTransitionError(
                "hash-only scientific commits are forbidden when component bundles are required"
            )
        with self._write_transaction() as connection:
            self._require_active(connection)
            self._require_preflight(connection)
            existing = connection.execute(
                "SELECT * FROM scientific_commit WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                commit = self._scientific_from_row(existing)
                if (
                    commit.request_sha256 != request_sha256
                    or commit.owner_logical_execution_key
                    != owner_logical_execution_key
                    or commit.before_state_sha256 != before_state_sha256
                    or commit.after_state_sha256 != after_state_sha256
                ):
                    raise PilotIdempotenceConflict(
                        "scientific operation_id was reused with different state"
                    )
                operation = self._operation_row(connection, operation_id)
                if operation is None or any(
                    (
                        str(operation["request_sha256"]) != request_sha256,
                        str(operation["operation_kind"]) != "scientific_commit",
                        str(operation["result_key"]) != str(commit.commit_ordinal),
                        str(operation["result_sha256"]) != commit.commit_sha256,
                    )
                ):
                    raise PilotStoreIntegrityError(
                        "scientific commit operation closure failed"
                    )
                return commit
            policy = self.protocol.capacity_policy
            ordinal = int(
                connection.execute("SELECT COUNT(*) FROM scientific_commit").fetchone()[0]
            ) + 1
            if ordinal > policy.max_scientific_commits:
                raise PilotCapacityError("scientific commit capacity is exhausted")
            owner = self._load_execution(connection, owner_logical_execution_key)
            if (
                owner.state != "completed"
                or owner.split != "TRAIN_UPDATE"
                or owner.operation_kind != "proposal_generation"
                or owner.action_id is None
            ):
                raise PilotStoreIntegrityError(
                    "scientific commit requires a completed TRAIN_UPDATE proposal owner"
                )
            prior_owner = connection.execute(
                "SELECT 1 FROM scientific_commit WHERE owner_logical_execution_key=?",
                (owner_logical_execution_key,),
            ).fetchone()
            if prior_owner is not None:
                raise PilotIdempotenceConflict(
                    "one completed execution can own only one scientific commit"
                )
            previous = connection.execute(
                """
                SELECT commit_sha256, after_state_sha256 FROM scientific_commit
                ORDER BY commit_ordinal DESC LIMIT 1
                """
            ).fetchone()
            previous_sha = ZERO_SHA256 if previous is None else str(previous[0])
            expected_before = (
                self.protocol.genesis_state_sha256
                if previous is None
                else str(previous[1])
            )
            if expected_before != before_state_sha256:
                raise PilotStoreIntegrityError(
                    "scientific state chain does not continue from protocol genesis/head"
                )
            body = {
                "commit_ordinal": ordinal,
                "operation_id": operation_id,
                "owner_logical_execution_key": owner_logical_execution_key,
                "owner_action_id": owner.action_id,
                "owner_split": owner.split,
                "request_sha256": request_sha256,
                "before_state_sha256": before_state_sha256,
                "after_state_sha256": after_state_sha256,
                "previous_commit_sha256": previous_sha,
                "protocol_sha256": self.protocol.digest,
                "schema_digest": EXPECTED_SCHEMA_DIGEST,
            }
            commit_sha = canonical_sha256(body)
            commit_hmac = pilot_hmac_sha256(
                self._hmac_key,
                domain="sft-pilot-scientific-commit-v1",
                value={"body": body, "commit_sha256": commit_sha},
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=request_sha256,
                operation_kind="scientific_commit",
                result_key=str(ordinal),
                result_sha256=commit_sha,
            )
            connection.execute(
                """
                INSERT INTO scientific_commit(
                    commit_ordinal, operation_id, owner_logical_execution_key,
                    owner_action_id, owner_split, request_sha256,
                    before_state_sha256, after_state_sha256,
                    previous_commit_sha256, commit_sha256, commit_hmac_sha256
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ordinal,
                    operation_id,
                    owner_logical_execution_key,
                    owner.action_id,
                    owner.split,
                    request_sha256,
                    before_state_sha256,
                    after_state_sha256,
                    previous_sha,
                    commit_sha,
                    commit_hmac,
                ),
            )
            return PilotScientificCommitV1(
                commit_ordinal=ordinal,
                operation_id=operation_id,
                owner_logical_execution_key=owner_logical_execution_key,
                owner_action_id=owner.action_id,
                owner_split="TRAIN_UPDATE",
                request_sha256=request_sha256,
                before_state_sha256=before_state_sha256,
                after_state_sha256=after_state_sha256,
                previous_commit_sha256=previous_sha,
                commit_sha256=commit_sha,
                commit_hmac_sha256=commit_hmac,
            )

    def _insert_component_checkpoint_promotion(
        self,
        connection: sqlite3.Connection,
        *,
        checkpoint_sha256: str,
        commit: PilotScientificCommitV1,
        bundle: PilotComponentBundleV1,
    ) -> None:
        body = {
            "promotion_version": "sft_pilot_component_checkpoint_promotion_v1",
            "protocol_sha256": self.protocol.digest,
            "checkpoint_sha256": checkpoint_sha256,
            "commit_ordinal": commit.commit_ordinal,
            "commit_sha256": commit.commit_sha256,
            "bundle_sha256": bundle.bundle_sha256,
        }
        promotion_sha = canonical_sha256(body)
        promotion_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-component-checkpoint-promotion-v1",
            value={"body": body, "promotion_sha256": promotion_sha},
        )
        connection.execute(
            """
            INSERT INTO component_checkpoint_promotion(
                checkpoint_sha256, commit_ordinal, promotion_sha256,
                promotion_hmac_sha256
            ) VALUES(?, ?, ?, ?)
            """,
            (
                checkpoint_sha256,
                commit.commit_ordinal,
                promotion_sha,
                promotion_hmac,
            ),
        )

    def _verify_component_checkpoint_promotion(
        self,
        connection: sqlite3.Connection,
        *,
        checkpoint: PilotComponentCheckpointSnapshotV1,
        commit: PilotScientificCommitV1,
        bundle: PilotComponentBundleSnapshotV1,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM component_checkpoint_promotion WHERE checkpoint_sha256=?",
            (checkpoint.metadata.checkpoint_sha256,),
        ).fetchone()
        if row is None or int(row["commit_ordinal"]) != commit.commit_ordinal:
            raise PilotStoreIntegrityError(
                "settled checkpoint lacks its exact scientific promotion"
            )
        body = {
            "promotion_version": "sft_pilot_component_checkpoint_promotion_v1",
            "protocol_sha256": self.protocol.digest,
            "checkpoint_sha256": checkpoint.metadata.checkpoint_sha256,
            "commit_ordinal": commit.commit_ordinal,
            "commit_sha256": commit.commit_sha256,
            "bundle_sha256": bundle.metadata.bundle_sha256,
        }
        promotion_sha = canonical_sha256(body)
        promotion_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-component-checkpoint-promotion-v1",
            value={"body": body, "promotion_sha256": promotion_sha},
        )
        if (
            not hmac.compare_digest(str(row["promotion_sha256"]), promotion_sha)
            or not hmac.compare_digest(
                str(row["promotion_hmac_sha256"]), promotion_hmac
            )
            or checkpoint.metadata.action_id != commit.owner_action_id
            or checkpoint.metadata.action_owner_logical_execution_key
            != commit.owner_logical_execution_key
            or checkpoint.phase_registry_envelope_bytes
            != bundle.phase_registry_envelope_bytes
            or checkpoint.factor_bank_envelope_bytes
            != bundle.factor_bank_envelope_bytes
        ):
            raise PilotStoreIntegrityError(
                "component checkpoint promotion authentication failed"
            )

    def _component_scientific_owner_is_eligible(
        self,
        owner: PilotExecutionLeaseV1,
    ) -> bool:
        if (
            owner.split != "TRAIN_UPDATE"
            or owner.operation_kind != "proposal_generation"
            or owner.action_id is None
        ):
            return False
        return owner.state == "completed"

    def append_component_scientific_commit(
        self,
        *,
        operation_id: str,
        owner_logical_execution_key: str,
        request_sha256: str,
        before_state_sha256: str,
        phase_registry_envelope_bytes: bytes,
        factor_bank_envelope_bytes: bytes,
        settled_checkpoint_sha256: str | None = None,
    ) -> tuple[PilotScientificCommitV1, PilotComponentBundleSnapshotV1]:
        """Atomically append one scientific commit and its exact recovery bytes."""

        require_opaque_id(operation_id, field_name="operation_id")
        require_opaque_id(
            owner_logical_execution_key,
            field_name="owner_logical_execution_key",
        )
        require_sha256(request_sha256, field_name="request_sha256")
        require_sha256(before_state_sha256, field_name="before_state_sha256")
        if not self.protocol.component_bundle_required:
            raise PilotStateTransitionError(
                "protocol does not authorize component-bundle persistence"
            )
        if self.protocol.component_checkpoint_saga_required:
            if settled_checkpoint_sha256 is None:
                raise PilotStateTransitionError(
                    "scientific publication requires a settled checkpoint"
                )
            require_sha256(
                settled_checkpoint_sha256,
                field_name="settled_checkpoint_sha256",
            )
        elif settled_checkpoint_sha256 is not None:
            raise PilotStoreIntegrityError(
                "legacy component protocols cannot assert checkpoint promotion"
            )
        if (
            len(phase_registry_envelope_bytes) + len(factor_bank_envelope_bytes)
            > self.protocol.capacity_policy.max_total_stored_scalar_bytes
        ):
            raise PilotCapacityError("component envelopes exceed byte capacity")

        with self._write_transaction() as connection:
            self._require_active(connection)
            self._require_preflight(connection)
            existing = connection.execute(
                "SELECT * FROM scientific_commit WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                commit = self._scientific_from_row(existing)
                bundle_row = connection.execute(
                    "SELECT * FROM component_bundle WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if bundle_row is None:
                    raise PilotStoreIntegrityError(
                        "scientific commit exists without its component bundle"
                    )
                persisted = self._component_snapshot_from_row(bundle_row)
                expected_metadata = self._component_bundle_metadata(
                    generation=commit.commit_ordinal,
                    scientific_commit_ordinal=commit.commit_ordinal,
                    phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                    factor_bank_envelope_bytes=factor_bank_envelope_bytes,
                    previous_bundle_sha256=persisted.metadata.previous_bundle_sha256,
                )
                if (
                    commit.request_sha256 != request_sha256
                    or commit.owner_logical_execution_key
                    != owner_logical_execution_key
                    or commit.before_state_sha256 != before_state_sha256
                    or commit.after_state_sha256 != expected_metadata.bundle_sha256
                    or persisted.metadata != expected_metadata
                    or persisted.phase_registry_envelope_bytes
                    != phase_registry_envelope_bytes
                    or persisted.factor_bank_envelope_bytes
                    != factor_bank_envelope_bytes
                ):
                    raise PilotIdempotenceConflict(
                        "component scientific operation retry changed state or exact bytes"
                    )
                operation = self._operation_row(connection, operation_id)
                if operation is None or any(
                    (
                        str(operation["request_sha256"]) != request_sha256,
                        str(operation["operation_kind"]) != "scientific_commit",
                        str(operation["result_key"]) != str(commit.commit_ordinal),
                        str(operation["result_sha256"]) != commit.commit_sha256,
                    )
                ):
                    raise PilotStoreIntegrityError(
                        "component scientific operation closure failed"
                    )
                if self.protocol.component_checkpoint_saga_required:
                    checkpoint_row = connection.execute(
                        "SELECT * FROM component_checkpoint WHERE checkpoint_sha256=?",
                        (settled_checkpoint_sha256,),
                    ).fetchone()
                    if checkpoint_row is None:
                        raise PilotStoreIntegrityError(
                            "scientific retry lost its settled checkpoint"
                        )
                    checkpoint = self._component_checkpoint_snapshot_from_row(
                        checkpoint_row
                    )
                    self._verify_component_checkpoint_promotion(
                        connection,
                        checkpoint=checkpoint,
                        commit=commit,
                        bundle=persisted,
                    )
                return commit, persisted

            latest_row = connection.execute(
                "SELECT * FROM component_bundle ORDER BY generation DESC LIMIT 1"
            ).fetchone()
            if latest_row is None:
                raise PilotStoreIntegrityError(
                    "component scientific commit requires an explicit genesis bundle"
                )
            latest = self._component_snapshot_from_row(latest_row)
            ordinal = int(
                connection.execute("SELECT COUNT(*) FROM scientific_commit").fetchone()[0]
            ) + 1
            if latest.metadata.generation != ordinal - 1:
                raise PilotStoreIntegrityError(
                    "component generation does not close the scientific head"
                )
            if before_state_sha256 != latest.metadata.bundle_sha256:
                raise PilotStoreIntegrityError(
                    "scientific state chain does not continue from the component head"
                )
            if (
                phase_registry_envelope_bytes
                == latest.phase_registry_envelope_bytes
                and factor_bank_envelope_bytes
                == latest.factor_bank_envelope_bytes
            ):
                raise PilotStateTransitionError(
                    "component scientific commit must change authoritative bytes"
                )
            metadata = self._component_bundle_metadata(
                generation=ordinal,
                scientific_commit_ordinal=ordinal,
                phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=factor_bank_envelope_bytes,
                previous_bundle_sha256=latest.metadata.bundle_sha256,
            )
            policy = self.protocol.capacity_policy
            if ordinal > policy.max_scientific_commits:
                raise PilotCapacityError("scientific commit capacity is exhausted")
            owner = self._load_execution(connection, owner_logical_execution_key)
            if not self._component_scientific_owner_is_eligible(owner):
                raise PilotStoreIntegrityError(
                    "scientific commit requires an eligible terminal TRAIN_UPDATE proposal owner"
                )
            promotion_checkpoint: PilotComponentCheckpointSnapshotV1 | None = None
            if self.protocol.component_checkpoint_saga_required:
                checkpoint_row = self._unpromoted_checkpoint_row(connection)
                if checkpoint_row is None:
                    raise PilotStateTransitionError(
                        "scientific publication has no unpromoted checkpoint"
                    )
                promotion_checkpoint = self._component_checkpoint_snapshot_from_row(
                    checkpoint_row
                )
                self._verify_component_checkpoint_snapshot(promotion_checkpoint)
                checkpoint_metadata = promotion_checkpoint.metadata
                if (
                    checkpoint_metadata.checkpoint_sha256
                    != settled_checkpoint_sha256
                    or not checkpoint_metadata.settled
                    or checkpoint_metadata.checkpoint_kind != "gate_terminal"
                    or checkpoint_metadata.action_id != owner.action_id
                    or checkpoint_metadata.action_owner_logical_execution_key
                    != owner.logical_execution_key
                    or checkpoint_metadata.action_owner_logical_arm_key
                    != owner.logical_arm_key
                    or promotion_checkpoint.phase_registry_envelope_bytes
                    != phase_registry_envelope_bytes
                    or promotion_checkpoint.factor_bank_envelope_bytes
                    != factor_bank_envelope_bytes
                ):
                    raise PilotStoreIntegrityError(
                        "scientific publication differs from its settled checkpoint"
                    )
            if connection.execute(
                "SELECT 1 FROM scientific_commit WHERE owner_logical_execution_key=?",
                (owner_logical_execution_key,),
            ).fetchone() is not None:
                raise PilotIdempotenceConflict(
                    "one completed execution can own only one scientific commit"
                )
            previous_commit = connection.execute(
                "SELECT commit_sha256 FROM scientific_commit "
                "ORDER BY commit_ordinal DESC LIMIT 1"
            ).fetchone()
            previous_commit_sha = (
                ZERO_SHA256 if previous_commit is None else str(previous_commit[0])
            )
            body = {
                "commit_ordinal": ordinal,
                "operation_id": operation_id,
                "owner_logical_execution_key": owner_logical_execution_key,
                "owner_action_id": owner.action_id,
                "owner_split": owner.split,
                "request_sha256": request_sha256,
                "before_state_sha256": before_state_sha256,
                "after_state_sha256": metadata.bundle_sha256,
                "previous_commit_sha256": previous_commit_sha,
                "protocol_sha256": self.protocol.digest,
                "schema_digest": EXPECTED_SCHEMA_DIGEST,
            }
            commit_sha = canonical_sha256(body)
            commit_hmac = pilot_hmac_sha256(
                self._hmac_key,
                domain="sft-pilot-scientific-commit-v1",
                value={"body": body, "commit_sha256": commit_sha},
            )
            commit = PilotScientificCommitV1(
                commit_ordinal=ordinal,
                operation_id=operation_id,
                owner_logical_execution_key=owner_logical_execution_key,
                owner_action_id=owner.action_id,
                owner_split="TRAIN_UPDATE",
                request_sha256=request_sha256,
                before_state_sha256=before_state_sha256,
                after_state_sha256=metadata.bundle_sha256,
                previous_commit_sha256=previous_commit_sha,
                commit_sha256=commit_sha,
                commit_hmac_sha256=commit_hmac,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=request_sha256,
                operation_kind="scientific_commit",
                result_key=str(ordinal),
                result_sha256=commit_sha,
            )
            connection.execute(
                """
                INSERT INTO scientific_commit(
                    commit_ordinal, operation_id, owner_logical_execution_key,
                    owner_action_id, owner_split, request_sha256,
                    before_state_sha256, after_state_sha256,
                    previous_commit_sha256, commit_sha256, commit_hmac_sha256
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ordinal,
                    operation_id,
                    owner_logical_execution_key,
                    owner.action_id,
                    owner.split,
                    request_sha256,
                    before_state_sha256,
                    metadata.bundle_sha256,
                    previous_commit_sha,
                    commit_sha,
                    commit_hmac,
                ),
            )
            self._insert_component_bundle(
                connection,
                operation_id=operation_id,
                metadata=metadata,
                phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=factor_bank_envelope_bytes,
            )
            if promotion_checkpoint is not None:
                self._insert_component_checkpoint_promotion(
                    connection,
                    checkpoint_sha256=(
                        promotion_checkpoint.metadata.checkpoint_sha256
                    ),
                    commit=commit,
                    bundle=metadata,
                )
            return commit, PilotComponentBundleSnapshotV1(
                metadata=metadata,
                phase_registry_envelope_bytes=phase_registry_envelope_bytes,
                factor_bank_envelope_bytes=factor_bank_envelope_bytes,
            )

    def _verify_scientific_chain(self) -> None:
        previous_sha = ZERO_SHA256
        previous_state = self.protocol.genesis_state_sha256
        rows = self._connection.execute(
            "SELECT * FROM scientific_commit ORDER BY commit_ordinal"
        ).fetchall()
        for expected_ordinal, row in enumerate(rows, start=1):
            commit = self._scientific_from_row(row)
            if commit.commit_ordinal != expected_ordinal:
                raise PilotStoreIntegrityError("scientific commit ordinal gap")
            if commit.previous_commit_sha256 != previous_sha:
                raise PilotStoreIntegrityError("scientific commit hash-chain gap")
            if commit.before_state_sha256 != previous_state:
                raise PilotStoreIntegrityError("scientific state-chain gap")
            owner = self._load_execution(
                self._connection, commit.owner_logical_execution_key
            )
            if (
                not self._component_scientific_owner_is_eligible(owner)
                or owner.action_id != commit.owner_action_id
            ):
                raise PilotStoreIntegrityError("scientific owner closure failed")
            body = {
                "commit_ordinal": commit.commit_ordinal,
                "operation_id": commit.operation_id,
                "owner_logical_execution_key": commit.owner_logical_execution_key,
                "owner_action_id": commit.owner_action_id,
                "owner_split": commit.owner_split,
                "request_sha256": commit.request_sha256,
                "before_state_sha256": commit.before_state_sha256,
                "after_state_sha256": commit.after_state_sha256,
                "previous_commit_sha256": commit.previous_commit_sha256,
                "protocol_sha256": self.protocol.digest,
                "schema_digest": EXPECTED_SCHEMA_DIGEST,
            }
            digest = canonical_sha256(body)
            expected_hmac = pilot_hmac_sha256(
                self._hmac_key,
                domain="sft-pilot-scientific-commit-v1",
                value={"body": body, "commit_sha256": digest},
            )
            if not hmac.compare_digest(commit.commit_sha256, digest) or not hmac.compare_digest(
                commit.commit_hmac_sha256, expected_hmac
            ):
                raise PilotStoreIntegrityError("scientific commit authentication failed")
            operation = self._operation_row(self._connection, commit.operation_id)
            if operation is None or any(
                (
                    str(operation["request_sha256"]) != commit.request_sha256,
                    str(operation["operation_kind"]) != "scientific_commit",
                    str(operation["result_key"]) != str(commit.commit_ordinal),
                    str(operation["result_sha256"]) != commit.commit_sha256,
                )
            ):
                raise PilotStoreIntegrityError("scientific operation closure failed")
            previous_sha = commit.commit_sha256
            previous_state = commit.after_state_sha256

    def _verify_component_snapshot(
        self, snapshot: PilotComponentBundleSnapshotV1
    ) -> None:
        expected = self._component_bundle_metadata(
            generation=snapshot.metadata.generation,
            scientific_commit_ordinal=snapshot.metadata.scientific_commit_ordinal,
            phase_registry_envelope_bytes=snapshot.phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=snapshot.factor_bank_envelope_bytes,
            previous_bundle_sha256=snapshot.metadata.previous_bundle_sha256,
        )
        if snapshot.metadata != expected:
            raise PilotStoreIntegrityError(
                "component bundle digest or authentication is invalid"
            )

    def _verify_component_bundles(self) -> None:
        rows = self._connection.execute(
            "SELECT * FROM component_bundle ORDER BY generation"
        ).fetchall()
        required = self.protocol.component_bundle_required
        if not required and rows:
            raise PilotStoreIntegrityError(
                "component bundles exist under a hash-only protocol"
            )
        commits = self._connection.execute(
            "SELECT * FROM scientific_commit ORDER BY commit_ordinal"
        ).fetchall()
        if not rows:
            if required and commits:
                raise PilotStoreIntegrityError(
                    "component-bundle protocol has hash-only scientific commits"
                )
            status = str(
                self._connection.execute(
                    "SELECT status FROM protocol WHERE only_id=1"
                ).fetchone()[0]
            )
            if required and status == "sealed":
                raise PilotStoreIntegrityError(
                    "sealed component-bundle protocol lacks its genesis state"
                )
            return
        if len(rows) != len(commits) + 1:
            raise PilotStoreIntegrityError(
                "component bundle count does not close scientific generations"
            )

        previous_bundle_sha = ZERO_SHA256
        previous_phase_bytes: bytes | None = None
        previous_factor_bytes: bytes | None = None
        for expected_generation, row in enumerate(rows):
            if int(row["generation"]) != expected_generation:
                raise PilotStoreIntegrityError("component bundle generation gap")
            try:
                snapshot = self._component_snapshot_from_row(row)
                self._verify_component_snapshot(snapshot)
            except (TypeError, ValueError) as exc:
                raise PilotStoreIntegrityError(
                    "component bundle schema or envelope is invalid"
                ) from exc
            metadata = snapshot.metadata
            if metadata.previous_bundle_sha256 != previous_bundle_sha:
                raise PilotStoreIntegrityError("component bundle hash-chain gap")
            operation_id = str(row["operation_id"])
            if expected_generation == 0:
                if metadata.bundle_sha256 != self.protocol.genesis_state_sha256:
                    raise PilotStoreIntegrityError(
                        "component genesis differs from the frozen protocol"
                    )
                operation = self._operation_row(self._connection, operation_id)
                if operation is None or any(
                    (
                        str(operation["operation_kind"])
                        != "record_genesis_component_bundle",
                        str(operation["result_key"]) != "0",
                        str(operation["result_sha256"]) != metadata.bundle_sha256,
                    )
                ):
                    raise PilotStoreIntegrityError(
                        "component genesis operation closure failed"
                    )
            else:
                if (
                    snapshot.phase_registry_envelope_bytes == previous_phase_bytes
                    and snapshot.factor_bank_envelope_bytes == previous_factor_bytes
                ):
                    raise PilotStoreIntegrityError(
                        "adjacent component generations repeat exact state bytes"
                    )
                commit = self._scientific_from_row(commits[expected_generation - 1])
                if (
                    metadata.scientific_commit_ordinal != commit.commit_ordinal
                    or operation_id != commit.operation_id
                    or metadata.previous_bundle_sha256
                    != commit.before_state_sha256
                    or metadata.bundle_sha256 != commit.after_state_sha256
                ):
                    raise PilotStoreIntegrityError(
                        "component bundle does not close its scientific commit"
                    )
            previous_bundle_sha = metadata.bundle_sha256
            previous_phase_bytes = snapshot.phase_registry_envelope_bytes
            previous_factor_bytes = snapshot.factor_bank_envelope_bytes

        scientific_state = (
            self.protocol.genesis_state_sha256
            if not commits
            else self._scientific_from_row(commits[-1]).after_state_sha256
        )
        if previous_bundle_sha != scientific_state:
            raise PilotStoreIntegrityError(
                "latest component bundle differs from the scientific state head"
            )

    def _verify_component_checkpoints(self) -> None:
        checkpoint_rows = self._connection.execute(
            "SELECT * FROM component_checkpoint ORDER BY checkpoint_ordinal"
        ).fetchall()
        promotion_rows = self._connection.execute(
            "SELECT * FROM component_checkpoint_promotion ORDER BY commit_ordinal"
        ).fetchall()
        if not self.protocol.component_checkpoint_saga_required:
            if checkpoint_rows or promotion_rows:
                raise PilotStoreIntegrityError(
                    "component checkpoints exist outside a saga protocol"
                )
            return

        bundle_rows = self._connection.execute(
            "SELECT * FROM component_bundle ORDER BY generation"
        ).fetchall()
        commit_rows = self._connection.execute(
            "SELECT * FROM scientific_commit ORDER BY commit_ordinal"
        ).fetchall()
        if not bundle_rows:
            if checkpoint_rows or promotion_rows:
                raise PilotStoreIntegrityError(
                    "component checkpoint chain lacks its genesis bundle"
                )
            return
        if len(promotion_rows) != len(commit_rows):
            raise PilotStoreIntegrityError(
                "every saga scientific commit must promote one settled checkpoint"
            )

        genesis = self._component_snapshot_from_row(bundle_rows[0])
        expected_root = genesis.metadata.bundle_sha256
        expected_phase_bytes = genesis.phase_registry_envelope_bytes
        expected_factor_bytes = genesis.factor_bank_envelope_bytes
        open_action: str | None = None
        prior_kind: PilotComponentCheckpointKind | None = None
        open_action_owner_execution_key: str | None = None
        open_action_owner_arm_key: str | None = None
        prior_semantics: PilotCheckpointSemanticWitnessV1 | None = None
        promoted_commit_ordinal = 0
        seen_promotions: set[str] = set()

        for expected_ordinal, row in enumerate(checkpoint_rows, start=1):
            try:
                checkpoint = self._component_checkpoint_snapshot_from_row(row)
                self._verify_component_checkpoint_snapshot(checkpoint)
            except (TypeError, ValueError) as exc:
                raise PilotStoreIntegrityError(
                    "component checkpoint schema or envelope is invalid"
                ) from exc
            metadata = checkpoint.metadata
            if metadata.checkpoint_ordinal != expected_ordinal:
                raise PilotStoreIntegrityError("component checkpoint ordinal gap")
            if metadata.protocol_sha256 != self.protocol.digest:
                raise PilotStoreIntegrityError(
                    "component checkpoint protocol commitment mismatch"
                )
            if metadata.previous_recovery_root_sha256 != expected_root:
                raise PilotStoreIntegrityError(
                    "component checkpoint recovery hash-chain gap"
                )
            if (
                checkpoint.phase_registry_envelope_bytes == expected_phase_bytes
                and checkpoint.factor_bank_envelope_bytes == expected_factor_bytes
            ):
                raise PilotStoreIntegrityError(
                    "component checkpoint repeats exact prior recovery bytes"
                )
            lease = self._load_execution(
                self._connection,
                metadata.logical_execution_key,
            )
            if (
                lease.split != "TRAIN_UPDATE"
                or lease.action_id != metadata.action_id
                or lease.logical_arm_key != metadata.logical_arm_key
            ):
                raise PilotStoreIntegrityError(
                    "component checkpoint execution/action join failed"
                )
            owner = self._load_execution(
                self._connection,
                metadata.action_owner_logical_execution_key,
            )
            if not (
                owner.split == "TRAIN_UPDATE"
                and owner.operation_kind == "proposal_generation"
                and owner.action_id == metadata.action_id
                and owner.logical_arm_key
                == metadata.action_owner_logical_arm_key
            ):
                raise PilotStoreIntegrityError(
                    "component checkpoint proposal-owner join failed"
                )
            operation = self._operation_row(
                self._connection,
                metadata.operation_id,
            )
            if operation is None or any(
                (
                    str(operation["operation_kind"]) != "component_checkpoint",
                    str(operation["result_key"])
                    != str(metadata.checkpoint_ordinal),
                    str(operation["result_sha256"])
                    != metadata.checkpoint_sha256,
                )
            ):
                raise PilotStoreIntegrityError(
                    "component checkpoint operation closure failed"
                )
            if open_action is None:
                if metadata.checkpoint_kind != "action_prepared":
                    raise PilotStoreIntegrityError(
                        "component checkpoint action lacks action_prepared ingress"
                    )
                open_action = metadata.action_id
                open_action_owner_execution_key = (
                    metadata.action_owner_logical_execution_key
                )
                open_action_owner_arm_key = (
                    metadata.action_owner_logical_arm_key
                )
            else:
                if metadata.action_id != open_action or prior_kind is None:
                    raise PilotStoreIntegrityError(
                        "component checkpoint action changed before promotion"
                    )
                if prior_kind not in _CHECKPOINT_PREDECESSORS[
                    metadata.checkpoint_kind
                ]:
                    raise PilotStoreIntegrityError(
                        "component checkpoint lifecycle transition is invalid"
                    )
                if prior_semantics is None or not (
                    prior_semantics.phase_state_after_sha256
                    == metadata.semantic_witness.phase_state_before_sha256
                    and prior_semantics.phase_sequence_after
                    == metadata.semantic_witness.phase_sequence_before
                    and prior_semantics.factor_state_after_sha256
                    == metadata.semantic_witness.factor_state_before_sha256
                    and prior_semantics.factor_event_seq_after
                    == metadata.semantic_witness.factor_event_seq_before
                    and prior_semantics.proposal_action_after_sha256
                    == metadata.semantic_witness.proposal_action_before_sha256
                ):
                    raise PilotStoreIntegrityError(
                        "component checkpoint semantic chain is discontinuous"
                    )
                if (
                    metadata.action_owner_logical_execution_key
                    != open_action_owner_execution_key
                    or metadata.action_owner_logical_arm_key
                    != open_action_owner_arm_key
                ):
                    raise PilotStoreIntegrityError(
                        "component checkpoint proposal owner continuity failed"
                    )
            expected_root = metadata.checkpoint_sha256
            expected_phase_bytes = checkpoint.phase_registry_envelope_bytes
            expected_factor_bytes = checkpoint.factor_bank_envelope_bytes
            prior_kind = metadata.checkpoint_kind
            prior_semantics = metadata.semantic_witness

            promotion_row = self._connection.execute(
                """
                SELECT * FROM component_checkpoint_promotion
                WHERE checkpoint_sha256=?
                """,
                (metadata.checkpoint_sha256,),
            ).fetchone()
            if promotion_row is None:
                continue
            promoted_commit_ordinal += 1
            if (
                not metadata.settled
                or metadata.checkpoint_kind != "gate_terminal"
                or int(promotion_row["commit_ordinal"])
                != promoted_commit_ordinal
                or promoted_commit_ordinal > len(commit_rows)
                or promoted_commit_ordinal >= len(bundle_rows)
            ):
                raise PilotStoreIntegrityError(
                    "component checkpoint promotion order is invalid"
                )
            commit = self._scientific_from_row(
                commit_rows[promoted_commit_ordinal - 1]
            )
            bundle = self._component_snapshot_from_row(
                bundle_rows[promoted_commit_ordinal]
            )
            self._verify_component_checkpoint_promotion(
                self._connection,
                checkpoint=checkpoint,
                commit=commit,
                bundle=bundle,
            )
            seen_promotions.add(metadata.checkpoint_sha256)
            expected_root = bundle.metadata.bundle_sha256
            expected_phase_bytes = bundle.phase_registry_envelope_bytes
            expected_factor_bytes = bundle.factor_bank_envelope_bytes
            open_action = None
            prior_kind = None
            prior_semantics = None
            open_action_owner_execution_key = None
            open_action_owner_arm_key = None

        if promoted_commit_ordinal != len(commit_rows) or len(seen_promotions) != len(
            promotion_rows
        ):
            raise PilotStoreIntegrityError(
                "component checkpoint promotion ledger has detached rows"
            )
        if open_action is None:
            latest_bundle = self._component_snapshot_from_row(bundle_rows[-1])
            if expected_root != latest_bundle.metadata.bundle_sha256:
                raise PilotStoreIntegrityError(
                    "settled checkpoint chain differs from the scientific head"
                )

    def _budget_ledger_root(self, connection: sqlite3.Connection) -> str:
        executions = [
            self._execution_from_row(row).model_dump(mode="json")
            for row in connection.execute(
                "SELECT * FROM execution_lease ORDER BY logical_arm_key"
            ).fetchall()
        ]
        calls = [
            self._call_from_row(row).model_dump(mode="json")
            for row in connection.execute(
                "SELECT * FROM call_receipt ORDER BY logical_execution_key, call_slot"
            ).fetchall()
        ]
        return canonical_sha256(
            {
                "domain": "sft-pilot-budget-ledger-v1",
                "protocol_sha256": self.protocol.digest,
                "authorized_phase_budgets": self.protocol.phase_budgets,
                "execution_leases": executions,
                "call_receipts": calls,
            }
        )

    def _operation_ledger_root(self, connection: sqlite3.Connection) -> str:
        rows = connection.execute(
            """
            SELECT operation_id, request_sha256, operation_kind,
                   result_key, result_sha256
            FROM operation_receipt
            WHERE operation_kind != 'seal_terminal_archive'
            ORDER BY operation_id
            """
        ).fetchall()
        return canonical_sha256(
            {
                "domain": "sft-pilot-operation-ledger-v1",
                "protocol_sha256": self.protocol.digest,
                "operations": [dict(row) for row in rows],
            }
        )

    @property
    def budget_ledger_root_sha256(self) -> str:
        self._ensure_owner()
        return self._budget_ledger_root(self._connection)

    @property
    def operation_ledger_root_sha256(self) -> str:
        self._ensure_owner()
        return self._operation_ledger_root(self._connection)

    def seal_terminal_archive(
        self,
        payload: PilotArchivePayloadV1,
        *,
        operation_id: str,
        operation_request_sha256: str,
    ) -> PilotArchiveEpochV1:
        if not isinstance(payload, PilotArchivePayloadV1):
            payload = PilotArchivePayloadV1.model_validate(payload)
        archive_sha = canonical_sha256(payload)
        archive_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-terminal-archive-v1",
            value={
                "protocol_sha256": self.protocol.digest,
                "archive_sha256": archive_sha,
            },
        )
        epoch = PilotArchiveEpochV1(
            payload=payload,
            archive_sha256=archive_sha,
            archive_hmac_sha256=archive_hmac,
        )
        result_sha = canonical_sha256(epoch)
        with self._write_transaction() as connection:
            if self._operation_already_applied(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="seal_terminal_archive",
                result_key=payload.archive_id,
                result_sha256=result_sha,
            ):
                archive = self._load_archive(connection, payload.archive_id)
                self._verify_archive()
                if archive != epoch:
                    raise PilotStoreIntegrityError(
                        "terminal seal retry differs from the authenticated epoch"
                    )
                return archive
            self._require_active(connection)
            self._require_preflight(connection)
            if self.protocol.component_bundle_required:
                self._verify_component_bundles()
            if self.protocol.component_checkpoint_saga_required:
                self._verify_component_checkpoints()
                if self._unpromoted_checkpoint_row(connection) is not None:
                    raise PilotStateTransitionError(
                        "terminal archive cannot abandon an unpromoted checkpoint"
                    )
            if payload.protocol_sha256 != self.protocol.digest:
                raise PilotStoreIntegrityError("archive protocol commitment mismatch")
            if payload.pair_manifest_sha256 != self.protocol.pair_manifest_sha256:
                raise PilotStoreIntegrityError("archive pair manifest mismatch")
            head_row = connection.execute(
                """
                SELECT commit_ordinal, commit_sha256, after_state_sha256
                FROM scientific_commit ORDER BY commit_ordinal DESC LIMIT 1
                """
            ).fetchone()
            generation = 0 if head_row is None else int(head_row[0])
            head_sha = ZERO_SHA256 if head_row is None else str(head_row[1])
            state_sha = (
                self.protocol.genesis_state_sha256
                if head_row is None
                else str(head_row[2])
            )
            if (
                payload.terminal_generation != generation
                or payload.commit_chain_head_sha256 != head_sha
                or payload.terminal_state_sha256 != state_sha
            ):
                raise PilotStoreIntegrityError("archive does not close the exact scientific head")
            nonterminal_calls = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM call_receipt
                    WHERE state IN ('reserved', 'request_started')
                    """
                ).fetchone()[0]
            )
            nonterminal_executions = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM execution_lease
                    WHERE state IN ('reserved', 'request_started')
                    """
                ).fetchone()[0]
            )
            if nonterminal_calls or nonterminal_executions:
                raise PilotStateTransitionError(
                    "terminal archive requires no nonterminal call or execution"
                )
            persisted_dispositions = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT state, COUNT(*) FROM execution_lease GROUP BY state"
                ).fetchall()
            }
            declared_dispositions = dict(payload.disposition_counts)
            if declared_dispositions != persisted_dispositions:
                raise PilotStoreIntegrityError(
                    "archive disposition counts do not close execution leases"
                )
            if payload.budget_ledger_root_sha256 != self._budget_ledger_root(
                connection
            ):
                raise PilotStoreIntegrityError(
                    "archive budget root is not derived from the exact ledger"
                )
            if payload.operation_ledger_root_sha256 != self._operation_ledger_root(
                connection
            ):
                raise PilotStoreIntegrityError(
                    "archive operation root is not derived from exact receipts"
                )
            archive_bytes = len(canonical_json(epoch).encode("utf-8"))
            if archive_bytes > self.protocol.capacity_policy.max_archive_bytes:
                raise PilotCapacityError("terminal archive exceeds its frozen byte capacity")
            preflight = self._load_preflight(connection)
            if archive_bytes > preflight.planned_archive_bytes:
                raise PilotCapacityError(
                    "terminal archive exceeds the frozen preflight byte envelope"
                )
            connection.execute(
                """
                INSERT INTO archive_epoch(
                    archive_id, seal_operation_id, seal_request_sha256,
                    archive_json, archive_sha256, archive_hmac_sha256
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.archive_id,
                    operation_id,
                    operation_request_sha256,
                    canonical_json(payload),
                    archive_sha,
                    archive_hmac,
                ),
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                request_sha256=operation_request_sha256,
                operation_kind="seal_terminal_archive",
                result_key=payload.archive_id,
                result_sha256=result_sha,
            )
            sealed_hmac = self._protocol_hmac(self.protocol.digest, "sealed")
            connection.execute(
                "UPDATE protocol SET status='sealed', protocol_hmac_sha256=? WHERE only_id=1",
                (sealed_hmac,),
            )
        return epoch

    def _verify_archive(self) -> None:
        rows = self._connection.execute("SELECT * FROM archive_epoch").fetchall()
        status_row = self._connection.execute(
            "SELECT status FROM protocol WHERE only_id=1"
        ).fetchone()
        status = None if status_row is None else str(status_row[0])
        if len(rows) > 1:
            raise PilotStoreIntegrityError("pilot may contain only one terminal archive")
        if not rows:
            if status == "sealed":
                raise PilotStoreIntegrityError(
                    "sealed protocol is missing its terminal archive"
                )
            return
        row = rows[0]
        try:
            payload = PilotArchivePayloadV1.model_validate_json(str(row["archive_json"]))
        except (ValueError, TypeError) as exc:
            raise PilotStoreIntegrityError("terminal archive schema is invalid") from exc
        digest = canonical_sha256(payload)
        expected_hmac = pilot_hmac_sha256(
            self._hmac_key,
            domain="sft-pilot-terminal-archive-v1",
            value={
                "protocol_sha256": self.protocol.digest,
                "archive_sha256": digest,
            },
        )
        if canonical_json(payload) != str(row["archive_json"]):
            raise PilotStoreIntegrityError("terminal archive JSON is not canonical")
        if str(row["archive_id"]) != payload.archive_id:
            raise PilotStoreIntegrityError("terminal archive row identity mismatch")
        if not hmac.compare_digest(str(row["archive_sha256"]), digest) or not hmac.compare_digest(
            str(row["archive_hmac_sha256"]), expected_hmac
        ):
            raise PilotStoreIntegrityError("terminal archive authentication failed")
        if payload.protocol_sha256 != self.protocol.digest:
            raise PilotStoreIntegrityError("terminal archive protocol mismatch")
        if payload.pair_manifest_sha256 != self.protocol.pair_manifest_sha256:
            raise PilotStoreIntegrityError("terminal archive pair manifest mismatch")
        if status != "sealed":
            raise PilotStoreIntegrityError("terminal archive exists without protocol seal")
        if int(
            self._connection.execute(
                """
                SELECT COUNT(*) FROM call_receipt
                WHERE state IN ('reserved', 'request_started')
                """
            ).fetchone()[0]
        ) or int(
            self._connection.execute(
                """
                SELECT COUNT(*) FROM execution_lease
                WHERE state IN ('reserved', 'request_started')
                """
            ).fetchone()[0]
        ):
            raise PilotStoreIntegrityError("terminal archive retained nonterminal work")
        head = self._connection.execute(
            """
            SELECT commit_ordinal, commit_sha256, after_state_sha256
            FROM scientific_commit ORDER BY commit_ordinal DESC LIMIT 1
            """
        ).fetchone()
        generation = 0 if head is None else int(head[0])
        head_sha = ZERO_SHA256 if head is None else str(head[1])
        state_sha = (
            self.protocol.genesis_state_sha256 if head is None else str(head[2])
        )
        if (
            payload.terminal_generation != generation
            or payload.commit_chain_head_sha256 != head_sha
            or payload.terminal_state_sha256 != state_sha
        ):
            raise PilotStoreIntegrityError("terminal archive no longer closes the head")
        persisted_dispositions = {
            str(item[0]): int(item[1])
            for item in self._connection.execute(
                "SELECT state, COUNT(*) FROM execution_lease GROUP BY state"
            ).fetchall()
        }
        if dict(payload.disposition_counts) != persisted_dispositions:
            raise PilotStoreIntegrityError(
                "terminal archive disposition closure is invalid"
            )
        if payload.budget_ledger_root_sha256 != self._budget_ledger_root(
            self._connection
        ):
            raise PilotStoreIntegrityError("terminal archive budget root is invalid")
        if payload.operation_ledger_root_sha256 != self._operation_ledger_root(
            self._connection
        ):
            raise PilotStoreIntegrityError("terminal archive operation root is invalid")
        epoch = PilotArchiveEpochV1(
            payload=payload,
            archive_sha256=digest,
            archive_hmac_sha256=expected_hmac,
        )
        archive_bytes = len(canonical_json(epoch).encode("utf-8"))
        preflight = self._load_preflight(self._connection)
        if (
            archive_bytes > self.protocol.capacity_policy.max_archive_bytes
            or archive_bytes > preflight.planned_archive_bytes
        ):
            raise PilotStoreIntegrityError("terminal archive exceeds frozen capacity")
        operation = self._operation_row(
            self._connection, str(row["seal_operation_id"])
        )
        if operation is None or any(
            (
                str(operation["request_sha256"])
                != str(row["seal_request_sha256"]),
                str(operation["operation_kind"]) != "seal_terminal_archive",
                str(operation["result_key"]) != payload.archive_id,
                str(operation["result_sha256"]) != canonical_sha256(epoch),
            )
        ):
            raise PilotStoreIntegrityError("terminal seal operation closure failed")

    def _recover_started_calls(self) -> int:
        if self.protocol_status != "active":
            return 0
        with self._write_transaction() as connection:
            execution_rows = connection.execute(
                """
                SELECT logical_execution_key FROM execution_lease
                WHERE state='request_started'
                """
            ).fetchall()
            execution_keys = [str(row[0]) for row in execution_rows]
            for execution_key in execution_keys:
                connection.execute(
                    """
                    UPDATE call_receipt
                    SET state='indeterminate',
                        conservative_charged_tokens=(
                            input_tokens_reserved + output_tokens_reserved
                        )
                    WHERE logical_execution_key=? AND state='request_started'
                    """,
                    (execution_key,),
                )
                connection.execute(
                    """
                    UPDATE call_receipt SET state='failed_before_start'
                    WHERE logical_execution_key=? AND state='reserved'
                    """,
                    (execution_key,),
                )
                connection.execute(
                    """
                    UPDATE execution_lease SET state='indeterminate'
                    WHERE logical_execution_key=? AND state='request_started'
                    """,
                    (execution_key,),
                )
            return len(execution_keys)

    def get_execution(self, logical_execution_key: str) -> PilotExecutionLeaseV1:
        self._ensure_owner()
        return self._load_execution(self._connection, logical_execution_key)

    def get_call(self, call_key: str) -> PilotCallReceiptV1:
        self._ensure_owner()
        return self._load_call(self._connection, call_key)

    @staticmethod
    def _load_execution(
        connection: sqlite3.Connection, logical_execution_key: str
    ) -> PilotExecutionLeaseV1:
        row = connection.execute(
            "SELECT * FROM execution_lease WHERE logical_execution_key=?",
            (logical_execution_key,),
        ).fetchone()
        if row is None:
            raise PilotStateTransitionError("unknown logical execution")
        return SingleWriterPilotStore._execution_from_row(row)

    @staticmethod
    def _execution_from_row(row: sqlite3.Row) -> PilotExecutionLeaseV1:
        return PilotExecutionLeaseV1(
            logical_execution_key=str(row["logical_execution_key"]),
            logical_arm_key=str(row["logical_arm_key"]),
            operation_kind=str(row["operation_kind"]),
            request_sha256=str(row["request_sha256"]),
            namespace_sha256=str(row["namespace_sha256"]),
            split=str(row["split"]),
            unit_commitment=str(row["unit_commitment"]),
            action_id=None if row["action_id"] is None else str(row["action_id"]),
            call_slots_reserved=int(row["call_slots_reserved"]),
            input_tokens_reserved=int(row["input_tokens_reserved"]),
            output_tokens_reserved=int(row["output_tokens_reserved"]),
            physical_block_ordinal=(
                None
                if row["physical_block_ordinal"] is None
                else int(row["physical_block_ordinal"])
            ),
            schedule_entry_sha256=(
                None
                if row["schedule_entry_sha256"] is None
                else str(row["schedule_entry_sha256"])
            ),
            state=str(row["state"]),
        )

    @staticmethod
    def _load_call(connection: sqlite3.Connection, call_key: str) -> PilotCallReceiptV1:
        row = connection.execute(
            "SELECT * FROM call_receipt WHERE call_key=?", (call_key,)
        ).fetchone()
        if row is None:
            raise PilotStateTransitionError("unknown call")
        return SingleWriterPilotStore._call_from_row(row)

    @staticmethod
    def _call_from_row(row: sqlite3.Row) -> PilotCallReceiptV1:
        return PilotCallReceiptV1(
            call_key=str(row["call_key"]),
            logical_execution_key=str(row["logical_execution_key"]),
            call_slot=int(row["call_slot"]),
            request_sha256=str(row["request_sha256"]),
            model_name=str(row["model_name"]),
            input_tokens_reserved=int(row["input_tokens_reserved"]),
            output_tokens_reserved=int(row["output_tokens_reserved"]),
            max_completion_tokens=int(row["max_completion_tokens"]),
            expected_component_recovery_root_sha256=(
                None
                if row["expected_component_recovery_root_sha256"] is None
                else str(row["expected_component_recovery_root_sha256"])
            ),
            scheduled_call_sha256=(
                None
                if row["scheduled_call_sha256"] is None
                else str(row["scheduled_call_sha256"])
            ),
            request_renderer_sha256=(
                None
                if row["request_renderer_sha256"] is None
                else str(row["request_renderer_sha256"])
            ),
            prompt_template_sha256=(
                None
                if row["prompt_template_sha256"] is None
                else str(row["prompt_template_sha256"])
            ),
            json_mode=(
                None if row["json_mode"] is None else bool(row["json_mode"])
            ),
            artifact_role=(
                None if row["artifact_role"] is None else str(row["artifact_role"])
            ),
            state=str(row["state"]),
            output_envelope_sha256=(
                None
                if row["output_envelope_sha256"] is None
                else str(row["output_envelope_sha256"])
            ),
            provider_usage_known=bool(row["provider_usage_known"]),
            input_tokens_used=(
                None if row["input_tokens_used"] is None else int(row["input_tokens_used"])
            ),
            output_tokens_used=(
                None if row["output_tokens_used"] is None else int(row["output_tokens_used"])
            ),
            conservative_charged_tokens=int(row["conservative_charged_tokens"]),
        )

    @staticmethod
    def _scientific_from_row(row: sqlite3.Row) -> PilotScientificCommitV1:
        return PilotScientificCommitV1(
            commit_ordinal=int(row["commit_ordinal"]),
            operation_id=str(row["operation_id"]),
            owner_logical_execution_key=str(row["owner_logical_execution_key"]),
            owner_action_id=str(row["owner_action_id"]),
            owner_split=str(row["owner_split"]),
            request_sha256=str(row["request_sha256"]),
            before_state_sha256=str(row["before_state_sha256"]),
            after_state_sha256=str(row["after_state_sha256"]),
            previous_commit_sha256=str(row["previous_commit_sha256"]),
            commit_sha256=str(row["commit_sha256"]),
            commit_hmac_sha256=str(row["commit_hmac_sha256"]),
        )

    @staticmethod
    def _load_archive(
        connection: sqlite3.Connection, archive_id: str
    ) -> PilotArchiveEpochV1:
        row = connection.execute(
            "SELECT * FROM archive_epoch WHERE archive_id=?", (archive_id,)
        ).fetchone()
        if row is None:
            raise PilotStateTransitionError("unknown archive")
        payload = PilotArchivePayloadV1.model_validate_json(str(row["archive_json"]))
        return PilotArchiveEpochV1(
            payload=payload,
            archive_sha256=str(row["archive_sha256"]),
            archive_hmac_sha256=str(row["archive_hmac_sha256"]),
        )

    def close(self) -> None:
        if self._closed:
            return
        current_pid = os.getpid()
        current_thread = threading.get_ident()
        if current_pid != self._pid:
            # ``flock`` is attached to the open-file description inherited by
            # fork.  A child must never issue LOCK_UN on the parent's shared
            # description.  Mark only the child's copy invalid; process exit
            # will close its duplicate descriptor without explicitly
            # unlocking the still-live parent authority.
            self._closed = True
            raise PilotStoreError(
                "fork child cannot close or unlock the parent pilot store"
            )
        if current_thread != self._thread_id:
            raise PilotStoreError(
                "non-owner thread cannot close or unlock the pilot store"
            )
        try:
            self._connection.close()
        finally:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._closed = True

    def __enter__(self) -> "SingleWriterPilotStore":
        self._ensure_owner()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
