"""Closed host authority for the SFT pilot's FactorBankV2 lifecycle.

The protocol, not an LLM, reconstructs the six outcome-before pairs, their
balanced order, the assignment manifest, and every execution budget.  Every
later receipt is authenticated with a distinct HMAC domain and is rechecked
on native Bank load.  Proposal-generation context and lease authority are
intentionally absent: states containing either fail closed until that separate
capability is implemented and audited.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from exp_graph.mas.factor_bank import DenseOutcome, ExecutionBudget, ExecutionUsage
from exp_graph.mas.factor_bank_v2 import (
    AggregatePolicyV1,
    ArmReceiptV2,
    AssignmentReceiptV2,
    AttemptCancellationReceiptV3,
    BaseSnapshotReceiptV2,
    FactorBankStateV2,
    GateReceiptV2,
    PairExecutionReceiptV2,
    ProbeAttemptV3,
    ProbePlanV2,
    RollbackTriggerV2,
    RunnerLeaseGrantV1,
    make_assignment_receipt_v2,
    make_pair_execution_receipt_v2,
    make_runner_lease_grant_v1,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    PHASE_FULL_FACTOR_BINDER_VERSION,
    PhaseArtifactRegistry,
    PhaseMaterializationProofRecord,
)
from exp_graph.mas.phase_factor_binding_v2 import (
    RegisteredPhaseFactorEdgeV2,
    make_phase_v2_arm_receipt_verifier,
    make_phase_v2_binding_verifier,
    make_phase_v2_proposal_action_terminal_verifier,
    make_phase_v2_repair_opportunity_verifier,
    make_registered_phase_arm_receipt_v2,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    RegisteredPhaseFactorEdgeV3,
    make_phase_v3_arm_receipt_verifier,
    make_phase_v3_binding_verifier,
    make_phase_v3_proposal_action_terminal_verifier,
    make_phase_v3_repair_opportunity_verifier,
    make_registered_phase_arm_receipt_v3,
)

from masbench.sft_pilot.schema import (
    PilotLogicalArmCoordinatesV1,
    PilotProtocolV1,
    canonical_sha256,
    pilot_hmac_sha256,
    require_sha256,
)
from masbench.sft_pilot.manifests import PilotPairManifestV1


FACTOR_AUTHORITY_VERSION = "sft_pilot_factor_authority_v1"
UNSIGNED_ATTESTATION_SHA256 = "0" * 64

_ASSIGNMENT_DOMAIN = "sft-pilot-factor-assignment-v1"
_RUNNER_LEASE_DOMAIN = "sft-pilot-factor-runner-lease-v1"
_PAIR_EXECUTION_DOMAIN = "sft-pilot-factor-pair-execution-v1"
_CANCELLATION_DOMAIN = "sft-pilot-factor-cancellation-v1"
_PHASE_ARM_DOMAIN = "sft-pilot-factor-phase-arm-v1"
_BASE_SNAPSHOT_DOMAIN = "sft-pilot-factor-base-snapshot-v1"
_GATE_DOMAIN = "sft-pilot-factor-gate-v1"
_ROLLBACK_DOMAIN = "sft-pilot-factor-rollback-v1"
_ARCHIVE_DOMAIN = "sft-pilot-factor-archive-v1"

_SUPPORTED_METHOD_ARMS = frozenset(
    {
        "sft_unified",
        "sft_shadow",
        "sft_shuffled_edge",
        "sft_uniform_target",
        "sft_no_failure_memory",
        "sft_no_diversity_eviction",
    }
)


@dataclass(frozen=True)
class _AuthorizedPair:
    ordinal: int
    pair_id: str
    case_id: str
    source: PilotLogicalArmCoordinatesV1
    target: PilotLogicalArmCoordinatesV1
    unit_commitment: str
    case_commitment_sha256: str
    assignment_unit_commitment_sha256: str
    arm_order: Literal["AB", "BA"]

    @property
    def manifest_value(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "pair_id": self.pair_id,
            "case_id": self.case_id,
            "source": self.source,
            "target": self.target,
            "unit_commitment": self.unit_commitment,
            "case_commitment_sha256": self.case_commitment_sha256,
            "assignment_unit_commitment_sha256": (
                self.assignment_unit_commitment_sha256
            ),
            "arm_order": self.arm_order,
        }


def _reconstruct_authorized_pairs(
    arms: Sequence[PilotLogicalArmCoordinatesV1],
    *,
    pair_manifest: PilotPairManifestV1,
) -> tuple[_AuthorizedPair, ...]:
    """Join the typed pair truth to the only twelve admitted Factor arms."""

    pair_manifest = PilotPairManifestV1.model_validate(
        pair_manifest.model_dump(mode="python")
    )
    if len(pair_manifest.pairs) != 6:
        raise ValueError("factor authority requires exactly six typed pairs")
    validated = tuple(
        PilotLogicalArmCoordinatesV1.model_validate(item.model_dump(mode="python"))
        for item in arms
    )
    if len(validated) != 12:
        raise ValueError(
            "factor authority requires exactly twelve source/target arm coordinates"
        )
    grouped: dict[str, dict[str, PilotLogicalArmCoordinatesV1]] = {}
    for arm in validated:
        if arm.split != "TRAIN_UPDATE":
            raise ValueError("factor authority rejects FINAL_VAL/private probe aliases")
        expected_operation = {
            "source": "source_probe",
            "target": "target_probe",
        }.get(arm.pair_arm)
        if expected_operation is None or arm.operation_kind != expected_operation:
            raise ValueError(
                "factor authority admits only exact source_probe/target_probe arms"
            )
        scoped = grouped.setdefault(arm.pair_id, {})
        if arm.pair_arm in scoped:
            raise ValueError("one logical pair contains a duplicate arm")
        scoped[arm.pair_arm] = arm
    if len(grouped) != 6:
        raise ValueError("factor authority requires exactly six logical pairs")

    typed_by_id = {item.pair_id: item for item in pair_manifest.pairs}
    if set(grouped) != set(typed_by_id):
        raise ValueError("authorized arms differ from the exact typed pair ids")

    by_ordinal: dict[
        int, tuple[str, Mapping[str, PilotLogicalArmCoordinatesV1]]
    ] = {}
    for pair_id, pair_arms in grouped.items():
        if set(pair_arms) != {"source", "target"}:
            raise ValueError("each logical pair must contain source and target")
        source = pair_arms["source"]
        target = pair_arms["target"]
        if not (
            source.case_commitment_sha256 == target.case_commitment_sha256
            and source.unit_commitment == target.unit_commitment
            and source.execution_ordinal == target.execution_ordinal
        ):
            raise ValueError("source/target coordinates do not describe one unit")
        ordinal = source.execution_ordinal
        typed = typed_by_id[pair_id]
        if not (
            typed.execution_ordinal == ordinal
            and typed.unit_commitment == source.unit_commitment
            and typed.case_commitment_sha256
            == source.case_commitment_sha256
        ):
            raise ValueError(
                "authorized arms differ from exact typed pair coordinates"
            )
        if ordinal in by_ordinal:
            raise ValueError("logical pairs reuse an execution ordinal")
        by_ordinal[ordinal] = (pair_id, pair_arms)
    if set(by_ordinal) != set(range(6)):
        raise ValueError("logical pair ordinals must be exactly 0..5")

    pairs: list[_AuthorizedPair] = []
    for ordinal in range(6):
        pair_id, pair_arms = by_ordinal[ordinal]
        source = pair_arms["source"]
        target = pair_arms["target"]
        typed = typed_by_id[pair_id]
        unit_sha256 = canonical_sha256(
            {
                "domain": "sft-pilot-factor-assignment-unit-v2",
                "typed_pair_manifest_sha256": pair_manifest.digest,
                "ordinal": ordinal,
                "pair_id": pair_id,
                "case_id": typed.case_id,
                "unit_commitment": typed.unit_commitment,
                "case_commitment_sha256": typed.case_commitment_sha256,
                "arm_order": typed.arm_order,
                "source": source,
                "target": target,
            }
        )
        pairs.append(
            _AuthorizedPair(
                ordinal=ordinal,
                pair_id=pair_id,
                case_id=typed.case_id,
                source=source,
                target=target,
                unit_commitment=typed.unit_commitment,
                case_commitment_sha256=typed.case_commitment_sha256,
                assignment_unit_commitment_sha256=unit_sha256,
                arm_order=typed.arm_order,
            )
        )
    return tuple(pairs)


def pilot_factor_assignment_schedule_sha256(
    arms: Sequence[PilotLogicalArmCoordinatesV1],
    *,
    pair_manifest: PilotPairManifestV1,
) -> str:
    """Commit Factor's internal assignment schedule under a distinct name."""

    pair_manifest = PilotPairManifestV1.model_validate(
        pair_manifest.model_dump(mode="python")
    )
    pairs = _reconstruct_authorized_pairs(arms, pair_manifest=pair_manifest)
    return canonical_sha256(
        {
            "domain": "sft-pilot-factor-assignment-schedule-v2",
            "typed_pair_manifest_sha256": pair_manifest.digest,
            "pairs": tuple(pair.manifest_value for pair in pairs),
        }
    )


