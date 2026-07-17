"""TRAIN arm-evidence -> FactorBank ``ArmReceiptV2`` adapter (v5 Stage 5).

This is the only path from trusted execution/scorer receipts to a Factor arm
receipt.  It re-runs both authority verifications through
``factor_arm_evidence_from_receipts`` (so a raw ``DenseOutcome``, a caller
dict, or a FINAL_VAL receipt can never enter), joins the attested execution to
the exact registered v3 edge and probe attempt, and re-derives the engine's
physical execution root from the journal arm root — binding the Bank receipt
to the exact physically executed artifact.
"""

from __future__ import annotations

from typing import Any, Literal

from exp_graph.mas.factor_bank import DenseOutcome, ExecutionUsage
from exp_graph.mas.factor_bank_v2 import (
    ArmReceiptV2,
    PairExecutionReceiptV2,
    ProbeAttemptV3,
    ProbePlanV2,
)
from exp_graph.mas.phase_artifact_registry import PhaseArtifactRegistry
from exp_graph.mas.phase_factor_binding_v3 import RegisteredPhaseFactorEdgeV3

from masbench.sft_pilot.execution_attestation import (
    PilotExecutionAttestationV1,
    PilotExecutionAttestor,
    PilotOutcomeScorer,
    PilotTrainUpdateOutcomeReceiptV1,
    factor_arm_evidence_from_receipts,
)
from masbench.sft_pilot.factor_authority import SFTPilotFactorAuthority
from masbench.sft_pilot.schema import canonical_sha256


def _physical_execution_root(
    execution: PilotExecutionAttestationV1,
    *,
    journal_physical_root_sha256: str,
) -> str:
    """Re-derive the engine's composite physical root for one journal root."""

    return canonical_sha256(
        {
            "domain": "sft-pilot-physical-exact-phase-execution-v1",
            "artifact_sha256": execution.selected_artifact_sha256,
            "proof_sha256": execution.proof_sha256,
            "call_receipt_root_sha256": execution.call_receipt_root_sha256,
            "nonoverlap_event_root_sha256": (
                execution.nonoverlap_event_root_sha256
            ),
            "journal_physical_root_sha256": journal_physical_root_sha256,
        }
    )


def make_phase_v3_factor_arm_receipt(
    *,
    authority: SFTPilotFactorAuthority,
    registry: PhaseArtifactRegistry,
    registered: RegisteredPhaseFactorEdgeV3,
    plan: ProbePlanV2,
    attempt: ProbeAttemptV3,
    pair_execution_receipt: PairExecutionReceiptV2,
    execution: PilotExecutionAttestationV1,
    outcome_receipt: PilotTrainUpdateOutcomeReceiptV1,
    execution_attestor: PilotExecutionAttestor,
    scorer: PilotOutcomeScorer,
    usage: ExecutionUsage,
    safe_failure_code: str | None = None,
    failed_stage_rank: int | None = None,
) -> ArmReceiptV2:
    """Project one verified TRAIN execution+score into the exact arm receipt."""

    if type(execution) is not PilotExecutionAttestationV1:
        raise TypeError("arm adapter requires the exact execution attestation type")
    if not isinstance(authority, SFTPilotFactorAuthority):
        raise TypeError("arm adapter requires the pilot factor authority")
    registered = RegisteredPhaseFactorEdgeV3.model_validate(
        registered.model_dump(mode="python")
    )
    pair_execution_receipt = PairExecutionReceiptV2.model_validate(
        pair_execution_receipt.model_dump(mode="python")
    )
    arm: Literal["source", "target"] = execution.pair_arm
    expected_factor = (
        registered.transition.from_revision_id
        if arm == "source"
        else registered.transition.to_revision_id
    )
    # Both authorities re-verify inside; the TRAIN-only law, method policy,
    # and the retrieved/activated separation are enforced there.
    evidence = factor_arm_evidence_from_receipts(
        protocol=authority.protocol,
        execution=execution,
        outcome_receipt=outcome_receipt,
        expected_activated_factor_revision_id=expected_factor,
        execution_attestor=execution_attestor,
        scorer=scorer,
    )

    composition = (
        registered.source_composition
        if arm == "source"
        else registered.target_composition
    )
    if not (
        execution.proof_id == registered.proof.handle_id
        and execution.proof_sha256 == registered.proof.proof_sha256
        and execution.composition_id == composition.composition_id
        and execution.selected_artifact_sha256 == composition.artifact_sha256
        and execution.namespace_sha256 == registered.transition.namespace.digest
    ):
        raise ValueError("attested execution differs from the registered v3 edge")
    if execution.execution_ordinal != attempt.ordinal:
        raise ValueError("attested execution ordinal differs from the probe attempt")

    root_id = (
        pair_execution_receipt.source_root_id
        if arm == "source"
        else pair_execution_receipt.target_root_id
    )
    paired_root_id = (
        pair_execution_receipt.target_root_id
        if arm == "source"
        else pair_execution_receipt.source_root_id
    )
    if execution.physical_execution_root_sha256 != _physical_execution_root(
        execution, journal_physical_root_sha256=root_id
    ):
        raise ValueError(
            "journal arm root is not the attested physical execution root"
        )

    execution_class = evidence.terminal_class
    if execution_class == "algorithm_failure":
        if safe_failure_code is None or failed_stage_rank is None:
            raise ValueError(
                "algorithm failure requires a safe failure code and stage rank"
            )
    elif safe_failure_code is not None or failed_stage_rank is not None:
        raise ValueError("completed arms cannot carry failure annotations")

    outcome = DenseOutcome.model_validate(
        evidence.metrics.model_dump(mode="python")
    )
    return authority.make_phase_arm_receipt(
        registry=registry,
        registered=registered,
        plan=plan,
        attempt=attempt,
        arm=arm,
        root_id=root_id,
        paired_arm_root_id=paired_root_id,
        pair_execution_receipt=pair_execution_receipt,
        activation_trace_root=evidence.activation_trace_root_sha256,
        usage=usage,
        execution_class=execution_class,
        outcome=outcome,
        safe_failure_code=safe_failure_code,
        failed_stage_rank=failed_stage_rank,
    )


__all__ = ["make_phase_v3_factor_arm_receipt"]
