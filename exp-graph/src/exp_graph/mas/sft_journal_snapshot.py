"""Read-only, freshly verified authority over one SFT journal checkpoint.

The caller supplies opaque journal/locator identities and trusted resolver
capabilities, never a filesystem path or an HMAC key.  Every load reopens the
file under the writer's lock, authenticates the complete v2 journal lifecycle,
checks the PUBLIC/TRAIN manifest and live checkpoint provider, and seals the
closed receipt under a separately pinned reader key.

The returned object deliberately has no save, mutation, checkpoint-claim or
provider-ack surface.  It is a short-lived input to projection verifiers, not
a second journal writer and not a cacheable grant.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import re
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from exp_graph.mas.factor_bank import assert_bank_safe_public_value
from exp_graph.mas.sft_journal import (
    CheckpointProviderSnapshotV2,
    JournalCheckpointV2,
    JournalScopeV2,
    RunnerJournalStateV2,
    journal_canonical_sha256_v2,
    journal_fixed_hmac_sha256_v2,
    verify_runner_journal_envelope_bytes_v2,
)


_HOST_ID_RE = re.compile(
    r"^(?P<prefix>[a-z]{1,8}):(?:[0-9a-f]{24}|[0-9a-f]{48}|[0-9a-f]{64})$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_CONSTRUCTION_TOKEN = object()


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
        raise ValueError(f"{name} must be a host-derived {expected}:<hex> identifier")


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
            raise ValueError("TEST/private split labels are forbidden in snapshots")


class _ClosedSnapshotModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def reject_oracle_or_private_values(self) -> "_ClosedSnapshotModel":
        value = self.model_dump(mode="python")
        assert_bank_safe_public_value(value)
        _reject_explicit_test_label(value)
        return self


class ScopeManifestVerificationV1(_ClosedSnapshotModel):
    """Authenticated structured result from the host manifest authority."""

    verification_version: Literal["sft_scope_manifest_verification_v1"] = (
        "sft_scope_manifest_verification_v1"
    )
    manifest_sha256: str
    source: Literal["PUBLIC", "TRAIN_UPDATE"]
    scope_sha256: str
    verifier_epoch_sha256: str
    verifier_attestation_sha256: str

    @model_validator(mode="after")
    def validate_digests(self) -> "ScopeManifestVerificationV1":
        for name in (
            "manifest_sha256",
            "scope_sha256",
            "verifier_epoch_sha256",
            "verifier_attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self

    @property
    def digest(self) -> str:
        return journal_canonical_sha256_v2(self)


class SnapshotTrustPolicyV1(_ClosedSnapshotModel):
    """Host-pinned identities for every authority used by a snapshot read.

    This expected policy is supplied by the trusted composition root, not
    derived from the capabilities being checked.  It prevents a substitute
    provider or self-validating manifest verifier from choosing its own epoch.
    """

    policy_version: Literal["sft_snapshot_trust_policy_v1"] = (
        "sft_snapshot_trust_policy_v1"
    )
    journal_locator_id: str
    journal_id: str
    scope_sha256: str
    journal_locator_sha256: str
    journal_key_commitment_sha256: str
    reader_key_commitment_sha256: str
    reader_policy_sha256: str
    provider_epoch_sha256: str
    manifest_verifier_epoch_sha256: str
    manifest_verifier_policy_sha256: str
    authority_scope: Literal["observation_only"] = "observation_only"

    @model_validator(mode="after")
    def validate_policy(self) -> "SnapshotTrustPolicyV1":
        _require_host_id(
            self.journal_locator_id,
            "journal_locator_id",
            allowed_prefixes=("jl",),
        )
        _require_host_id(self.journal_id, "journal_id", allowed_prefixes=("jr",))
        for name in (
            "scope_sha256",
            "journal_locator_sha256",
            "journal_key_commitment_sha256",
            "reader_key_commitment_sha256",
            "reader_policy_sha256",
            "provider_epoch_sha256",
            "manifest_verifier_epoch_sha256",
            "manifest_verifier_policy_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        return self

    @property
    def digest(self) -> str:
        return journal_canonical_sha256_v2(self)


class VerifiedJournalSnapshotReceiptV1(_ClosedSnapshotModel):
    """Closed point-in-time observation; never physical-execution authority."""

    receipt_version: Literal["sft_verified_journal_snapshot_v1"] = (
        "sft_verified_journal_snapshot_v1"
    )
    journal_id: str
    journal_locator_sha256: str
    trust_policy_sha256: str
    authority_scope: Literal["observation_only"] = "observation_only"
    envelope_sha256: str
    state_sha256: str
    state: RunnerJournalStateV2
    checkpoint: JournalCheckpointV2
    provider_epoch_sha256: str
    provider_snapshot_sha256: str
    provider_pending: Literal[False] = False
    scope_verification: ScopeManifestVerificationV1
    reader_policy_sha256: str
    reader_attestation_sha256: str

    @model_validator(mode="after")
    def validate_receipt_relations(self) -> "VerifiedJournalSnapshotReceiptV1":
        _require_host_id(self.journal_id, "journal_id", allowed_prefixes=("jr",))
        for name in (
            "journal_locator_sha256",
            "trust_policy_sha256",
            "envelope_sha256",
            "state_sha256",
            "provider_epoch_sha256",
            "provider_snapshot_sha256",
            "reader_policy_sha256",
            "reader_attestation_sha256",
        ):
            _require_sha(str(getattr(self, name)), name)
        if self.state.journal_id != self.journal_id:
            raise ValueError("snapshot state crosses journal identities")
        if self.state_sha256 != self.state.digest:
            raise ValueError("snapshot state digest is not reproducible")
        if not (
            self.checkpoint.journal_id == self.journal_id
            and self.checkpoint.scope_sha256 == self.state.scope.digest
            and self.checkpoint.sequence == self.state.sequence
            and self.checkpoint.fencing_generation == self.state.fencing_generation
            and self.checkpoint.head_event_sha256 == self.state.head_event_sha256
            and self.checkpoint.state_sha256 == self.state_sha256
        ):
            raise ValueError("snapshot checkpoint differs from its exact state")
        if not (
            self.scope_verification.manifest_sha256
            == self.state.scope.mode_payload_manifest_sha256
            and self.scope_verification.source == self.state.scope.mode_payload_source
            and self.scope_verification.scope_sha256 == self.state.scope.digest
        ):
            raise ValueError("snapshot scope verification differs from journal scope")
        return self

    @property
    def attestation_body(self) -> dict[str, Any]:
        return self.model_dump(
            mode="python",
            exclude={"reader_attestation_sha256"},
        )

    @property
    def digest(self) -> str:
        return journal_canonical_sha256_v2(self)


class TrustedJournalLocatorResolver(Protocol):
    """Host registry authority; untrusted call sites never provide a path."""

    def resolve_journal_path(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> Path:
        ...

    def pinned_locator_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        ...


class ReadOnlyLatestCheckpointProviderV2(Protocol):
    """Narrow provider view: snapshot readers can inspect but never claim/ack."""

    def inspect(self, journal_id: str) -> CheckpointProviderSnapshotV2:
        ...


class TrustedJournalKeyResolver(Protocol):
    """Trusted composition-root authority for journal and reader keys.

    The loader accepts this resolver capability, never raw keys.  Implementors
    must pin commitments independently of the bytes returned by the two key
    methods; the loader recomputes and compares both commitments on every read.
    """

    def resolve_journal_hmac_key(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> bytes:
        ...

    def resolve_reader_hmac_key(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> bytes:
        ...

    def pinned_journal_key_commitment_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        ...

    def pinned_reader_key_commitment_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        ...

    def reader_policy_sha256(
        self,
        *,
        journal_locator_id: str,
        expected_journal_id: str,
    ) -> str:
        ...


class TrustedScopeManifestVerifier(Protocol):
    """Structured PUBLIC/TRAIN manifest authority, not a boolean callback."""

    def verify_scope_manifest(
        self,
        scope: JournalScopeV2,
    ) -> ScopeManifestVerificationV1:
        ...

    def verifier_policy_sha256(self) -> str:
        """Return the host-registered verifier/key-policy commitment."""

        ...

    def validate_scope_manifest_verification(
        self,
        *,
        scope: JournalScopeV2,
        verification: ScopeManifestVerificationV1,
    ) -> None:
        ...


def journal_locator_commitment_v1(
    *,
    journal_locator_id: str,
    expected_journal_id: str,
    resolved_path: Path | str,
) -> str:
    """Commit an out-of-band registry entry without persisting its path."""

    _require_host_id(
        journal_locator_id,
        "journal_locator_id",
        allowed_prefixes=("jl",),
    )
    _require_host_id(
        expected_journal_id,
        "expected_journal_id",
        allowed_prefixes=("jr",),
    )
    path = Path(resolved_path).resolve()
    path_sha256 = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return journal_canonical_sha256_v2(
        {
            "commitment_version": "sft_journal_locator_commitment_v1",
            "journal_locator_id": journal_locator_id,
            "expected_journal_id": expected_journal_id,
            "absolute_path_sha256": path_sha256,
        }
    )


def journal_key_commitment_v1(*, role: Literal["journal", "reader"], key: bytes) -> str:
    """Commit resolver-pinned key bytes without placing key material in state."""

    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError(f"{role} key must contain at least 32 bytes")
    return journal_canonical_sha256_v2(
        {
            "commitment_version": "sft_journal_key_commitment_v1",
            "role": role,
            "key_sha256": hashlib.sha256(key).hexdigest(),
        }
    )


class VerifiedJournalSnapshot:
    """Ephemeral point-in-time observation created only by a fresh load.

    It intentionally exposes no method that releases physical execution or
    mutates another store.  A downstream transition must fresh-load internally
    and conditionally consume the exact provider/checkpoint+saga authority;
    caching or replaying this object is never sufficient.
    """

    __slots__ = ("_receipt",)

    def __init__(
        self,
        receipt: VerifiedJournalSnapshotReceiptV1,
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _SNAPSHOT_CONSTRUCTION_TOKEN:
            raise ValueError("verified snapshots require a fresh authenticated load")
        self._receipt = VerifiedJournalSnapshotReceiptV1.model_validate(
            receipt.model_dump(mode="python")
        )

    @property
    def receipt(self) -> VerifiedJournalSnapshotReceiptV1:
        return self._receipt.model_copy(deep=True)

    @property
    def state(self) -> RunnerJournalStateV2:
        return self._receipt.state.model_copy(deep=True)

    @property
    def authority_scope(self) -> Literal["observation_only"]:
        return "observation_only"


def _call_resolver(method: Any, *, label: str, **kwargs: str) -> Any:
    try:
        return method(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"trusted {label} resolution failed") from exc


def load_verified_snapshot(
    *,
    journal_locator_id: str,
    expected_journal_id: str,
    expected_scope: JournalScopeV2,
    expected_trust_policy: SnapshotTrustPolicyV1,
    journal_key_resolver: TrustedJournalKeyResolver,
    journal_locator_resolver: TrustedJournalLocatorResolver,
    checkpoint_provider: ReadOnlyLatestCheckpointProviderV2,
    scope_manifest_verifier: TrustedScopeManifestVerifier,
) -> VerifiedJournalSnapshot:
    """Load a fresh closed observation at one provider linearization point.

    This is not an execution-release lease.  The provider can advance after
    its ``inspect`` returns, so any authoritative downstream mutation still
    needs a provider-backed conditional consume/read fence plus saga CAS.
    """

    _require_host_id(
        journal_locator_id,
        "journal_locator_id",
        allowed_prefixes=("jl",),
    )
    _require_host_id(
        expected_journal_id,
        "expected_journal_id",
        allowed_prefixes=("jr",),
    )
    if any(
        capability is None
        for capability in (
            journal_key_resolver,
            journal_locator_resolver,
            checkpoint_provider,
            scope_manifest_verifier,
        )
    ):
        raise ValueError("all trusted snapshot capabilities are required")
    expected_scope = JournalScopeV2.model_validate(
        expected_scope.model_dump(mode="python")
    )
    expected_trust_policy = SnapshotTrustPolicyV1.model_validate(
        expected_trust_policy.model_dump(mode="python")
    )
    if not (
        expected_trust_policy.journal_locator_id == journal_locator_id
        and expected_trust_policy.journal_id == expected_journal_id
        and expected_trust_policy.scope_sha256 == expected_scope.digest
        and expected_trust_policy.authority_scope == "observation_only"
    ):
        raise ValueError("snapshot trust policy differs from expected identity/scope")
    resolver_kwargs = {
        "journal_locator_id": journal_locator_id,
        "expected_journal_id": expected_journal_id,
    }
    target = Path(
        _call_resolver(
            journal_locator_resolver.resolve_journal_path,
            label="journal locator path",
            **resolver_kwargs,
        )
    ).resolve()
    pinned_locator = str(
        _call_resolver(
            journal_locator_resolver.pinned_locator_sha256,
            label="journal locator commitment",
            **resolver_kwargs,
        )
    )
    _require_sha(pinned_locator, "pinned_locator_sha256")
    actual_locator = journal_locator_commitment_v1(
        journal_locator_id=journal_locator_id,
        expected_journal_id=expected_journal_id,
        resolved_path=target,
    )
    if not hmac.compare_digest(pinned_locator, actual_locator):
        raise ValueError("resolved journal path differs from pinned locator")
    if not hmac.compare_digest(
        pinned_locator,
        expected_trust_policy.journal_locator_sha256,
    ):
        raise ValueError("locator resolver differs from host trust policy")

    journal_key = _call_resolver(
        journal_key_resolver.resolve_journal_hmac_key,
        label="journal HMAC key",
        **resolver_kwargs,
    )
    reader_key = _call_resolver(
        journal_key_resolver.resolve_reader_hmac_key,
        label="reader HMAC key",
        **resolver_kwargs,
    )
    if not isinstance(journal_key, bytes) or not isinstance(reader_key, bytes):
        raise TypeError("trusted key resolver must return bytes")
    pinned_journal_key = str(
        _call_resolver(
            journal_key_resolver.pinned_journal_key_commitment_sha256,
            label="journal key commitment",
            **resolver_kwargs,
        )
    )
    pinned_reader_key = str(
        _call_resolver(
            journal_key_resolver.pinned_reader_key_commitment_sha256,
            label="reader key commitment",
            **resolver_kwargs,
        )
    )
    _require_sha(pinned_journal_key, "pinned_journal_key_commitment_sha256")
    _require_sha(pinned_reader_key, "pinned_reader_key_commitment_sha256")
    if not hmac.compare_digest(
        pinned_journal_key,
        expected_trust_policy.journal_key_commitment_sha256,
    ):
        raise ValueError("journal key registry differs from host trust policy")
    if not hmac.compare_digest(
        pinned_reader_key,
        expected_trust_policy.reader_key_commitment_sha256,
    ):
        raise ValueError("reader key registry differs from host trust policy")
    if not hmac.compare_digest(
        pinned_journal_key,
        journal_key_commitment_v1(role="journal", key=journal_key),
    ):
        raise ValueError("resolved journal key differs from pinned commitment")
    if not hmac.compare_digest(
        pinned_reader_key,
        journal_key_commitment_v1(role="reader", key=reader_key),
    ):
        raise ValueError("resolved reader key differs from pinned commitment")
    reader_policy_sha256 = str(
        _call_resolver(
            journal_key_resolver.reader_policy_sha256,
            label="reader policy",
            **resolver_kwargs,
        )
    )
    _require_sha(reader_policy_sha256, "reader_policy_sha256")
    if not hmac.compare_digest(
        reader_policy_sha256,
        expected_trust_policy.reader_policy_sha256,
    ):
        raise ValueError("reader policy differs from host trust policy")

    lock_path = target.with_suffix(target.suffix + ".lock")
    # A persisted writer creates this lock before publication.  The reader
    # opens it without create/write flags so snapshot loading itself performs
    # no filesystem mutation and a missing writer lock fails closed.
    with lock_path.open("rb") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        try:
            raw_bytes = target.read_bytes()
            envelope_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            envelope, checkpoint = verify_runner_journal_envelope_bytes_v2(
                raw_bytes,
                journal_key=journal_key,
                expected_journal_id=expected_journal_id,
                expected_scope=expected_scope,
            )
            try:
                raw_verification = scope_manifest_verifier.verify_scope_manifest(
                    envelope.state.scope
                )
            except Exception as exc:
                raise RuntimeError("trusted scope manifest verification failed") from exc
            scope_verification = ScopeManifestVerificationV1.model_validate(
                raw_verification.model_dump(mode="python")
                if isinstance(raw_verification, BaseModel)
                else raw_verification
            )
            if not (
                scope_verification.manifest_sha256
                == expected_scope.mode_payload_manifest_sha256
                and scope_verification.source == expected_scope.mode_payload_source
                and scope_verification.scope_sha256 == expected_scope.digest
            ):
                raise ValueError("scope manifest verification differs from expected scope")
            if not hmac.compare_digest(
                scope_verification.verifier_epoch_sha256,
                expected_trust_policy.manifest_verifier_epoch_sha256,
            ):
                raise ValueError("manifest verifier epoch differs from host trust policy")
            try:
                manifest_verifier_policy_sha256 = str(
                    scope_manifest_verifier.verifier_policy_sha256()
                )
            except Exception as exc:
                raise RuntimeError("manifest verifier policy lookup failed") from exc
            _require_sha(
                manifest_verifier_policy_sha256,
                "manifest_verifier_policy_sha256",
            )
            if not hmac.compare_digest(
                manifest_verifier_policy_sha256,
                expected_trust_policy.manifest_verifier_policy_sha256,
            ):
                raise ValueError(
                    "manifest verifier policy differs from host trust policy"
                )
            try:
                scope_manifest_verifier.validate_scope_manifest_verification(
                    scope=expected_scope,
                    verification=scope_verification,
                )
            except Exception as exc:
                raise RuntimeError(
                    "scope manifest verification attestation was rejected"
                ) from exc

            try:
                raw_provider_snapshot = checkpoint_provider.inspect(
                    expected_journal_id
                )
            except Exception as exc:
                raise RuntimeError("latest-checkpoint provider inspection failed") from exc
            provider_snapshot = CheckpointProviderSnapshotV2.model_validate(
                raw_provider_snapshot.model_dump(mode="python")
                if isinstance(raw_provider_snapshot, BaseModel)
                else raw_provider_snapshot
            )
            if provider_snapshot.journal_id != expected_journal_id:
                raise ValueError("checkpoint provider returned the wrong journal")
            if not hmac.compare_digest(
                provider_snapshot.provider_epoch_sha256,
                expected_trust_policy.provider_epoch_sha256,
            ):
                raise ValueError("checkpoint provider epoch differs from host trust policy")
            if provider_snapshot.pending_claim is not None:
                raise RuntimeError(
                    "external checkpoint update awaits owner acknowledgement"
                )
            if provider_snapshot.latest_checkpoint != checkpoint:
                raise RuntimeError(
                    "external latest checkpoint differs from the exact journal state"
                )

            # A non-cooperating process can replace a pathname without taking
            # the advisory lock.  Re-read before granting authority; only the
            # exact bytes authenticated above may still occupy the registry path.
            if target.read_bytes() != raw_bytes:
                raise RuntimeError("journal file changed during verified snapshot read")

            provider_snapshot_sha256 = journal_canonical_sha256_v2(
                provider_snapshot
            )
            receipt_body = {
                "receipt_version": "sft_verified_journal_snapshot_v1",
                "journal_id": expected_journal_id,
                "journal_locator_sha256": pinned_locator,
                "trust_policy_sha256": expected_trust_policy.digest,
                "authority_scope": "observation_only",
                "envelope_sha256": envelope_sha256,
                "state_sha256": envelope.state.digest,
                "state": envelope.state,
                "checkpoint": checkpoint,
                "provider_epoch_sha256": provider_snapshot.provider_epoch_sha256,
                "provider_snapshot_sha256": provider_snapshot_sha256,
                "provider_pending": False,
                "scope_verification": scope_verification,
                "reader_policy_sha256": reader_policy_sha256,
            }
            receipt = VerifiedJournalSnapshotReceiptV1(
                **receipt_body,
                reader_attestation_sha256=journal_fixed_hmac_sha256_v2(
                    reader_key,
                    domain="sft-journal-snapshot-reader-v1",
                    value=receipt_body,
                ),
            )
            expected_reader_attestation = journal_fixed_hmac_sha256_v2(
                reader_key,
                domain="sft-journal-snapshot-reader-v1",
                value=receipt.attestation_body,
            )
            if not hmac.compare_digest(
                receipt.reader_attestation_sha256,
                expected_reader_attestation,
            ):
                raise ValueError("verified journal reader attestation mismatch")
            return VerifiedJournalSnapshot(
                receipt,
                _construction_token=_SNAPSHOT_CONSTRUCTION_TOKEN,
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


__all__ = [
    "ReadOnlyLatestCheckpointProviderV2",
    "ScopeManifestVerificationV1",
    "SnapshotTrustPolicyV1",
    "TrustedJournalKeyResolver",
    "TrustedJournalLocatorResolver",
    "TrustedScopeManifestVerifier",
    "VerifiedJournalSnapshot",
    "VerifiedJournalSnapshotReceiptV1",
    "journal_key_commitment_v1",
    "journal_locator_commitment_v1",
    "load_verified_snapshot",
]
