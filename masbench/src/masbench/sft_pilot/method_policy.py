"""Closed state-backend capability policy for preliminary experiment arms.

An arm name is not an implementation.  This table specifies both the
scientific operations an executable adapter may expose and the exact state
backend that adapter may update.  Generic lifecycle operations deliberately do
not imply FactorBank authority: a current-system operation updates the native
QueenBee SkillBank, while whole-artifact and ECT operations update their own
backends.  Runtime adapters must call ``require_operation`` and
``require_state_write`` before using a Bank-mutating capability.
"""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    PilotMethodArm,
    PilotPhase,
    canonical_sha256,
)


PilotScientificOperation = Literal[
    "retrieve",
    "observe_activation",
    "attribute_factor_evidence",
    "select_proposal",
    "create_action",
    "generate_carrier",
    "commit_probe",
    "record_failure",
    "apply_gate",
    "apply_rollback",
    "archive",
    "final_val_result",
]
PilotProposalLaw = Literal[
    "not_applicable",
    "queenbee_native_reuse_mutate_fresh",
    "whole_artifact",
    "ect_transaction",
    "sft_true_sign",
    "sft_shuffled_sign",
    "sft_uniform_target",
]
PilotFailureLaw = Literal["not_applicable", "full", "disabled"]
PilotDiversityLaw = Literal["not_applicable", "full", "eviction_disabled"]
PilotStateBackend = Literal[
    "queenbee_skillbank_v1",
    "whole_artifact_bank_v1",
    "ect_transaction_bank_v1",
    "factor_bank_v2",
    "none",
]
PilotStateWriteMode = Literal[
    "native_update",
    "whole_artifact_update",
    "ect_transaction_update",
    "factor_update",
    "observe_only",
]


_READ_ONLY = frozenset(
    {"retrieve", "observe_activation", "final_val_result"}
)
_BACKEND_MUTATING = frozenset(
    {
        "retrieve",
        "observe_activation",
        "select_proposal",
        "create_action",
        "generate_carrier",
        "commit_probe",
        "record_failure",
        "apply_gate",
        "apply_rollback",
        "archive",
        "final_val_result",
    }
)
_SFT_MUTATING = _BACKEND_MUTATING | {"attribute_factor_evidence"}

# Closed operation-to-phase law.  This is separate from state-backend
# authority: e.g. ``commit_probe`` can persist an execution receipt without
# granting FactorBank writes, and FINAL_VAL is read/result-only for every arm.
_OPERATION_PHASES: dict[PilotScientificOperation, frozenset[PilotPhase]] = {
    "retrieve": frozenset({"TRAIN_UPDATE", "PROBE", "FINAL_VAL"}),
    "observe_activation": frozenset({"TRAIN_UPDATE", "PROBE", "FINAL_VAL"}),
    "attribute_factor_evidence": frozenset({"PROBE"}),
    "select_proposal": frozenset({"TRAIN_UPDATE"}),
    "create_action": frozenset({"TRAIN_UPDATE"}),
    "generate_carrier": frozenset({"TRAIN_UPDATE"}),
    "commit_probe": frozenset({"PROBE"}),
    "record_failure": frozenset({"TRAIN_UPDATE", "PROBE"}),
    "apply_gate": frozenset({"TRAIN_UPDATE"}),
    "apply_rollback": frozenset({"TRAIN_UPDATE"}),
    "archive": frozenset({"TRAIN_UPDATE"}),
    "final_val_result": frozenset({"FINAL_VAL"}),
}


def _canonical_values(method_arm: PilotMethodArm) -> dict[str, object]:
    """Return the single admitted law for ``method_arm`` without constructing it."""

    if method_arm == "current":
        return {
            "allowed_operations": tuple(sorted(_BACKEND_MUTATING)),
            "proposal_law": "queenbee_native_reuse_mutate_fresh",
            "failure_law": "full",
            "diversity_law": "full",
            "state_backend": "queenbee_skillbank_v1",
            "state_write_mode": "native_update",
        }
    if method_arm == "whole_artifact_receipt":
        return {
            "allowed_operations": tuple(sorted(_BACKEND_MUTATING)),
            "proposal_law": "whole_artifact",
            "failure_law": "full",
            "diversity_law": "full",
            "state_backend": "whole_artifact_bank_v1",
            "state_write_mode": "whole_artifact_update",
        }
    if method_arm == "ect_whole_transaction":
        return {
            "allowed_operations": tuple(sorted(_BACKEND_MUTATING)),
            "proposal_law": "ect_transaction",
            "failure_law": "full",
            "diversity_law": "full",
            "state_backend": "ect_transaction_bank_v1",
            "state_write_mode": "ect_transaction_update",
        }
    if method_arm == "sft_shadow":
        return {
            "allowed_operations": tuple(sorted(_READ_ONLY)),
            "proposal_law": "sft_true_sign",
            "failure_law": "not_applicable",
            "diversity_law": "not_applicable",
            # Shadow observes the same FactorBank representation but receives
            # no capability that can update it.
            "state_backend": "factor_bank_v2",
            "state_write_mode": "observe_only",
        }

    operations = set(_SFT_MUTATING)
    proposal_law: PilotProposalLaw = "sft_true_sign"
    failure_law: PilotFailureLaw = "full"
    diversity_law: PilotDiversityLaw = "full"
    if method_arm == "sft_shuffled_edge":
        proposal_law = "sft_shuffled_sign"
    elif method_arm == "sft_uniform_target":
        proposal_law = "sft_uniform_target"
    elif method_arm == "sft_no_failure_memory":
        operations.remove("record_failure")
        failure_law = "disabled"
    elif method_arm == "sft_no_diversity_eviction":
        diversity_law = "eviction_disabled"
    elif method_arm != "sft_unified":
        raise ValueError(f"unsupported method arm {method_arm!r}")
    return {
        "allowed_operations": tuple(sorted(operations)),
        "proposal_law": proposal_law,
        "failure_law": failure_law,
        "diversity_law": diversity_law,
        "state_backend": "factor_bank_v2",
        "state_write_mode": "factor_update",
    }


