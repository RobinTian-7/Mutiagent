"""Single-use pair consumer for FactorBank commits (v5 Stage 5).

One complete outcome-before pair — two authority-signed arm receipts plus the
runner's pair-execution receipt — is consumed exactly once into
``FactorBankV2.commit_attempt`` and immediately checkpointed as
``probe_terminal`` in the single-writer store.  Byte-identical replay is
idempotent; presenting a consumed physical root or receipt id again is an
integrity error surfaced by the Bank's single-use registries; a mis-joined
pair fails loudly *before* anything is consumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from exp_graph.mas.factor_bank_v2 import (
    ArmReceiptV2,
    PairExecutionReceiptV2,
    ProbeAttemptV3,
)


@dataclass(frozen=True)
class ConsumedPhasePair:
    """Result of one single-use pair consumption."""

    attempt: ProbeAttemptV3
    loaded: Any
    replayed: bool


def _require_exact_join(
    attempt: ProbeAttemptV3,
    source_receipt: ArmReceiptV2,
    target_receipt: ArmReceiptV2,
    pair_execution_receipt: PairExecutionReceiptV2,
) -> None:
    if source_receipt.arm != "source" or target_receipt.arm != "target":
        raise ValueError("pair consumer requires one source and one target arm")
    for receipt in (source_receipt, target_receipt):
        if not (
            receipt.plan_id == attempt.plan_id
            and receipt.ordinal == attempt.ordinal
            and receipt.unit_commitment == attempt.assignment.unit_commitment
            and receipt.split == "TRAIN_UPDATE"
        ):
            raise ValueError(
                "arm receipt does not join the exact plan/attempt unit"
            )
        if receipt.pair_execution_receipt_sha256 != pair_execution_receipt.digest:
            raise ValueError("arm receipt binds a foreign pair execution receipt")
    if source_receipt.budget_sha256 != target_receipt.budget_sha256:
        raise ValueError("pair arms carry different frozen budgets")
    if (
        pair_execution_receipt.plan_id != attempt.plan_id
        or pair_execution_receipt.ordinal != attempt.ordinal
    ):
        raise ValueError("pair execution receipt is not this attempt's pair")
    if (
        source_receipt.root_id != pair_execution_receipt.source_root_id
        or target_receipt.root_id != pair_execution_receipt.target_root_id
    ):
        raise ValueError("arm roots differ from the journal pair receipt")
    if (
        source_receipt.observed_arm_order
        != pair_execution_receipt.observed_arm_order
        or target_receipt.observed_arm_order
        != pair_execution_receipt.observed_arm_order
    ):
        raise ValueError("arm receipts disagree on the observed physical order")


def consume_phase_v3_pair_once(
    *,
    loaded: Any,
    coordinator: Any,
    attempt_id: str,
    source_receipt: ArmReceiptV2,
    target_receipt: ArmReceiptV2,
    pair_execution_receipt: PairExecutionReceiptV2,
    operation_id: str,
    operation_request_sha256: str,
) -> ConsumedPhasePair:
    """Atomically commit one complete pair and checkpoint ``probe_terminal``."""

    bank = loaded.bank
    source_receipt = ArmReceiptV2.model_validate(
        source_receipt.model_dump(mode="python")
    )
    target_receipt = ArmReceiptV2.model_validate(
        target_receipt.model_dump(mode="python")
    )
    pair_execution_receipt = PairExecutionReceiptV2.model_validate(
        pair_execution_receipt.model_dump(mode="python")
    )
    attempt = bank.attempts.get(attempt_id)
    if attempt is None:
        raise ValueError("pair consumer requires an existing probe attempt")

    if attempt.state != "open":
        # Byte-identical replay of an already-consumed pair is idempotent;
        # any other terminal shape is a conflict.
        if (
            attempt.source_receipt is not None
            and attempt.target_receipt is not None
            and attempt.source_receipt.receipt_id == source_receipt.receipt_id
            and attempt.target_receipt.receipt_id == target_receipt.receipt_id
            and attempt.pair_execution_receipt is not None
            and attempt.pair_execution_receipt.pair_receipt_id
            == pair_execution_receipt.pair_receipt_id
            and attempt.source_receipt == source_receipt
            and attempt.target_receipt == target_receipt
            and attempt.pair_execution_receipt == pair_execution_receipt
        ):
            return ConsumedPhasePair(
                attempt=attempt, loaded=loaded, replayed=True
            )
        raise ValueError(
            "probe attempt is already settled with different pair evidence"
        )

    _require_exact_join(
        attempt, source_receipt, target_receipt, pair_execution_receipt
    )
    committed = bank.commit_attempt(
        attempt_id,
        source_receipt,
        target_receipt,
        pair_execution_receipt,
    )
    new_loaded = coordinator.checkpoint_loaded(
        loaded,
        operation_id=operation_id,
        operation_request_sha256=operation_request_sha256,
    )
    checkpoint = new_loaded.snapshot.checkpoint
    if checkpoint is None or checkpoint.checkpoint_kind != "probe_terminal":
        raise RuntimeError(
            "pair consumption did not settle into a probe_terminal checkpoint"
        )
    return ConsumedPhasePair(
        attempt=committed, loaded=new_loaded, replayed=False
    )


__all__ = ["ConsumedPhasePair", "consume_phase_v3_pair_once"]
