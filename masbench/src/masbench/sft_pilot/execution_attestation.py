"""Exact-artifact execution and isolated scalar-scoring boundary for SFT.

The models in this module contain commitments and scalar metrics only.  In
particular, an execution attestation contains no benchmark outcome or model
text.  It can be issued only from the opaque capability returned by
``masbench.engine.register_exact_phase_execution_result``; the public issuer
does not accept a bag of caller-provided execution fields.

Scoring is a second authority with a distinct key.  TRAIN_UPDATE and
FINAL_VAL receipts are different Python/Pydantic types.  The only Factor
conversion helper accepts the former exact type and joins both authenticated
roots, so a raw :class:`DenseOutcome` or FINAL_VAL receipt cannot enter that
boundary.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Literal

from pydantic import field_validator, model_validator

from exp_graph.mas.factor_bank import DenseOutcome

from masbench.sft_pilot.schema import (
    ClosedPilotModel,
    PilotMethodArm,
    PilotProtocolV1,
    PilotSplit,
    canonical_sha256,
    pilot_hmac_sha256,
    require_opaque_id,
    require_sha256,
)
from masbench.sft_pilot.method_policy import method_capability_policy


EXECUTION_ATTESTATION_VERSION = "sft_pilot_execution_attestation_v1"
OUTCOME_RECEIPT_VERSION = "sft_pilot_outcome_receipt_v1"
FACTOR_ARM_EVIDENCE_VERSION = "sft_pilot_factor_arm_evidence_v1"

_ENGINE_CAPABILITY_DOMAIN = "sft-pilot-engine-exact-phase-capability-v1"
_EXECUTION_ATTESTATION_DOMAIN = "sft-pilot-exact-phase-execution-v1"
_TRAIN_OUTCOME_DOMAIN = "sft-pilot-train-update-outcome-v1"
_FINAL_VAL_OUTCOME_DOMAIN = "sft-pilot-final-val-outcome-v1"

def _key_commitment(*, role: str, key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError(f"{role} key must contain at least 32 bytes")
    return canonical_sha256(
        {
            "domain": "sft-pilot-authority-key-commitment-v1",
            "role": role,
            "key_sha256": hashlib.sha256(key).hexdigest(),
        }
    )


class PilotExecutionCapabilityBodyV1(ClosedPilotModel):
    """Commitment-only body sealed by the exact Phase engine entry."""

    capability_version: Literal["sft_pilot_execution_capability_v1"] = (
        "sft_pilot_execution_capability_v1"
    )
    protocol_sha256: str
    method_arm: PilotMethodArm
    namespace_sha256: str
    planner_mode: Literal["program_generate"] = "program_generate"
    information_goal: Literal["sink", "all_agents"]
    worker_contract: Literal["not_applicable"] = "not_applicable"
    logical_arm_key: str
    logical_arm_sha256: str
    split: PilotSplit
    pair_id: str
    pair_arm: Literal["source", "target"]
    unit_commitment: str
    execution_ordinal: int
    proof_id: str
    proof_sha256: str
    materialization_event_id: str
    materialization_event_sha256: str
    runtime_profile_id: str
    composition_id: str
    selected_artifact_sha256: str
    loaded_artifact_sha256: str
    call_receipt_root_sha256: str
    nonoverlap_event_root_sha256: str
    physical_execution_root_sha256: str
    retrieved_factor_revision_ids: tuple[str, ...]
    activated_factor_revision_ids: tuple[str, ...]
    activation_trace_root_sha256: str
    execution_class: Literal["completed"] = "completed"

    @field_validator(
        "protocol_sha256",
        "namespace_sha256",
        "logical_arm_sha256",
        "proof_sha256",
        "materialization_event_sha256",
        "selected_artifact_sha256",
        "loaded_artifact_sha256",
        "call_receipt_root_sha256",
        "nonoverlap_event_root_sha256",
        "physical_execution_root_sha256",
        "activation_trace_root_sha256",
    )
    @classmethod
    def validate_sha_fields(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator(
        "logical_arm_key",
        "pair_id",
        "unit_commitment",
        "proof_id",
        "materialization_event_id",
        "runtime_profile_id",
        "composition_id",
    )
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @field_validator(
        "retrieved_factor_revision_ids", "activated_factor_revision_ids"
    )
    @classmethod
    def validate_factor_ids(
        cls, value: tuple[str, ...], info: Any
    ) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError(f"{info.field_name} must be canonical and unique")
        for item in value:
            require_opaque_id(item, field_name=info.field_name)
        return value

    @model_validator(mode="after")
    def validate_execution_join(self) -> "PilotExecutionCapabilityBodyV1":
        if self.execution_ordinal < 0 or self.execution_ordinal > 1_000_000:
            raise ValueError("execution ordinal is outside the pilot domain")
        if self.selected_artifact_sha256 != self.loaded_artifact_sha256:
            raise ValueError("selected and loaded exact artifacts differ")
        if not self.activated_factor_revision_ids:
            raise ValueError("completed exact execution requires an activated factor")
        if not set(self.activated_factor_revision_ids).issubset(
            self.retrieved_factor_revision_ids
        ):
            raise ValueError("activated factors must belong to the exact retrieval set")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class PilotExecutionAttestationV1(PilotExecutionCapabilityBodyV1):
    """Outcome-free receipt for one engine-registered exact Phase execution."""

    attestation_version: Literal[EXECUTION_ATTESTATION_VERSION] = (
        EXECUTION_ATTESTATION_VERSION
    )
    engine_key_commitment_sha256: str
    engine_capability_sha256: str
    execution_attestation_sha256: str

    @field_validator(
        "engine_key_commitment_sha256",
        "engine_capability_sha256",
        "execution_attestation_sha256",
    )
    @classmethod
    def validate_attestation_sha(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @property
    def attestation_body(self) -> dict[str, Any]:
        return self.model_dump(
            mode="python", exclude={"execution_attestation_sha256"}
        )

    @property
    def root_sha256(self) -> str:
        return canonical_sha256(self)


class PilotExecutionAttestor:
    """Issue/verify receipts without exposing an arbitrary-field signer."""

    def __init__(self, protocol: PilotProtocolV1, *, engine_key: bytes) -> None:
        self.protocol = PilotProtocolV1.model_validate(
            protocol.model_dump(mode="python")
        )
        if not (
            self.protocol.namespace.planner_mode == "program_generate"
            and self.protocol.namespace.payload_format == "phase_program_skill_v1"
            and self.protocol.namespace.worker_contract == "not_applicable"
        ):
            raise ValueError("execution attestor supports only exact Phase mode")
        _key_commitment(role="exact_phase_engine", key=engine_key)
        self._engine_key = bytes(engine_key)

    def issue(self, capability: Any) -> PilotExecutionAttestationV1:
        """Consume an opaque engine capability, never caller execution fields."""

        # Delayed import avoids making engine import this module recursively.
        from masbench.engine import ExactRegisteredPhaseExecution

        if type(capability) is not ExactRegisteredPhaseExecution:
            raise TypeError(
                "execution attestations require an exact engine capability"
            )
        body, capability_sha256 = capability._export_for_attestation(  # noqa: SLF001
            protocol_sha256=self.protocol.digest,
            engine_key=self._engine_key,
        )
        values = {
            **body.model_dump(mode="python"),
            "attestation_version": EXECUTION_ATTESTATION_VERSION,
            "engine_key_commitment_sha256": _key_commitment(
                role="exact_phase_engine", key=self._engine_key
            ),
            "engine_capability_sha256": capability_sha256,
        }
        attestation = pilot_hmac_sha256(
            self._engine_key,
            domain=_EXECUTION_ATTESTATION_DOMAIN,
            value=values,
        )
        return PilotExecutionAttestationV1(
            **values,
            execution_attestation_sha256=attestation,
        )

    def verify(self, receipt: PilotExecutionAttestationV1) -> bool:
        try:
            checked = PilotExecutionAttestationV1.model_validate(
                receipt.model_dump(mode="python")
            )
            expected_key = _key_commitment(
                role="exact_phase_engine", key=self._engine_key
            )
            body = PilotExecutionCapabilityBodyV1.model_validate(
                checked.model_dump(
                    mode="python",
                    exclude={
                        "attestation_version",
                        "engine_key_commitment_sha256",
                        "engine_capability_sha256",
                        "execution_attestation_sha256",
                    },
                )
            )
            expected_capability = pilot_hmac_sha256(
                self._engine_key,
                domain=_ENGINE_CAPABILITY_DOMAIN,
                value=body,
            )
            expected_attestation = pilot_hmac_sha256(
                self._engine_key,
                domain=_EXECUTION_ATTESTATION_DOMAIN,
                value=checked.attestation_body,
            )
            return bool(
                checked.protocol_sha256 == self.protocol.digest
                and checked.method_arm == self.protocol.method_arm
                and checked.namespace_sha256 == self.protocol.namespace.digest
                and checked.information_goal
                == self.protocol.namespace.information_goal
                and checked.logical_arm_key
                in {
                    item.derive_logical_arm_key(self.protocol)
                    for item in self.protocol.authorized_logical_arms
                }
                and hmac.compare_digest(
                    checked.engine_key_commitment_sha256, expected_key
                )
                and hmac.compare_digest(
                    checked.engine_capability_sha256, expected_capability
                )
                and hmac.compare_digest(
                    checked.execution_attestation_sha256,
                    expected_attestation,
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False


class PilotOutcomeReceiptV1(ClosedPilotModel):
    """Common scalar receipt body; concrete split subclasses are mandatory."""

    receipt_version: Literal[OUTCOME_RECEIPT_VERSION] = OUTCOME_RECEIPT_VERSION
    receipt_kind: Literal["train_update", "final_val"]
    split: PilotSplit
    protocol_sha256: str
    namespace_sha256: str
    logical_arm_key: str
    execution_root_sha256: str
    execution_attestation_sha256: str
    scorer_id: str
    scorer_version_sha256: str
    scorer_key_commitment_sha256: str
    terminal_class: Literal["completed", "algorithm_failure"]
    metrics: DenseOutcome
    scorer_attestation_sha256: str

    @field_validator(
        "protocol_sha256",
        "namespace_sha256",
        "execution_root_sha256",
        "execution_attestation_sha256",
        "scorer_version_sha256",
        "scorer_key_commitment_sha256",
        "scorer_attestation_sha256",
    )
    @classmethod
    def validate_outcome_sha(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("logical_arm_key", "scorer_id")
    @classmethod
    def validate_outcome_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def require_concrete_split_type(self) -> "PilotOutcomeReceiptV1":
        if type(self) is PilotOutcomeReceiptV1:
            raise ValueError("outcome receipt base type is abstract")
        return self

    @property
    def attestation_body(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"scorer_attestation_sha256"})

    @property
    def root_sha256(self) -> str:
        return canonical_sha256(self)


class PilotTrainUpdateOutcomeReceiptV1(PilotOutcomeReceiptV1):
    receipt_kind: Literal["train_update"] = "train_update"
    split: Literal["TRAIN_UPDATE"] = "TRAIN_UPDATE"


class PilotFinalValOutcomeReceiptV1(PilotOutcomeReceiptV1):
    receipt_kind: Literal["final_val"] = "final_val"
    split: Literal["FINAL_VAL"] = "FINAL_VAL"


class PilotOutcomeScorer:
    """Independent scalar authority; raw answers never enter its receipts."""

    def __init__(
        self,
        protocol: PilotProtocolV1,
        *,
        scorer_key: bytes,
        execution_attestor: PilotExecutionAttestor,
        scorer_id: str,
        scorer_version_sha256: str,
    ) -> None:
        self.protocol = PilotProtocolV1.model_validate(
            protocol.model_dump(mode="python")
        )
        _key_commitment(role="isolated_scalar_scorer", key=scorer_key)
        require_opaque_id(scorer_id, field_name="scorer_id")
        require_sha256(
            scorer_version_sha256, field_name="scorer_version_sha256"
        )
        if execution_attestor.protocol.digest != self.protocol.digest:
            raise ValueError("scorer and execution attestor cross protocols")
        if hmac.compare_digest(
            hashlib.sha256(scorer_key).digest(),
            hashlib.sha256(execution_attestor._engine_key).digest(),  # noqa: SLF001
        ):
            raise ValueError("execution and scorer authorities require distinct keys")
        self._scorer_key = bytes(scorer_key)
        self._execution_attestor = execution_attestor
        self._scorer_id = scorer_id
        self._scorer_version_sha256 = scorer_version_sha256

    def _issue(
        self,
        execution: PilotExecutionAttestationV1,
        metrics: DenseOutcome,
        *,
        split: PilotSplit,
        terminal_class: Literal["completed", "algorithm_failure"],
    ) -> PilotOutcomeReceiptV1:
        if not self._execution_attestor.verify(execution):
            raise ValueError("scorer rejects an unauthenticated execution root")
        if execution.split != split:
            raise ValueError("scorer split differs from exact execution")
        checked_metrics = DenseOutcome.model_validate(
            metrics.model_dump(mode="python")
        )
        values = {
            "receipt_version": OUTCOME_RECEIPT_VERSION,
            "receipt_kind": (
                "train_update" if split == "TRAIN_UPDATE" else "final_val"
            ),
            "split": split,
            "protocol_sha256": self.protocol.digest,
            "namespace_sha256": self.protocol.namespace.digest,
            "logical_arm_key": execution.logical_arm_key,
            "execution_root_sha256": execution.root_sha256,
            "execution_attestation_sha256": (
                execution.execution_attestation_sha256
            ),
            "scorer_id": self._scorer_id,
            "scorer_version_sha256": self._scorer_version_sha256,
            "scorer_key_commitment_sha256": _key_commitment(
                role="isolated_scalar_scorer", key=self._scorer_key
            ),
            "terminal_class": terminal_class,
            "metrics": checked_metrics,
        }
        domain = (
            _TRAIN_OUTCOME_DOMAIN
            if split == "TRAIN_UPDATE"
            else _FINAL_VAL_OUTCOME_DOMAIN
        )
        attestation = pilot_hmac_sha256(
            self._scorer_key, domain=domain, value=values
        )
        receipt_type: type[PilotOutcomeReceiptV1] = (
            PilotTrainUpdateOutcomeReceiptV1
            if split == "TRAIN_UPDATE"
            else PilotFinalValOutcomeReceiptV1
        )
        return receipt_type(
            **values,
            scorer_attestation_sha256=attestation,
        )

    def score_train_update(
        self,
        execution: PilotExecutionAttestationV1,
        metrics: DenseOutcome,
        *,
        terminal_class: Literal["completed", "algorithm_failure"] = "completed",
    ) -> PilotTrainUpdateOutcomeReceiptV1:
        receipt = self._issue(
            execution,
            metrics,
            split="TRAIN_UPDATE",
            terminal_class=terminal_class,
        )
        assert type(receipt) is PilotTrainUpdateOutcomeReceiptV1
        return receipt

    def score_final_val(
        self,
        execution: PilotExecutionAttestationV1,
        metrics: DenseOutcome,
        *,
        terminal_class: Literal["completed", "algorithm_failure"] = "completed",
    ) -> PilotFinalValOutcomeReceiptV1:
        receipt = self._issue(
            execution,
            metrics,
            split="FINAL_VAL",
            terminal_class=terminal_class,
        )
        assert type(receipt) is PilotFinalValOutcomeReceiptV1
        return receipt

    def verify(
        self,
        receipt: PilotOutcomeReceiptV1,
        execution: PilotExecutionAttestationV1,
    ) -> bool:
        try:
            if type(receipt) not in {
                PilotTrainUpdateOutcomeReceiptV1,
                PilotFinalValOutcomeReceiptV1,
            }:
                return False
            receipt_type = type(receipt)
            checked = receipt_type.model_validate(receipt.model_dump(mode="python"))
            if not self._execution_attestor.verify(execution):
                return False
            domain = (
                _TRAIN_OUTCOME_DOMAIN
                if type(checked) is PilotTrainUpdateOutcomeReceiptV1
                else _FINAL_VAL_OUTCOME_DOMAIN
            )
            expected = pilot_hmac_sha256(
                self._scorer_key,
                domain=domain,
                value=checked.attestation_body,
            )
            return bool(
                checked.protocol_sha256 == self.protocol.digest
                and checked.namespace_sha256 == self.protocol.namespace.digest
                and checked.split == execution.split
                and checked.logical_arm_key == execution.logical_arm_key
                and checked.execution_root_sha256 == execution.root_sha256
                and checked.execution_attestation_sha256
                == execution.execution_attestation_sha256
                and checked.scorer_id == self._scorer_id
                and checked.scorer_version_sha256
                == self._scorer_version_sha256
                and hmac.compare_digest(
                    checked.scorer_key_commitment_sha256,
                    _key_commitment(
                        role="isolated_scalar_scorer", key=self._scorer_key
                    ),
                )
                and hmac.compare_digest(
                    checked.scorer_attestation_sha256, expected
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False


class PilotFactorArmEvidenceV1(ClosedPilotModel):
    """Verified TRAIN_UPDATE join consumed by a future ArmReceipt adapter."""

    evidence_version: Literal[FACTOR_ARM_EVIDENCE_VERSION] = (
        FACTOR_ARM_EVIDENCE_VERSION
    )
    protocol_sha256: str
    namespace_sha256: str
    logical_arm_key: str
    pair_arm: Literal["source", "target"]
    factor_revision_id: str
    terminal_class: Literal["completed", "algorithm_failure"]
    execution_root_sha256: str
    outcome_root_sha256: str
    activation_trace_root_sha256: str
    metrics: DenseOutcome

    @field_validator(
        "protocol_sha256",
        "namespace_sha256",
        "execution_root_sha256",
        "outcome_root_sha256",
        "activation_trace_root_sha256",
    )
    @classmethod
    def validate_evidence_sha(cls, value: str, info: Any) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("logical_arm_key", "factor_revision_id")
    @classmethod
    def validate_evidence_ids(cls, value: str, info: Any) -> str:
        return require_opaque_id(value, field_name=info.field_name)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


def factor_arm_evidence_from_receipts(
    *,
    protocol: PilotProtocolV1,
    execution: PilotExecutionAttestationV1,
    outcome_receipt: PilotTrainUpdateOutcomeReceiptV1,
    expected_activated_factor_revision_id: str,
    execution_attestor: PilotExecutionAttestor,
    scorer: PilotOutcomeScorer,
) -> PilotFactorArmEvidenceV1:
    """Join execution+score authority; raw outcomes and FINAL_VAL are impossible.

    Runtime exact-type checks intentionally supplement the type annotation so
    a caller cannot pass a FINAL_VAL subclass through ``Any`` or a cast.
    """

    if type(outcome_receipt) is not PilotTrainUpdateOutcomeReceiptV1:
        raise TypeError("Factor conversion accepts TRAIN_UPDATE receipt type only")
    require_opaque_id(
        expected_activated_factor_revision_id,
        field_name="expected_activated_factor_revision_id",
    )
    checked_protocol = PilotProtocolV1.model_validate(
        protocol.model_dump(mode="python")
    )
    method_policy = method_capability_policy(checked_protocol.method_arm)
    try:
        method_policy.require_operation("attribute_factor_evidence")
    except PermissionError as exc:
        raise ValueError("method arm has no Factor-evidence capability") from exc
    if (
        method_policy.failure_law == "disabled"
        and outcome_receipt.terminal_class != "completed"
    ):
        raise ValueError("method arm forbids algorithm-failure memory conversion")
    if not (
        execution_attestor.protocol.digest == checked_protocol.digest
        and scorer.protocol.digest == checked_protocol.digest
        and execution_attestor.verify(execution)
        and scorer.verify(outcome_receipt, execution)
    ):
        raise ValueError("Factor conversion rejects unjoined receipt authorities")
    if execution.split != "TRAIN_UPDATE" or execution.pair_arm not in {
        "source",
        "target",
    }:
        raise ValueError("Factor conversion requires a TRAIN_UPDATE probe arm")
    if expected_activated_factor_revision_id not in (
        execution.activated_factor_revision_ids
    ):
        if expected_activated_factor_revision_id in (
            execution.retrieved_factor_revision_ids
        ):
            raise ValueError("retrieved-but-not-activated factor receives zero credit")
        raise ValueError("factor is absent from the exact execution closure")
    return PilotFactorArmEvidenceV1(
        protocol_sha256=checked_protocol.digest,
        namespace_sha256=checked_protocol.namespace.digest,
        logical_arm_key=execution.logical_arm_key,
        pair_arm=execution.pair_arm,
        factor_revision_id=expected_activated_factor_revision_id,
        terminal_class=outcome_receipt.terminal_class,
        execution_root_sha256=execution.root_sha256,
        outcome_root_sha256=outcome_receipt.root_sha256,
        activation_trace_root_sha256=execution.activation_trace_root_sha256,
        metrics=outcome_receipt.metrics,
    )


__all__ = [
    "PilotExecutionAttestationV1",
    "PilotExecutionAttestor",
    "PilotFactorArmEvidenceV1",
    "PilotFinalValOutcomeReceiptV1",
    "PilotOutcomeReceiptV1",
    "PilotOutcomeScorer",
    "PilotTrainUpdateOutcomeReceiptV1",
    "factor_arm_evidence_from_receipts",
]
