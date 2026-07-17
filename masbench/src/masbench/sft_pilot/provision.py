"""Deterministic provisioning for one sealed single-writer SFT pilot.

Provisioning is deliberately separate from experiment execution.  The caller
must first freeze a closed :class:`PilotProtocolV1` whose genesis digest was
computed from the exact native Phase/Factor envelopes.  This module only
records those bytes and the bounded capacity preflight; it never invents a
manifest, candidate, budget, or scientific transition.  Executable
checkpoint-saga protocols additionally have to close those bytes over the
non-evidence structural anchor plan and bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from masbench.sft_pilot.schema import (
    PilotCapacityPreflightV1,
    PilotProtocolV1,
    canonical_sha256,
)
from masbench.sft_pilot.store import (
    SingleWriterPilotStore,
    component_bundle_state_sha256,
)
from masbench.sft_pilot.structural_anchor import (
    StructuralAnchorBundleV1,
    StructuralAnchorPlanV1,
)


@dataclass(frozen=True)
class PilotProvisioningReceipt:
    """Non-secret commitments returned after an idempotent provisioning pass."""

    protocol_sha256: str
    genesis_state_sha256: str
    preflight_sha256: str
    schema_sha256: str
    structural_anchor_root_sha256: str | None


def _validate_required_structural_anchor(
    *,
    protocol: PilotProtocolV1,
    anchor: StructuralAnchorBundleV1 | None,
    anchor_plan: StructuralAnchorPlanV1 | None,
    phase_registry_envelope_bytes: bytes,
    factor_bank_envelope_bytes: bytes,
) -> StructuralAnchorBundleV1 | None:
    """Close executable saga genesis over one exact non-evidence anchor."""

    if not protocol.component_checkpoint_saga_required:
        if anchor is not None or anchor_plan is not None:
            raise ValueError(
                "a structural anchor is admitted only by a checkpoint-saga protocol"
            )
        return None
    if anchor is None or anchor_plan is None:
        raise ValueError(
            "checkpoint-saga provisioning requires a non-empty structural anchor"
        )
    checked = StructuralAnchorBundleV1.model_validate(
        anchor.model_dump(mode="python")
    )
    checked_plan = StructuralAnchorPlanV1.model_validate(
        anchor_plan.model_dump(mode="python")
    )
    phase_sha256 = hashlib.sha256(phase_registry_envelope_bytes).hexdigest()
    factor_sha256 = hashlib.sha256(factor_bank_envelope_bytes).hexdigest()
    if not (
        checked.anchor_plan_sha256 == checked_plan.digest
        and checked_plan.namespace == protocol.namespace
        and checked.namespace_sha256 == protocol.namespace.digest
        and checked.source_authority_sha256 == protocol.source_authority_sha256
        and checked_plan.source_catalog_sha256
        == protocol.source_manifest.source_catalog_sha256
        and checked_plan.source_policy_sha256
        == protocol.source_manifest.source_policy_sha256
        and checked.phase_registry_envelope_sha256 == phase_sha256
        and checked.factor_bank_envelope_sha256 == factor_sha256
        and checked.zero_evidence.plans == 0
        and checked.zero_evidence.outcomes == 0
        and checked.zero_evidence.assessments == 0
        and checked.zero_evidence.gate_receipts == 0
        and checked.zero_evidence.failures == 0
        and checked.zero_evidence.positive_credit == 0
        and checked.zero_evidence.negative_credit == 0
    ):
        raise ValueError(
            "structural anchor differs from the executable protocol or exact envelopes"
        )
    return checked


def _operation_request_sha256(
    *,
    protocol: PilotProtocolV1,
    operation: str,
    payload_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "domain": "sft-pilot-provision-operation-v1",
            "protocol_sha256": protocol.digest,
            "operation": operation,
            "payload_sha256": payload_sha256,
        }
    )


def provision_pilot_store(
    state_dir: str | Path,
    *,
    protocol: PilotProtocolV1,
    preflight: PilotCapacityPreflightV1,
    store_hmac_key: bytes,
    phase_registry_envelope_bytes: bytes,
    factor_bank_envelope_bytes: bytes,
    structural_anchor: StructuralAnchorBundleV1 | None = None,
    structural_anchor_plan: StructuralAnchorPlanV1 | None = None,
    execution_schedule: object | None = None,
) -> PilotProvisioningReceipt:
    """Record and reverify the exact generation-zero pilot state.

    Repeating the call with the same frozen values is idempotent.  Any changed
    protocol, envelope byte, or preflight is rejected by the underlying
    authenticated store instead of silently creating a second experiment.
    """

    if not isinstance(protocol, PilotProtocolV1):
        protocol = PilotProtocolV1.model_validate(protocol)
    if not isinstance(preflight, PilotCapacityPreflightV1):
        preflight = PilotCapacityPreflightV1.model_validate(preflight)
    if (
        type(phase_registry_envelope_bytes) is not bytes
        or not phase_registry_envelope_bytes
    ):
        raise ValueError("phase registry genesis must be non-empty exact bytes")
    if (
        type(factor_bank_envelope_bytes) is not bytes
        or not factor_bank_envelope_bytes
    ):
        raise ValueError("factor bank genesis must be non-empty exact bytes")

    checked_anchor = _validate_required_structural_anchor(
        protocol=protocol,
        anchor=structural_anchor,
        anchor_plan=structural_anchor_plan,
        phase_registry_envelope_bytes=phase_registry_envelope_bytes,
        factor_bank_envelope_bytes=factor_bank_envelope_bytes,
    )

    computed_genesis = component_bundle_state_sha256(
        phase_registry_envelope_bytes=phase_registry_envelope_bytes,
        factor_bank_envelope_bytes=factor_bank_envelope_bytes,
    )
    if computed_genesis != protocol.genesis_state_sha256:
        raise ValueError("exact component bytes differ from the frozen protocol genesis")

    root = Path(state_dir)
    if not root.is_absolute():
        raise ValueError("pilot state_dir must be absolute")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)

    genesis_request_sha256 = _operation_request_sha256(
        protocol=protocol,
        operation="genesis",
        payload_sha256=computed_genesis,
    )
    preflight_request_sha256 = _operation_request_sha256(
        protocol=protocol,
        operation="preflight",
        payload_sha256=preflight.digest,
    )
    with SingleWriterPilotStore.open(
        root,
        protocol=protocol,
        hmac_key=store_hmac_key,
        execution_schedule=execution_schedule,
    ) as store:
        snapshot = store.record_genesis_component_bundle(
            operation_id="sft-provision-genesis-v1",
            request_sha256=genesis_request_sha256,
            phase_registry_envelope_bytes=phase_registry_envelope_bytes,
            factor_bank_envelope_bytes=factor_bank_envelope_bytes,
        )
        recorded_preflight = store.record_capacity_preflight(
            preflight,
            operation_id="sft-provision-preflight-v1",
            request_sha256=preflight_request_sha256,
        )
        # Re-read through the authenticated recovery path before reporting
        # success.  Opening the same database later repeats all chain checks.
        restored = store.latest_component_bundle()
        if restored != snapshot:
            raise RuntimeError("provisioned component genesis failed exact recovery")
        return PilotProvisioningReceipt(
            protocol_sha256=protocol.digest,
            genesis_state_sha256=restored.metadata.bundle_sha256,
            preflight_sha256=recorded_preflight.digest,
            schema_sha256=store.schema_digest,
            structural_anchor_root_sha256=(
                checked_anchor.anchor_root_sha256
                if checked_anchor is not None
                else None
            ),
        )


__all__ = ["PilotProvisioningReceipt", "provision_pilot_store"]
