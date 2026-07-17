"""Pinned runtime roles for the default-off SFT pilot.

The earlier pilot codecs accepted caller-supplied HMAC keys.  Those keys can
detect accidental byte corruption, but they cannot establish which engine,
renderer, scorer, or pair consumer was preregistered.  This module narrows the
trust root to one exact manifest whose digest is supplied externally before a
scientific run.  The loader verifies the fixed Git commit, code bytes, state
root, complete role set, and every host key commitment before minting opaque
process-local capabilities.

Capabilities are an authority API boundary, not a hostile in-process Python
sandbox.  Raw keys have no public accessor and each role is restricted to its
frozen domains.  Later runtime/scorer modules consume the role capabilities;
workers and proposal code must never receive the aggregate bundle.
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

from masbench.sft_pilot.manifests import PilotCodeSourceV1, load_frozen_manifest
from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    canonical_sha256,
    pilot_hmac_sha256,
    require_opaque_id,
    require_sha256,
)


RUNTIME_AUTHORITY_MANIFEST_VERSION = "sft_runtime_authority_v1"
RuntimeAuthorityKind = Literal["host_pinned", "synthetic_fixture"]
RuntimeAuthorityRole = Literal[
    "exact_phase_engine",
    "factor_pair_adapter",
    "journal_reader",
    "journal_writer",
    "pair_consumer",
    "request_renderer",
    "result_ledger",
    "train_scorer",
]

RUNTIME_AUTHORITY_ROLES: tuple[str, ...] = (
    "exact_phase_engine",
    "factor_pair_adapter",
    "journal_reader",
    "journal_writer",
    "pair_consumer",
    "request_renderer",
    "result_ledger",
    "train_scorer",
)

RUNTIME_ROLE_DOMAINS: Mapping[str, tuple[str, ...]] = {
    "exact_phase_engine": (
        "sft-exact-phase-runtime-terminal-v1",
        "sft-execution-attestation-v2",
    ),
    "factor_pair_adapter": ("sft-factor-pair-import-v1",),
    "journal_reader": ("sft-journal-checkpoint-v3",),
    "journal_writer": ("sft-journal-event-v3",),
    "pair_consumer": ("sft-pair-consume-v1",),
    "request_renderer": ("sft-rendered-request-v1",),
    "result_ledger": ("sft-result-ledger-row-v1",),
    "train_scorer": ("sft-train-outcome-v2",),
}

REQUIRED_RUNTIME_CODE_SOURCES = frozenset(
    {
        "exact_phase_runtime",
        "factor_pair_adapter",
        "phase_full_factor_v3_binder",
        "phase_registry",
        "pilot_metered_llm_client",
        "pilot_single_writer_store",
        "protocol_runner",
        "request_renderer",
        "result_ledger",
        "sft_journal",
        "single_use_pair_consumer",
        "train_scalar_evaluator",
    }
)

_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CAPABILITY_MINT_TOKEN = object()


def runtime_authority_key_commitment(*, role: str, key: bytes) -> str:
    """Commit to one host key under a role-specific domain."""

    if role not in RUNTIME_AUTHORITY_ROLES:
        raise ValueError("unknown runtime authority role")
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("runtime authority keys must contain at least 32 bytes")
    return hashlib.sha256(
        b"sft-runtime-authority-key-v1\0"
        + role.encode("ascii")
        + b"\0"
        + key
    ).hexdigest()


def runtime_authority_root_commitment(path_value: str | Path) -> str:
    """Commit to the absolute authority state root without publishing it."""

    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("runtime authority root must be absolute")
    return canonical_sha256(
        {
            "domain": "sft-runtime-authority-root-v1",
            "absolute_path": os.path.normpath(str(path)),
        }
    )


class PilotRuntimeRoleCommitmentV1(ClosedPilotModel):
    role: RuntimeAuthorityRole
    allowed_domains: tuple[str, ...]
    key_commitment_sha256: str

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or tuple(sorted(set(value))) != value:
            raise ValueError("runtime role domains must be non-empty and canonical")
        for domain in value:
            require_opaque_id(domain, field_name="allowed_domains")
        return value

    @field_validator("key_commitment_sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        return require_sha256(value, field_name="key_commitment_sha256")


class PilotRuntimeAuthorityManifestV1(ClosedPilotModel):
    """Pre-registered identity of every evidence-producing runtime role."""

    manifest_version: Literal[RUNTIME_AUTHORITY_MANIFEST_VERSION] = (
        RUNTIME_AUTHORITY_MANIFEST_VERSION
    )
    authority_kind: RuntimeAuthorityKind
    runtime_authority_id: str
    fixed_git_commit: str
    bootstrap_authority_manifest_sha256: str
    source_authority_manifest_sha256: str
    runner_manifest_sha256: str
    execution_schedule_sha256: str
    method_policy_sha256: str
    authority_root_commitment_sha256: str
    model_name: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    temperature: Literal[0.0] = 0.0
    sdk_max_retries: Literal[0] = 0
    application_max_retries: Literal[0] = 0
    planner_mode: Literal["program_generate"] = "program_generate"
    payload_format: Literal["phase_program_skill_v1"] = "phase_program_skill_v1"
    worker_contract: Literal["not_applicable"] = "not_applicable"
    authority_code_sources: tuple[PilotCodeSourceV1, ...]
    role_commitments: tuple[PilotRuntimeRoleCommitmentV1, ...]

    @field_validator("runtime_authority_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="runtime_authority_id")

    @field_validator("fixed_git_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if not _GIT_COMMIT_RE.fullmatch(value):
            raise ValueError("fixed_git_commit must be a full lowercase Git commit")
        return value

    @field_validator(
        "bootstrap_authority_manifest_sha256",
        "source_authority_manifest_sha256",
        "runner_manifest_sha256",
        "execution_schedule_sha256",
        "method_policy_sha256",
        "authority_root_commitment_sha256",
    )
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_closed_role_graph(self) -> "PilotRuntimeAuthorityManifestV1":
        source_ids = tuple(item.source_id for item in self.authority_code_sources)
        if tuple(sorted(set(source_ids))) != source_ids:
            raise ValueError("runtime code sources must be unique and canonical")
        if not REQUIRED_RUNTIME_CODE_SOURCES.issubset(source_ids):
            missing = sorted(REQUIRED_RUNTIME_CODE_SOURCES.difference(source_ids))
            raise ValueError(f"runtime authority code pins are incomplete: {missing}")

        roles = tuple(item.role for item in self.role_commitments)
        if roles != RUNTIME_AUTHORITY_ROLES:
            raise ValueError("runtime roles must be complete, unique, and canonical")
        for commitment in self.role_commitments:
            if commitment.allowed_domains != RUNTIME_ROLE_DOMAINS[commitment.role]:
                raise ValueError(
                    f"runtime domains differ from the closed role law: {commitment.role}"
                )
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class _NonSerializableCapability:
    __slots__ = ()

    def __copy__(self) -> None:
        raise TypeError("runtime authority capabilities cannot be copied")

    def __deepcopy__(self, _memo: object) -> None:
        raise TypeError("runtime authority capabilities cannot be copied")

    def __reduce__(self) -> None:
        raise TypeError("runtime authority capabilities cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> None:
        raise TypeError("runtime authority capabilities cannot be serialized")


class RuntimeRoleCapability(_NonSerializableCapability):
    """One role-scoped signer; construction and domains are host-owned."""

    __slots__ = (
        "__authority_identity",
        "__key",
        "__manifest_sha256",
        "__role",
    )

    def __init__(
        self,
        *,
        _mint_token: object,
        authority_identity: object,
        manifest_sha256: str,
        role: str,
        key: bytes,
    ) -> None:
        if _mint_token is not _CAPABILITY_MINT_TOKEN:
            raise TypeError("RuntimeRoleCapability has no public constructor")
        object.__setattr__(self, "_RuntimeRoleCapability__authority_identity", authority_identity)
        object.__setattr__(self, "_RuntimeRoleCapability__manifest_sha256", manifest_sha256)
        object.__setattr__(self, "_RuntimeRoleCapability__role", role)
        object.__setattr__(self, "_RuntimeRoleCapability__key", bytes(key))

    @property
    def manifest_sha256(self) -> str:
        return self.__manifest_sha256

    @property
    def role(self) -> str:
        return self.__role

    @property
    def key_commitment_sha256(self) -> str:
        return runtime_authority_key_commitment(role=self.__role, key=self.__key)

    def __repr__(self) -> str:
        return (
            "RuntimeRoleCapability("
            f"role={self.role!r}, manifest_sha256={self.manifest_sha256!r})"
        )

    def _sign(self, *, domain: str, value: Any) -> str:
        if domain not in RUNTIME_ROLE_DOMAINS[self.__role]:
            raise ValueError("runtime role cannot sign outside its frozen domains")
        return pilot_hmac_sha256(self.__key, domain=domain, value=value)

    def _verify(self, *, domain: str, value: Any, signature: str) -> bool:
        require_sha256(signature, field_name="signature")
        return hmac.compare_digest(
            signature, self._sign(domain=domain, value=value)
        )

    def _same_authority(self, identity: object) -> bool:
        return identity is self.__authority_identity


class RuntimeAuthorityBundle(_NonSerializableCapability):
    """Aggregate verified host material retained only by the orchestrator."""

    __slots__ = ("__identity", "__keys", "__manifest")

    def __init__(
        self,
        *,
        _mint_token: object,
        manifest: PilotRuntimeAuthorityManifestV1,
        keys: Mapping[str, bytes],
    ) -> None:
        if _mint_token is not _CAPABILITY_MINT_TOKEN:
            raise TypeError("RuntimeAuthorityBundle has no public constructor")
        object.__setattr__(self, "_RuntimeAuthorityBundle__identity", object())
        object.__setattr__(
            self,
            "_RuntimeAuthorityBundle__keys",
            {role: bytes(value) for role, value in keys.items()},
        )
        object.__setattr__(self, "_RuntimeAuthorityBundle__manifest", manifest)

    @property
    def manifest(self) -> PilotRuntimeAuthorityManifestV1:
        return self.__manifest

    @property
    def manifest_sha256(self) -> str:
        return self.__manifest.digest

    def __repr__(self) -> str:
        return f"RuntimeAuthorityBundle(manifest_sha256={self.manifest_sha256!r})"

    def _mint_all_roles(self) -> tuple[RuntimeRoleCapability, ...]:
        return tuple(
            RuntimeRoleCapability(
                _mint_token=_CAPABILITY_MINT_TOKEN,
                authority_identity=self.__identity,
                manifest_sha256=self.manifest_sha256,
                role=role,
                key=self.__keys[role],
            )
            for role in RUNTIME_AUTHORITY_ROLES
        )


class PilotRuntimeRoleCapabilities(_NonSerializableCapability):
    """Complete role set issued atomically; there is no caller-selected role API."""

    __slots__ = tuple(RUNTIME_AUTHORITY_ROLES) + ("__manifest_sha256",)

    def __init__(
        self,
        *,
        _mint_token: object,
        manifest_sha256: str,
        roles: tuple[RuntimeRoleCapability, ...],
    ) -> None:
        if _mint_token is not _CAPABILITY_MINT_TOKEN:
            raise TypeError("PilotRuntimeRoleCapabilities has no public constructor")
        if tuple(item.role for item in roles) != RUNTIME_AUTHORITY_ROLES:
            raise ValueError("runtime role capability set is incomplete")
        object.__setattr__(
            self,
            "_PilotRuntimeRoleCapabilities__manifest_sha256",
            manifest_sha256,
        )
        for role in roles:
            object.__setattr__(self, role.role, role)

    @property
    def manifest_sha256(self) -> str:
        return self.__manifest_sha256

    def __repr__(self) -> str:
        return (
            "PilotRuntimeRoleCapabilities("
            f"manifest_sha256={self.manifest_sha256!r})"
        )


HostRuntimeKeyProvider = Callable[[str], bytes]


def _stable_file_sha256(path_value: str | Path) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("runtime code source paths must be absolute")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("runtime code source cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError("runtime code source must be a stable regular file")
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        return digest.hexdigest()
    finally:
        os.close(fd)


def load_runtime_authority(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    expected_fixed_git_commit: str,
    authority_root: str | Path,
    code_source_paths: Mapping[str, str | Path],
    key_provider: HostRuntimeKeyProvider,
) -> RuntimeAuthorityBundle:
    """Load only an externally pinned, host-backed runtime authority."""

    require_sha256(expected_manifest_sha256, field_name="expected_manifest_sha256")
    if not _GIT_COMMIT_RE.fullmatch(expected_fixed_git_commit):
        raise ValueError("expected_fixed_git_commit must be a full lowercase Git commit")
    manifest = load_frozen_manifest(
        manifest_path,
        model_type=PilotRuntimeAuthorityManifestV1,
        expected_sha256=expected_manifest_sha256,
    )
    if manifest.authority_kind != "host_pinned":
        raise ValueError("real runtime path rejects synthetic fixture authority")
    if not hmac.compare_digest(manifest.fixed_git_commit, expected_fixed_git_commit):
        raise ValueError("runtime authority Git commit differs from preregistration")
    if not hmac.compare_digest(
        manifest.authority_root_commitment_sha256,
        runtime_authority_root_commitment(authority_root),
    ):
        raise ValueError("runtime authority state root differs from preregistration")

    expected_sources = tuple(
        item.source_id for item in manifest.authority_code_sources
    )
    if set(code_source_paths) != set(expected_sources):
        raise ValueError("runtime code path set differs from the manifest")
    for source in manifest.authority_code_sources:
        observed = _stable_file_sha256(code_source_paths[source.source_id])
        if not hmac.compare_digest(observed, source.sha256):
            raise ValueError(f"runtime authority code pin mismatch: {source.source_id}")

    keys: dict[str, bytes] = {}
    for commitment in manifest.role_commitments:
        try:
            key = key_provider(commitment.role)
        except BaseException as exc:
            raise ValueError("host key provider did not supply every runtime role") from exc
        observed = runtime_authority_key_commitment(
            role=commitment.role, key=key
        )
        if not hmac.compare_digest(observed, commitment.key_commitment_sha256):
            raise ValueError(
                f"runtime authority key commitment mismatch: {commitment.role}"
            )
        keys[commitment.role] = bytes(key)
    return RuntimeAuthorityBundle(
        _mint_token=_CAPABILITY_MINT_TOKEN,
        manifest=manifest,
        keys=keys,
    )


def issue_runtime_role_capabilities(
    authority: RuntimeAuthorityBundle,
) -> PilotRuntimeRoleCapabilities:
    """Mint the complete role set without accepting a caller-selected role."""

    if not isinstance(authority, RuntimeAuthorityBundle):
        raise TypeError("a verified runtime authority is required")
    return PilotRuntimeRoleCapabilities(
        _mint_token=_CAPABILITY_MINT_TOKEN,
        manifest_sha256=authority.manifest_sha256,
        roles=authority._mint_all_roles(),
    )


__all__ = [
    "REQUIRED_RUNTIME_CODE_SOURCES",
    "RUNTIME_AUTHORITY_ROLES",
    "RUNTIME_ROLE_DOMAINS",
    "PilotRuntimeAuthorityManifestV1",
    "PilotRuntimeRoleCapabilities",
    "PilotRuntimeRoleCommitmentV1",
    "RuntimeAuthorityBundle",
    "RuntimeRoleCapability",
    "issue_runtime_role_capabilities",
    "load_runtime_authority",
    "runtime_authority_key_commitment",
    "runtime_authority_root_commitment",
]
