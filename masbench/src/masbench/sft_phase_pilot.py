"""Isolated default-off control plane for the Phase SFT research profiles.

Both opt-in profiles are deliberately mechanics-only.  v3 creates/loads empty
component sidecars; v4 authenticates a frozen protocol and restores the exact
SQLite-owned component generation.  Neither runs a benchmark, LLM, probe, or
gate, so neither is an efficacy experiment.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import stat
from typing import Any

import masbench  # noqa: F401  (bootstraps the sibling exp_graph package)
from exp_graph.mas.factor_bank_v2 import FactorBankV2
from exp_graph.mas.phase_artifact_registry import PhaseArtifactRegistry
from exp_graph.mas.phase_artifact_registry import PHASE_FULL_FACTOR_BINDER_VERSION
from exp_graph.mas.phase_factor_binding_v2 import (
    make_phase_v2_binding_verifier,
    make_phase_v2_proposal_action_terminal_verifier,
    make_phase_v2_repair_opportunity_verifier,
)
from exp_graph.mas.phase_program import PHASE_PROGRAM_COMPILER_VERSION

from masbench.core.config import RunConfig
from masbench.sft_pilot.components import PilotComponentCoordinator
from masbench.sft_pilot.schema import (
    PilotProtocolV1,
    canonical_sha256,
)
from masbench.sft_pilot.store import (
    DATABASE_FILENAME,
    SingleWriterPilotStore,
)


_STATE_KEY_ENV = "MASBENCH_SFT_STATE_KEY"
_V4_PROFILE = "phase_v4_single_writer_preliminary"
_V4_STORE_KEY_DOMAIN = b"pilot-store-v1"
_V4_PHASE_KEY_DOMAIN = b"phase-registry-v8"
_V4_FACTOR_KEY_DOMAIN = b"factor-bank-v14"
_MAX_PROTOCOL_BYTES = 8 * 1024 * 1024


def _decode_master_key() -> bytes:
    encoded = os.environ.get(_STATE_KEY_ENV)
    if not encoded:
        raise RuntimeError(
            f"{_STATE_KEY_ENV} is required for an active SFT profile"
        )
    try:
        key = bytes.fromhex(encoded)
    except ValueError:
        try:
            key = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(
                f"{_STATE_KEY_ENV} must be hex or strict base64"
            ) from exc
    if len(key) < 32:
        raise ValueError(f"{_STATE_KEY_ENV} must decode to at least 32 bytes")
    return key


def _derive_key(master: bytes, domain: bytes) -> bytes:
    return hmac.new(master, b"queenbee-sft\0" + domain, hashlib.sha256).digest()


def _open_registry(path: Path, key: bytes) -> PhaseArtifactRegistry:
    verifier = lambda _manifest: False  # shadow-register admits no source manifest
    if path.exists():
        return PhaseArtifactRegistry.load(
            path,
            registry_key=key,
            manifest_verifier=verifier,
        )
    registry = PhaseArtifactRegistry(
        registry_key=key,
        manifest_verifier=verifier,
    )
    registry.save(path)
    return registry


def _bank_capabilities(registry: PhaseArtifactRegistry) -> dict[str, Any]:
    return {
        "direct_binding_verifier": make_phase_v2_binding_verifier(registry),
        "proposal_action_terminal_verifier": (
            make_phase_v2_proposal_action_terminal_verifier(registry)
        ),
        "repair_opportunity_verifier": (
            make_phase_v2_repair_opportunity_verifier(registry)
        ),
    }


def _open_bank(
    path: Path,
    key: bytes,
    registry: PhaseArtifactRegistry,
) -> FactorBankV2:
    capabilities = _bank_capabilities(registry)
    if path.exists():
        return FactorBankV2.load(path, state_key=key, **capabilities)
    bank = FactorBankV2(state_key=key, **capabilities)
    bank.save(path)
    return bank


def _load_frozen_protocol(path_value: str | None) -> PilotProtocolV1:
    """Load one closed protocol without following a replaceable symlink."""

    if not path_value:
        raise ValueError("phase_v4 requires sft_protocol_path")
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("phase_v4 requires an absolute sft_protocol_path")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("frozen SFT protocol cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError(
                "frozen SFT protocol must be a stable non-symlink regular file"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(_MAX_PROTOCOL_BYTES + 1)
    finally:
        os.close(fd)
    if not payload or len(payload) > _MAX_PROTOCOL_BYTES:
        raise ValueError("frozen SFT protocol has an invalid byte length")
    try:
        return PilotProtocolV1.model_validate_json(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("frozen SFT protocol is not a closed PilotProtocolV1") from exc


def _validate_v4_protocol(
    protocol: PilotProtocolV1,
    cfg: RunConfig,
    *,
    agent_counts: list[int] | None,
) -> None:
    """Close the frozen protocol over the observable RunConfig namespace."""

    namespace = protocol.namespace
    mismatches: list[str] = []
    if protocol.method_arm != "sft_unified":
        mismatches.append("method_arm")
    if not protocol.component_bundle_required:
        mismatches.append("component_bundle_required")
    if namespace.task_family != cfg.benchmark:
        mismatches.append("task_family")
    if namespace.objective != cfg.objective:
        mismatches.append("objective")
    if namespace.information_goal != cfg.silo_eval_mode:
        mismatches.append("information_goal")
    if (
        namespace.planner_mode != "program_generate"
        or namespace.payload_format != "phase_program_skill_v1"
        or namespace.worker_contract != "not_applicable"
    ):
        mismatches.append("planner_payload_worker_contract")
    if namespace.model_name != protocol.model_name:
        mismatches.append("namespace_model")
    if namespace.binder_version != PHASE_FULL_FACTOR_BINDER_VERSION:
        mismatches.append("binder_version")
    if namespace.compiler_version != PHASE_PROGRAM_COMPILER_VERSION:
        mismatches.append("compiler_version")
    if float(cfg.temperature) != protocol.temperature:
        mismatches.append("temperature")
    if cfg.llm_provider == "openai" and cfg.model_name != protocol.model_name:
        mismatches.append("real_model_name")
    if cfg.n_agents is not None and int(cfg.n_agents) != namespace.n_agents:
        mismatches.append("n_agents")
    if agent_counts is not None and tuple(agent_counts) != (namespace.n_agents,):
        mismatches.append("agent_counts")
    if {budget.phase for budget in protocol.phase_budgets} != {
        "TRAIN_UPDATE",
        "PROBE",
        "FINAL_VAL",
    }:
        mismatches.append("phase_budgets")
    if mismatches:
        raise ValueError(
            "frozen SFT protocol does not match the phase_v4 run: "
            + ", ".join(sorted(mismatches))
        )


def _manifest_verifier(protocol: PilotProtocolV1):
    """Bind native Phase manifests to the protocol's physical source seal."""

    pilot_manifest = protocol.source_manifest

    def verify(manifest: Any) -> bool:
        return bool(
            manifest.split == pilot_manifest.split
            and manifest.source_catalog_sha256
            == pilot_manifest.source_catalog_sha256
            and manifest.policy_sha256 == pilot_manifest.source_policy_sha256
            and canonical_sha256(manifest) == protocol.source_authority_sha256
        )

    return verify


