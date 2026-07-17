"""Append-only first-root ledger for the authority-closed SFT bootstrap.

The Phase registry uses a random sealing nonce.  A scientific run must reserve
one anchor identity *before* the first native build and must never treat a
crash as permission to draw another root.  This module provides that narrow
pre-protocol state machine in a SQLite database separate from the child pilot
store.

The ledger proves reservation/freeze ordering, key and file commitments,
stable local identities, and fail-closed recovery.  It intentionally does not
claim to implement native Phase/Factor recount.  Finalization and every frozen
reopen require a private ``_VerifiedAnchorNativeWitness`` supplied by the
future pinned recount boundary; a hash-only witness may be minted by focused
tests through an explicitly private seam, but is not exported as production
authority.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading
from typing import Any, Literal

from pydantic import field_validator

from masbench.sft_pilot.bootstrap_authority import (
    BootstrapAuthorityBundle,
    VerifiedTrainSourceCapability,
)
from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    canonical_sha256,
    require_sha256,
)


ANCHOR_FREEZE_APPLICATION_ID = 0x53464131
ANCHOR_FREEZE_USER_VERSION = 1
ANCHOR_FREEZE_DATABASE_FILENAME = "anchor_freeze.sqlite3"
ANCHOR_FREEZE_LOCK_FILENAME = "anchor_freeze.lock"
ANCHOR_NATIVE_DIRNAME = "anchors"
PHASE_ANCHOR_FILENAME = "phase_registry_anchor_v2.json"
FACTOR_ANCHOR_FILENAME = "factor_bank_anchor_v2.json"
ZERO_SHA256 = "0" * 64

AnchorFreezeState = Literal["absent", "reserved", "frozen", "failed_closed"]
AnchorFailureCode = Literal[
    "no_native_root",
    "partial_native_root",
    "invalid_native_root",
]

_PERMIT_MINT_TOKEN = object()
_WITNESS_MINT_TOKEN = object()


class AnchorFreezeError(RuntimeError):
    """Base class for authority freeze failures."""


class AnchorFreezeBusyError(AnchorFreezeError):
    """Another process owns the stable authority lock."""


class AnchorFreezeIntegrityError(AnchorFreezeError):
    """Persisted schema, chain, key, path, or native bytes are inconsistent."""


class AnchorFreezeStateError(AnchorFreezeError):
    """The requested transition is not legal from the durable state."""


class AnchorNativeWitnessRequired(AnchorFreezeError):
    """Both native files exist but a pinned native witness was not supplied."""


@dataclass(frozen=True, slots=True)
class _AnchorNativeBuildPaths:
    native_dir: Path
    phase_envelope_path: Path
    factor_envelope_path: Path


@dataclass(frozen=True, slots=True)
class _AnchorNativeWitnessRequest:
    bootstrap_authority_manifest_sha256: str
    source_authority_manifest_sha256: str
    anchor_plan_sha256: str
    freeze_key: str
    build_ticket_sha256: str
    native_dir: Path
    phase_envelope_path: Path
    factor_envelope_path: Path


class _AnchorBuildPermit:
    """One process-local permit minted only after reservation commit."""

    __slots__ = (
        "__ledger_identity",
        "__freeze_key",
        "__build_ticket_sha256",
        "__spent",
    )

    def __init__(
        self,
        *,
        _mint_token: object,
        ledger_identity: object,
        freeze_key: str,
        build_ticket_sha256: str,
    ) -> None:
        if _mint_token is not _PERMIT_MINT_TOKEN:
            raise TypeError("anchor build permits have no public constructor")
        object.__setattr__(self, "_AnchorBuildPermit__ledger_identity", ledger_identity)
        object.__setattr__(self, "_AnchorBuildPermit__freeze_key", freeze_key)
        object.__setattr__(
            self,
            "_AnchorBuildPermit__build_ticket_sha256",
            build_ticket_sha256,
        )
        object.__setattr__(self, "_AnchorBuildPermit__spent", False)

    @property
    def freeze_key(self) -> str:
        return self.__freeze_key

    @property
    def build_ticket_sha256(self) -> str:
        return self.__build_ticket_sha256

    def _claim(self, ledger_identity: object) -> None:
        if self.__ledger_identity is not ledger_identity:
            raise AnchorFreezeStateError("build permit belongs to another ledger instance")
        if self.__spent:
            raise AnchorFreezeStateError("anchor build permit has already been consumed")
        object.__setattr__(self, "_AnchorBuildPermit__spent", True)

    def _assert_claimed_by(self, ledger_identity: object) -> None:
        if self.__ledger_identity is not ledger_identity or not self.__spent:
            raise AnchorFreezeStateError("anchor build permit was not consumed for a build")

    def __reduce_ex__(self, _protocol: int) -> None:
        raise TypeError("anchor build permits cannot be serialized")


class _VerifiedAnchorNativeWitness:
    """Private authenticated return value of the future native recount seam."""

    __slots__ = ("__body", "__attestation_sha256", "__mint_identity")

    def __init__(
        self,
        *,
        _mint_token: object,
        body: Mapping[str, Any],
        attestation_sha256: str,
        mint_identity: object,
    ) -> None:
        if _mint_token is not _WITNESS_MINT_TOKEN:
            raise TypeError("native witnesses have no public constructor")
        object.__setattr__(self, "_VerifiedAnchorNativeWitness__body", dict(body))
        object.__setattr__(
            self,
            "_VerifiedAnchorNativeWitness__attestation_sha256",
            attestation_sha256,
        )
        object.__setattr__(
            self, "_VerifiedAnchorNativeWitness__mint_identity", mint_identity
        )

    def _open_for(
        self, *, authority: BootstrapAuthorityBundle, request: _AnchorNativeWitnessRequest
    ) -> dict[str, Any]:
        if not authority._mint_identity_is(self.__mint_identity):
            raise AnchorFreezeIntegrityError(
                "native witness belongs to another bootstrap authority"
            )
        expected_identity = {
            "bootstrap_authority_manifest_sha256": (
                request.bootstrap_authority_manifest_sha256
            ),
            "source_authority_manifest_sha256": (
                request.source_authority_manifest_sha256
            ),
            "anchor_plan_sha256": request.anchor_plan_sha256,
            "freeze_key": request.freeze_key,
            "build_ticket_sha256": request.build_ticket_sha256,
        }
        for field_name, expected in expected_identity.items():
            if self.__body.get(field_name) != expected:
                raise AnchorFreezeIntegrityError(
                    f"native witness identity mismatch: {field_name}"
                )
        expected_attestation = authority._authority_hmac(
            role="anchor_native_recount",
            domain="sft-anchor-native-witness-v1",
            value=self.__body,
        )
        if not hmac.compare_digest(
            self.__attestation_sha256, expected_attestation
        ):
            raise AnchorFreezeIntegrityError("native witness attestation mismatch")
        return dict(self.__body)

    def __reduce_ex__(self, _protocol: int) -> None:
        raise TypeError("native witnesses cannot be serialized")


NativeWitnessProvider = Callable[
    [_AnchorNativeWitnessRequest], _VerifiedAnchorNativeWitness
]


class AnchorFreezeReceiptV1(ClosedPilotModel):
    receipt_version: Literal["sft_anchor_freeze_receipt_v1"] = (
        "sft_anchor_freeze_receipt_v1"
    )
    freeze_key: str
    bootstrap_authority_manifest_sha256: str
    source_authority_manifest_sha256: str
    anchor_plan_sha256: str
    build_ticket_sha256: str
    phase_envelope_sha256: str
    factor_envelope_sha256: str
    anchor_root_sha256: str
    native_recount_sha256: str
    terminal_event_sha256: str

    @field_validator(
        "freeze_key",
        "bootstrap_authority_manifest_sha256",
        "source_authority_manifest_sha256",
        "anchor_plan_sha256",
        "build_ticket_sha256",
        "phase_envelope_sha256",
        "factor_envelope_sha256",
        "anchor_root_sha256",
        "native_recount_sha256",
        "terminal_event_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta(
    only_id INTEGER PRIMARY KEY CHECK(only_id=1),
    schema_digest TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_meta(
    only_id INTEGER PRIMARY KEY CHECK(only_id=1),
    schema_digest TEXT NOT NULL,
    bootstrap_authority_manifest_sha256 TEXT NOT NULL,
    stable_lock_device INTEGER NOT NULL,
    stable_lock_inode INTEGER NOT NULL,
    stable_database_device INTEGER NOT NULL,
    stable_database_inode INTEGER NOT NULL,
    meta_hmac_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anchor_freeze_event(
    freeze_key TEXT NOT NULL,
    event_ordinal INTEGER NOT NULL CHECK(event_ordinal IN (1,2)),
    event_kind TEXT NOT NULL CHECK(event_kind IN ('reserved','frozen','failed_closed')),
    bootstrap_authority_manifest_sha256 TEXT NOT NULL,
    source_authority_manifest_sha256 TEXT NOT NULL,
    anchor_plan_sha256 TEXT NOT NULL,
    reservation_nonce_commitment_sha256 TEXT NOT NULL,
    build_ticket_sha256 TEXT NOT NULL,
    native_dir_commitment_sha256 TEXT NOT NULL,
    native_dir_device INTEGER NOT NULL,
    native_dir_inode INTEGER NOT NULL,
    phase_envelope_sha256 TEXT,
    phase_file_device INTEGER,
    phase_file_inode INTEGER,
    factor_envelope_sha256 TEXT,
    factor_file_device INTEGER,
    factor_file_inode INTEGER,
    anchor_root_sha256 TEXT,
    native_recount_sha256 TEXT,
    safe_failure_code TEXT CHECK(safe_failure_code IS NULL OR safe_failure_code IN (
        'no_native_root','partial_native_root','invalid_native_root'
    )),
    previous_event_sha256 TEXT NOT NULL,
    event_sha256 TEXT NOT NULL UNIQUE,
    event_hmac_sha256 TEXT NOT NULL,
    PRIMARY KEY(freeze_key,event_ordinal)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_reservation_ticket
ON anchor_freeze_event(build_ticket_sha256) WHERE event_ordinal=1;
CREATE UNIQUE INDEX IF NOT EXISTS one_native_dir_identity
ON anchor_freeze_event(native_dir_device,native_dir_inode) WHERE event_ordinal=1;
CREATE UNIQUE INDEX IF NOT EXISTS one_terminal_per_freeze
ON anchor_freeze_event(freeze_key) WHERE event_kind IN ('frozen','failed_closed');

CREATE TRIGGER IF NOT EXISTS schema_meta_no_update
BEFORE UPDATE ON schema_meta BEGIN
  SELECT RAISE(ABORT,'anchor freeze schema metadata is immutable');
END;
CREATE TRIGGER IF NOT EXISTS schema_meta_no_delete
BEFORE DELETE ON schema_meta BEGIN
  SELECT RAISE(ABORT,'anchor freeze schema metadata is immutable');
END;
CREATE TRIGGER IF NOT EXISTS ledger_meta_no_update
BEFORE UPDATE ON ledger_meta BEGIN
  SELECT RAISE(ABORT,'anchor freeze metadata is immutable');
END;
CREATE TRIGGER IF NOT EXISTS ledger_meta_no_delete
BEFORE DELETE ON ledger_meta BEGIN
  SELECT RAISE(ABORT,'anchor freeze metadata is immutable');
END;
CREATE TRIGGER IF NOT EXISTS anchor_freeze_event_no_update
BEFORE UPDATE ON anchor_freeze_event BEGIN
  SELECT RAISE(ABORT,'anchor freeze events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS anchor_freeze_event_no_delete
BEFORE DELETE ON anchor_freeze_event BEGIN
  SELECT RAISE(ABORT,'anchor freeze events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS anchor_freeze_reserved_shape
BEFORE INSERT ON anchor_freeze_event WHEN NEW.event_ordinal=1 BEGIN
  SELECT CASE WHEN NEW.event_kind!='reserved'
    THEN RAISE(ABORT,'ordinal one must be reserved') END;
  SELECT CASE WHEN NEW.previous_event_sha256!='0000000000000000000000000000000000000000000000000000000000000000'
    THEN RAISE(ABORT,'reservation previous root must be zero') END;
  SELECT CASE WHEN NEW.phase_envelope_sha256 IS NOT NULL
    OR NEW.phase_file_device IS NOT NULL OR NEW.phase_file_inode IS NOT NULL
    OR NEW.factor_envelope_sha256 IS NOT NULL
    OR NEW.factor_file_device IS NOT NULL OR NEW.factor_file_inode IS NOT NULL
    OR NEW.anchor_root_sha256 IS NOT NULL OR NEW.native_recount_sha256 IS NOT NULL
    OR NEW.safe_failure_code IS NOT NULL
    THEN RAISE(ABORT,'reservation cannot contain terminal data') END;
  SELECT CASE WHEN EXISTS(
    SELECT 1 FROM anchor_freeze_event WHERE freeze_key=NEW.freeze_key
  ) THEN RAISE(ABORT,'freeze key already reserved') END;
END;

CREATE TRIGGER IF NOT EXISTS anchor_freeze_terminal_shape
BEFORE INSERT ON anchor_freeze_event WHEN NEW.event_ordinal=2 BEGIN
  SELECT CASE WHEN NEW.event_kind NOT IN ('frozen','failed_closed')
    THEN RAISE(ABORT,'ordinal two must be terminal') END;
  SELECT CASE WHEN NOT EXISTS(
    SELECT 1 FROM anchor_freeze_event R
    WHERE R.freeze_key=NEW.freeze_key AND R.event_ordinal=1 AND R.event_kind='reserved'
      AND R.bootstrap_authority_manifest_sha256=NEW.bootstrap_authority_manifest_sha256
      AND R.source_authority_manifest_sha256=NEW.source_authority_manifest_sha256
      AND R.anchor_plan_sha256=NEW.anchor_plan_sha256
      AND R.reservation_nonce_commitment_sha256=NEW.reservation_nonce_commitment_sha256
      AND R.build_ticket_sha256=NEW.build_ticket_sha256
      AND R.native_dir_commitment_sha256=NEW.native_dir_commitment_sha256
      AND R.native_dir_device=NEW.native_dir_device
      AND R.native_dir_inode=NEW.native_dir_inode
      AND R.event_sha256=NEW.previous_event_sha256
  ) THEN RAISE(ABORT,'terminal event does not copy its reservation') END;
  SELECT CASE WHEN NEW.event_kind='frozen' AND (
      NEW.phase_envelope_sha256 IS NULL
      OR NEW.phase_file_device IS NULL OR NEW.phase_file_inode IS NULL
      OR NEW.factor_envelope_sha256 IS NULL
      OR NEW.factor_file_device IS NULL OR NEW.factor_file_inode IS NULL
      OR NEW.anchor_root_sha256 IS NULL OR NEW.native_recount_sha256 IS NULL
      OR NEW.safe_failure_code IS NOT NULL
    ) THEN RAISE(ABORT,'frozen event requires exact native roots') END;
  SELECT CASE WHEN NEW.event_kind='failed_closed' AND (
      NEW.phase_envelope_sha256 IS NOT NULL
      OR NEW.phase_file_device IS NOT NULL OR NEW.phase_file_inode IS NOT NULL
      OR NEW.factor_envelope_sha256 IS NOT NULL
      OR NEW.factor_file_device IS NOT NULL OR NEW.factor_file_inode IS NOT NULL
      OR NEW.anchor_root_sha256 IS NOT NULL OR NEW.native_recount_sha256 IS NOT NULL
      OR NEW.safe_failure_code IS NULL
    ) THEN RAISE(ABORT,'failed event cannot contain deployable roots') END;
END;
"""


