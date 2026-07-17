"""Method-arm control backends and the policy-enforced gateway (v5 Stage 10).

Every experiment arm operates through one gateway bound to its *own* state
backend: the closed method-capability policy decides which operations exist,
which phases they may run in, and whether the backend is writable at all.  A
control arm is therefore a real adapter — it owns real evidence rows in its
own ledger — never a relabeled SFT arm, and no arm can reach another arm's
backend through this surface.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from exp_graph.mas.factor_bank_v2 import FactorBankV2, ReadOnlyFactorBankV2

from masbench.sft_pilot.method_policy import (
    PilotMethodCapabilityPolicyV2,
    method_capability_policy,
)
from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    canonical_sha256,
    pilot_hmac_sha256,
    require_opaque_id,
    require_sha256,
)


_ROW_DOMAIN = "sft-control-backend-row-v1"
_ZERO = "0" * 64


class ControlEvidenceRowV1(ClosedPilotModel):
    """One safe evidence row owned by a non-Factor control backend."""

    row_version: Literal["sft_control_evidence_row_v1"] = (
        "sft_control_evidence_row_v1"
    )
    backend: Literal[
        "queenbee_skillbank_v1",
        "whole_artifact_bank_v1",
        "ect_transaction_bank_v1",
    ]
    row_ordinal: int = Field(ge=0)
    operation: str
    subject_sha256: str
    outcome_sha256: str
    previous_row_sha256: str
    row_attestation_sha256: str

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        return require_opaque_id(value, field_name="operation")

    @field_validator(
        "subject_sha256",
        "outcome_sha256",
        "previous_row_sha256",
        "row_attestation_sha256",
    )
    @classmethod
    def validate_sha(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class _ChainedControlBackend:
    """Append-only, key-attested in-process control-arm evidence ledger."""

    backend_name: str

    def __init__(self, *, backend_key: bytes) -> None:
        if not isinstance(backend_key, bytes) or len(backend_key) < 32:
            raise ValueError("control backend key must contain at least 32 bytes")
        self._key = bytes(backend_key)
        self._rows: list[ControlEvidenceRowV1] = []

    @property
    def rows(self) -> tuple[ControlEvidenceRowV1, ...]:
        return tuple(self._rows)

    @property
    def evidence_root_sha256(self) -> str:
        return canonical_sha256(
            {
                "domain": "sft-control-backend-root-v1",
                "backend": self.backend_name,
                "rows": tuple(row.digest for row in self._rows),
            }
        )

    def record(
        self, *, operation: str, subject_sha256: str, outcome_sha256: str
    ) -> ControlEvidenceRowV1:
        previous = self._rows[-1].digest if self._rows else _ZERO
        body = {
            "row_version": "sft_control_evidence_row_v1",
            "backend": self.backend_name,
            "row_ordinal": len(self._rows),
            "operation": operation,
            "subject_sha256": subject_sha256,
            "outcome_sha256": outcome_sha256,
            "previous_row_sha256": previous,
        }
        row = ControlEvidenceRowV1(
            **body,
            row_attestation_sha256=pilot_hmac_sha256(
                self._key, domain=_ROW_DOMAIN, value=body
            ),
        )
        self._rows.append(row)
        return row


class QueenBeeSkillBankBackendV1(_ChainedControlBackend):
    backend_name = "queenbee_skillbank_v1"


class WholeArtifactBankV1(_ChainedControlBackend):
    backend_name = "whole_artifact_bank_v1"


class EctTransactionBankV1(_ChainedControlBackend):
    backend_name = "ect_transaction_bank_v1"


_BACKEND_TYPES: dict[str, type] = {
    "queenbee_skillbank_v1": QueenBeeSkillBankBackendV1,
    "whole_artifact_bank_v1": WholeArtifactBankV1,
    "ect_transaction_bank_v1": EctTransactionBankV1,
    "factor_bank_v2": FactorBankV2,
}


class PilotMethodBackendGateway:
    """The only sanctioned surface between one method arm and its backend."""

    def __init__(self, *, method_arm: str, backend: Any) -> None:
        self.policy: PilotMethodCapabilityPolicyV2 = method_capability_policy(
            method_arm
        )
        expected_type = _BACKEND_TYPES.get(self.policy.state_backend)
        if self.policy.state_backend == "none":
            if backend is not None:
                raise TypeError("this method arm owns no state backend")
        elif self.policy.state_write_mode == "observe_only":
            if not isinstance(backend, ReadOnlyFactorBankV2):
                raise TypeError(
                    "observe-only arms accept only the read-only Factor facade"
                )
        elif expected_type is None or not isinstance(backend, expected_type):
            raise TypeError(
                "backend instance does not match the arm's closed backend law"
            )
        self.method_arm = method_arm
        self._backend = backend

    def reader(self) -> Any:
        return self._backend

    def writer(self, operation: str, *, phase: str) -> Any:
        """Return the backend for one authorized mutating operation."""

        self.policy.require_operation(operation, phase=phase)
        self.policy.require_state_write(
            phase=phase, backend=self.policy.state_backend
        )
        return self._backend


def build_control_gateways(
    *,
    method_arms: tuple[str, ...],
    factor_bank: FactorBankV2,
    backend_key: bytes,
) -> dict[str, PilotMethodBackendGateway]:
    """One gateway per arm, each with its own exclusive backend instance."""

    gateways: dict[str, PilotMethodBackendGateway] = {}
    for method_arm in method_arms:
        policy = method_capability_policy(method_arm)
        backend: Any
        if policy.state_backend == "factor_bank_v2":
            backend = (
                factor_bank.read_only_snapshot()
                if policy.state_write_mode == "observe_only"
                else factor_bank
            )
        elif policy.state_backend == "none":
            backend = None
        else:
            backend = _BACKEND_TYPES[policy.state_backend](
                backend_key=backend_key
            )
        gateways[method_arm] = PilotMethodBackendGateway(
            method_arm=method_arm, backend=backend
        )
    return gateways


def verify_equal_all_in_budgets(protocols: tuple[Any, ...]) -> dict[str, Any]:
    """Require identical per-dimension all-in budgets across every arm."""

    if len(protocols) < 2:
        raise ValueError("equal-budget comparison requires at least two arms")
    projections = []
    for protocol in protocols:
        totals = {
            "executions": 0,
            "call_slots": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        for budget in protocol.phase_budgets:
            totals["executions"] += budget.executions
            totals["call_slots"] += budget.call_slots
            totals["input_tokens"] += budget.input_tokens
            totals["output_tokens"] += budget.output_tokens
        projections.append(
            {
                "method_arm": protocol.method_arm,
                "totals": totals,
                "per_phase": {
                    budget.phase: {
                        "executions": budget.executions,
                        "call_slots": budget.call_slots,
                        "input_tokens": budget.input_tokens,
                        "output_tokens": budget.output_tokens,
                    }
                    for budget in protocol.phase_budgets
                },
            }
        )
    reference = projections[0]
    for projection in projections[1:]:
        if projection["totals"] != reference["totals"] or (
            projection["per_phase"] != reference["per_phase"]
        ):
            raise ValueError(
                "method arms do not share equal all-in budgets: "
                f"{projection['method_arm']} differs from "
                f"{reference['method_arm']}"
            )
    return {
        "equal_all_in": True,
        "arms": tuple(item["method_arm"] for item in projections),
        "totals": reference["totals"],
        "budget_root_sha256": canonical_sha256(projections),
    }


__all__ = [
    "ControlEvidenceRowV1",
    "EctTransactionBankV1",
    "PilotMethodBackendGateway",
    "QueenBeeSkillBankBackendV1",
    "WholeArtifactBankV1",
    "build_control_gateways",
    "verify_equal_all_in_budgets",
]
