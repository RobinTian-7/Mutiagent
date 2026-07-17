"""Pre-protocol trust root and TRAIN-only source authority for the SFT pilot.

The scientific pilot must not let a run-time caller choose the source catalog,
split, signing key, or authority code after seeing an outcome.  This module
therefore starts from one externally preregistered manifest digest, verifies
the host commit/code/key pins, and mints process-local capabilities from exact
canonical dataset release and split manifests.

Only commitments cross this boundary.  Dataset text, answers, expected output,
private score packs, and FINAL_VAL rows are neither accepted by the TRAIN
loader nor represented by the public authority schemas.  The capabilities are
deliberately non-serializable.  They are an authority API boundary, not a
hostile in-process Python sandbox; a compromised host authority remains an
explicit external trust assumption.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
from typing import Any, Literal

from pydantic import field_validator, model_validator

from masbench.sft_pilot.manifests import (
    PilotCodeSourceV1,
    load_frozen_manifest,
)
from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    canonical_sha256,
    pilot_hmac_sha256,
    require_opaque_id,
    require_sha256,
)


BOOTSTRAP_MANIFEST_VERSION = "sft_bootstrap_authority_v1"
TRAIN_CATALOG_MANIFEST_VERSION = "sft_train_catalog_v1"
SOURCE_AUTHORITY_MANIFEST_VERSION = "sft_source_authority_v1"

AuthorityKind = Literal["host_pinned", "synthetic_fixture"]
AuthorityKeyRole = Literal[
    "source_manifest_signer",
    "anchor_freeze_ledger",
    "phase_registry",
    "factor_bank",
    "anchor_native_recount",
]

AUTHORITY_KEY_ROLES: tuple[str, ...] = (
    "anchor_freeze_ledger",
    "anchor_native_recount",
    "factor_bank",
    "phase_registry",
    "source_manifest_signer",
)
REQUIRED_AUTHORITY_CODE_SOURCES = frozenset(
    {
        "anchor_freeze_ledger",
        "anchor_native_recount",
        "dataset_adapter",
        "factor_bank",
        "phase_full_factor_v3_binder",
        "phase_registry",
        "provision",
        "source_authority_issuer",
        "structural_anchor_builder",
        "train_catalog_loader",
    }
)

_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CAPABILITY_MINT_TOKEN = object()


def authority_key_commitment(*, role: str, key: bytes) -> str:
    """Return the domain-separated public commitment for one authority key."""

    if role not in AUTHORITY_KEY_ROLES:
        raise ValueError("unknown bootstrap authority key role")
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("bootstrap authority keys must contain at least 32 bytes")
    return hashlib.sha256(
        b"sft-bootstrap-authority-key-v1\0"
        + role.encode("ascii")
        + b"\0"
        + key
    ).hexdigest()


def authority_root_commitment(path_value: str | Path) -> str:
    """Commit to the exact absolute authority root without publishing the path."""

    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("bootstrap authority root must be absolute")
    return canonical_sha256(
        {
            "domain": "sft-bootstrap-authority-root-v1",
            "absolute_path": os.path.normpath(str(path)),
        }
    )


class PilotAuthorityKeyCommitmentV1(ClosedPilotModel):
    role: AuthorityKeyRole
    key_commitment_sha256: str

    @field_validator("key_commitment_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return require_sha256(value, field_name="key_commitment_sha256")


class PilotBootstrapAuthorityManifestV1(ClosedPilotModel):
    manifest_version: Literal[BOOTSTRAP_MANIFEST_VERSION] = BOOTSTRAP_MANIFEST_VERSION
    authority_kind: AuthorityKind
    bootstrap_id: str
    fixed_git_commit: str
    dataset_release_manifest_sha256: str
    dataset_split_manifest_sha256: str
    train_partition: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    train_loader_policy_sha256: str
    namespace_template_sha256: str
    anchor_freeze_dir_commitment_sha256: str
    authority_code_sources: tuple[PilotCodeSourceV1, ...]
    authority_key_commitments: tuple[PilotAuthorityKeyCommitmentV1, ...]

    @field_validator("bootstrap_id")
    @classmethod
    def validate_bootstrap_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="bootstrap_id")

    @field_validator("fixed_git_commit")
    @classmethod
    def validate_fixed_commit(cls, value: str) -> str:
        if not _GIT_COMMIT_RE.fullmatch(value):
            raise ValueError("fixed_git_commit must be a full lowercase Git commit")
        return value

    @field_validator(
        "dataset_release_manifest_sha256",
        "dataset_split_manifest_sha256",
        "train_loader_policy_sha256",
        "namespace_template_sha256",
        "anchor_freeze_dir_commitment_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_closed_authority(self) -> "PilotBootstrapAuthorityManifestV1":
        code_ids = tuple(item.source_id for item in self.authority_code_sources)
        if len(set(code_ids)) != len(code_ids):
            raise ValueError("authority code source ids must be unique")
        if tuple(sorted(code_ids)) != code_ids:
            raise ValueError("authority code sources must use canonical source-id order")
        if not REQUIRED_AUTHORITY_CODE_SOURCES.issubset(code_ids):
            missing = sorted(REQUIRED_AUTHORITY_CODE_SOURCES.difference(code_ids))
            raise ValueError(f"authority code pins are incomplete: {missing}")

        key_roles = tuple(item.role for item in self.authority_key_commitments)
        if key_roles != AUTHORITY_KEY_ROLES:
            raise ValueError("authority key roles must be complete, unique, and canonical")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotDatasetReleaseEntryV1(ClosedPilotModel):
    case_id: str
    unit_commitment: str
    input_commitment_sha256: str

    @field_validator("case_id", "unit_commitment")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("input_commitment_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return require_sha256(value, field_name="input_commitment_sha256")


class PilotDatasetReleaseManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_dataset_release_v1"] = "sft_dataset_release_v1"
    dataset_release_id: str
    entries: tuple[PilotDatasetReleaseEntryV1, ...]

    @field_validator("dataset_release_id")
    @classmethod
    def validate_release_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="dataset_release_id")

    @model_validator(mode="after")
    def validate_entries(self) -> "PilotDatasetReleaseManifestV1":
        if not self.entries:
            raise ValueError("dataset release manifest cannot be empty")
        case_ids = tuple(item.case_id for item in self.entries)
        units = tuple(item.unit_commitment for item in self.entries)
        inputs = tuple(item.input_commitment_sha256 for item in self.entries)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("dataset release case ids must be unique")
        if len(set(units)) != len(units):
            raise ValueError("dataset release unit commitments must be unique")
        if len(set(inputs)) != len(inputs):
            raise ValueError("dataset release input commitments must be unique")
        if tuple(sorted(case_ids)) != case_ids:
            raise ValueError("dataset release entries must use canonical case-id order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotDatasetSplitEntryV1(ClosedPilotModel):
    case_id: str
    split: Literal["TRAIN_UPDATE", "FINAL_VAL"]

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="case_id")


class PilotDatasetSplitManifestV1(ClosedPilotModel):
    manifest_version: Literal["sft_dataset_split_v1"] = "sft_dataset_split_v1"
    dataset_release_id: str
    entries: tuple[PilotDatasetSplitEntryV1, ...]

    @field_validator("dataset_release_id")
    @classmethod
    def validate_release_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="dataset_release_id")

    @model_validator(mode="after")
    def validate_entries(self) -> "PilotDatasetSplitManifestV1":
        if not self.entries:
            raise ValueError("dataset split manifest cannot be empty")
        case_ids = tuple(item.case_id for item in self.entries)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("dataset split case ids must be unique")
        if tuple(sorted(case_ids)) != case_ids:
            raise ValueError("dataset split entries must use canonical case-id order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotTrainCatalogEntryV1(ClosedPilotModel):
    case_id: str
    unit_commitment: str
    input_commitment_sha256: str
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"

    @field_validator("case_id", "unit_commitment")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator("input_commitment_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return require_sha256(value, field_name="input_commitment_sha256")


class PilotTrainCatalogManifestV1(ClosedPilotModel):
    manifest_version: Literal[TRAIN_CATALOG_MANIFEST_VERSION] = (
        TRAIN_CATALOG_MANIFEST_VERSION
    )
    dataset_release_manifest_sha256: str
    dataset_split_manifest_sha256: str
    entries: tuple[PilotTrainCatalogEntryV1, ...]

    @field_validator(
        "dataset_release_manifest_sha256", "dataset_split_manifest_sha256"
    )
    @classmethod
    def validate_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_entries(self) -> "PilotTrainCatalogManifestV1":
        if not self.entries:
            raise ValueError("TRAIN catalog cannot be empty")
        case_ids = tuple(item.case_id for item in self.entries)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("TRAIN catalog case ids must be unique")
        if tuple(sorted(case_ids)) != case_ids:
            raise ValueError("TRAIN catalog must use canonical case-id order")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotSourceAuthorityManifestV1(ClosedPilotModel):
    manifest_version: Literal[SOURCE_AUTHORITY_MANIFEST_VERSION] = (
        SOURCE_AUTHORITY_MANIFEST_VERSION
    )
    authority_kind: Literal["host_pinned"] = "host_pinned"
    bootstrap_authority_manifest_sha256: str
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"
    train_catalog_manifest_sha256: str
    source_policy_sha256: str
    dataset_release_manifest_sha256: str
    dataset_split_manifest_sha256: str
    train_case_count: int
    source_authority_key_commitment_sha256: str
    source_loader_code_sha256: str
    attestation_sha256: str

    @field_validator(
        "bootstrap_authority_manifest_sha256",
        "train_catalog_manifest_sha256",
        "source_policy_sha256",
        "dataset_release_manifest_sha256",
        "dataset_split_manifest_sha256",
        "source_authority_key_commitment_sha256",
        "source_loader_code_sha256",
        "attestation_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("train_case_count")
    @classmethod
    def validate_count(cls, value: int) -> int:
        if value < 1 or value > 1_000_000:
            raise ValueError("train_case_count is outside the frozen pilot bound")
        return value

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class _NonSerializableCapability:
    __slots__ = ()

    def __copy__(self) -> None:
        raise TypeError("authority capabilities cannot be copied")

    def __deepcopy__(self, _memo: object) -> None:
        raise TypeError("authority capabilities cannot be copied")

    def __reduce__(self) -> None:
        raise TypeError("authority capabilities cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> None:
        raise TypeError("authority capabilities cannot be serialized")


class BootstrapAuthorityBundle(_NonSerializableCapability):
    """Verified host authority; raw keys have no public accessor."""

    __slots__ = ("__manifest", "__keys", "__mint_identity")

    def __init__(
        self,
        *,
        _mint_token: object,
        manifest: PilotBootstrapAuthorityManifestV1,
        keys: Mapping[str, bytes],
    ) -> None:
        if _mint_token is not _CAPABILITY_MINT_TOKEN:
            raise TypeError("BootstrapAuthorityBundle has no public constructor")
        object.__setattr__(self, "_BootstrapAuthorityBundle__manifest", manifest)
        object.__setattr__(
            self,
            "_BootstrapAuthorityBundle__keys",
            {role: bytes(value) for role, value in keys.items()},
        )
        object.__setattr__(
            self, "_BootstrapAuthorityBundle__mint_identity", object()
        )

    @property
    def manifest(self) -> PilotBootstrapAuthorityManifestV1:
        return self.__manifest

    @property
    def manifest_sha256(self) -> str:
        return self.__manifest.digest

    def __repr__(self) -> str:
        return f"BootstrapAuthorityBundle(manifest_sha256={self.manifest_sha256!r})"

    def _authority_hmac(self, *, role: str, domain: str, value: Any) -> str:
        try:
            key = self.__keys[role]
        except KeyError as exc:
            raise ValueError("authority key role was not verified") from exc
        return pilot_hmac_sha256(key, domain=domain, value=value)

    def _authority_key_commitment(self, role: str) -> str:
        try:
            key = self.__keys[role]
        except KeyError as exc:
            raise ValueError("authority key role was not verified") from exc
        return authority_key_commitment(role=role, key=key)

    def _mint_identity_is(self, identity: object) -> bool:
        return identity is self.__mint_identity

    def _mint_identity(self) -> object:
        return self.__mint_identity


class VerifiedDatasetTrainSnapshotCapability(_NonSerializableCapability):
    """Opaque exact release/split join; it contains commitments, never rows."""

    __slots__ = ("__mint_identity", "__catalog")

    def __init__(
        self,
        *,
        _mint_token: object,
        mint_identity: object,
        catalog: PilotTrainCatalogManifestV1,
    ) -> None:
        if _mint_token is not _CAPABILITY_MINT_TOKEN:
            raise TypeError("verified TRAIN snapshots have no public constructor")
        object.__setattr__(
            self,
            "_VerifiedDatasetTrainSnapshotCapability__mint_identity",
            mint_identity,
        )
        object.__setattr__(
            self, "_VerifiedDatasetTrainSnapshotCapability__catalog", catalog
        )

    def _open_for(self, authority: BootstrapAuthorityBundle) -> PilotTrainCatalogManifestV1:
        if not authority._mint_identity_is(self.__mint_identity):
            raise ValueError("TRAIN snapshot belongs to a different bootstrap authority")
        return self.__catalog


class VerifiedTrainSourceCapability(_NonSerializableCapability):
    """Opaque signed TRAIN source authorization consumed by later anchor code."""

    __slots__ = ("__mint_identity", "__manifest", "__catalog")

    def __init__(
        self,
        *,
        _mint_token: object,
        mint_identity: object,
        manifest: PilotSourceAuthorityManifestV1,
        catalog: PilotTrainCatalogManifestV1,
    ) -> None:
        if _mint_token is not _CAPABILITY_MINT_TOKEN:
            raise TypeError("verified TRAIN source capabilities have no public constructor")
        object.__setattr__(
            self, "_VerifiedTrainSourceCapability__mint_identity", mint_identity
        )
        object.__setattr__(
            self, "_VerifiedTrainSourceCapability__manifest", manifest
        )
        object.__setattr__(self, "_VerifiedTrainSourceCapability__catalog", catalog)

    @property
    def manifest(self) -> PilotSourceAuthorityManifestV1:
        return self.__manifest

    @property
    def manifest_sha256(self) -> str:
        return self.__manifest.digest

    @property
    def train_catalog_manifest(self) -> PilotTrainCatalogManifestV1:
        return self.__catalog

    def __repr__(self) -> str:
        return f"VerifiedTrainSourceCapability(manifest_sha256={self.manifest_sha256!r})"

    def _open_for(
        self, authority: BootstrapAuthorityBundle
    ) -> tuple[PilotSourceAuthorityManifestV1, PilotTrainCatalogManifestV1]:
        if not authority._mint_identity_is(self.__mint_identity):
            raise ValueError("source capability belongs to a different bootstrap authority")
        verify_source_authority_manifest(
            authority=authority,
            manifest=self.__manifest,
            train_catalog=self.__catalog,
        )
        return self.__manifest, self.__catalog


HostKeyProvider = Callable[[str], bytes]


def _stable_file_sha256(path_value: str | Path) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("authority code source paths must be absolute")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("authority code source cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError("authority code source must be a stable regular file")
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        return digest.hexdigest()
    finally:
        os.close(fd)


def load_bootstrap_authority(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    expected_fixed_git_commit: str,
    authority_root: str | Path,
    code_source_paths: Mapping[str, str | Path],
    key_provider: HostKeyProvider,
) -> BootstrapAuthorityBundle:
    """Verify an externally pinned real bootstrap manifest and host material."""

    require_sha256(expected_manifest_sha256, field_name="expected_manifest_sha256")
    if not _GIT_COMMIT_RE.fullmatch(expected_fixed_git_commit):
        raise ValueError("expected_fixed_git_commit must be a full lowercase Git commit")
    manifest = load_frozen_manifest(
        manifest_path,
        model_type=PilotBootstrapAuthorityManifestV1,
        expected_sha256=expected_manifest_sha256,
    )
    if manifest.authority_kind != "host_pinned":
        raise ValueError("real bootstrap path rejects synthetic fixture authority")
    if not hmac.compare_digest(manifest.fixed_git_commit, expected_fixed_git_commit):
        raise ValueError("running Git commit differs from the preregistered authority")
    root_commitment = authority_root_commitment(authority_root)
    if not hmac.compare_digest(
        manifest.anchor_freeze_dir_commitment_sha256, root_commitment
    ):
        raise ValueError("authority root differs from its preregistered commitment")

    expected_code_ids = tuple(item.source_id for item in manifest.authority_code_sources)
    if set(code_source_paths) != set(expected_code_ids):
        raise ValueError("host authority code path set differs from the manifest")
    for source in manifest.authority_code_sources:
        observed = _stable_file_sha256(code_source_paths[source.source_id])
        if not hmac.compare_digest(observed, source.sha256):
            raise ValueError(f"authority code pin mismatch: {source.source_id}")

    keys: dict[str, bytes] = {}
    for commitment in manifest.authority_key_commitments:
        try:
            key = key_provider(commitment.role)
        except BaseException as exc:
            raise ValueError("host key provider did not supply every authority role") from exc
        observed = authority_key_commitment(role=commitment.role, key=key)
        if not hmac.compare_digest(observed, commitment.key_commitment_sha256):
            raise ValueError(f"authority key commitment mismatch: {commitment.role}")
        keys[commitment.role] = bytes(key)
    return BootstrapAuthorityBundle(
        _mint_token=_CAPABILITY_MINT_TOKEN,
        manifest=manifest,
        keys=keys,
    )


def load_train_catalog(
    authority: BootstrapAuthorityBundle,
    *,
    dataset_release_manifest_path: str | Path,
    dataset_split_manifest_path: str | Path,
) -> VerifiedDatasetTrainSnapshotCapability:
    """Load the exact pinned TRAIN projection; the split is never caller-chosen."""

    if not isinstance(authority, BootstrapAuthorityBundle):
        raise TypeError("a verified bootstrap authority is required")
    bootstrap = authority.manifest
    release = load_frozen_manifest(
        dataset_release_manifest_path,
        model_type=PilotDatasetReleaseManifestV1,
        expected_sha256=bootstrap.dataset_release_manifest_sha256,
    )
    split = load_frozen_manifest(
        dataset_split_manifest_path,
        model_type=PilotDatasetSplitManifestV1,
        expected_sha256=bootstrap.dataset_split_manifest_sha256,
    )
    if release.dataset_release_id != split.dataset_release_id:
        raise ValueError("release and split manifests name different dataset releases")
    release_ids = tuple(item.case_id for item in release.entries)
    split_ids = tuple(item.case_id for item in split.entries)
    if release_ids != split_ids:
        missing = sorted(set(release_ids).difference(split_ids))
        unknown = sorted(set(split_ids).difference(release_ids))
        raise ValueError(
            f"split membership does not close the release: missing={missing}, unknown={unknown}"
        )
    if any(item.split != "TRAIN_UPDATE" for item in split.entries):
        raise ValueError("TRAIN authority rejects FINAL_VAL or non-TRAIN members")

    catalog = PilotTrainCatalogManifestV1(
        dataset_release_manifest_sha256=release.digest,
        dataset_split_manifest_sha256=split.digest,
        entries=tuple(
            PilotTrainCatalogEntryV1(
                case_id=item.case_id,
                unit_commitment=item.unit_commitment,
                input_commitment_sha256=item.input_commitment_sha256,
            )
            for item in release.entries
        ),
    )
    return VerifiedDatasetTrainSnapshotCapability(
        _mint_token=_CAPABILITY_MINT_TOKEN,
        mint_identity=authority._mint_identity(),
        catalog=catalog,
    )


def _source_attestation_body(
    manifest: PilotSourceAuthorityManifestV1 | Mapping[str, Any]
) -> dict[str, Any]:
    if isinstance(manifest, PilotSourceAuthorityManifestV1):
        payload = manifest.model_dump(mode="json")
    else:
        payload = dict(manifest)
    payload.pop("attestation_sha256", None)
    return payload


def issue_source_authority(
    authority: BootstrapAuthorityBundle,
    verified_train_snapshot: VerifiedDatasetTrainSnapshotCapability,
) -> VerifiedTrainSourceCapability:
    """Sign the internally derived TRAIN catalog using the pinned host key."""

    if not isinstance(authority, BootstrapAuthorityBundle):
        raise TypeError("a verified bootstrap authority is required")
    if not isinstance(
        verified_train_snapshot, VerifiedDatasetTrainSnapshotCapability
    ):
        raise TypeError("a verified TRAIN snapshot capability is required")
    catalog = verified_train_snapshot._open_for(authority)
    bootstrap = authority.manifest
    key_commitment = authority._authority_key_commitment("source_manifest_signer")
    loader_source = next(
        item
        for item in bootstrap.authority_code_sources
        if item.source_id == "train_catalog_loader"
    )
    unsigned: dict[str, Any] = {
        "manifest_version": SOURCE_AUTHORITY_MANIFEST_VERSION,
        "authority_kind": "host_pinned",
        "bootstrap_authority_manifest_sha256": bootstrap.digest,
        "split": "TRAIN_UPDATE",
        "train_catalog_manifest_sha256": catalog.digest,
        "source_policy_sha256": bootstrap.train_loader_policy_sha256,
        "dataset_release_manifest_sha256": catalog.dataset_release_manifest_sha256,
        "dataset_split_manifest_sha256": catalog.dataset_split_manifest_sha256,
        "train_case_count": len(catalog.entries),
        "source_authority_key_commitment_sha256": key_commitment,
        "source_loader_code_sha256": loader_source.sha256,
    }
    attestation = authority._authority_hmac(
        role="source_manifest_signer",
        domain="sft-source-authority-manifest-v1",
        value=unsigned,
    )
    manifest = PilotSourceAuthorityManifestV1(
        **unsigned,
        attestation_sha256=attestation,
    )
    verify_source_authority_manifest(
        authority=authority,
        manifest=manifest,
        train_catalog=catalog,
    )
    return VerifiedTrainSourceCapability(
        _mint_token=_CAPABILITY_MINT_TOKEN,
        mint_identity=authority._mint_identity(),
        manifest=manifest,
        catalog=catalog,
    )


def verify_source_authority_manifest(
    *,
    authority: BootstrapAuthorityBundle,
    manifest: PilotSourceAuthorityManifestV1,
    train_catalog: PilotTrainCatalogManifestV1,
) -> None:
    """Re-verify every source binding before a capability is consumed."""

    bootstrap = authority.manifest
    loader_sha = next(
        item.sha256
        for item in bootstrap.authority_code_sources
        if item.source_id == "train_catalog_loader"
    )
    expected_key_commitment = authority._authority_key_commitment(
        "source_manifest_signer"
    )
    exact = {
        "bootstrap_authority_manifest_sha256": bootstrap.digest,
        "train_catalog_manifest_sha256": train_catalog.digest,
        "source_policy_sha256": bootstrap.train_loader_policy_sha256,
        "dataset_release_manifest_sha256": bootstrap.dataset_release_manifest_sha256,
        "dataset_split_manifest_sha256": bootstrap.dataset_split_manifest_sha256,
        "train_case_count": len(train_catalog.entries),
        "source_authority_key_commitment_sha256": expected_key_commitment,
        "source_loader_code_sha256": loader_sha,
    }
    for field_name, expected in exact.items():
        observed = getattr(manifest, field_name)
        if observed != expected:
            raise ValueError(f"source authority binding mismatch: {field_name}")
    expected_attestation = authority._authority_hmac(
        role="source_manifest_signer",
        domain="sft-source-authority-manifest-v1",
        value=_source_attestation_body(manifest),
    )
    if not hmac.compare_digest(manifest.attestation_sha256, expected_attestation):
        raise ValueError("source authority attestation mismatch")


__all__ = [
    "AUTHORITY_KEY_ROLES",
    "REQUIRED_AUTHORITY_CODE_SOURCES",
    "BootstrapAuthorityBundle",
    "PilotAuthorityKeyCommitmentV1",
    "PilotBootstrapAuthorityManifestV1",
    "PilotDatasetReleaseEntryV1",
    "PilotDatasetReleaseManifestV1",
    "PilotDatasetSplitEntryV1",
    "PilotDatasetSplitManifestV1",
    "PilotSourceAuthorityManifestV1",
    "PilotTrainCatalogEntryV1",
    "PilotTrainCatalogManifestV1",
    "VerifiedDatasetTrainSnapshotCapability",
    "VerifiedTrainSourceCapability",
    "authority_key_commitment",
    "authority_root_commitment",
    "issue_source_authority",
    "load_bootstrap_authority",
    "load_train_catalog",
    "verify_source_authority_manifest",
]