def _run_v4_mechanics(
    cfg: RunConfig,
    *,
    agent_counts: list[int] | None,
    workers: int,
) -> dict[str, Any]:
    """Authenticate and recover one pre-provisioned bundle, with zero calls."""

    if workers != 1:
        raise ValueError("phase_v4 requires workers=1 for single-writer authority")
    master = _decode_master_key()
    protocol = _load_frozen_protocol(cfg.sft_protocol_path)
    _validate_v4_protocol(protocol, cfg, agent_counts=agent_counts)

    state_root = Path(str(cfg.sft_state_dir))
    database_path = state_root / DATABASE_FILENAME
    try:
        database_stat = os.lstat(database_path)
    except OSError as exc:
        raise RuntimeError(
            "phase_v4 requires a pre-provisioned component-bundle pilot store"
        ) from exc
    if not stat.S_ISREG(database_stat.st_mode):
        raise RuntimeError(
            "phase_v4 pilot database must be a non-symlink regular file"
        )

    with SingleWriterPilotStore.open(
        state_root,
        protocol=protocol,
        hmac_key=_derive_key(master, _V4_STORE_KEY_DOMAIN),
    ) as store:
        loaded = PilotComponentCoordinator(
            store=store,
            phase_registry_key=_derive_key(master, _V4_PHASE_KEY_DOMAIN),
            factor_bank_key=_derive_key(master, _V4_FACTOR_KEY_DOMAIN),
            manifest_verifier=_manifest_verifier(protocol),
        ).restore_latest()
        snapshot = loaded.snapshot
        registry_digest = hashlib.sha256(
            loaded.registry.to_state().model_dump_json().encode("utf-8")
        ).hexdigest()
        bank_digest = loaded.bank.scientific_state_sha256
        bank_size = len(loaded.bank.factors)

    return {
        "method": "Sealed Factor-Transition Bank",
        "method_status": "component_restore_only_no_efficacy_claim",
        "sft_profile": cfg.sft_profile,
        "sft_state_dir": str(state_root),
        "sft_protocol_path": str(Path(str(cfg.sft_protocol_path))),
        "sft_protocol_sha256": protocol.digest,
        "component_bundle_generation": snapshot.metadata.generation,
        "component_bundle_sha256": snapshot.metadata.bundle_sha256,
        "phase_registry_envelope_sha256": (
            snapshot.metadata.phase_registry_envelope_sha256
        ),
        "factor_bank_envelope_sha256": (
            snapshot.metadata.factor_bank_envelope_sha256
        ),
        "phase_registry_state_sha256": registry_digest,
        "factor_bank_state_sha256": bank_digest,
        "model_calls": 0,
        "total_tokens": 0,
        "gate": {
            "accepted": False,
            "j_before": 0.0,
            "j_after": 0.0,
            "epsilon": 0.0,
            "reason": "component_restore_has_no_probe_or_gate",
        },
        "train_cases": [],
        "val_cases": [],
        "n_train_rows": 0,
        "n_val_rows_real": 0,
        "train_success_rate": 0.0,
        "val_success_rate": 0.0,
        "objective_knobs": {"sft_profile": cfg.sft_profile},
        "skill_bank_size_before": bank_size,
        "skill_bank_size_after": bank_size,
        "skill_bank_mutated": False,
    }