def _schema_objects(connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    rows = connection.execute(
        """
        SELECT type,name,tbl_name,sql FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY type,name,tbl_name
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


EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST = _expected_schema_digest()


def compute_anchor_freeze_key(
    *,
    bootstrap_authority_manifest_sha256: str,
    source_authority_manifest_sha256: str,
    anchor_plan_sha256: str,
) -> str:
    for name, value in (
        ("bootstrap_authority_manifest_sha256", bootstrap_authority_manifest_sha256),
        ("source_authority_manifest_sha256", source_authority_manifest_sha256),
        ("anchor_plan_sha256", anchor_plan_sha256),
    ):
        require_sha256(value, field_name=name)
    return canonical_sha256(
        {
            "domain": "sft-anchor-freeze-key-v1",
            "bootstrap_authority_manifest_sha256": (
                bootstrap_authority_manifest_sha256
            ),
            "source_authority_manifest_sha256": source_authority_manifest_sha256,
            "anchor_plan_sha256": anchor_plan_sha256,
        }
    )


def _inspect_native_file(path: Path, *, native_dir_stat: os.stat_result) -> dict[str, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AnchorFreezeIntegrityError("native anchor file cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise AnchorFreezeIntegrityError(
                "native anchor files must be stable non-symlink regular files"
            )
        if stat.S_IMODE(descriptor_stat.st_mode) != 0o600:
            raise AnchorFreezeIntegrityError("native anchor files must be mode 0600")
        if descriptor_stat.st_dev != native_dir_stat.st_dev:
            raise AnchorFreezeIntegrityError(
                "native anchor files must share the directory device"
            )
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        return {
            "sha256": digest.hexdigest(),
            "device": int(descriptor_stat.st_dev),
            "inode": int(descriptor_stat.st_ino),
        }
    finally:
        os.close(fd)


def _mint_verified_anchor_native_witness(
    authority: BootstrapAuthorityBundle,
    request: _AnchorNativeWitnessRequest,
    *,
    phase_envelope_sha256: str,
    factor_envelope_sha256: str,
    anchor_root_sha256: str,
    native_recount_sha256: str,
) -> _VerifiedAnchorNativeWitness:
    """Private seam for pinned recount code (focused tests use hash-only inputs).

    This function authenticates a recount result but does not perform native
    Phase/Factor semantic recount itself.  It remains underscore-private until
    that independent implementation exists.
    """

    for name, value in (
        ("phase_envelope_sha256", phase_envelope_sha256),
        ("factor_envelope_sha256", factor_envelope_sha256),
        ("anchor_root_sha256", anchor_root_sha256),
        ("native_recount_sha256", native_recount_sha256),
    ):
        require_sha256(value, field_name=name)
    if authority.manifest_sha256 != request.bootstrap_authority_manifest_sha256:
        raise AnchorFreezeIntegrityError("native witness request has wrong authority")
    body = {
        "witness_version": "sft-anchor-native-witness-v1",
        "bootstrap_authority_manifest_sha256": request.bootstrap_authority_manifest_sha256,
        "source_authority_manifest_sha256": request.source_authority_manifest_sha256,
        "anchor_plan_sha256": request.anchor_plan_sha256,
        "freeze_key": request.freeze_key,
        "build_ticket_sha256": request.build_ticket_sha256,
        "phase_envelope_sha256": phase_envelope_sha256,
        "factor_envelope_sha256": factor_envelope_sha256,
        "anchor_root_sha256": anchor_root_sha256,
        "native_recount_sha256": native_recount_sha256,
    }
    attestation = authority._authority_hmac(
        role="anchor_native_recount",
        domain="sft-anchor-native-witness-v1",
        value=body,
    )
    return _VerifiedAnchorNativeWitness(
        _mint_token=_WITNESS_MINT_TOKEN,
        body=body,
        attestation_sha256=attestation,
        mint_identity=authority._mint_identity(),
    )


class AnchorFreezeLedger:
    """One stable-lock authority ledger with an append-only two-event chain."""

    def __init__(
        self,
        *,
        authority: BootstrapAuthorityBundle,
        root_dir: Path,
        lock_fd: int,
        connection: sqlite3.Connection,
        native_witness_provider: NativeWitnessProvider | None,
    ) -> None:
        self.authority = authority
        self.root_dir = root_dir
        self.database_path = root_dir / ANCHOR_FREEZE_DATABASE_FILENAME
        self.lock_path = root_dir / ANCHOR_FREEZE_LOCK_FILENAME
        self.anchors_dir = root_dir / ANCHOR_NATIVE_DIRNAME
        self._lock_fd = lock_fd
        self._connection = connection
        self._native_witness_provider = native_witness_provider
        self._pid = os.getpid()
        self._thread_id = threading.get_ident()
        self._closed = False
        self._identity = object()
        lock_stat = os.fstat(lock_fd)
        database_stat = os.lstat(self.database_path)
        self._lock_identity = (int(lock_stat.st_dev), int(lock_stat.st_ino))
        self._database_identity = (
            int(database_stat.st_dev),
            int(database_stat.st_ino),
        )

    @classmethod
    def open(
        cls,
        root_dir: str | Path,
        *,
        authority: BootstrapAuthorityBundle,
        _native_witness_provider: NativeWitnessProvider | None = None,
    ) -> "AnchorFreezeLedger":
        if not isinstance(authority, BootstrapAuthorityBundle):
            raise TypeError("anchor freeze requires a verified bootstrap authority")
        root = Path(root_dir)
        if not root.is_absolute():
            raise AnchorFreezeIntegrityError("anchor freeze root must be absolute")
        expected_root_commitment = authority.manifest.anchor_freeze_dir_commitment_sha256
        from masbench.sft_pilot.bootstrap_authority import authority_root_commitment

        if authority_root_commitment(root) != expected_root_commitment:
            raise AnchorFreezeIntegrityError("anchor freeze root commitment mismatch")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_stat = os.lstat(root)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            raise AnchorFreezeIntegrityError(
                "anchor freeze root must be a non-symlink directory"
            )
        if stat.S_IMODE(root_stat.st_mode) != 0o700:
            raise AnchorFreezeIntegrityError("anchor freeze root must be mode 0700")

        lock_path = root / ANCHOR_FREEZE_LOCK_FILENAME
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            lock_fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise AnchorFreezeIntegrityError("stable freeze lock cannot be opened") from exc
        connection: sqlite3.Connection | None = None
        try:
            os.fchmod(lock_fd, 0o600)
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise AnchorFreezeIntegrityError(
                    "stable freeze lock must be a regular file"
                )
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AnchorFreezeBusyError(
                    "another authority process owns the freeze lock"
                ) from exc
            path_stat = os.lstat(lock_path)
            if (path_stat.st_dev, path_stat.st_ino) != (
                lock_stat.st_dev,
                lock_stat.st_ino,
            ):
                raise AnchorFreezeIntegrityError("stable freeze lock path was replaced")

            database_path = root / ANCHOR_FREEZE_DATABASE_FILENAME
            if database_path.exists() or database_path.is_symlink():
                database_stat = os.lstat(database_path)
                if not stat.S_ISREG(database_stat.st_mode):
                    raise AnchorFreezeIntegrityError(
                        "freeze database must be a non-symlink regular file"
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
            database_stat = os.lstat(database_path)
            cls._initialize_or_verify_schema(connection)

            anchors_dir = root / ANCHOR_NATIVE_DIRNAME
            anchors_dir.mkdir(mode=0o700, exist_ok=True)
            anchors_stat = os.lstat(anchors_dir)
            if (
                not stat.S_ISDIR(anchors_stat.st_mode)
                or stat.S_ISLNK(anchors_stat.st_mode)
                or stat.S_IMODE(anchors_stat.st_mode) != 0o700
            ):
                raise AnchorFreezeIntegrityError(
                    "anchor native root must be a mode-0700 non-symlink directory"
                )

            ledger = cls(
                authority=authority,
                root_dir=root,
                lock_fd=lock_fd,
                connection=connection,
                native_witness_provider=_native_witness_provider,
            )
            ledger._initialize_or_verify_meta(
                lock_device=int(lock_stat.st_dev),
                lock_inode=int(lock_stat.st_ino),
                database_device=int(database_stat.st_dev),
                database_inode=int(database_stat.st_ino),
            )
            ledger._verify_event_chains()
            ledger._recover_or_verify_native_state()
            return ledger
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
            raise AnchorFreezeIntegrityError("freeze database must use WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=0")
        connection.execute("PRAGMA trusted_schema=OFF")
        if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
            raise AnchorFreezeIntegrityError("freeze SQLite synchronous mode is not FULL")
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        if application_id == 0:
            connection.execute(f"PRAGMA application_id={ANCHOR_FREEZE_APPLICATION_ID}")
        elif application_id != ANCHOR_FREEZE_APPLICATION_ID:
            raise AnchorFreezeIntegrityError("freeze SQLite application_id mismatch")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version == 0:
            connection.execute(f"PRAGMA user_version={ANCHOR_FREEZE_USER_VERSION}")
        elif user_version != ANCHOR_FREEZE_USER_VERSION:
            raise AnchorFreezeIntegrityError("freeze SQLite user_version mismatch")

    @staticmethod
    def _initialize_or_verify_schema(connection: sqlite3.Connection) -> None:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]) != "ok":
            raise AnchorFreezeIntegrityError("freeze SQLite quick_check failed")
        connection.executescript(_SCHEMA_SQL)
        actual = canonical_sha256(_schema_objects(connection))
        if not hmac.compare_digest(actual, EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST):
            raise AnchorFreezeIntegrityError("freeze SQLite schema digest mismatch")
        row = connection.execute(
            "SELECT schema_digest FROM schema_meta WHERE only_id=1"
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO schema_meta(only_id,schema_digest) VALUES(1,?)",
                (EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST,),
            )
        elif not hmac.compare_digest(
            str(row[0]), EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST
        ):
            raise AnchorFreezeIntegrityError("persisted freeze schema digest mismatch")

    def _meta_body(
        self,
        *,
        lock_device: int,
        lock_inode: int,
        database_device: int,
        database_inode: int,
    ) -> dict[str, Any]:
        return {
            "schema_digest": EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST,
            "bootstrap_authority_manifest_sha256": self.authority.manifest_sha256,
            "stable_lock_device": lock_device,
            "stable_lock_inode": lock_inode,
            "stable_database_device": database_device,
            "stable_database_inode": database_inode,
        }

    def _initialize_or_verify_meta(
        self,
        *,
        lock_device: int,
        lock_inode: int,
        database_device: int,
        database_inode: int,
    ) -> None:
        body = self._meta_body(
            lock_device=lock_device,
            lock_inode=lock_inode,
            database_device=database_device,
            database_inode=database_inode,
        )
        expected_hmac = self.authority._authority_hmac(
            role="anchor_freeze_ledger",
            domain="sft-anchor-freeze-ledger-meta-v1",
            value=body,
        )
        row = self._connection.execute(
            "SELECT * FROM ledger_meta WHERE only_id=1"
        ).fetchone()
        if row is None:
            self._connection.execute(
                """
                INSERT INTO ledger_meta(
                    only_id,schema_digest,bootstrap_authority_manifest_sha256,
                    stable_lock_device,stable_lock_inode,
                    stable_database_device,stable_database_inode,meta_hmac_sha256
                ) VALUES(1,?,?,?,?,?,?,?)
                """,
                (
                    body["schema_digest"],
                    body["bootstrap_authority_manifest_sha256"],
                    lock_device,
                    lock_inode,
                    database_device,
                    database_inode,
                    expected_hmac,
                ),
            )
            return
        for field_name, expected in body.items():
            if row[field_name] != expected:
                raise AnchorFreezeIntegrityError(
                    f"freeze ledger metadata mismatch: {field_name}"
                )
        if not hmac.compare_digest(str(row["meta_hmac_sha256"]), expected_hmac):
            raise AnchorFreezeIntegrityError("freeze ledger metadata HMAC mismatch")

    def _assert_owner(self) -> None:
        if self._closed:
            raise AnchorFreezeStateError("anchor freeze ledger is closed")
        if os.getpid() != self._pid or threading.get_ident() != self._thread_id:
            raise AnchorFreezeStateError("anchor freeze ledger crossed process/thread owner")
        lock_stat = os.fstat(self._lock_fd)
        lock_path_stat = os.lstat(self.lock_path)
        if (lock_stat.st_dev, lock_stat.st_ino) != self._lock_identity or (
            lock_path_stat.st_dev,
            lock_path_stat.st_ino,
        ) != self._lock_identity:
            raise AnchorFreezeIntegrityError("stable freeze lock identity changed")
        database_stat = os.lstat(self.database_path)
        if (
            database_stat.st_dev,
            database_stat.st_ino,
        ) != self._database_identity:
            raise AnchorFreezeIntegrityError("freeze database identity changed")

    def _native_dir_path(self, freeze_key: str) -> Path:
        return self.anchors_dir / freeze_key

    def _native_dir_commitment(self, freeze_key: str) -> str:
        return canonical_sha256(
            {
                "domain": "sft-anchor-native-dir-v1",
                "authority_root_commitment_sha256": (
                    self.authority.manifest.anchor_freeze_dir_commitment_sha256
                ),
                "relative_path": f"{ANCHOR_NATIVE_DIRNAME}/{freeze_key}",
            }
        )

    @staticmethod
    def _event_payload(row: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload.pop("event_sha256", None)
        payload.pop("event_hmac_sha256", None)
        return payload

    @staticmethod
    def _reservation_ticket(payload: Mapping[str, Any]) -> str:
        ticket_body = dict(payload)
        ticket_body.pop("build_ticket_sha256", None)
        return canonical_sha256(
            {"domain": "sft-anchor-build-ticket-v1", "reservation": ticket_body}
        )

    @staticmethod
    def _terminal_event_sha(payload: Mapping[str, Any]) -> str:
        return canonical_sha256(
            {"domain": "sft-anchor-freeze-terminal-event-v1", "event": payload}
        )

    def _event_hmac(self, *, payload: Mapping[str, Any], event_sha256: str) -> str:
        return self.authority._authority_hmac(
            role="anchor_freeze_ledger",
            domain="sft-anchor-freeze-event-v1",
            value={"event": dict(payload), "event_sha256": event_sha256},
        )

    def _verify_event_chains(self) -> None:
        rows = self._connection.execute(
            "SELECT * FROM anchor_freeze_event ORDER BY freeze_key,event_ordinal"
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        tickets: set[str] = set()
        native_identities: set[tuple[int, int]] = set()
        for row in rows:
            groups.setdefault(str(row["freeze_key"]), []).append(row)
        for freeze_key, chain in groups.items():
            if len(chain) not in {1, 2}:
                raise AnchorFreezeIntegrityError("freeze event chain has invalid length")
            reservation = chain[0]
            if int(reservation["event_ordinal"]) != 1 or reservation["event_kind"] != "reserved":
                raise AnchorFreezeIntegrityError("freeze event chain lacks reservation root")
            exact_freeze_key = compute_anchor_freeze_key(
                bootstrap_authority_manifest_sha256=str(
                    reservation["bootstrap_authority_manifest_sha256"]
                ),
                source_authority_manifest_sha256=str(
                    reservation["source_authority_manifest_sha256"]
                ),
                anchor_plan_sha256=str(reservation["anchor_plan_sha256"]),
            )
            if freeze_key != exact_freeze_key:
                raise AnchorFreezeIntegrityError("persisted anchor freeze key mismatch")
            if reservation["bootstrap_authority_manifest_sha256"] != self.authority.manifest_sha256:
                raise AnchorFreezeIntegrityError("freeze event belongs to another authority")
            payload = self._event_payload(reservation)
            expected_ticket = self._reservation_ticket(payload)
            if (
                reservation["build_ticket_sha256"] != expected_ticket
                or reservation["event_sha256"] != expected_ticket
            ):
                raise AnchorFreezeIntegrityError("reservation ticket/event root mismatch")
            expected_hmac = self._event_hmac(
                payload=payload, event_sha256=expected_ticket
            )
            if not hmac.compare_digest(
                str(reservation["event_hmac_sha256"]), expected_hmac
            ):
                raise AnchorFreezeIntegrityError("reservation event HMAC mismatch")
            if expected_ticket in tickets:
                raise AnchorFreezeIntegrityError("reservation ticket alias detected")
            tickets.add(expected_ticket)
            native_identity = (
                int(reservation["native_dir_device"]),
                int(reservation["native_dir_inode"]),
            )
            if native_identity in native_identities:
                raise AnchorFreezeIntegrityError("native directory alias detected")
            native_identities.add(native_identity)
            self._verify_native_dir_identity(reservation)

            if len(chain) == 2:
                terminal = chain[1]
                if int(terminal["event_ordinal"]) != 2:
                    raise AnchorFreezeIntegrityError("terminal event has wrong ordinal")
                terminal_payload = self._event_payload(terminal)
                expected_terminal_sha = self._terminal_event_sha(terminal_payload)
                if terminal["event_sha256"] != expected_terminal_sha:
                    raise AnchorFreezeIntegrityError("terminal event digest mismatch")
                expected_terminal_hmac = self._event_hmac(
                    payload=terminal_payload,
                    event_sha256=expected_terminal_sha,
                )
                if not hmac.compare_digest(
                    str(terminal["event_hmac_sha256"]), expected_terminal_hmac
                ):
                    raise AnchorFreezeIntegrityError("terminal event HMAC mismatch")
                identity_fields = (
                    "freeze_key",
                    "bootstrap_authority_manifest_sha256",
                    "source_authority_manifest_sha256",
                    "anchor_plan_sha256",
                    "reservation_nonce_commitment_sha256",
                    "build_ticket_sha256",
                    "native_dir_commitment_sha256",
                    "native_dir_device",
                    "native_dir_inode",
                )
                if any(terminal[name] != reservation[name] for name in identity_fields):
                    raise AnchorFreezeIntegrityError("terminal identity differs from reservation")
                if terminal["previous_event_sha256"] != reservation["event_sha256"]:
                    raise AnchorFreezeIntegrityError("terminal previous root mismatch")

    def _verify_native_dir_identity(self, row: Mapping[str, Any]) -> os.stat_result:
        freeze_key = str(row["freeze_key"])
        path = self._native_dir_path(freeze_key)
        try:
            path_stat = os.lstat(path)
        except OSError as exc:
            raise AnchorFreezeIntegrityError("reserved native directory is missing") from exc
        if (
            not stat.S_ISDIR(path_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or stat.S_IMODE(path_stat.st_mode) != 0o700
        ):
            raise AnchorFreezeIntegrityError(
                "reserved native directory must remain mode 0700 and non-symlink"
            )
        if (path_stat.st_dev, path_stat.st_ino) != (
            int(row["native_dir_device"]),
            int(row["native_dir_inode"]),
        ):
            raise AnchorFreezeIntegrityError("reserved native directory identity changed")
        expected_commitment = self._native_dir_commitment(freeze_key)
        if row["native_dir_commitment_sha256"] != expected_commitment:
            raise AnchorFreezeIntegrityError("reserved native directory commitment mismatch")
        return path_stat

    def _reservation_row(self, freeze_key: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM anchor_freeze_event WHERE freeze_key=? AND event_ordinal=1",
            (freeze_key,),
        ).fetchone()
        if row is None:
            raise AnchorFreezeStateError("anchor freeze reservation does not exist")
        return row

    def _terminal_row(self, freeze_key: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM anchor_freeze_event WHERE freeze_key=? AND event_ordinal=2",
            (freeze_key,),
        ).fetchone()

    def reserve(
        self,
        *,
        source_capability: VerifiedTrainSourceCapability,
        anchor_plan_sha256: str,
    ) -> _AnchorBuildPermit:
        """Commit the sole reservation, then mint its one-shot build permit."""

        self._assert_owner()
        require_sha256(anchor_plan_sha256, field_name="anchor_plan_sha256")
        source_manifest, _ = source_capability._open_for(self.authority)
        freeze_key = compute_anchor_freeze_key(
            bootstrap_authority_manifest_sha256=self.authority.manifest_sha256,
            source_authority_manifest_sha256=source_manifest.digest,
            anchor_plan_sha256=anchor_plan_sha256,
        )
        exists = self._connection.execute(
            "SELECT 1 FROM anchor_freeze_event WHERE freeze_key=?", (freeze_key,)
        ).fetchone()
        if exists is not None:
            raise AnchorFreezeStateError("anchor identity was already attempted")

        native_dir = self._native_dir_path(freeze_key)
        try:
            os.mkdir(native_dir, 0o700)
        except FileExistsError as exc:
            raise AnchorFreezeIntegrityError(
                "unledgered native directory blocks a fresh reservation"
            ) from exc
        native_stat = os.lstat(native_dir)
        if (
            not stat.S_ISDIR(native_stat.st_mode)
            or stat.S_ISLNK(native_stat.st_mode)
            or stat.S_IMODE(native_stat.st_mode) != 0o700
        ):
            raise AnchorFreezeIntegrityError("new native directory is not securely owned")

        nonce_commitment = hashlib.sha256(
            b"sft-anchor-reservation-nonce-v1\0" + secrets.token_bytes(32)
        ).hexdigest()
        payload: dict[str, Any] = {
            "freeze_key": freeze_key,
            "event_ordinal": 1,
            "event_kind": "reserved",
            "bootstrap_authority_manifest_sha256": self.authority.manifest_sha256,
            "source_authority_manifest_sha256": source_manifest.digest,
            "anchor_plan_sha256": anchor_plan_sha256,
            "reservation_nonce_commitment_sha256": nonce_commitment,
            "build_ticket_sha256": ZERO_SHA256,
            "native_dir_commitment_sha256": self._native_dir_commitment(freeze_key),
            "native_dir_device": int(native_stat.st_dev),
            "native_dir_inode": int(native_stat.st_ino),
            "phase_envelope_sha256": None,
            "phase_file_device": None,
            "phase_file_inode": None,
            "factor_envelope_sha256": None,
            "factor_file_device": None,
            "factor_file_inode": None,
            "anchor_root_sha256": None,
            "native_recount_sha256": None,
            "safe_failure_code": None,
            "previous_event_sha256": ZERO_SHA256,
        }
        ticket = self._reservation_ticket(payload)
        payload["build_ticket_sha256"] = ticket
        event_hmac = self._event_hmac(payload=payload, event_sha256=ticket)
        columns = tuple(payload) + ("event_sha256", "event_hmac_sha256")
        values = tuple(payload.values()) + (ticket, event_hmac)
        placeholders = ",".join("?" for _ in columns)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                f"INSERT INTO anchor_freeze_event({','.join(columns)}) VALUES({placeholders})",
                values,
            )
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        return _AnchorBuildPermit(
            _mint_token=_PERMIT_MINT_TOKEN,
            ledger_identity=self._identity,
            freeze_key=freeze_key,
            build_ticket_sha256=ticket,
        )

    @contextmanager
    def _native_build_scope(
        self, permit: _AnchorBuildPermit
    ) -> Iterator[_AnchorNativeBuildPaths]:
        """Private one-shot file scope consumed by the future anchor wrapper."""

        self._assert_owner()
        if not isinstance(permit, _AnchorBuildPermit):
            raise TypeError("a committed anchor build permit is required")
        permit._claim(self._identity)
        reservation = self._reservation_row(permit.freeze_key)
        if reservation["build_ticket_sha256"] != permit.build_ticket_sha256:
            raise AnchorFreezeStateError("build permit ticket differs from reservation")
        if self._terminal_row(permit.freeze_key) is not None:
            raise AnchorFreezeStateError("anchor identity is already terminal")
        native_dir = self._native_dir_path(permit.freeze_key)
        entries = tuple(sorted(item.name for item in native_dir.iterdir()))
        if entries:
            raise AnchorFreezeIntegrityError("native build directory is not empty")
        yield _AnchorNativeBuildPaths(
            native_dir=native_dir,
            phase_envelope_path=native_dir / PHASE_ANCHOR_FILENAME,
            factor_envelope_path=native_dir / FACTOR_ANCHOR_FILENAME,
        )

    def _native_witness_request(self, freeze_key: str) -> _AnchorNativeWitnessRequest:
        reservation = self._reservation_row(freeze_key)
        native_dir = self._native_dir_path(freeze_key)
        return _AnchorNativeWitnessRequest(
            bootstrap_authority_manifest_sha256=str(
                reservation["bootstrap_authority_manifest_sha256"]
            ),
            source_authority_manifest_sha256=str(
                reservation["source_authority_manifest_sha256"]
            ),
            anchor_plan_sha256=str(reservation["anchor_plan_sha256"]),
            freeze_key=freeze_key,
            build_ticket_sha256=str(reservation["build_ticket_sha256"]),
            native_dir=native_dir,
            phase_envelope_path=native_dir / PHASE_ANCHOR_FILENAME,
            factor_envelope_path=native_dir / FACTOR_ANCHOR_FILENAME,
        )

    def _native_file_state(
        self, reservation: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        native_stat = self._verify_native_dir_identity(reservation)
        native_dir = self._native_dir_path(str(reservation["freeze_key"]))
        names = tuple(sorted(item.name for item in native_dir.iterdir()))
        expected = {PHASE_ANCHOR_FILENAME, FACTOR_ANCHOR_FILENAME}
        if not names:
            return "none", None, None
        if set(names).difference(expected):
            return "invalid", None, None
        if set(names) != expected:
            return "partial", None, None
        try:
            phase = _inspect_native_file(
                native_dir / PHASE_ANCHOR_FILENAME, native_dir_stat=native_stat
            )
            factor = _inspect_native_file(
                native_dir / FACTOR_ANCHOR_FILENAME, native_dir_stat=native_stat
            )
        except AnchorFreezeIntegrityError:
            return "invalid", None, None
        return "both", phase, factor

    def _append_terminal(
        self,
        *,
        reservation: Mapping[str, Any],
        event_kind: Literal["frozen", "failed_closed"],
        phase: Mapping[str, Any] | None = None,
        factor: Mapping[str, Any] | None = None,
        anchor_root_sha256: str | None = None,
        native_recount_sha256: str | None = None,
        safe_failure_code: AnchorFailureCode | None = None,
    ) -> sqlite3.Row:
        payload: dict[str, Any] = {
            "freeze_key": reservation["freeze_key"],
            "event_ordinal": 2,
            "event_kind": event_kind,
            "bootstrap_authority_manifest_sha256": reservation[
                "bootstrap_authority_manifest_sha256"
            ],
            "source_authority_manifest_sha256": reservation[
                "source_authority_manifest_sha256"
            ],
            "anchor_plan_sha256": reservation["anchor_plan_sha256"],
            "reservation_nonce_commitment_sha256": reservation[
                "reservation_nonce_commitment_sha256"
            ],
            "build_ticket_sha256": reservation["build_ticket_sha256"],
            "native_dir_commitment_sha256": reservation[
                "native_dir_commitment_sha256"
            ],
            "native_dir_device": reservation["native_dir_device"],
            "native_dir_inode": reservation["native_dir_inode"],
            "phase_envelope_sha256": None if phase is None else phase["sha256"],
            "phase_file_device": None if phase is None else phase["device"],
            "phase_file_inode": None if phase is None else phase["inode"],
            "factor_envelope_sha256": None if factor is None else factor["sha256"],
            "factor_file_device": None if factor is None else factor["device"],
            "factor_file_inode": None if factor is None else factor["inode"],
            "anchor_root_sha256": anchor_root_sha256,
            "native_recount_sha256": native_recount_sha256,
            "safe_failure_code": safe_failure_code,
            "previous_event_sha256": reservation["event_sha256"],
        }
        event_sha = self._terminal_event_sha(payload)
        event_hmac = self._event_hmac(payload=payload, event_sha256=event_sha)
        columns = tuple(payload) + ("event_sha256", "event_hmac_sha256")
        values = tuple(payload.values()) + (event_sha, event_hmac)
        placeholders = ",".join("?" for _ in columns)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                f"INSERT INTO anchor_freeze_event({','.join(columns)}) VALUES({placeholders})",
                values,
            )
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        terminal = self._terminal_row(str(reservation["freeze_key"]))
        if terminal is None:
            raise AnchorFreezeIntegrityError("terminal freeze event was not committed")
        return terminal

    def _validate_native_witness(
        self,
        *,
        request: _AnchorNativeWitnessRequest,
        witness: _VerifiedAnchorNativeWitness,
        phase: Mapping[str, Any],
        factor: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(witness, _VerifiedAnchorNativeWitness):
            raise AnchorFreezeIntegrityError("private native witness has wrong type")
        body = witness._open_for(authority=self.authority, request=request)
        for field_name, observed in (
            ("phase_envelope_sha256", phase["sha256"]),
            ("factor_envelope_sha256", factor["sha256"]),
        ):
            if body.get(field_name) != observed:
                raise AnchorFreezeIntegrityError(
                    f"native witness differs from exact file bytes: {field_name}"
                )
        require_sha256(str(body.get("anchor_root_sha256")), field_name="anchor_root_sha256")
        require_sha256(
            str(body.get("native_recount_sha256")), field_name="native_recount_sha256"
        )
        return body

    def _finalize_with_native_witness(
        self,
        permit: _AnchorBuildPermit,
        witness: _VerifiedAnchorNativeWitness,
    ) -> AnchorFreezeReceiptV1:
        """Private finalization seam; semantic recount is deliberately external."""

        self._assert_owner()
        if not isinstance(permit, _AnchorBuildPermit):
            raise TypeError("a committed anchor build permit is required")
        permit._assert_claimed_by(self._identity)
        reservation = self._reservation_row(permit.freeze_key)
        if self._terminal_row(permit.freeze_key) is not None:
            raise AnchorFreezeStateError("anchor identity is already terminal")
        state, phase, factor = self._native_file_state(reservation)
        if state != "both" or phase is None or factor is None:
            raise AnchorFreezeStateError("exactly two valid native files are required")
        request = self._native_witness_request(permit.freeze_key)
        body = self._validate_native_witness(
            request=request, witness=witness, phase=phase, factor=factor
        )
        terminal = self._append_terminal(
            reservation=reservation,
            event_kind="frozen",
            phase=phase,
            factor=factor,
            anchor_root_sha256=str(body["anchor_root_sha256"]),
            native_recount_sha256=str(body["native_recount_sha256"]),
        )
        return self._receipt_from_terminal(terminal)

    def _receipt_from_terminal(self, terminal: Mapping[str, Any]) -> AnchorFreezeReceiptV1:
        if terminal["event_kind"] != "frozen":
            raise AnchorFreezeStateError("anchor identity is not frozen")
        return AnchorFreezeReceiptV1(
            freeze_key=str(terminal["freeze_key"]),
            bootstrap_authority_manifest_sha256=str(
                terminal["bootstrap_authority_manifest_sha256"]
            ),
            source_authority_manifest_sha256=str(
                terminal["source_authority_manifest_sha256"]
            ),
            anchor_plan_sha256=str(terminal["anchor_plan_sha256"]),
            build_ticket_sha256=str(terminal["build_ticket_sha256"]),
            phase_envelope_sha256=str(terminal["phase_envelope_sha256"]),
            factor_envelope_sha256=str(terminal["factor_envelope_sha256"]),
            anchor_root_sha256=str(terminal["anchor_root_sha256"]),
            native_recount_sha256=str(terminal["native_recount_sha256"]),
            terminal_event_sha256=str(terminal["event_sha256"]),
        )

    def _recover_or_verify_native_state(self) -> None:
        rows = self._connection.execute(
            "SELECT * FROM anchor_freeze_event WHERE event_ordinal=1 ORDER BY freeze_key"
        ).fetchall()
        for reservation in rows:
            freeze_key = str(reservation["freeze_key"])
            terminal = self._terminal_row(freeze_key)
            state, phase, factor = self._native_file_state(reservation)
            if terminal is None:
                if state == "none":
                    self._append_terminal(
                        reservation=reservation,
                        event_kind="failed_closed",
                        safe_failure_code="no_native_root",
                    )
                    continue
                if state == "partial":
                    self._append_terminal(
                        reservation=reservation,
                        event_kind="failed_closed",
                        safe_failure_code="partial_native_root",
                    )
                    continue
                if state == "invalid":
                    self._append_terminal(
                        reservation=reservation,
                        event_kind="failed_closed",
                        safe_failure_code="invalid_native_root",
                    )
                    continue
                if self._native_witness_provider is None:
                    raise AnchorNativeWitnessRequired(
                        "reserved native files require the private recount witness interface"
                    )
                assert phase is not None and factor is not None
                request = self._native_witness_request(freeze_key)
                try:
                    witness = self._native_witness_provider(request)
                    body = self._validate_native_witness(
                        request=request,
                        witness=witness,
                        phase=phase,
                        factor=factor,
                    )
                except BaseException as exc:
                    self._append_terminal(
                        reservation=reservation,
                        event_kind="failed_closed",
                        safe_failure_code="invalid_native_root",
                    )
                    raise AnchorFreezeIntegrityError(
                        "reserved native files failed private witness verification"
                    ) from exc
                self._append_terminal(
                    reservation=reservation,
                    event_kind="frozen",
                    phase=phase,
                    factor=factor,
                    anchor_root_sha256=str(body["anchor_root_sha256"]),
                    native_recount_sha256=str(body["native_recount_sha256"]),
                )
                continue

            if terminal["event_kind"] == "failed_closed":
                continue
            if state != "both" or phase is None or factor is None:
                raise AnchorFreezeIntegrityError("frozen native files are missing or invalid")
            for field_name, observed in (
                ("phase_envelope_sha256", phase["sha256"]),
                ("phase_file_device", phase["device"]),
                ("phase_file_inode", phase["inode"]),
                ("factor_envelope_sha256", factor["sha256"]),
                ("factor_file_device", factor["device"]),
                ("factor_file_inode", factor["inode"]),
            ):
                if terminal[field_name] != observed:
                    raise AnchorFreezeIntegrityError(
                        f"frozen native identity mismatch: {field_name}"
                    )
            if self._native_witness_provider is None:
                raise AnchorNativeWitnessRequired(
                    "frozen reopen requires a fresh private native witness"
                )
            request = self._native_witness_request(freeze_key)
            witness = self._native_witness_provider(request)
            body = self._validate_native_witness(
                request=request, witness=witness, phase=phase, factor=factor
            )
            if (
                body["anchor_root_sha256"] != terminal["anchor_root_sha256"]
                or body["native_recount_sha256"] != terminal["native_recount_sha256"]
            ):
                raise AnchorFreezeIntegrityError(
                    "fresh native witness differs from frozen receipt"
                )

    def state(self, freeze_key: str) -> AnchorFreezeState:
        self._assert_owner()
        require_sha256(freeze_key, field_name="freeze_key")
        reservation = self._connection.execute(
            "SELECT 1 FROM anchor_freeze_event WHERE freeze_key=? AND event_ordinal=1",
            (freeze_key,),
        ).fetchone()
        if reservation is None:
            return "absent"
        terminal = self._terminal_row(freeze_key)
        if terminal is None:
            return "reserved"
        return str(terminal["event_kind"])  # type: ignore[return-value]

    def frozen_receipt(self, freeze_key: str) -> AnchorFreezeReceiptV1:
        self._assert_owner()
        require_sha256(freeze_key, field_name="freeze_key")
        terminal = self._terminal_row(freeze_key)
        if terminal is None:
            raise AnchorFreezeStateError("anchor identity has no terminal event")
        return self._receipt_from_terminal(terminal)

    def close(self) -> None:
        if self._closed:
            return
        if os.getpid() != self._pid:
            raise AnchorFreezeStateError("forked process cannot close authority ledger")
        self._connection.close()
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(self._lock_fd)
        self._closed = True

    def __enter__(self) -> "AnchorFreezeLedger":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()


__all__ = [
    "ANCHOR_FREEZE_APPLICATION_ID",
    "ANCHOR_FREEZE_DATABASE_FILENAME",
    "ANCHOR_FREEZE_LOCK_FILENAME",
    "ANCHOR_FREEZE_USER_VERSION",
    "EXPECTED_ANCHOR_FREEZE_SCHEMA_DIGEST",
    "AnchorFreezeBusyError",
    "AnchorFreezeError",
    "AnchorFreezeIntegrityError",
    "AnchorFreezeLedger",
    "AnchorFreezeReceiptV1",
    "AnchorFreezeStateError",
    "AnchorNativeWitnessRequired",
    "compute_anchor_freeze_key",
]
