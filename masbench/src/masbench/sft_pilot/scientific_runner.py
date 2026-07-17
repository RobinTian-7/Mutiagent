"""Orchestration entry for the ``phase_v5_executable_sft`` profile.

v5 is the only SFT profile that may ever spend scientific model calls, so this
module is fail-closed by construction: every frozen input (protocol,
experiment seal, both authority manifests) must exist as a stable non-symlink
regular file before anything else happens, the store must already be
provisioned by the external provision command, and any gap raises before a
state directory, result directory, or model call can be created.  The module
never implements Bank/Registry/store internals — it only sequences their
authorities.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from masbench.core.config import RunConfig
from masbench.sft_phase_pilot import (
    _decode_master_key,
    _derive_key,
    _load_frozen_protocol,
    _validate_v4_protocol,
)
from masbench.sft_pilot.schema import PilotProtocolV1
from masbench.sft_pilot.store import DATABASE_FILENAME

V5_PROFILE = "phase_v5_executable_sft"
_MAX_FROZEN_INPUT_BYTES = 8 * 1024 * 1024

# v5 key-derivation law.  Domains are distinct from every v3/v4 domain so a
# v5 experiment can never silently reopen (or be reopened by) an older
# profile's authenticated state.
V5_STORE_KEY_DOMAIN = b"pilot-store-v5"
V5_PHASE_KEY_DOMAIN = b"phase-registry-v5"
V5_FACTOR_KEY_DOMAIN = b"factor-bank-v5"
V5_SOURCE_AUTHORITY_KEY_DOMAIN = b"source-authority-v5"


def derive_v5_component_keys(master: bytes) -> dict[str, bytes]:
    """Derive the four v5 state keys from the host master key."""

    return {
        "store": _derive_key(master, V5_STORE_KEY_DOMAIN),
        "phase_registry": _derive_key(master, V5_PHASE_KEY_DOMAIN),
        "factor_bank": _derive_key(master, V5_FACTOR_KEY_DOMAIN),
        "source_authority": _derive_key(master, V5_SOURCE_AUTHORITY_KEY_DOMAIN),
    }


def derive_v5_runtime_role_key(master: bytes, role: str) -> bytes:
    """Derive one runtime authority role key under a role-separated domain."""

    return _derive_key(master, b"runtime-role-v5:" + role.encode("ascii"))


def derive_v5_bootstrap_role_key(master: bytes, role: str) -> bytes:
    """Derive one bootstrap authority role key under a role-separated domain."""

    return _derive_key(master, b"bootstrap-role-v5:" + role.encode("ascii"))


def _read_frozen_input(path_value: str | None, *, description: str) -> bytes:
    """Read one externally frozen input without following a symlink.

    The same physical law as the v4 protocol loader: absolute path, O_NOFOLLOW
    open, stable dev/ino between descriptor and lstat, bounded byte length.
    A replaceable symlink or FIFO must never become experiment authority.
    """

    if not path_value:
        raise ValueError(f"{description} requires a configured path")
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{description} requires an absolute path")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{description} cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError(
                f"{description} must be a stable non-symlink regular file"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(_MAX_FROZEN_INPUT_BYTES + 1)
    finally:
        os.close(fd)
    if not payload or len(payload) > _MAX_FROZEN_INPUT_BYTES:
        raise ValueError(f"{description} has an invalid byte length")
    return payload


def _validate_v5_protocol(
    protocol: PilotProtocolV1,
    cfg: RunConfig,
    *,
    agent_counts: list[int] | None,
) -> None:
    """Close the frozen protocol over the v5 run configuration.

    The namespace/model/budget closure law is shared with v4; v5 additionally
    demands the recoverable-execution surface: an exact component bundle,
    the checkpoint saga, and a store-derived execution schedule.
    """

    _validate_v4_protocol(protocol, cfg, agent_counts=agent_counts)
    missing = [
        name
        for name, enabled in (
            ("component_checkpoint_saga_required", protocol.component_checkpoint_saga_required),
            ("store_derived_schedule_required", protocol.store_derived_schedule_required),
        )
        if not enabled
    ]
    if missing:
        raise ValueError(
            "phase_v5 requires a recoverable protocol: " + ", ".join(missing)
        )


def run_phase_v5_executable_sft(
    cfg: RunConfig,
    *,
    agent_counts: list[int] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Fail-closed v5 entry: verify every authority before any effect."""

    if cfg.sft_profile != V5_PROFILE:
        raise ValueError(f"unsupported v5 dispatch for profile {cfg.sft_profile!r}")
    if workers != 1:
        raise ValueError(
            "phase_v5_executable_sft requires workers=1 for single-writer authority"
        )
    _decode_master_key()  # fail before touching any path

    # Physical closure of every externally frozen input, before semantics.
    _read_frozen_input(
        cfg.sft_protocol_path, description="frozen SFT protocol"
    )
    _read_frozen_input(
        cfg.sft_experiment_manifest_path,
        description="frozen SFT experiment manifest",
    )
    _read_frozen_input(
        cfg.sft_runtime_authority_path,
        description="frozen SFT runtime authority manifest",
    )
    _read_frozen_input(
        cfg.sft_bootstrap_authority_path,
        description="frozen SFT bootstrap authority manifest",
    )

    protocol = _load_frozen_protocol(cfg.sft_protocol_path)
    _validate_v5_protocol(protocol, cfg, agent_counts=agent_counts)

    # Seal closure: the experiment root must bind this exact protocol and
    # both frozen authority manifests before the store may even be opened.
    from masbench.sft_pilot.experiment import (
        load_experiment_seal,
        load_sealed_authority_manifests,
        validate_experiment_seal,
    )

    seal = load_experiment_seal(str(cfg.sft_experiment_manifest_path))
    runtime_authority, bootstrap_authority = load_sealed_authority_manifests(
        seal,
        runtime_authority_path=str(cfg.sft_runtime_authority_path),
        bootstrap_authority_path=str(cfg.sft_bootstrap_authority_path),
    )
    validate_experiment_seal(
        seal,
        runtime_authority=runtime_authority,
        bootstrap_authority=bootstrap_authority,
        protocol=protocol,
    )

    state_root = Path(str(cfg.sft_state_dir))
    database_path = state_root / DATABASE_FILENAME
    try:
        database_stat = os.lstat(database_path)
    except OSError as exc:
        raise RuntimeError(
            "phase_v5 requires a pre-provisioned experiment pilot store"
        ) from exc
    if not stat.S_ISREG(database_stat.st_mode):
        raise RuntimeError(
            "phase_v5 pilot database must be a non-symlink regular file"
        )

    raise RuntimeError(
        "phase_v5_executable_sft is fail-closed: the scientific execution "
        "loop is not authorized in this build"
    )


__all__ = ["V5_PROFILE", "run_phase_v5_executable_sft"]
