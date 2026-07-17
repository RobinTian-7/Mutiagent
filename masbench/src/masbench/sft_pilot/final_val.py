"""FINAL_VAL whole-snapshot gate adapter (v5 Stage 8).

The only path from a candidate assessment to a deployment change: freeze the
pending gate opportunity's incumbent/candidate snapshots, spend the frozen
FINAL_VAL executions read-only (store control receipts only — no TRAIN
evidence API exists here), aggregate case-balanced paired samples, run the
real ``strict_dense_v2`` predicate, sign one ``GateReceiptV2`` under the
authority's gate domain, and apply it to the whole snapshot.  Rejection keeps
the incumbent; nothing here can write a TRAIN transition, retrieval counter,
failure observation, or archive entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from exp_graph.mas.factor_bank import DenseOutcome
from exp_graph.mas.factor_bank_v2 import GateReceiptV2

from masbench.gates import evaluate_strict_dense_gate
from masbench.sft_pilot.schema import canonical_sha256


@dataclass(frozen=True)
class FinalValCaseSample:
    """One safe per-case FINAL_VAL observation (no answers, no prompts)."""

    case_id: str
    seed: int
    metrics: DenseOutcome
    algorithm_failure: bool = False

    def strict_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "seed": self.seed,
            "failure_class": (
                "algorithm_failure" if self.algorithm_failure else ""
            ),
            "program_validity": self.metrics.V,
            "structural_coverage": self.metrics.K,
            "submission_rate": self.metrics.U,
            "evolution_partial": self.metrics.P,
            "evolution_success": self.metrics.S,
            "evolution_stage_score": self.metrics.stage_score,
            "paper_C": self.metrics.C,
            "paper_D": self.metrics.D,
        }


@dataclass(frozen=True)
class FinalValGateOutcome:
    """External gate report plus the applied whole-snapshot decision."""

    accepted: bool
    receipt: GateReceiptV2
    strict_result: dict[str, Any]
    report_sha256: str
    active_snapshot_id_before: str
    active_snapshot_id_after: str


def frozen_final_val_arms(protocol: Any) -> tuple[Any, Any]:
    """The two frozen FINAL_VAL logical arms in schedule order."""

    arms = sorted(
        (
            item
            for item in protocol.authorized_logical_arms
            if item.operation_kind == "final_val"
        ),
        key=lambda item: item.execution_ordinal,
    )
    if len(arms) != 2:
        raise ValueError(
            "phase_v5 FINAL_VAL requires exactly two frozen logical arms"
        )
    return arms[0], arms[1]


def run_final_val_gate(
    *,
    loaded: Any,
    coordinator: Any,
    store: Any,
    schedule: Any,
    authority: Any,
    protocol: Any,
    incumbent_samples: tuple[FinalValCaseSample, ...],
    candidate_samples: tuple[FinalValCaseSample, ...],
    owner_logical_execution_key: str,
    execute_final_val_arm: Any,
    operation_id: str = "final-val-gate",
    operation_request_sha256: str | None = None,
) -> tuple[FinalValGateOutcome, Any]:
    """Consume the pending gate opportunity through the strict dense gate.

    ``execute_final_val_arm(arm, role)`` performs the read-only deployment
    execution for one frozen FINAL_VAL arm (store leases/calls only); it must
    never receive or return Bank state.  Case aggregation happens per
    (case_id, seed) inside the strict predicate, which requires identical
    paired keys.
    """

    bank = loaded.bank
    pending = [
        item
        for item in bank.to_state().gate_opportunities
        if item.state == "pending"
    ]
    if len(pending) != 1:
        raise ValueError("FINAL_VAL gate requires exactly one pending opportunity")
    opportunity = pending[0]
    assessment = bank.assessments[opportunity.plan_id]
    if assessment.label != "candidate":
        raise ValueError("gate opportunity is not backed by a candidate assessment")

    head = bank.deployment_heads[opportunity.deployment_slot_id]
    incumbent_snapshot = next(
        item
        for item in bank.to_state().deployment_snapshots
        if item.snapshot_id == head.active_snapshot_id
    )

    incumbent_arm, candidate_arm = frozen_final_val_arms(protocol)
    execute_final_val_arm(incumbent_arm, "incumbent")
    execute_final_val_arm(candidate_arm, "candidate")

    # The strict parameters come from the sealed plan's aggregate policy —
    # never from a caller-tunable argument.
    policy = bank.plans[opportunity.plan_id].aggregate_policy
    strict_result = evaluate_strict_dense_gate(
        [sample.strict_row() for sample in incumbent_samples],
        [sample.strict_row() for sample in candidate_samples],
        min_dense_delta=policy.min_dense_delta,
        partial_tolerance=policy.partial_tolerance,
        bootstrap_samples=policy.bootstrap_samples,
        bootstrap_seed=policy.bootstrap_seed,
    )
    gate_config_sha256 = policy.strict_gate_config_sha256
    report_body = {
        "domain": "sft-pilot-final-val-gate-report-v1",
        "protocol_sha256": protocol.digest,
        "opportunity_id": opportunity.opportunity_id,
        "incumbent_arm": incumbent_arm,
        "candidate_arm": candidate_arm,
        "incumbent_samples": [
            sample.strict_row() for sample in incumbent_samples
        ],
        "candidate_samples": [
            sample.strict_row() for sample in candidate_samples
        ],
        "strict_result": strict_result,
        "gate_config_sha256": gate_config_sha256,
    }
    report_sha256 = canonical_sha256(report_body)

    # The Bank closes the receipt over ITS OWN settled TRAIN strict summary;
    # the external FINAL_VAL report binds the receipt through decision_id
    # (and is persisted in the external result ledger, never in the Bank).
    unsigned = GateReceiptV2(
        decision_id=f"gd:{report_sha256[:24]}",
        opportunity_id=opportunity.opportunity_id,
        deployment_slot_id=opportunity.deployment_slot_id,
        accepted=bool(strict_result["accepted"]),
        incumbent_snapshot_sha256=canonical_sha256(incumbent_snapshot),
        candidate_snapshot_sha256=opportunity.candidate_snapshot_sha256,
        settled_assessment_sha256=assessment.digest,
        gate_config_sha256=gate_config_sha256,
        aggregate_summary_sha256=canonical_sha256(assessment.strict_summary),
        verifier_epoch=authority.verifier_epoch,
        verification_attestation_sha256="0" * 64,
        emitted_seq=bank.to_state().event_seq + 1,
    )
    receipt = authority.attest_gate(unsigned)
    bank.apply_gate(receipt)
    new_head = bank.deployment_heads[opportunity.deployment_slot_id]

    new_loaded = coordinator.checkpoint_loaded(
        loaded,
        operation_id=operation_id,
        operation_request_sha256=(
            operation_request_sha256
            or canonical_sha256(
                {
                    "domain": "sft-pilot-final-val-gate-operation-v1",
                    "report_sha256": report_sha256,
                }
            )
        ),
    )
    checkpoint = new_loaded.snapshot.checkpoint
    if checkpoint is None or checkpoint.checkpoint_kind != "gate_terminal":
        raise RuntimeError("gate application did not settle as gate_terminal")
    promoted = coordinator.promote_settled_checkpoint(
        new_loaded,
        operation_id=f"{operation_id}-promote",
        owner_logical_execution_key=owner_logical_execution_key,
        request_sha256=canonical_sha256(
            {
                "domain": "sft-pilot-final-val-promotion-v1",
                "report_sha256": report_sha256,
            }
        ),
    )
    outcome = FinalValGateOutcome(
        accepted=bool(strict_result["accepted"]),
        receipt=receipt,
        strict_result=strict_result,
        report_sha256=report_sha256,
        active_snapshot_id_before=incumbent_snapshot.snapshot_id,
        active_snapshot_id_after=new_head.active_snapshot_id,
    )
    return outcome, promoted


__all__ = [
    "FinalValCaseSample",
    "FinalValGateOutcome",
    "frozen_final_val_arms",
    "run_final_val_gate",
]
