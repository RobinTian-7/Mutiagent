"""Sealed v5 experiment root: one closed object binds every frozen authority.

The seal is the single file a ``phase_v5_executable_sft`` run may trust.  It
embeds the exact child manifests (case/pair/candidate/runner/schedule and the
multi-arm experiment manifest) so there is no path-resolution surface, and it
pins by digest everything that must stay external: both authority manifests,
the structural anchor, TEST/report commitments, and the genesis component
root.  TEST content itself never enters this object — only its commitment.

Provisioning is deliberately execution-free: it verifies the full seal graph,
native-reloads the frozen structural anchor, and idempotently records the
generation-zero component bundle plus capacity preflight in the single-writer
store.  Any byte difference anywhere fails closed instead of minting a second
experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Literal

from pydantic import field_validator, model_validator

import masbench  # noqa: F401  (bootstraps the sibling exp_graph package)
import exp_graph

from masbench.sft_pilot.bootstrap_authority import (
    PilotBootstrapAuthorityManifestV1,
)
from masbench.sft_pilot.manifests import (
    PilotCandidateManifestV1,
    PilotCaseManifestV1,
    PilotExecutionScheduleV1,
    PilotExperimentManifestV1,
    PilotPairManifestV1,
    PilotRunnerManifestV1,
    load_frozen_manifest,
    published_manifest_bytes,
    validate_schedule_against_protocol,
)
from masbench.sft_pilot.method_policy import method_capability_policy
from masbench.sft_pilot.provision import (
    PilotProvisioningReceipt,
    provision_pilot_store,
)
from masbench.sft_pilot.runtime_authority import (
    PilotRuntimeAuthorityManifestV1,
)
from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    PilotCapacityPreflightV1,
    PilotProtocolV1,
    canonical_sha256,
    require_opaque_id,
    require_sha256,
)
from masbench.sft_pilot.store import (
    component_genesis_sha256_from_envelope_digests,
)
from masbench.sft_pilot.structural_anchor import (
    StructuralAnchorBundleV1,
    StructuralAnchorPlanV1,
    StructuralAnchorRuntimeV1,
    load_structural_anchor_v1,
)


EXPERIMENT_SEAL_VERSION = "sft_pilot_experiment_seal_v1"
ANCHOR_DIRNAME = "anchor"
_MAX_SEAL_BYTES = 16 * 1024 * 1024
_GIT_COMMIT_RE_TEXT = r"[0-9a-f]{40}"

# Host-pinned law: which repository file backs each runtime authority code
# source.  Callers never choose these paths; the sealed manifest pins their
# exact bytes and any drift fails closed at authority load time.
_RUNTIME_CODE_SOURCE_FILES: dict[str, tuple[str, str]] = {
    "exact_phase_runtime": ("masbench", "engine.py"),
    "factor_pair_adapter": ("masbench", "sft_pilot/pair_adapter.py"),
    "phase_full_factor_v3_binder": ("exp_graph", "mas/phase_factor_binding_v3.py"),
    "phase_registry": ("exp_graph", "mas/phase_artifact_registry.py"),
    "pilot_metered_llm_client": ("masbench", "sft_pilot/llm_meter.py"),
    "pilot_single_writer_store": ("masbench", "sft_pilot/store.py"),
    "protocol_runner": ("exp_graph", "runner/protocol.py"),
    "request_renderer": ("masbench", "sft_pilot/request_renderer.py"),
    "result_ledger": ("masbench", "sft_pilot/result_ledger.py"),
    "sft_journal": ("exp_graph", "mas/sft_journal.py"),
    "single_use_pair_consumer": ("masbench", "sft_pilot/pair_consumer.py"),
    "train_scalar_evaluator": ("masbench", "sft_pilot/execution_attestation.py"),
}

_BOOTSTRAP_CODE_SOURCE_FILES: dict[str, tuple[str, str]] = {
    "anchor_freeze_ledger": ("masbench", "sft_pilot/anchor_freeze.py"),
    "anchor_native_recount": ("masbench", "sft_pilot/anchor_freeze.py"),
    "dataset_adapter": ("masbench", "adapters/silo_bench.py"),
    "factor_bank": ("exp_graph", "mas/factor_bank_v2.py"),
    "phase_full_factor_v3_binder": ("exp_graph", "mas/phase_factor_binding_v3.py"),
    "phase_registry": ("exp_graph", "mas/phase_artifact_registry.py"),
    "provision": ("masbench", "sft_pilot/provision.py"),
    "source_authority_issuer": ("masbench", "sft_pilot/bootstrap_authority.py"),
    "structural_anchor_builder": ("masbench", "sft_pilot/structural_anchor.py"),
    "train_catalog_loader": ("masbench", "sft_pilot/bootstrap_authority.py"),
}


def _package_root(package: str) -> Path:
    if package == "masbench":
        return Path(masbench.__file__).resolve().parent
    if package == "exp_graph":
        return Path(exp_graph.__file__).resolve().parent
    raise ValueError(f"unknown code-source package {package!r}")


def _code_source_paths(law: dict[str, tuple[str, str]]) -> dict[str, Path]:
    return {
        source_id: _package_root(package) / relative
        for source_id, (package, relative) in law.items()
    }


def runtime_code_source_paths() -> dict[str, Path]:
    """Host-pinned file for every required runtime authority code source."""

    return _code_source_paths(_RUNTIME_CODE_SOURCE_FILES)


def bootstrap_code_source_paths() -> dict[str, Path]:
    """Host-pinned file for every required bootstrap authority code source."""

    return _code_source_paths(_BOOTSTRAP_CODE_SOURCE_FILES)


def derive_method_policy_sha256(
    method_arms: tuple[str, ...],
) -> str:
    """Commit to the closed capability law of every experiment arm."""

    if not method_arms or len(set(method_arms)) != len(method_arms):
        raise ValueError("method arms must be non-empty and unique")
    policies = tuple(
        method_capability_policy(method_arm) for method_arm in method_arms
    )
    return canonical_sha256(
        {
            "domain": "sft-pilot-experiment-method-policy-v1",
            "arms": tuple(method_arms),
            "policies": policies,
        }
    )


def split_case_manifest_sha256(
    case_manifest: PilotCaseManifestV1,
    *,
    split: Literal["TRAIN_UPDATE", "FINAL_VAL"],
) -> str:
    """Derive the per-split case-subset root from the frozen case manifest."""

    subset = tuple(
        item for item in case_manifest.cases if item.split == split
    )
    return canonical_sha256(
        {
            "domain": "sft-pilot-split-case-manifest-v1",
            "split": split,
            "case_manifest_sha256": case_manifest.digest,
            "cases": subset,
        }
    )


class PilotExperimentSealV1(ClosedPilotModel):
    """The single trust root of one preregistered v5 experiment."""

    seal_version: Literal["sft_pilot_experiment_seal_v1"] = (
        EXPERIMENT_SEAL_VERSION
    )
    experiment_id: str
    fixed_git_commit: str
    runtime_authority_manifest_sha256: str
    bootstrap_authority_manifest_sha256: str
    method_policy_sha256: str
    experiment: PilotExperimentManifestV1
    case_manifest: PilotCaseManifestV1
    pair_manifest: PilotPairManifestV1
    candidate_manifest: PilotCandidateManifestV1
    runner_manifest: PilotRunnerManifestV1
    execution_schedule: PilotExecutionScheduleV1
    structural_anchor_plan: StructuralAnchorPlanV1
    structural_anchor: StructuralAnchorBundleV1
    train_case_manifest_sha256: str
    final_val_case_manifest_sha256: str
    test_manifest_sha256: str
    report_manifest_sha256: str
    state_genesis_sha256: str

    @field_validator("experiment_id")
    @classmethod
    def validate_experiment_id(cls, value: str) -> str:
        return require_opaque_id(value, field_name="experiment_id")

    @field_validator("fixed_git_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        import re

        if re.fullmatch(_GIT_COMMIT_RE_TEXT, value) is None:
            raise ValueError("fixed_git_commit must be a full lowercase Git commit")
        return value

    @field_validator(
        "runtime_authority_manifest_sha256",
        "bootstrap_authority_manifest_sha256",
        "method_policy_sha256",
        "train_case_manifest_sha256",
        "final_val_case_manifest_sha256",
        "test_manifest_sha256",
        "report_manifest_sha256",
        "state_genesis_sha256",
    )
    @classmethod
    def validate_sha(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_seal_closure(self) -> "PilotExperimentSealV1":
        expected = {
            "case_manifest_sha256": self.case_manifest.digest,
            "pair_manifest_sha256": self.pair_manifest.digest,
            "candidate_manifest_sha256": self.candidate_manifest.digest,
            "runner_manifest_sha256": self.runner_manifest.digest,
            "execution_schedule_sha256": self.execution_schedule.digest,
        }
        for field_name, digest in expected.items():
            if getattr(self.experiment, field_name) != digest:
                raise ValueError(
                    f"experiment {field_name} differs from the embedded child bytes"
                )
        if self.experiment_id != self.experiment.experiment_id:
            raise ValueError("seal and experiment manifest disagree on identity")
        if self.fixed_git_commit != self.runner_manifest.fixed_git_commit:
            raise ValueError("seal Git commit differs from the runner manifest")
        expected_policy = derive_method_policy_sha256(
            tuple(item.method_arm for item in self.experiment.arms)
        )
        if self.method_policy_sha256 != expected_policy:
            raise ValueError("method policy root differs from the closed arm law")
        if self.train_case_manifest_sha256 != split_case_manifest_sha256(
            self.case_manifest, split="TRAIN_UPDATE"
        ):
            raise ValueError("TRAIN_UPDATE case root is not reproducible")
        if self.final_val_case_manifest_sha256 != split_case_manifest_sha256(
            self.case_manifest, split="FINAL_VAL"
        ):
            raise ValueError("FINAL_VAL case root is not reproducible")
        if self.test_manifest_sha256 == self.report_manifest_sha256:
            raise ValueError(
                "TEST and report commitments must be distinct sealed objects"
            )
        if (
            self.structural_anchor.anchor_plan_sha256
            != self.structural_anchor_plan.digest
        ):
            raise ValueError("structural anchor does not bind the embedded plan")
        expected_genesis = component_genesis_sha256_from_envelope_digests(
            phase_registry_envelope_sha256=(
                self.structural_anchor.phase_registry_envelope_sha256
            ),
            factor_bank_envelope_sha256=(
                self.structural_anchor.factor_bank_envelope_sha256
            ),
        )
        if self.state_genesis_sha256 != expected_genesis:
            raise ValueError(
                "genesis root differs from the frozen structural anchor envelopes"
            )
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


def load_experiment_seal(path_value: str | Path) -> PilotExperimentSealV1:
    """Open the seal root without following a symlink; require canonical bytes.

    The seal is its own trust root, so unlike ``load_frozen_manifest`` there is
    no external expected digest — every inner commitment is closed by the
    model validators instead.
    """

    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("frozen SFT experiment manifest requires an absolute path")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("frozen SFT experiment manifest cannot be opened") from exc
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError(
                "frozen SFT experiment manifest must be a stable non-symlink "
                "regular file"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(_MAX_SEAL_BYTES + 1)
    finally:
        os.close(fd)
    if not payload or len(payload) > _MAX_SEAL_BYTES:
        raise ValueError("frozen SFT experiment manifest has an invalid byte length")
    try:
        seal = PilotExperimentSealV1.model_validate_json(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "frozen SFT experiment manifest is not a sealed PilotExperimentSealV1"
        ) from exc
    if payload != published_manifest_bytes(seal):
        raise ValueError(
            "frozen SFT experiment manifest is not canonical exact JSON"
        )
    return seal


def validate_experiment_seal(
    seal: PilotExperimentSealV1,
    *,
    runtime_authority: PilotRuntimeAuthorityManifestV1,
    bootstrap_authority: PilotBootstrapAuthorityManifestV1,
    protocol: PilotProtocolV1,
) -> None:
    """Close one run's protocol and both authority manifests over the seal."""

    seal = PilotExperimentSealV1.model_validate(seal.model_dump(mode="python"))
    runtime_authority = PilotRuntimeAuthorityManifestV1.model_validate(
        runtime_authority.model_dump(mode="python")
    )
    bootstrap_authority = PilotBootstrapAuthorityManifestV1.model_validate(
        bootstrap_authority.model_dump(mode="python")
    )
    protocol = PilotProtocolV1.model_validate(protocol.model_dump(mode="python"))

    mismatches: list[str] = []
    if seal.runtime_authority_manifest_sha256 != runtime_authority.digest:
        mismatches.append("runtime_authority_manifest")
    if seal.bootstrap_authority_manifest_sha256 != bootstrap_authority.digest:
        mismatches.append("bootstrap_authority_manifest")
    if (
        runtime_authority.bootstrap_authority_manifest_sha256
        != bootstrap_authority.digest
    ):
        mismatches.append("runtime_bootstrap_cross_pin")
    if not (
        seal.fixed_git_commit
        == runtime_authority.fixed_git_commit
        == bootstrap_authority.fixed_git_commit
    ):
        mismatches.append("fixed_git_commit")
    if runtime_authority.runner_manifest_sha256 != seal.runner_manifest.digest:
        mismatches.append("runner_manifest")
    if (
        runtime_authority.execution_schedule_sha256
        != seal.execution_schedule.digest
    ):
        mismatches.append("execution_schedule")
    if runtime_authority.method_policy_sha256 != seal.method_policy_sha256:
        mismatches.append("method_policy")
    if mismatches:
        raise ValueError(
            "experiment seal does not close over its authorities: "
            + ", ".join(sorted(mismatches))
        )

    matching_arms = tuple(
        item
        for item in seal.experiment.arms
        if item.child_protocol_sha256 == protocol.digest
    )
    if len(matching_arms) != 1:
        raise ValueError("protocol is not a sealed arm of this experiment")
    arm = matching_arms[0]
    if arm.method_arm != protocol.method_arm:
        raise ValueError("sealed arm method differs from the protocol method arm")
    validate_schedule_against_protocol(
        seal.execution_schedule,
        protocol,
        case_manifest=seal.case_manifest,
        pair_manifest=seal.pair_manifest,
    )
    if protocol.namespace != seal.structural_anchor_plan.namespace:
        raise ValueError(
            "protocol namespace differs from the sealed anchor plan"
        )
    if (
        protocol.source_authority_sha256
        != seal.structural_anchor.source_authority_sha256
    ):
        raise ValueError(
            "protocol source authority differs from the sealed anchor"
        )
    # Only Factor-backed arms share the structural-anchor genesis; control
    # backends own their genesis but can never claim the anchor's evidence.
    if method_capability_policy(protocol.method_arm).state_backend == (
        "factor_bank_v2"
    ):
        if protocol.genesis_state_sha256 != seal.state_genesis_sha256:
            raise ValueError(
                "factor-backed protocol genesis differs from the sealed anchor"
            )
    elif protocol.genesis_state_sha256 == seal.state_genesis_sha256:
        raise ValueError(
            "non-factor backend cannot claim the structural-anchor genesis"
        )