def pilot_factor_pair_manifest_sha256(
    arms: Sequence[PilotLogicalArmCoordinatesV1],
) -> str:
    """Fail closed for the removed protocol-root helper.

    ``PilotProtocolV1.pair_manifest_sha256`` now has exactly one meaning: the
    digest of frozen :class:`PilotPairManifestV1` bytes.  Older callers must
    not substitute Factor's private assignment-schedule commitment.
    """

    del arms
    raise ValueError(
        "removed: pair_manifest_sha256 must equal PilotPairManifestV1.digest; "
        "use pilot_factor_assignment_schedule_sha256 only for Factor internals"
    )


def _without_field(value: Any, field_name: str) -> dict[str, Any]:
    return value.model_dump(mode="python", exclude={field_name})


class SFTPilotFactorAuthority:
    """Deterministic signer/verifier bundle for one exact Phase pilot."""

    uncovered_capabilities: tuple[str, ...] = (
        "proposal_generation_context_verifier",
        "proposal_generation_lease_verifier",
        "proposal_abort_verifier",
    )

    def __init__(
        self,
        protocol: PilotProtocolV1,
        *,
        pair_manifest: PilotPairManifestV1,
        attestation_key: bytes,
    ) -> None:
        self.protocol = PilotProtocolV1.model_validate(
            protocol.model_dump(mode="python")
        )
        if not isinstance(attestation_key, bytes) or len(attestation_key) < 32:
            raise ValueError("factor attestation key must contain at least 32 bytes")
        if self.protocol.method_arm not in _SUPPORTED_METHOD_ARMS:
            raise ValueError("factor authority requires an SFT method arm")
        namespace = self.protocol.namespace
        if not (
            namespace.planner_mode == "program_generate"
            and namespace.payload_format == "phase_program_skill_v1"
            and namespace.worker_contract == "not_applicable"
        ):
            raise ValueError("factor authority is scoped to the exact Phase runtime")
        if namespace.binder_version not in {
            PHASE_FACTOR_BINDER_VERSION,
            PHASE_FULL_FACTOR_BINDER_VERSION,
        }:
            raise ValueError(
                "factor authority requires an explicit leaf-v2 or full-factor-v3 "
                "Phase binder"
            )
        self.pair_manifest = PilotPairManifestV1.model_validate(
            pair_manifest.model_dump(mode="python")
        )
        if self.protocol.pair_manifest_sha256 != self.pair_manifest.digest:
            raise ValueError(
                "protocol pair manifest is not the exact typed manifest"
            )
        self._key = bytes(attestation_key)
        self._pairs = _reconstruct_authorized_pairs(
            self.protocol.authorized_logical_arms,
            pair_manifest=self.pair_manifest,
        )
        self.factor_assignment_schedule_sha256 = (
            pilot_factor_assignment_schedule_sha256(
                self.protocol.authorized_logical_arms,
                pair_manifest=self.pair_manifest,
            )
        )
        probe_budget = next(
            (item for item in self.protocol.phase_budgets if item.phase == "PROBE"),
            None,
        )
        if probe_budget is None or probe_budget.executions != 12:
            raise ValueError("factor probe protocol must authorize twelve executions")
        for field_name in ("call_slots", "input_tokens", "output_tokens"):
            if getattr(probe_budget, field_name) % probe_budget.executions:
                raise ValueError(
                    f"PROBE {field_name} must divide exactly across twelve arms"
                )
        calls = probe_budget.call_slots // probe_budget.executions
        input_tokens = probe_budget.input_tokens // probe_budget.executions
        output_tokens = probe_budget.output_tokens // probe_budget.executions
        self.plan_budget = ExecutionBudget(
            max_messages=calls * 4,
            max_model_calls=calls,
            max_input_tokens=input_tokens,
            max_output_tokens=output_tokens,
            max_wall_time_ms=60_000 * max(1, calls),
            # Fixed conservative pilot accounting coefficients.  They are a
            # hard authorization cap, not a provider list-price claim.
            max_cost_microusd=input_tokens * 10 + output_tokens * 40,
        )
        self.aggregate_policy = AggregatePolicyV1()
        suffix = self.protocol.digest[:24]
        self.verifier_epoch = f"sft-factor-authority:{suffix}"
        self.assignment_producer_epoch = f"sft-assignment:{suffix}"
        self.runner_version = f"sft-runner:{self.protocol.runner_config_sha256[:24]}"
        self.origin_pool_sha256 = canonical_sha256(
            {
                "domain": "sft-pilot-factor-origin-pool-v1",
                "protocol_sha256": self.protocol.digest,
                "source_catalog_sha256": (
                    self.protocol.source_manifest.source_catalog_sha256
                ),
                "source_authority_sha256": self.protocol.source_authority_sha256,
                "candidate_pool_manifest_sha256": (
                    self.protocol.candidate_pool_manifest_sha256
                ),
                "pair_manifest_sha256": self.protocol.pair_manifest_sha256,
                "factor_assignment_schedule_sha256": (
                    self.factor_assignment_schedule_sha256
                ),
            }
        )
        self.assignment_manifest_sha256 = canonical_sha256(
            {
                "domain": "sft-pilot-factor-assignment-manifest-v1",
                "protocol_sha256": self.protocol.digest,
                "namespace_sha256": self.protocol.namespace.digest,
                "runner_config_sha256": self.protocol.runner_config_sha256,
                "model_config_sha256": self.protocol.model_config_sha256,
                "model_name": self.protocol.model_name,
                "runner_version": self.runner_version,
                "runtime_version": self.protocol.namespace.runtime_version,
                "pair_manifest_sha256": self.protocol.pair_manifest_sha256,
                "factor_assignment_schedule_sha256": (
                    self.factor_assignment_schedule_sha256
                ),
                "pairs": tuple(pair.manifest_value for pair in self._pairs),
                "aggregate_policy_sha256": self.aggregate_policy.digest,
                "per_arm_budget": self.plan_budget,
                "per_arm_budget_sha256": self.plan_budget.digest,
            }
        )

    @property
    def unit_commitments(self) -> tuple[str, ...]:
        return tuple(
            pair.assignment_unit_commitment_sha256 for pair in self._pairs
        )

    @property
    def arm_orders(self) -> tuple[Literal["AB", "BA"], ...]:
        return tuple(pair.arm_order for pair in self._pairs)

    def epoch_id_for(
        self,
        *,
        transition_id: str,
    ) -> str:
        digest = canonical_sha256(
            {
                "domain": "sft-pilot-factor-epoch-v1",
                "protocol_sha256": self.protocol.digest,
                "transition_id": transition_id,
                "pair_manifest_sha256": self.protocol.pair_manifest_sha256,
                "factor_assignment_schedule_sha256": (
                    self.factor_assignment_schedule_sha256
                ),
            }
        )
        return f"epoch:{digest[:24]}"

    def _mac(self, domain: str, record: Any, **context: Any) -> str:
        return pilot_hmac_sha256(
            self._key,
            domain=domain,
            value={
                "authority_version": FACTOR_AUTHORITY_VERSION,
                "protocol_sha256": self.protocol.digest,
                "record": record,
                "context": context,
            },
        )

    def verify_plan(self, plan: ProbePlanV2) -> bool:
        try:
            plan = ProbePlanV2.model_validate(plan.model_dump(mode="python"))
            expected_epoch = self.epoch_id_for(
                transition_id=plan.transition_id,
            )
            return bool(
                plan.owner_kind == "direct_factor"
                and plan.split == "TRAIN_UPDATE"
                and plan.namespace_digest == self.protocol.namespace.digest
                and plan.model_name == self.protocol.model_name
                and plan.runtime_version == self.protocol.namespace.runtime_version
                and plan.runner_version == self.runner_version
                and plan.epoch_id == expected_epoch
                and plan.assignment_manifest_sha256
                == self.assignment_manifest_sha256
                and plan.aggregate_policy == self.aggregate_policy
                and plan.aggregate_policy_sha256 == self.aggregate_policy.digest
                and plan.budget == self.plan_budget
                and plan.budget_sha256 == self.plan_budget.digest
                and tuple(unit.unit_commitment for unit in plan.units)
                == self.unit_commitments
                and tuple(unit.arm_order for unit in plan.units) == self.arm_orders
            )
        except (TypeError, ValueError):
            return False

    def assignment_attestation(self, plan: ProbePlanV2, *, ordinal: int) -> str:
        if not self.verify_plan(plan):
            raise ValueError("cannot attest an unauthorized probe plan")
        unsigned = make_assignment_receipt_v2(
            plan=plan,
            ordinal=ordinal,
            origin_pool_sha256=self.origin_pool_sha256,
            producer_epoch=self.assignment_producer_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
        )
        return self._mac(
            _ASSIGNMENT_DOMAIN,
            _without_field(unsigned, "attestation_sha256"),
            plan_sha256=plan.digest,
        )

    def make_assignment(
        self, plan: ProbePlanV2, *, ordinal: int
    ) -> AssignmentReceiptV2:
        attestation = self.assignment_attestation(plan, ordinal=ordinal)
        return make_assignment_receipt_v2(
            plan=plan,
            ordinal=ordinal,
            origin_pool_sha256=self.origin_pool_sha256,
            producer_epoch=self.assignment_producer_epoch,
            attestation_sha256=attestation,
        )

    def verify_assignment(
        self, receipt: AssignmentReceiptV2, plan: ProbePlanV2
    ) -> bool:
        try:
            if not self.verify_plan(plan):
                return False
            expected = self.make_assignment(plan, ordinal=receipt.ordinal)
            return bool(
                receipt == expected
                and hmac.compare_digest(
                    receipt.attestation_sha256,
                    expected.attestation_sha256,
                )
            )
        except (IndexError, TypeError, ValueError):
            return False

    def runner_lease_attestation(
        self,
        *,
        plan: ProbePlanV2,
        assignment: AssignmentReceiptV2,
        runner_session_id: str,
        runner_lease_token_sha256: str,
        journal_anchor_sha256: str,
    ) -> str:
        if not self.verify_assignment(assignment, plan):
            raise ValueError("cannot attest an unauthorized assignment")
        unsigned = make_runner_lease_grant_v1(
            plan=plan,
            assignment=assignment,
            runner_session_id=runner_session_id,
            runner_lease_token_sha256=runner_lease_token_sha256,
            journal_anchor_sha256=journal_anchor_sha256,
            verifier_epoch=self.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
        )
        return self._mac(
            _RUNNER_LEASE_DOMAIN,
            _without_field(unsigned, "attestation_sha256"),
            plan_sha256=plan.digest,
            assignment_sha256=canonical_sha256(assignment),
        )

    def make_runner_lease(
        self,
        *,
        plan: ProbePlanV2,
        assignment: AssignmentReceiptV2,
        runner_session_id: str,
        runner_lease_token_sha256: str,
        journal_anchor_sha256: str,
    ) -> RunnerLeaseGrantV1:
        attestation = self.runner_lease_attestation(
            plan=plan,
            assignment=assignment,
            runner_session_id=runner_session_id,
            runner_lease_token_sha256=runner_lease_token_sha256,
            journal_anchor_sha256=journal_anchor_sha256,
        )
        return make_runner_lease_grant_v1(
            plan=plan,
            assignment=assignment,
            runner_session_id=runner_session_id,
            runner_lease_token_sha256=runner_lease_token_sha256,
            journal_anchor_sha256=journal_anchor_sha256,
            verifier_epoch=self.verifier_epoch,
            attestation_sha256=attestation,
        )

    def verify_runner_lease(
        self,
        lease: RunnerLeaseGrantV1,
        assignment: AssignmentReceiptV2,
        plan: ProbePlanV2,
    ) -> bool:
        try:
            if not self.verify_assignment(assignment, plan):
                return False
            expected = self.make_runner_lease(
                plan=plan,
                assignment=assignment,
                runner_session_id=lease.runner_session_id,
                runner_lease_token_sha256=lease.runner_lease_token_sha256,
                journal_anchor_sha256=lease.journal_anchor_sha256,
            )
            return lease == expected
        except (TypeError, ValueError):
            return False

    def pair_execution_attestation(
        self,
        *,
        plan: ProbePlanV2,
        attempt: ProbeAttemptV3,
        source_root_id: str,
        target_root_id: str,
        source_started_seq: int,
        source_finished_seq: int,
        target_started_seq: int,
        target_finished_seq: int,
    ) -> str:
        if not (
            self.verify_plan(plan)
            and attempt.plan_id == plan.plan_id
            and self.verify_assignment(attempt.assignment, plan)
            and self.verify_runner_lease(
                attempt.runner_lease, attempt.assignment, plan
            )
        ):
            raise ValueError("cannot attest an unauthorized open attempt")
        unsigned = make_pair_execution_receipt_v2(
            attempt=attempt,
            source_root_id=source_root_id,
            target_root_id=target_root_id,
            source_started_seq=source_started_seq,
            source_finished_seq=source_finished_seq,
            target_started_seq=target_started_seq,
            target_finished_seq=target_finished_seq,
            verifier_epoch=self.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
        )
        return self._mac(
            _PAIR_EXECUTION_DOMAIN,
            _without_field(unsigned, "attestation_sha256"),
            plan_sha256=plan.digest,
            open_attempt_sha256=canonical_sha256(attempt),
        )

    def make_pair_execution(
        self,
        *,
        plan: ProbePlanV2,
        attempt: ProbeAttemptV3,
        source_root_id: str,
        target_root_id: str,
        source_started_seq: int,
        source_finished_seq: int,
        target_started_seq: int,
        target_finished_seq: int,
    ) -> PairExecutionReceiptV2:
        arguments = {
            "attempt": attempt,
            "source_root_id": source_root_id,
            "target_root_id": target_root_id,
            "source_started_seq": source_started_seq,
            "source_finished_seq": source_finished_seq,
            "target_started_seq": target_started_seq,
            "target_finished_seq": target_finished_seq,
        }
        attestation = self.pair_execution_attestation(plan=plan, **arguments)
        return make_pair_execution_receipt_v2(
            **arguments,
            verifier_epoch=self.verifier_epoch,
            attestation_sha256=attestation,
        )

    def verify_pair_execution(
        self,
        receipt: PairExecutionReceiptV2,
        attempt: ProbeAttemptV3,
        plan: ProbePlanV2,
    ) -> bool:
        try:
            expected = self.make_pair_execution(
                plan=plan,
                attempt=attempt,
                source_root_id=receipt.source_root_id,
                target_root_id=receipt.target_root_id,
                source_started_seq=receipt.source_started_seq,
                source_finished_seq=receipt.source_finished_seq,
                target_started_seq=receipt.target_started_seq,
                target_finished_seq=receipt.target_finished_seq,
            )
            return receipt == expected
        except (TypeError, ValueError):
            return False

    def phase_arm_attestation(
        self,
        *,
        registry: PhaseArtifactRegistry,
        registered: RegisteredPhaseFactorEdgeV2 | RegisteredPhaseFactorEdgeV3,
        plan: ProbePlanV2,
        attempt: ProbeAttemptV3,
        arm: Literal["source", "target"],
        root_id: str,
        paired_arm_root_id: str,
        pair_execution_receipt: PairExecutionReceiptV2,
        activation_trace_root: str,
        usage: ExecutionUsage,
        execution_class: Literal[
            "completed",
            "algorithm_failure",
            "infrastructure_failure",
            "harness_failure",
        ],
        outcome: DenseOutcome | None,
        safe_failure_code: str | None = None,
        failed_stage_rank: int | None = None,
    ) -> str:
        if not (
            self.verify_plan(plan)
            and attempt.plan_id == plan.plan_id
            and self.verify_pair_execution(
                pair_execution_receipt, attempt, plan
            )
        ):
            raise ValueError("cannot attest an unauthorized Phase arm")
        receipt_factory = self._phase_arm_receipt_factory(registered)
        unsigned = receipt_factory(
            registry=registry,
            registered=registered,
            plan=plan,
            attempt=attempt,
            arm=arm,
            root_id=root_id,
            paired_arm_root_id=paired_arm_root_id,
            pair_execution_receipt=pair_execution_receipt,
            activation_trace_root=activation_trace_root,
            usage=usage,
            execution_class=execution_class,
            outcome=outcome,
            producer_epoch=self.verifier_epoch,
            attestation_sha256=UNSIGNED_ATTESTATION_SHA256,
            safe_failure_code=safe_failure_code,
            failed_stage_rank=failed_stage_rank,
        )
        proof = registry.resolve_proof(registered.proof)
        return self._mac(
            _PHASE_ARM_DOMAIN,
            _without_field(unsigned, "attestation_sha256"),
            phase_proof_sha256=proof.handle.proof_sha256,
        )

    def make_phase_arm_receipt(
        self,
        *,
        registry: PhaseArtifactRegistry,
        registered: RegisteredPhaseFactorEdgeV2 | RegisteredPhaseFactorEdgeV3,
        plan: ProbePlanV2,
        attempt: ProbeAttemptV3,
        arm: Literal["source", "target"],
        root_id: str,
        paired_arm_root_id: str,
        pair_execution_receipt: PairExecutionReceiptV2,
        activation_trace_root: str,
        usage: ExecutionUsage,
        execution_class: Literal[
            "completed",
            "algorithm_failure",
            "infrastructure_failure",
            "harness_failure",
        ],
        outcome: DenseOutcome | None,
        safe_failure_code: str | None = None,
        failed_stage_rank: int | None = None,
    ) -> ArmReceiptV2:
        arguments = {
            "registry": registry,
            "registered": registered,
            "plan": plan,
            "attempt": attempt,
            "arm": arm,
            "root_id": root_id,
            "paired_arm_root_id": paired_arm_root_id,
            "pair_execution_receipt": pair_execution_receipt,
            "activation_trace_root": activation_trace_root,
            "usage": usage,
            "execution_class": execution_class,
            "outcome": outcome,
            "safe_failure_code": safe_failure_code,
            "failed_stage_rank": failed_stage_rank,
        }
        attestation = self.phase_arm_attestation(**arguments)
        receipt_factory = self._phase_arm_receipt_factory(registered)
        return receipt_factory(
            **arguments,
            producer_epoch=self.verifier_epoch,
            attestation_sha256=attestation,
        )

    def _phase_arm_receipt_factory(
        self,
        registered: RegisteredPhaseFactorEdgeV2 | RegisteredPhaseFactorEdgeV3,
    ) -> Any:
        """Select one exact receipt codec; cross-version objects fail closed."""

        binder = self.protocol.namespace.binder_version
        if binder == PHASE_FULL_FACTOR_BINDER_VERSION:
            if not isinstance(registered, RegisteredPhaseFactorEdgeV3):
                raise ValueError("full-factor-v3 protocol rejects a leaf-v2 edge")
            return make_registered_phase_arm_receipt_v3
        if binder == PHASE_FACTOR_BINDER_VERSION:
            if not isinstance(registered, RegisteredPhaseFactorEdgeV2):
                raise ValueError("leaf-v2 protocol rejects a full-factor-v3 edge")
            return make_registered_phase_arm_receipt_v2
        raise RuntimeError("unreachable Phase binder dispatch")

    def _verify_phase_runner_receipt(
        self,
        receipt: ArmReceiptV2,
        proof: PhaseMaterializationProofRecord,
    ) -> bool:
        expected = self._mac(
            _PHASE_ARM_DOMAIN,
            _without_field(receipt, "attestation_sha256"),
            phase_proof_sha256=proof.handle.proof_sha256,
        )
        return bool(
            receipt.producer_epoch == self.verifier_epoch
            and receipt.model_name == self.protocol.model_name
            and receipt.runtime_version == self.protocol.namespace.runtime_version
            and proof.namespace == self.protocol.namespace
            and hmac.compare_digest(receipt.attestation_sha256, expected)
        )

    def attest_cancellation(
        self,
        receipt: AttemptCancellationReceiptV3,
        *,
        attempt: ProbeAttemptV3,
        plan: ProbePlanV2,
    ) -> AttemptCancellationReceiptV3:
        if not (
            self.verify_plan(plan)
            and attempt.plan_id == plan.plan_id
            and self.verify_assignment(attempt.assignment, plan)
            and self.verify_runner_lease(
                attempt.runner_lease, attempt.assignment, plan
            )
            and receipt.attempt_id == attempt.attempt_id
            and receipt.verifier_epoch == self.verifier_epoch
        ):
            raise ValueError("cannot attest an unauthorized cancellation")
        attestation = self._mac(
            _CANCELLATION_DOMAIN,
            _without_field(receipt, "attestation_sha256"),
            plan_sha256=plan.digest,
            open_attempt_sha256=canonical_sha256(attempt),
        )
        return AttemptCancellationReceiptV3.model_validate(
            {
                **receipt.model_dump(mode="python"),
                "attestation_sha256": attestation,
            }
        )

    def verify_cancellation(
        self,
        receipt: AttemptCancellationReceiptV3,
        attempt: ProbeAttemptV3,
        plan: ProbePlanV2,
    ) -> bool:
        try:
            unsigned = AttemptCancellationReceiptV3.model_validate(
                {
                    **receipt.model_dump(mode="python"),
                    "attestation_sha256": UNSIGNED_ATTESTATION_SHA256,
                }
            )
            return receipt == self.attest_cancellation(
                unsigned,
                attempt=attempt,
                plan=plan,
            )
        except (TypeError, ValueError):
            return False

    def attest_base_snapshot(
        self, receipt: BaseSnapshotReceiptV2
    ) -> BaseSnapshotReceiptV2:
        if not (
            receipt.namespace_digest == self.protocol.namespace.digest
            and receipt.runtime_version == self.protocol.namespace.runtime_version
            and receipt.verifier_epoch == self.verifier_epoch
        ):
            raise ValueError("base snapshot crosses the frozen protocol")
        attestation = self._mac(
            _BASE_SNAPSHOT_DOMAIN,
            _without_field(receipt, "attestation_sha256"),
        )
        return BaseSnapshotReceiptV2.model_validate(
            {
                **receipt.model_dump(mode="python"),
                "attestation_sha256": attestation,
            }
        )

    def verify_base_snapshot(
        self, receipt: BaseSnapshotReceiptV2, state: FactorBankStateV2
    ) -> bool:
        try:
            composition = next(
                (
                    item
                    for item in state.compositions
                    if item.composition_id == receipt.composition_id
                ),
                None,
            )
            if composition is None or composition.namespace != self.protocol.namespace:
                return False
            unsigned = BaseSnapshotReceiptV2.model_validate(
                {
                    **receipt.model_dump(mode="python"),
                    "attestation_sha256": UNSIGNED_ATTESTATION_SHA256,
                }
            )
            return receipt == self.attest_base_snapshot(unsigned)
        except (TypeError, ValueError):
            return False

    def attest_gate(self, receipt: GateReceiptV2) -> GateReceiptV2:
        if receipt.verifier_epoch != self.verifier_epoch:
            raise ValueError("gate verifier epoch crosses the frozen protocol")
        attestation = self._mac(
            _GATE_DOMAIN,
            _without_field(receipt, "verification_attestation_sha256"),
        )
        return GateReceiptV2.model_validate(
            {
                **receipt.model_dump(mode="python"),
                "verification_attestation_sha256": attestation,
            }
        )

    def verify_gate(
        self, receipt: GateReceiptV2, state: FactorBankStateV2
    ) -> bool:
        try:
            opportunity = next(
                (
                    item
                    for item in state.gate_opportunities
                    if item.opportunity_id == receipt.opportunity_id
                ),
                None,
            )
            if opportunity is None or opportunity.namespace_digest != (
                self.protocol.namespace.digest
            ):
                return False
            plan = next(
                (item for item in state.plans if item.plan_id == opportunity.plan_id),
                None,
            )
            if plan is None or not self.verify_plan(plan):
                return False
            if receipt.gate_config_sha256 != (
                plan.aggregate_policy.strict_gate_config_sha256
            ):
                return False
            final_budget = next(
                (
                    item
                    for item in self.protocol.phase_budgets
                    if item.phase == "FINAL_VAL"
                ),
                None,
            )
            if final_budget is None or final_budget.executions <= 0:
                return False
            unsigned = GateReceiptV2.model_validate(
                {
                    **receipt.model_dump(mode="python"),
                    "verification_attestation_sha256": (
                        UNSIGNED_ATTESTATION_SHA256
                    ),
                }
            )
            return receipt == self.attest_gate(unsigned)
        except (TypeError, ValueError):
            return False

    def attest_rollback(self, trigger: RollbackTriggerV2) -> RollbackTriggerV2:
        if trigger.verifier_epoch != self.verifier_epoch:
            raise ValueError("rollback verifier epoch crosses the frozen protocol")
        attestation = self._mac(
            _ROLLBACK_DOMAIN,
            _without_field(trigger, "attestation_sha256"),
        )
        return RollbackTriggerV2.model_validate(
            {
                **trigger.model_dump(mode="python"),
                "attestation_sha256": attestation,
            }
        )

    def verify_rollback(
        self, trigger: RollbackTriggerV2, state: FactorBankStateV2
    ) -> bool:
        try:
            head = next(
                (
                    item
                    for item in state.deployment_heads
                    if item.deployment_slot_id == trigger.deployment_slot_id
                ),
                None,
            )
            if head is None or head.namespace_digest != self.protocol.namespace.digest:
                return False
            unsigned = RollbackTriggerV2.model_validate(
                {
                    **trigger.model_dump(mode="python"),
                    "attestation_sha256": UNSIGNED_ATTESTATION_SHA256,
                }
            )
            return trigger == self.attest_rollback(unsigned)
        except (TypeError, ValueError):
            return False

    def archive_attestation(self, merkle_root_sha256: str) -> str:
        require_sha256(merkle_root_sha256, field_name="merkle_root_sha256")
        return self._mac(
            _ARCHIVE_DOMAIN,
            {"merkle_root_sha256": merkle_root_sha256},
        )

    def verify_archive(
        self, merkle_root_sha256: str, archive_attestation_sha256: str
    ) -> bool:
        try:
            expected = self.archive_attestation(merkle_root_sha256)
            return hmac.compare_digest(archive_attestation_sha256, expected)
        except (TypeError, ValueError):
            return False

    def capabilities(self, registry: PhaseArtifactRegistry) -> dict[str, Any]:
        """Return the implemented verifier set, with no permissive callbacks."""

        binder = self.protocol.namespace.binder_version
        if binder == PHASE_FULL_FACTOR_BINDER_VERSION:
            direct_binding_verifier = make_phase_v3_binding_verifier(registry)
            proposal_action_terminal_verifier = (
                make_phase_v3_proposal_action_terminal_verifier(registry)
            )
            repair_opportunity_verifier = (
                make_phase_v3_repair_opportunity_verifier(registry)
            )
            arm_receipt_verifier = make_phase_v3_arm_receipt_verifier(
                registry,
                trusted_runner_verifier=self._verify_phase_runner_receipt,
            )
        elif binder == PHASE_FACTOR_BINDER_VERSION:
            direct_binding_verifier = make_phase_v2_binding_verifier(registry)
            proposal_action_terminal_verifier = (
                make_phase_v2_proposal_action_terminal_verifier(registry)
            )
            repair_opportunity_verifier = (
                make_phase_v2_repair_opportunity_verifier(registry)
            )
            arm_receipt_verifier = make_phase_v2_arm_receipt_verifier(
                registry,
                trusted_runner_verifier=self._verify_phase_runner_receipt,
            )
        else:
            raise RuntimeError("unreachable Phase binder dispatch")

        return {
            "direct_binding_verifier": direct_binding_verifier,
            "proposal_action_terminal_verifier": proposal_action_terminal_verifier,
            "repair_opportunity_verifier": repair_opportunity_verifier,
            "plan_verifier": self.verify_plan,
            "assignment_verifier": self.verify_assignment,
            "runner_lease_verifier": self.verify_runner_lease,
            "arm_receipt_verifier": arm_receipt_verifier,
            "pair_execution_receipt_verifier": self.verify_pair_execution,
            "cancellation_verifier": self.verify_cancellation,
            "base_snapshot_verifier": self.verify_base_snapshot,
            "gate_verifier": self.verify_gate,
            "rollback_verifier": self.verify_rollback,
            "archive_verifier": self.verify_archive,
        }


__all__ = [
    "FACTOR_AUTHORITY_VERSION",
    "SFTPilotFactorAuthority",
    "UNSIGNED_ATTESTATION_SHA256",
    "pilot_factor_assignment_schedule_sha256",
    "pilot_factor_pair_manifest_sha256",
]