class PilotMethodCapabilityPolicyV2(ClosedPilotModel):
    """Exact method adapter law; no operation implies authority for another Bank."""

    policy_version: Literal["sft_pilot_method_capability_v2"] = (
        "sft_pilot_method_capability_v2"
    )
    method_arm: PilotMethodArm
    allowed_operations: tuple[PilotScientificOperation, ...]
    proposal_law: PilotProposalLaw
    failure_law: PilotFailureLaw
    diversity_law: PilotDiversityLaw
    state_backend: PilotStateBackend
    state_write_mode: PilotStateWriteMode
    final_val_bank_writable: Literal[False] = False

    @model_validator(mode="after")
    def validate_policy(self) -> "PilotMethodCapabilityPolicyV2":
        if tuple(sorted(set(self.allowed_operations))) != self.allowed_operations:
            raise ValueError("allowed operations must be unique and canonical")

        actual = self.model_dump(
            mode="python",
            exclude={"policy_version", "method_arm", "final_val_bank_writable"},
        )
        expected = _canonical_values(self.method_arm)
        if actual != expected:
            differing = sorted(
                key
                for key in expected
                if actual.get(key) != expected[key]
            )
            raise ValueError(
                "method policy differs from its closed arm law: "
                + ", ".join(differing)
            )
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)

    @property
    def factor_bank_writable(self) -> bool:
        """Derived Factor capability, never inferred from generic operations."""

        return (
            self.state_backend == "factor_bank_v2"
            and self.state_write_mode == "factor_update"
        )

    @property
    def state_writable(self) -> bool:
        return self.state_write_mode != "observe_only"

    @property
    def backend_capability_sha256(self) -> str:
        """Commit the backend-qualified adapter surface for future authority pins."""

        return canonical_sha256(
            {
                "domain": "sft-pilot-method-backend-capability-v2",
                "policy_sha256": self.digest,
                "state_backend": self.state_backend,
                "state_write_mode": self.state_write_mode,
                "allowed_operations": self.allowed_operations,
            }
        )

    def require_operation(
        self,
        operation: PilotScientificOperation,
        *,
        phase: PilotPhase | None = None,
    ) -> None:
        """Require method capability and, when supplied, its closed phase law.

        ``phase=None`` is retained for structural converters that are not yet
        bound to the executable lifecycle runner.  Executable adapters must
        always pass their phase.
        """

        if operation not in self.allowed_operations:
            raise PermissionError(
                f"method arm {self.method_arm} does not authorize {operation}"
            )
        if phase is not None and phase not in _OPERATION_PHASES[operation]:
            raise PermissionError(
                f"operation {operation} is not legal in phase {phase}"
            )

    def require_state_write(
        self,
        *,
        phase: PilotPhase,
        backend: PilotStateBackend,
    ) -> None:
        """Require an exact backend write capability outside FINAL_VAL."""

        if phase == "FINAL_VAL":
            raise PermissionError("FINAL_VAL cannot write any method Bank")
        if not self.state_writable:
            raise PermissionError(f"method arm {self.method_arm} is observe-only")
        if backend != self.state_backend:
            raise PermissionError(
                f"method arm {self.method_arm} cannot write backend {backend}"
            )


def method_capability_policy(
    method_arm: PilotMethodArm,
) -> PilotMethodCapabilityPolicyV2:
    """Return the only policy admitted for one named method arm."""

    return PilotMethodCapabilityPolicyV2(
        method_arm=method_arm,
        **_canonical_values(method_arm),
    )


__all__ = [
    "PilotMethodCapabilityPolicyV2",
    "PilotScientificOperation",
    "PilotStateBackend",
    "PilotStateWriteMode",
    "method_capability_policy",
]