def derive_capacity_preflight(
    protocol: PilotProtocolV1,
    schedule: PilotExecutionScheduleV1,
) -> PilotCapacityPreflightV1:
    """Derive the worst-case bounded preflight from frozen facts only."""

    policy = protocol.capacity_policy
    total_calls = sum(len(entry.calls) for entry in schedule.entries)
    return PilotCapacityPreflightV1(
        planned_scientific_commits=policy.max_scientific_commits,
        planned_execution_leases=len(schedule.entries),
        planned_call_receipts=total_calls,
        planned_component_checkpoints=policy.max_component_checkpoints,
        planned_max_calls_per_execution=max(
            len(entry.calls) for entry in schedule.entries
        ),
        planned_max_active_db_bytes=policy.max_active_db_bytes,
        planned_archive_bytes=policy.max_archive_bytes,
        planned_total_stored_scalar_bytes=policy.max_total_stored_scalar_bytes,
        planned_max_input_tokens_per_call=max(
            call.input_tokens_reserved
            for entry in schedule.entries
            for call in entry.calls
        ),
        planned_max_output_tokens_per_call=max(
            call.output_tokens_reserved
            for entry in schedule.entries
            for call in entry.calls
        ),
        quarantined_carriers_reserved=1,
        indeterminate_call_reserve=1,
    )