def run_sft_phase_evolution(
    _adapter: Any,
    *,
    cfg: RunConfig,
    agent_counts: list[int] | None = None,
    workers: int = 1,
    held_out_rows: list[dict[str, Any]] | None = None,
    initial_skills: list[dict[str, Any]] | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    """Run the explicit mechanics-only SFT profile with zero model calls."""

    if cfg.sft_profile == _V4_PROFILE:
        if held_out_rows is not None or initial_skills:
            raise ValueError(
                "phase_v4 rejects synthetic held-out rows and initial skills"
            )
        return _run_v4_mechanics(
            cfg,
            agent_counts=agent_counts,
            workers=workers,
        )
    if cfg.sft_profile != "phase_v3_shadow_register":
        raise ValueError(f"unsupported active SFT profile {cfg.sft_profile!r}")
    if held_out_rows is not None or initial_skills:
        raise ValueError(
            "shadow-register profile rejects synthetic held-out rows and initial skills"
        )
    master = _decode_master_key()  # fail before creating any state path
    state_root = Path(str(cfg.sft_state_dir)).resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = state_root / ".sft-profile.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        registry = _open_registry(
            state_root / "phase_registry.v7.json",
            _derive_key(master, b"phase-registry-v7"),
        )
        bank = _open_bank(
            state_root / "factor_bank.v4.json",
            _derive_key(master, b"factor-bank-v4"),
            registry,
        )
        registry_digest = hashlib.sha256(
            registry.to_state().model_dump_json().encode("utf-8")
        ).hexdigest()
        bank_digest = bank.scientific_state_sha256
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return {
        "method": "Sealed Factor-Transition Bank",
        "method_status": "shadow_register_only_no_efficacy_claim",
        "sft_profile": cfg.sft_profile,
        "sft_state_dir": str(state_root),
        "phase_registry_state_sha256": registry_digest,
        "factor_bank_state_sha256": bank_digest,
        "model_calls": 0,
        "total_tokens": 0,
        "gate": {
            "accepted": False,
            "j_before": 0.0,
            "j_after": 0.0,
            "epsilon": 0.0,
            "reason": "shadow_register_has_no_probe_or_gate",
        },
        "train_cases": [],
        "val_cases": [],
        "n_train_rows": 0,
        "n_val_rows_real": 0,
        "train_success_rate": 0.0,
        "val_success_rate": 0.0,
        "objective_knobs": {"sft_profile": cfg.sft_profile},
        "skill_bank_size_before": 0,
        "skill_bank_size_after": 0,
        "skill_bank_mutated": False,
    }


__all__ = ["run_sft_phase_evolution"]