@dataclass(frozen=True)
class PilotExperimentProvisionReceipt:
    """Non-secret commitments after one idempotent v5 provisioning pass."""

    seal_sha256: str
    protocol_sha256: str
    genesis_state_sha256: str
    preflight_sha256: str
    schema_sha256: str
    structural_anchor_root_sha256: str


def provision_phase_v5_experiment(
    *,
    seal: PilotExperimentSealV1,
    protocol: PilotProtocolV1,
    runtime_authority: PilotRuntimeAuthorityManifestV1,
    bootstrap_authority: PilotBootstrapAuthorityManifestV1,
    state_dir: str | Path,
    anchor_dir: str | Path | None = None,
    store_hmac_key: bytes,
    source_authority_key: bytes,
    phase_registry_key: bytes,
    factor_bank_key: bytes,
) -> PilotExperimentProvisionReceipt:
    """Verify the full seal graph, then idempotently provision generation zero.

    Zero model calls by construction.  The structural anchor must already be
    frozen at ``anchor_dir`` (default ``<state_dir>/anchor``); its exact
    envelope bytes become the genesis component bundle.
    """

    validate_experiment_seal(
        seal,
        runtime_authority=runtime_authority,
        bootstrap_authority=bootstrap_authority,
        protocol=protocol,
    )
    if not protocol.component_bundle_required:
        raise ValueError(
            "phase_v5 provisioning targets a component-bundle protocol arm"
        )
    state_root = Path(state_dir)
    if not state_root.is_absolute():
        raise ValueError("phase_v5 state_dir must be absolute")
    anchor_root = (
        state_root / ANCHOR_DIRNAME if anchor_dir is None else Path(anchor_dir)
    )
    anchor_runtime: StructuralAnchorRuntimeV1 = load_structural_anchor_v1(
        anchor_root,
        plan=seal.structural_anchor_plan,
        expected_bundle=seal.structural_anchor,
        source_authority_key=source_authority_key,
        phase_registry_key=phase_registry_key,
        factor_bank_key=factor_bank_key,
    )
    preflight = derive_capacity_preflight(protocol, seal.execution_schedule)
    receipt: PilotProvisioningReceipt = provision_pilot_store(
        state_root,
        protocol=protocol,
        preflight=preflight,
        store_hmac_key=store_hmac_key,
        phase_registry_envelope_bytes=(
            anchor_runtime.phase_registry_envelope_bytes
        ),
        factor_bank_envelope_bytes=anchor_runtime.factor_bank_envelope_bytes,
        structural_anchor=seal.structural_anchor,
        structural_anchor_plan=seal.structural_anchor_plan,
        execution_schedule=seal.execution_schedule,
    )
    if receipt.structural_anchor_root_sha256 is None:
        raise RuntimeError("phase_v5 provisioning lost its structural anchor root")
    return PilotExperimentProvisionReceipt(
        seal_sha256=seal.digest,
        protocol_sha256=receipt.protocol_sha256,
        genesis_state_sha256=receipt.genesis_state_sha256,
        preflight_sha256=receipt.preflight_sha256,
        schema_sha256=receipt.schema_sha256,
        structural_anchor_root_sha256=receipt.structural_anchor_root_sha256,
    )


def load_sealed_authority_manifests(
    seal: PilotExperimentSealV1,
    *,
    runtime_authority_path: str | Path,
    bootstrap_authority_path: str | Path,
) -> tuple[PilotRuntimeAuthorityManifestV1, PilotBootstrapAuthorityManifestV1]:
    """Load both authority manifest files at their seal-pinned digests."""

    runtime_authority = load_frozen_manifest(
        runtime_authority_path,
        model_type=PilotRuntimeAuthorityManifestV1,
        expected_sha256=seal.runtime_authority_manifest_sha256,
    )
    bootstrap_authority = load_frozen_manifest(
        bootstrap_authority_path,
        model_type=PilotBootstrapAuthorityManifestV1,
        expected_sha256=seal.bootstrap_authority_manifest_sha256,
    )
    return runtime_authority, bootstrap_authority


__all__ = [
    "ANCHOR_DIRNAME",
    "EXPERIMENT_SEAL_VERSION",
    "PilotExperimentProvisionReceipt",
    "PilotExperimentSealV1",
    "bootstrap_code_source_paths",
    "derive_capacity_preflight",
    "derive_method_policy_sha256",
    "load_experiment_seal",
    "load_sealed_authority_manifests",
    "provision_phase_v5_experiment",
    "runtime_code_source_paths",
    "split_case_manifest_sha256",
    "validate_experiment_seal",
]
