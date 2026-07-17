from __future__ import annotations

import hashlib
import hmac
import json
import threading

import pytest

import exp_graph.mas.factor_bank_v2 as factor_bank_v2_module

from exp_graph.mas.factor_bank import (
    DenseOutcome,
    ExecutionBudget,
    ExecutionNamespace,
    ExecutionUsage,
    FactorLocator,
    SlotBinding,
)
from exp_graph.mas.factor_bank_v2 import (
    AttemptCancellationReceiptV3,
    BaseSnapshotReceiptV2,
    CapacityPolicyV1,
    CompositionRevisionV2,
    FactorBankV2,
    FactorRevisionV2,
    FailureObservationV2,
    GateReceiptV2,
    LegacyStateRejected,
    MAX_PROPOSAL_DECISION_BYTES,
    ProposalActionAbortReceiptV2,
    ProposalActionV2,
    ProposalCarrierAdmissionV1,
    ProposalGenerationContextV1,
    ProposalGenerationRequestV1,
    ProposalLifetimeCounterV1,
    RollbackTriggerV2,
    StartedArmJournalWitnessV2,
    _host_proposal_scheduler_decision_sha256,
    _proposal_conditioned_branch_tiebreak_sha256,
    _proposal_lifetime_counter_root,
    cancellation_event_root_v3,
    make_runner_lease_grant_v1,
    runner_schedule_commitment_v1,
    make_arm_receipt_v2,
    make_assignment_receipt_v2,
    make_pair_execution_receipt_v2,
    make_proposal_action_abort_receipt_v2,
    make_proposal_generation_context_v1,
    make_proposal_generation_lease_v1,
)
from exp_graph.mas.sft_proposal import (
    ExactFactorLocusV1,
    ExactProposalCellV1,
    PortableBackgroundSignV1,
    PortableCandidateV1,
    ProposalCursorV1,
    ProposalRequestV1,
    SFTProposalInputV1,
    proposal_counter_state_sha256,
    select_exact_edge_proposal,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _namespace(*, background: str = "small") -> ExecutionNamespace:
    return ExecutionNamespace(
        task_family="synthetic_count",
        objective="balanced",
        information_goal="sink",
        planner_mode="program_generate",
        payload_format="phase_program_skill_v1",
        worker_contract="not_applicable",
        n_agents=4,
        array_size_bucket=background,
        budget_level="normal",
        model_name="gpt-4o-mini",
        runtime_version="shadow-runtime-v2",
        binder_version="facts-phase-leaf-v2",
        compiler_version="1",
    )


def _budget() -> ExecutionBudget:
    return ExecutionBudget(
        max_messages=16,
        max_model_calls=8,
        max_input_tokens=8_000,
        max_output_tokens=2_000,
        max_wall_time_ms=60_000,
        max_cost_microusd=50_000,
    )


def _usage() -> ExecutionUsage:
    return ExecutionUsage(
        messages=4,
        model_calls=2,
        input_tokens=1_000,
        output_tokens=200,
        wall_time_ms=2_000,
        cost_microusd=2_000,
    )


def _outcome(
    stage: float,
    *,
    V: float,
    K: float = 0.8,
    U: float = 0.8,
    P: float = 0.8,
    S: float = 0.8,
    C: float = 10.0,
    D: float = 1.0,
) -> DenseOutcome:
    return DenseOutcome(V=V, K=K, U=U, P=P, S=S, stage_score=stage, C=C, D=D)


def _runner_lease(plan, assignment, tag: str):
    return make_runner_lease_grant_v1(
        plan=plan,
        assignment=assignment,
        runner_session_id=f"runner-session:{tag}",
        runner_lease_token_sha256=_h(f"runner-lease-token:{tag}"),
        journal_anchor_sha256=_h(f"runner-journal-anchor:{tag}"),
        verifier_epoch="runner-lease-verifier:one",
        attestation_sha256=_h(f"runner-lease-attestation:{tag}"),
    )


class Fixture:
    def __init__(
        self,
        *,
        capacity_policy: CapacityPolicyV1 | None = None,
        cancellation_verifier=None,
        pair_execution_receipt_verifier=None,
        runner_lease_verifier=None,
        proposal_abort_verifier=None,
        proposal_generation_context_verifier=None,
        proposal_generation_lease_verifier=None,
        proposal_action_terminal_verifier=None,
    ) -> None:
        self.key = b"factor-bank-v2-test-key" * 2
        self.bank = FactorBankV2(
            state_key=self.key,
            direct_binding_verifier=lambda *_args: True,
            whole_operation_verifier=lambda *_args: True,
            plan_verifier=lambda _plan: True,
            assignment_verifier=lambda _receipt, _plan: True,
            runner_lease_verifier=(
                runner_lease_verifier
                or (lambda _lease, _assignment, _plan: True)
            ),
            arm_receipt_verifier=lambda _receipt, _plan, _assignment: True,
            pair_execution_receipt_verifier=(
                pair_execution_receipt_verifier
                or (lambda _receipt, _attempt, _plan: True)
            ),
            cancellation_verifier=(
                cancellation_verifier
                or (lambda _receipt, _attempt, _plan: True)
            ),
            proposal_abort_verifier=(
                proposal_abort_verifier
                or (lambda _receipt, _action, _state: True)
            ),
            proposal_generation_context_verifier=(
                proposal_generation_context_verifier
                or (lambda *_args: True)
            ),
            proposal_generation_lease_verifier=(
                proposal_generation_lease_verifier
                or (lambda *_args: True)
            ),
            proposal_action_terminal_verifier=(
                proposal_action_terminal_verifier or (lambda *_args: True)
            ),
            repair_opportunity_verifier=lambda *_args: True,
            gate_verifier=lambda _receipt, _state: True,
            base_snapshot_verifier=lambda _receipt, _state: True,
            rollback_verifier=lambda _trigger, _state: True,
            archive_verifier=lambda _digest, _attestation: True,
            capacity_policy=capacity_policy,
        )
        self.namespace = _namespace()
        self.old = self._factor("instruction:a", "value-a")
        self.new = self._factor("instruction:b", "value-b", parent=self.old.revision_id)
        self.background = self._factor(
            "background:one",
            "background",
            carrier="constraint",
            surface="atomic_artifact",
            path="/background",
            status="locked_atomic",
        )
        self.source = self._composition("composition:a", self.old.revision_id, "artifact-a")
        self.target = self._composition("composition:b", self.new.revision_id, "artifact-b")
        self.transition = self.bank.register_direct_transition(
            source_composition_id=self.source.composition_id,
            target_composition_id=self.target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:one",
            binding_proof_sha256=_h("proof-one"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:one",
            origin_branch="mutate",
        )
        self.base = self.bank.register_base_snapshot(
            BaseSnapshotReceiptV2(
                receipt_id="base:one",
                deployment_slot_id=self.bank.deployment_slot_id(self.namespace),
                namespace_digest=self.namespace.digest,
                composition_id=self.source.composition_id,
                loaded_artifact_sha256=self.source.artifact_sha256,
                binding_map_sha256=_canonical_hash(
                    sorted(self.source.binding_map.items())
                ),
                runtime_version=self.namespace.runtime_version,
                verifier_epoch="base-verifier:one",
                attestation_sha256=_h("base-attestation"),
                emitted_seq=self.bank.to_state().event_seq + 1,
            )
        )
        self.plan = self.bank.seal_probe_plan(
            transition_id=self.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:one",
            unit_commitments=tuple(_h(f"unit-{index}") for index in range(6)),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("assignment-manifest"),
            runner_version="runner:one",
            budget=_budget(),
        )

    def _factor(
        self,
        revision_id: str,
        content: str,
        *,
        parent: str | None = None,
        carrier: str = "phase_program",
        surface: str = "phase_field",
        path: str = "/phases/0/instruction",
        status: str = "proven_factorized",
    ) -> FactorRevisionV2:
        factor = FactorRevisionV2(
            revision_id=revision_id,
            logical_factor_id=(
                "background" if status == "locked_atomic" else "instruction"
            ),
            namespace=self.namespace,
            carrier=carrier,
            locator=FactorLocator(
                surface=surface,
                path=path,
                locator_version="facts-phase-leaf-v2",
            ),
            binding_status=status,
            content_sha256=_h(content),
            parent_revision_id=parent,
            origin_branch="mutate",
            created_seq=self.bank.to_state().event_seq + 1,
        )
        self.bank.add_factor(factor)
        return factor

    def _composition(
        self,
        composition_id: str,
        instruction_factor: str,
        artifact: str,
    ) -> CompositionRevisionV2:
        composition = CompositionRevisionV2(
            composition_id=composition_id,
            namespace=self.namespace,
            carrier="phase_program",
            artifact_revision_id=f"artifact:{composition_id}",
            artifact_sha256=_h(artifact),
            bindings=(
                SlotBinding(
                    slot_id="fixed_background",
                    factor_revision_id=self.background.revision_id,
                ),
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=instruction_factor,
                ),
            ),
            origin_branch="migration",
            canonical_metadata_bytes=256,
            artifact_bytes=512,
            prompt_summary_tokens=32,
            created_seq=self.bank.to_state().event_seq + 1,
        )
        self.bank.add_composition(composition)
        return composition

    def complete(
        self,
        kind: str,
        *,
        tag: str | None = None,
        plan=None,
        transition=None,
        source=None,
        target=None,
        source_updates: dict | None = None,
        target_updates: dict | None = None,
        physical_root_ids: tuple[str, str] | None = None,
        physical_arm_order: str | None = None,
    ):
        plan = plan or self.plan
        transition = transition or self.transition
        source = source or self.source
        target = target or self.target
        ordinal = len(
            [item for item in self.bank.to_state().attempts if item.plan_id == plan.plan_id]
        )
        assignment = make_assignment_receipt_v2(
            plan=plan,
            ordinal=ordinal,
            origin_pool_sha256=_h("origin-pool"),
            producer_epoch="assignment-producer:one",
            attestation_sha256=_h(f"assignment-{ordinal}"),
        )
        tag = tag or f"{kind}-{ordinal}"
        attempt = self.bank.open_next_attempt(
            plan.plan_id,
            assignment,
            _runner_lease(plan, assignment, tag),
        )
        if kind == "benefit":
            source_class, target_class = "completed", "completed"
            before = _outcome(0.50, V=0.50)
            after = _outcome(0.60, V=0.60, C=9.0)
        elif kind == "null":
            source_class, target_class = "completed", "completed"
            before = after = _outcome(0.50, V=0.50)
        elif kind == "harm":
            source_class, target_class = "completed", "completed"
            before = _outcome(0.50, V=0.50)
            after = _outcome(0.40, V=0.40)
        elif kind == "zero":
            source_class, target_class = "completed", "completed"
            before = _outcome(0.0, V=0.0, K=0, U=0, P=0, S=0, C=10)
            after = _outcome(0.0, V=0.0, K=0, U=0, P=0, S=0, C=1)
        elif kind == "both_algorithm_failure":
            source_class = target_class = "algorithm_failure"
            before = _outcome(0.20, V=0.20)
            after = _outcome(0.40, V=0.40)
        elif kind == "target_algorithm_failure":
            source_class, target_class = "completed", "algorithm_failure"
            before = _outcome(0.50, V=0.50)
            after = _outcome(0.0, V=0.0, K=0, U=0, P=0, S=0)
        elif kind == "infrastructure":
            source_class, target_class = "completed", "infrastructure_failure"
            before = _outcome(0.50, V=0.50)
            after = None
        else:
            raise AssertionError(kind)
        source_root_id, target_root_id = physical_root_ids or (
            _h(f"root-{tag}-source"),
            _h(f"root-{tag}-target"),
        )
        physical_arm_order = physical_arm_order or attempt.assignment.arm_order
        if physical_arm_order == "AB":
            source_started, source_finished = 1, 2
            target_started, target_finished = 3, 4
        elif physical_arm_order == "BA":
            target_started, target_finished = 1, 2
            source_started, source_finished = 3, 4
        else:
            raise AssertionError(physical_arm_order)
        pair_receipt = make_pair_execution_receipt_v2(
            attempt=attempt,
            source_root_id=source_root_id,
            target_root_id=target_root_id,
            source_started_seq=source_started,
            source_finished_seq=source_finished,
            target_started_seq=target_started,
            target_finished_seq=target_finished,
            verifier_epoch="pair-runner:one",
            attestation_sha256=_h(f"pair-attestation-{tag}"),
        )

        def receipt(arm: str, execution_class: str, outcome):
            failed = execution_class != "completed"
            return make_arm_receipt_v2(
                plan=plan,
                attempt=attempt,
                composition=source if arm == "source" else target,
                transition=transition,
                arm=arm,
                root_id=(source_root_id if arm == "source" else target_root_id),
                paired_arm_root_id=(
                    target_root_id if arm == "source" else source_root_id
                ),
                pair_execution_receipt=pair_receipt,
                runtime_profile_id="runtime-profile:one",
                materialization_event_id="materialization:one",
                activation_trace_root=_h(f"activation-{tag}-{arm}"),
                usage=_usage(),
                execution_class=execution_class,
                outcome=outcome,
                producer_epoch="receipt-producer:one",
                attestation_sha256=_h(f"receipt-attestation-{tag}-{arm}"),
                safe_failure_code=("safe_failure" if failed else None),
                failed_stage_rank=(2 if execution_class == "algorithm_failure" else None),
            )

        source_receipt = receipt("source", source_class, before)
        target_receipt = receipt("target", target_class, after)
        if source_updates:
            source_receipt = source_receipt.model_copy(update=source_updates)
        if target_updates:
            target_receipt = target_receipt.model_copy(update=target_updates)
        return self.bank.commit_attempt(
            attempt.attempt_id,
            source_receipt,
            target_receipt,
            pair_receipt,
        )

    def gate(self, accepted: bool = True):
        opportunity = next(
            item for item in self.bank.to_state().gate_opportunities
            if item.plan_id == self.plan.plan_id and item.state == "pending"
        )
        assessment = self.bank.assessments[self.plan.plan_id]
        head = self.bank.deployment_heads[opportunity.deployment_slot_id]
        incumbent = next(
            item for item in self.bank.to_state().deployment_snapshots
            if item.snapshot_id == head.active_snapshot_id
        )
        return self.bank.apply_gate(
            GateReceiptV2(
                decision_id="gate:one",
                opportunity_id=opportunity.opportunity_id,
                deployment_slot_id=opportunity.deployment_slot_id,
                accepted=accepted,
                incumbent_snapshot_sha256=_canonical_hash(incumbent),
                candidate_snapshot_sha256=opportunity.candidate_snapshot_sha256,
                settled_assessment_sha256=assessment.digest,
                gate_config_sha256=_h("strict-gate-config"),
                aggregate_summary_sha256=_canonical_hash(
                    assessment.strict_summary
                ),
                verifier_epoch="gate-verifier:one",
                verification_attestation_sha256=_h("gate-attestation"),
                emitted_seq=self.bank.to_state().event_seq + 1,
            )
        )


def _repair_opportunity(
    fixture: Fixture,
    suffix: str,
    *,
    feasible_branches=("reuse", "mutate", "fresh"),
):
    observation = FailureObservationV2(
        failure_id=f"failure:proposal:{suffix}",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=fixture.source.composition_id,
        artifact_sha256=fixture.source.artifact_sha256,
        created_seq=fixture.bank.to_state().event_seq + 1,
    )
    opportunity = fixture.bank.record_failure(
        observation,
        feasible_branches=feasible_branches,
    )
    assert opportunity is not None
    return opportunity


def _proposal_receipt(
    fixture: Fixture,
    opportunity,
    *,
    cursor: ProposalCursorV1 | None = None,
    include_target: bool = True,
    background_signs=None,
):
    locus = ExactFactorLocusV1(
        carrier="phase_program",
        slot_id="instruction_slot",
        logical_factor_id=fixture.old.logical_factor_id,
        locator_surface="phase_field",
        locator_path=fixture.old.locator.path,
        locator_version=fixture.old.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=fixture.old.revision_id,
        canonical_from_factor_key_sha256=(
            fixture.bank._factor_carrier_key_sha256(fixture.old)
        ),
        canonical_background_sha256=(
            fixture.bank._canonical_direct_background_sha256(
                fixture.bank.to_state(),
                source=fixture.source,
                source_factor=fixture.old,
                slot_id=locus.slot_id,
            )
        ),
    )
    candidates = ()
    if include_target:
        signs = (
            fixture.bank._proposal_portable_signs(
                slot_id=locus.slot_id,
                from_revision_id=fixture.old.revision_id,
                to_revision_id=fixture.new.revision_id,
            )
            if background_signs is None
            else tuple(background_signs)
        )
        candidates = (
            PortableCandidateV1(
                target_revision_id=fixture.new.revision_id,
                target_factor_key_sha256=(
                    fixture.bank._factor_carrier_key_sha256(fixture.new)
                ),
                target_content_sha256=fixture.new.content_sha256,
                lineage_niche=fixture.bank._proposal_lineage_niche(fixture.new),
                background_signs=signs,
            ),
        )
    state = fixture.bank.to_state()
    return select_exact_edge_proposal(
        SFTProposalInputV1(
            request=ProposalRequestV1(
                opportunity_id=opportunity.opportunity_id,
                cell=cell,
            ),
            cursor=cursor or ProposalCursorV1.empty(cell),
            candidates=candidates,
            proposal_counter_state_sha256=proposal_counter_state_sha256(
                tuple(
                    item.witness
                    for item in state.proposal_lifetime_counters
                    if item.cell_sha256 == cell.scheduler_key_sha256
                )
            ),
            candidate_counter_witnesses=(
                fixture.bank._proposal_counter_witnesses(
                    state,
                    cell_sha256=cell.scheduler_key_sha256,
                    candidates=candidates,
                )
            ),
        )
    )


def _host_proposal_input(
    fixture: Fixture,
    *,
    request: ProposalRequestV1,
    cursor: ProposalCursorV1,
    candidates: tuple[PortableCandidateV1, ...],
) -> SFTProposalInputV1:
    state = fixture.bank.to_state()
    return SFTProposalInputV1(
        request=request,
        cursor=cursor,
        candidates=candidates,
        proposal_counter_state_sha256=proposal_counter_state_sha256(
            tuple(
                item.witness
                for item in state.proposal_lifetime_counters
                if item.cell_sha256 == request.cell.scheduler_key_sha256
            )
        ),
        candidate_counter_witnesses=(
            fixture.bank._proposal_counter_witnesses(
                state,
                cell_sha256=request.cell.scheduler_key_sha256,
                candidates=candidates,
            )
        ),
    )


def _generation_context(
    fixture: Fixture,
    opportunity,
    proposal,
    *,
    tag: str = "default",
) -> ProposalGenerationContextV1:
    failure = next(
        item
        for item in fixture.bank.to_state().failures
        if item.created_seq == opportunity.created_seq
        and item.composition_id == opportunity.source_composition_id
    )
    return make_proposal_generation_context_v1(
        opportunity=opportunity,
        failure=failure,
        proposal_receipt=proposal,
        source=fixture.source,
        source_factor=fixture.old,
        source_manifest_sha256=_h(f"manifest:{tag}"),
        train_update_source_catalog_sha256=_h(f"catalog:{tag}"),
        train_update_policy_sha256=_h(f"train-policy:{tag}"),
        generation_policy_sha256=_h(f"generation-policy:{tag}"),
        prompt_template_sha256=_h(f"prompt-template:{tag}"),
        scalar_output_schema_sha256=_h(f"scalar-schema:{tag}"),
        budget=ExecutionBudget(
            max_messages=1,
            max_model_calls=1,
            max_input_tokens=1024,
            max_output_tokens=64,
            max_wall_time_ms=30_000,
            max_cost_microusd=1_000,
        ),
        verifier_epoch="generation-context-verifier:one",
        attestation_sha256=_h(f"generation-context-attestation:{tag}"),
    )


def _prepare_generated_action(
    fixture: Fixture,
    branch: str,
    tag: str,
):
    opportunity = _repair_opportunity(
        fixture,
        tag,
        feasible_branches=(branch,),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    context = _generation_context(fixture, opportunity, proposal, tag=tag)
    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch=f"proposal-host:{tag}",
        attestation_sha256=_h(f"proposal-action:{tag}"),
        generation_context=context,
    )
    assert assignment is not None and action is not None
    return opportunity, proposal, context, decision, assignment, action


def _generation_lease(action: ProposalActionV2, tag: str):
    return make_proposal_generation_lease_v1(
        action=action,
        runner_session_id=f"generation-runner:{tag}",
        runner_lease_token_sha256=_h(f"generation-token:{tag}"),
        journal_anchor_sha256=_h(f"generation-journal:{tag}"),
        verifier_epoch="generation-lease-verifier:one",
        attestation_sha256=_h(f"generation-lease-attestation:{tag}"),
    )


def _uninstalled_generated_carrier(
    fixture: Fixture,
    branch: str,
    tag: str,
) -> tuple[FactorRevisionV2, CompositionRevisionV2]:
    """Build the exact rows which the action bundle must install atomically."""

    next_seq = fixture.bank.to_state().event_seq + 1
    generated = FactorRevisionV2(
        revision_id=f"instruction:generated-recovery:{tag}",
        logical_factor_id=fixture.old.logical_factor_id,
        namespace=fixture.namespace,
        carrier=fixture.old.carrier,
        locator=fixture.old.locator,
        binding_status=fixture.old.binding_status,
        content_sha256=_h(f"generated-recovery-value:{tag}"),
        parent_revision_id=(
            fixture.old.revision_id if branch == "mutate" else None
        ),
        origin_branch=branch,
        created_seq=next_seq,
    )
    target = CompositionRevisionV2(
        composition_id=f"composition:generated-recovery:{tag}",
        namespace=fixture.namespace,
        carrier=fixture.source.carrier,
        artifact_revision_id=f"artifact:generated-recovery:{tag}",
        artifact_sha256=_h(f"generated-recovery-artifact:{tag}"),
        bindings=(
            SlotBinding(
                slot_id="fixed_background",
                factor_revision_id=fixture.background.revision_id,
            ),
            SlotBinding(
                slot_id="instruction_slot",
                factor_revision_id=generated.revision_id,
            ),
        ),
        origin_branch=branch,
        canonical_metadata_bytes=256,
        artifact_bytes=512,
        prompt_summary_tokens=32,
        created_seq=next_seq + 1,
    )
    return generated, target


def _register_action_bundle(
    fixture: Fixture,
    *,
    action: ProposalActionV2,
    branch: str,
    tag: str,
    generated: FactorRevisionV2,
    target: CompositionRevisionV2,
    proof_sha256: str,
):
    return fixture.bank.register_direct_bundle(
        factors=(generated,),
        compositions=(target,),
        transition_fields={
            "source_composition_id": fixture.source.composition_id,
            "target_composition_id": target.composition_id,
            "slot_id": "instruction_slot",
            "binding_proof_id": f"proof:generated-recovery:{tag}",
            "binding_proof_sha256": proof_sha256,
            "masked_background_sha256": _h("masked-background"),
            "binding_verifier_epoch": "binder:generated-recovery",
            "origin_branch": branch,
            "proposal_action_id": action.action_id,
            "proposal_action_intent_sha256": action.action_intent_sha256,
        },
    )


def _project_generated_edge(fixture: Fixture, branch: str, tag: str):
    *_prefix, prepared = _prepare_generated_action(fixture, branch, tag)
    executing = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, tag),
    )
    generated, target = _uninstalled_generated_carrier(fixture, branch, tag)
    proof_sha256 = _h(f"generated-recovery-proof:{tag}")
    transition = _register_action_bundle(
        fixture,
        action=executing,
        branch=branch,
        tag=tag,
        generated=generated,
        target=target,
        proof_sha256=proof_sha256,
    )
    return executing, generated, target, transition, proof_sha256


def _admission_for_edge(bank: FactorBankV2, transition) -> ProposalCarrierAdmissionV1:
    return next(
        item
        for item in bank.to_state().proposal_carrier_admissions
        if item.transition_id == transition.transition_id
    )


def _carrier_reservation_for_action(bank: FactorBankV2, action):
    return next(
        item
        for item in bank.to_state().proposal_carrier_reservations
        if item.action_id == action.action_id
    )


def _rewrite_admission(
    admission: ProposalCarrierAdmissionV1,
    **updates,
) -> ProposalCarrierAdmissionV1:
    payload = admission.model_dump(mode="python")
    payload.update(updates)
    identity = dict(payload)
    for field in ("admission_id", "state", "terminal_seq", "terminal_sha256"):
        identity.pop(field)
    payload["admission_id"] = f"pca:{_canonical_hash(identity)[:24]}"
    return ProposalCarrierAdmissionV1.model_validate(payload)


def _retarget_cleanup_receipt(
    receipt: ProposalActionAbortReceiptV2,
    transition,
    admission: ProposalCarrierAdmissionV1,
) -> ProposalActionAbortReceiptV2:
    body = receipt.model_dump(
        mode="python",
        exclude={"abort_id", "emitted_seq"},
    )
    body.update(
        {
            "cleanup_transition_id": transition.transition_id,
            "cleanup_transition_sha256": _canonical_hash(transition),
            "cleanup_admission_id": admission.admission_id,
            "cleanup_admission_sha256": _canonical_hash(admission),
        }
    )
    return ProposalActionAbortReceiptV2.model_validate(
        {
            "abort_id": f"pab:{_canonical_hash(body)[:24]}",
            **body,
        }
    )


def _trusted_bank_capabilities():
    return {
        "direct_binding_verifier": lambda *_args: True,
        "whole_operation_verifier": lambda *_args: True,
        "plan_verifier": lambda *_args: True,
        "assignment_verifier": lambda *_args: True,
        "runner_lease_verifier": lambda *_args: True,
        "arm_receipt_verifier": lambda *_args: True,
        "pair_execution_receipt_verifier": lambda *_args: True,
        "cancellation_verifier": lambda *_args: True,
        "proposal_generation_context_verifier": lambda *_args: True,
        "proposal_generation_lease_verifier": lambda *_args: True,
        "proposal_abort_verifier": lambda *_args: True,
        "proposal_action_terminal_verifier": lambda *_args: True,
        "repair_opportunity_verifier": lambda *_args: True,
        "gate_verifier": lambda *_args: True,
        "base_snapshot_verifier": lambda *_args: True,
        "rollback_verifier": lambda *_args: True,
        "archive_verifier": lambda *_args: True,
    }


def _open_next(fixture: Fixture):
    ordinal = len(
        [
            item
            for item in fixture.bank.to_state().attempts
            if item.plan_id == fixture.plan.plan_id
        ]
    )
    assignment = make_assignment_receipt_v2(
        plan=fixture.plan,
        ordinal=ordinal,
        origin_pool_sha256=_h("origin-pool"),
        producer_epoch="assignment-producer:one",
        attestation_sha256=_h(f"cancel-assignment-{ordinal}"),
    )
    return fixture.bank.open_next_attempt(
        fixture.plan.plan_id,
        assignment,
        _runner_lease(fixture.plan, assignment, f"cancel-{ordinal}"),
    )


def _cancellation(
    fixture: Fixture,
    attempt,
    *,
    terminate_scope: bool = False,
    attestation: str | None = None,
    started_root_id: str | None = None,
    second_started_root_id: str | None = None,
    started_arm: str | None = None,
    runner_session_id: str | None = None,
    fencing_generation: int = 1,
    cancel_kind: str = "infrastructure",
) -> AttemptCancellationReceiptV3:
    scheduled_arm_order = attempt.assignment.arm_order
    runner_session_id = runner_session_id or attempt.runner_lease.runner_session_id
    schedule_event_id = f"cancel-schedule:{attempt.ordinal}"
    base_seq = 10 + attempt.ordinal * 10
    assignment_sha256 = _canonical_hash(attempt.assignment)
    open_sha256 = _canonical_hash(attempt)
    schedule_sha256 = runner_schedule_commitment_v1(
        expected_open_attempt_sha256=open_sha256,
        assignment_receipt_sha256=assignment_sha256,
        plan_id=attempt.plan_id,
        ordinal=attempt.ordinal,
        scheduled_arm_order=scheduled_arm_order,
        runner_session_id=runner_session_id,
        runner_lease_token_sha256=attempt.runner_lease.runner_lease_token_sha256,
        fencing_generation=fencing_generation,
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        prestart_schedule_event_id=schedule_event_id,
        prestart_schedule_event_seq=base_seq,
    )
    witnesses = ()
    if started_root_id is not None:
        witnesses = (
            StartedArmJournalWitnessV2(
                arm=started_arm
                or ("source" if scheduled_arm_order == "AB" else "target"),
                root_id=started_root_id,
                start_event_id=f"cancel-start:{attempt.ordinal}",
                start_event_seq=base_seq + 1,
                finish_event_id=(
                    f"cancel-finish:{attempt.ordinal}"
                    if second_started_root_id is not None
                    else None
                ),
                finish_event_seq=(
                    base_seq + 2 if second_started_root_id is not None else None
                ),
            ),
        )
        terminate_scope = True
    if second_started_root_id is not None:
        if started_root_id is None:
            raise AssertionError("second start requires the scheduled first start")
        witnesses = (
            *witnesses,
            StartedArmJournalWitnessV2(
                arm=("target" if scheduled_arm_order == "AB" else "source"),
                root_id=second_started_root_id,
                start_event_id=f"cancel-second-start:{attempt.ordinal}",
                start_event_seq=base_seq + 3,
            ),
        )
    abort_event_id = f"cancel-abort:{attempt.ordinal}"
    abort_seq = base_seq + (4 if second_started_root_id is not None else 2)
    event_root = cancellation_event_root_v3(
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        schedule_commitment_sha256=schedule_sha256,
        started_arm_roots=witnesses,
        abort_event_id=abort_event_id,
        abort_event_seq=abort_seq,
        cancel_kind=cancel_kind,
        safe_failure_code="runner_unavailable",
        terminate_scope=terminate_scope,
        runner_lease_token_sha256=attempt.runner_lease.runner_lease_token_sha256,
        fencing_generation=fencing_generation,
        next_fencing_generation=fencing_generation + 1,
    )
    cancellation_id = "ac:" + _canonical_hash(
        {
            "attempt": open_sha256,
            "runner_lease": attempt.runner_lease.digest,
            "terminal_event_root": event_root,
        }
    )[:24]
    return AttemptCancellationReceiptV3(
        cancellation_id=cancellation_id,
        attempt_id=attempt.attempt_id,
        plan_id=attempt.plan_id,
        ordinal=attempt.ordinal,
        assignment_receipt_sha256=assignment_sha256,
        expected_opened_seq=attempt.opened_seq,
        expected_open_attempt_sha256=open_sha256,
        scheduled_arm_order=scheduled_arm_order,
        runner_lease_sha256=attempt.runner_lease.digest,
        runner_session_id=runner_session_id,
        runner_lease_token_sha256=attempt.runner_lease.runner_lease_token_sha256,
        fencing_generation=fencing_generation,
        next_fencing_generation=fencing_generation + 1,
        journal_anchor_sha256=attempt.runner_lease.journal_anchor_sha256,
        prestart_schedule_event_id=schedule_event_id,
        prestart_schedule_event_seq=base_seq,
        schedule_commitment_sha256=schedule_sha256,
        started_arm_roots=witnesses,
        abort_event_id=abort_event_id,
        abort_event_seq=abort_seq,
        runner_event_root_sha256=event_root,
        cancel_kind=cancel_kind,
        safe_failure_code="runner_unavailable",
        terminate_scope=terminate_scope,
        verifier_epoch="cancel-verifier:one",
        attestation_sha256=attestation or _h(f"cancel-{attempt.ordinal}"),
    )


def _record_algorithm_failure(
    fixture: Fixture,
    tag: str,
    *,
    composition: CompositionRevisionV2 | None = None,
    transition_id: str | None = None,
):
    composition = composition or fixture.target
    return fixture.bank.record_failure(
        FailureObservationV2(
            failure_id=f"failure:{tag}",
            failure_class="algorithm",
            failed_stage="program_generate",
            safe_failure_code=f"safe_failure_{tag}",
            composition_id=composition.composition_id,
            transition_id=(
                fixture.transition.transition_id
                if transition_id is None and composition == fixture.target
                else transition_id
            ),
            artifact_sha256=composition.artifact_sha256,
            created_seq=fixture.bank.to_state().event_seq + 1,
        ),
        feasible_branches=("reuse", "mutate", "fresh"),
    )


def _add_sibling_transition_and_plan(fixture: Fixture, suffix: str):
    factor = fixture._factor(
        f"instruction:{suffix}",
        f"value-{suffix}",
        parent=fixture.old.revision_id,
    )
    target = fixture._composition(
        f"composition:{suffix}", factor.revision_id, f"artifact-{suffix}"
    )
    transition = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id=f"proof:{suffix}",
        binding_proof_sha256=_h(f"proof-{suffix}"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:one",
        origin_branch="mutate",
    )
    plan = fixture.bank.seal_probe_plan(
        transition_id=transition.transition_id,
        owner_kind="direct_factor",
        epoch_id=f"epoch:{suffix}",
        unit_commitments=tuple(_h(f"{suffix}-unit-{index}") for index in range(6)),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_h(f"assignment-manifest-{suffix}"),
        runner_version="runner:one",
        budget=_budget(),
    )
    return transition, target, plan


def _settle_candidate(
    fixture: Fixture,
    *,
    suffix: str,
    transition,
    target,
    plan,
) -> None:
    for index, vote in enumerate(("benefit", "benefit", "null", "benefit")):
        fixture.complete(
            vote,
            tag=f"{suffix}-{index}",
            plan=plan,
            transition=transition,
            target=target,
        )


def test_two_benefits_remain_neutral_until_target_complete_count() -> None:
    fixture = Fixture()
    fixture.complete("benefit")
    fixture.complete("benefit")

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.label == "neutral"
    assert not assessment.settled
    assert fixture.bank.to_state().gate_opportunities == ()


def test_p_p_n_reverts_neutral_without_touching_factor_content() -> None:
    fixture = Fixture()
    before_factors = fixture.bank.to_state().factors
    fixture.complete("benefit")
    fixture.complete("benefit")
    fixture.complete("null")

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.label == "neutral"
    assert not assessment.settled
    assert fixture.bank.to_state().factors == before_factors
    assert fixture.bank.to_state().gate_opportunities == ()


def test_p_p_n_p_settles_and_gate_only_swaps_deployment_head() -> None:
    fixture = Fixture()
    for vote in ("benefit", "benefit", "null", "benefit"):
        fixture.complete(vote)
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.label == "candidate"
    assert assessment.settled
    assert len(
        [item for item in fixture.bank.to_state().gate_opportunities if item.state == "pending"]
    ) == 1
    before = fixture.bank.to_state()

    head = fixture.gate(True)
    after = fixture.bank.to_state()

    assert head is not None
    assert before.factors == after.factors
    assert before.compositions == after.compositions
    assert before.assessments == after.assessments
    assert fixture.bank.retrieve(fixture.namespace)[0].composition_id == (
        fixture.target.composition_id
    )


def test_probe_epoch_cannot_reuse_same_transition_unit_commitments() -> None:
    fixture = Fixture()
    before = fixture.bank.to_state()
    reused = [item.unit_commitment for item in fixture.plan.units]
    reused[1:] = [_h(f"new-unit-{index}") for index in range(1, 6)]

    with pytest.raises(ValueError, match="reuses a unit commitment"):
        fixture.bank.seal_probe_plan(
            transition_id=fixture.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:reused-unit",
            unit_commitments=tuple(reused),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("reused-unit-manifest"),
            runner_version="runner:one",
            budget=_budget(),
        )

    assert fixture.bank.to_state() == before


def test_harm_poison_is_transition_scoped_and_new_transition_may_probe() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure")

    with pytest.raises(ValueError, match="new transition, not a new epoch"):
        fixture.bank.seal_probe_plan(
            transition_id=fixture.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:after-harm",
            unit_commitments=tuple(_h(f"after-harm-{index}") for index in range(6)),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("after-harm-manifest"),
            runner_version="runner:one",
            budget=_budget(),
        )

    superseding, _target, superseding_plan = _add_sibling_transition_and_plan(
        fixture, "superseding"
    )
    assert superseding.transition_id != fixture.transition.transition_id
    assert superseding_plan.transition_id == superseding.transition_id


def test_unsettled_canonical_edge_cannot_preseal_another_epoch() -> None:
    fixture = Fixture()
    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="zero-complete infrastructure retry"):
        fixture.bank.seal_probe_plan(
            transition_id=fixture.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:presealed",
            unit_commitments=tuple(_h(f"presealed-{index}") for index in range(6)),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("presealed-manifest"),
            runner_version="runner:one",
            budget=_budget(),
        )
    assert fixture.bank.to_state() == before


def test_only_zero_complete_infrastructure_epochs_retry_and_cap_at_three() -> None:
    fixture = Fixture()

    def exhaust(plan, tag: str) -> None:
        for ordinal in range(6):
            fixture.complete(
                "infrastructure",
                tag=f"{tag}-{ordinal}",
                plan=plan,
                transition=fixture.transition,
                target=fixture.target,
            )
        assessment = fixture.bank.assessments[plan.plan_id]
        assert assessment.settled
        assert assessment.label == "infrastructure_exhausted"
        assert assessment.n_complete == 0

    def seal(tag: str):
        return fixture.bank.seal_probe_plan(
            transition_id=fixture.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id=f"epoch:{tag}",
            unit_commitments=tuple(
                _h(f"{tag}-unit-{index}") for index in range(6)
            ),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h(f"{tag}-manifest"),
            runner_version="runner:infrastructure-retry",
            budget=_budget(),
        )

    exhaust(fixture.plan, "infrastructure-first")
    second = seal("infrastructure-second")
    exhaust(second, "infrastructure-second")
    third = seal("infrastructure-third")
    exhaust(third, "infrastructure-third")

    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="exhausted infrastructure-only epochs"):
        seal("infrastructure-fourth")
    assert fixture.bank.to_state() == before
    edge_key = fixture.plan.canonical_scientific_edge_key_sha256
    assert [
        item for item in fixture.bank.to_state().used_edge_epochs
        if item[0] == edge_key
    ] == sorted(
        [
            (edge_key, "epoch:one"),
            (edge_key, "epoch:infrastructure-second"),
            (edge_key, "epoch:infrastructure-third"),
        ]
    )


def test_zero_complete_edge_is_archive_stable_during_bounded_retry_lease() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_hot_compositions_per_namespace=2,
            unknown_structural_reserve=0,
            infrastructure_retry_lease_events=8,
        )
    )
    for ordinal in range(6):
        fixture.complete("infrastructure", tag=f"archive-retry-{ordinal}")
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.label == "infrastructure_exhausted"
    assert assessment.n_complete == 0

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-retry-lease-attestation"),
        required_hot_slots=1,
    )
    assert checkpoint is None
    assert fixture.bank.direct_transitions[
        fixture.transition.transition_id
    ].structural_state == "live"
    retry = fixture.bank.seal_probe_plan(
        transition_id=fixture.transition.transition_id,
        owner_kind="direct_factor",
        epoch_id="epoch:retry-inside-archive-lease",
        unit_commitments=tuple(
            _h(f"retry-inside-archive-lease-{index}") for index in range(6)
        ),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_h("retry-inside-archive-lease-manifest"),
        runner_version="runner:retry-inside-archive-lease",
        budget=_budget(),
    )
    assert retry.canonical_scientific_edge_key_sha256 == (
        fixture.plan.canonical_scientific_edge_key_sha256
    )


@pytest.mark.parametrize("registry", ("epoch", "unit"))
def test_lifetime_registry_rejects_rows_without_active_or_checkpoint_owner(
    registry: str,
) -> None:
    fixture = Fixture()
    state = fixture.bank.to_state()
    edge_key = fixture.plan.canonical_scientific_edge_key_sha256
    if registry == "epoch":
        forged = state.model_copy(
            update={
                "used_edge_epochs": tuple(
                    sorted((*state.used_edge_epochs, (edge_key, "epoch:padding")))
                )
            }
        )
        message = "lifetime epoch registry"
    else:
        forged = state.model_copy(
            update={
                "used_unit_commitments": tuple(
                    sorted(
                        (*state.used_unit_commitments, (edge_key, _h("unit-padding")))
                    )
                )
            }
        )
        message = "lifetime unit registry"
    with pytest.raises(ValueError, match=message):
        FactorBankV2(
            forged,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_archive_explicitly_terminates_retry_after_lease_expiry() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_hot_compositions_per_namespace=2,
            unknown_structural_reserve=0,
            infrastructure_retry_lease_events=1,
        )
    )
    for ordinal in range(6):
        fixture.complete("infrastructure", tag=f"archive-expiry-{ordinal}")
    for ordinal in range(2):
        fixture.bank.record_failure(
            FailureObservationV2(
                failure_id=f"failure:archive-expiry:{ordinal}",
                failure_class="infrastructure",
                failed_stage="execute",
                safe_failure_code="runner_unavailable",
                composition_id=fixture.source.composition_id,
                artifact_sha256=fixture.source.artifact_sha256,
                created_seq=fixture.bank.to_state().event_seq + 1,
            )
        )
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-expired-retry-attestation"),
        required_hot_slots=1,
    )
    assert checkpoint is not None
    assert fixture.bank.direct_transitions[
        fixture.transition.transition_id
    ].structural_state == "cold"
    with pytest.raises(ValueError, match="only a live scientific transition"):
        fixture.bank.seal_probe_plan(
            transition_id=fixture.transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:retry-after-archive-expiry",
            unit_commitments=tuple(
                _h(f"retry-after-archive-expiry-{index}")
                for index in range(6)
            ),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h(
                "retry-after-archive-expiry-manifest"
            ),
            runner_version="runner:retry-after-archive-expiry",
            budget=_budget(),
        )


def test_checkpoint_manifest_binds_exact_archived_plan_and_root() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure", tag="manifest-positive")
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("manifest-positive-attestation"),
        max_victims=1,
    )

    assert checkpoint is not None
    assert len(checkpoint.archived_epoch_manifests) == 1
    manifest = checkpoint.archived_epoch_manifests[0]
    assert manifest.canonical_scientific_edge_key_sha256 == (
        fixture.plan.canonical_scientific_edge_key_sha256
    )
    assert manifest.credit_owner_transition_id == fixture.plan.credit_owner_transition_id
    assert manifest.exact_transition_id == fixture.plan.transition_id
    assert manifest.plan_id == fixture.plan.plan_id
    assert manifest.epoch_id == fixture.plan.epoch_id
    assert manifest.unit_commitments == tuple(
        item.unit_commitment for item in fixture.plan.units
    )
    assert manifest.plan_sha256 == fixture.plan.digest
    state = fixture.bank.to_state()
    assert set(state.used_edge_epochs) == set(checkpoint.archived_edge_epochs)
    assert set(state.used_unit_commitments) == set(
        checkpoint.archived_unit_commitments
    )
    assert checkpoint.merkle_root_sha256 == _canonical_hash(
        {
            "namespace_digest": checkpoint.namespace_digest,
            "capacity_policy_sha256": checkpoint.capacity_policy_sha256,
            "archived_epoch_manifests": [manifest.model_dump(mode="json")],
            "archive_records_sha256": checkpoint.archive_records_sha256,
        }
    )


@pytest.mark.parametrize(
    "mutation",
    ("epoch_substitution", "unit_deletion", "unit_substitution"),
)
def test_checkpoint_manifest_rejects_registry_body_rewrites(mutation: str) -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure", tag=f"manifest-{mutation}")
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h(f"manifest-{mutation}-attestation"),
        max_victims=1,
    )
    assert checkpoint is not None
    state = fixture.bank.to_state()
    manifest = checkpoint.archived_epoch_manifests[0]
    edge_key = manifest.canonical_scientific_edge_key_sha256
    state_updates: dict[str, object] = {}
    if mutation == "epoch_substitution":
        forged_manifest = manifest.model_copy(
            update={"epoch_id": "epoch:substituted"}
        )
        state_updates["used_edge_epochs"] = tuple(
            sorted(
                (edge_key, "epoch:substituted")
                if item == (edge_key, manifest.epoch_id)
                else item
                for item in state.used_edge_epochs
            )
        )
        expected = "checkpoint root does not cover"
    elif mutation == "unit_deletion":
        removed_unit = manifest.unit_commitments[-1]
        forged_manifest = manifest.model_copy(
            update={"unit_commitments": manifest.unit_commitments[:-1]}
        )
        state_updates["used_unit_commitments"] = tuple(
            item
            for item in state.used_unit_commitments
            if item != (edge_key, removed_unit)
        )
        expected = "exactly six units"
    else:
        old_unit = manifest.unit_commitments[-1]
        new_unit = _h("manifest-substituted-unit")
        forged_manifest = manifest.model_copy(
            update={
                "unit_commitments": (
                    *manifest.unit_commitments[:-1],
                    new_unit,
                )
            }
        )
        state_updates["used_unit_commitments"] = tuple(
            sorted(
                (edge_key, new_unit)
                if item == (edge_key, old_unit)
                else item
                for item in state.used_unit_commitments
            )
        )
        expected = "checkpoint root does not cover"
    forged_checkpoint = checkpoint.model_copy(
        update={"archived_epoch_manifests": (forged_manifest,)}
    )
    forged_state = state.model_copy(
        update={
            **state_updates,
            "checkpoints": (forged_checkpoint,),
        }
    )

    with pytest.raises(ValueError, match=expected):
        FactorBankV2(
            forged_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_authenticated_checkpoint_epoch_rewrite_is_rejected_on_load(tmp_path) -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure", tag="manifest-load-rewrite")
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("manifest-load-rewrite-attestation"),
        max_victims=1,
    )
    assert checkpoint is not None
    path = tmp_path / "sft-v14-checkpoint-rewrite.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    old_epoch = checkpoint.archived_epoch_manifests[0].epoch_id
    edge_key = (
        checkpoint.archived_epoch_manifests[0]
        .canonical_scientific_edge_key_sha256
    )
    payload["state"]["checkpoints"][0]["archived_epoch_manifests"][0][
        "epoch_id"
    ] = "epoch:rewritten-on-load"
    payload["state"]["used_edge_epochs"] = [
        [edge_key, "epoch:rewritten-on-load"]
        if item == [edge_key, old_epoch]
        else item
        for item in payload["state"]["used_edge_epochs"]
    ]
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="checkpoint root does not cover"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_checkpoint_manifest_cannot_move_between_checkpoint_subjects() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure", tag="manifest-move-first")
    first_checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("manifest-move-first-attestation"),
        max_victims=1,
    )
    assert first_checkpoint is not None
    sibling, sibling_target, sibling_plan = _add_sibling_transition_and_plan(
        fixture,
        "manifest-move-second",
    )
    fixture.complete(
        "target_algorithm_failure",
        tag="manifest-move-second",
        plan=sibling_plan,
        transition=sibling,
        target=sibling_target,
    )
    second_checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("manifest-move-second-attestation"),
        max_victims=1,
    )
    assert second_checkpoint is not None

    def with_manifests(checkpoint, manifests):
        root = _canonical_hash(
            {
                "namespace_digest": checkpoint.namespace_digest,
                "capacity_policy_sha256": checkpoint.capacity_policy_sha256,
                "archived_epoch_manifests": [
                    item.model_dump(mode="json") for item in manifests
                ],
                "archive_records_sha256": checkpoint.archive_records_sha256,
            }
        )
        return checkpoint.model_copy(
            update={
                "archived_epoch_manifests": manifests,
                "merkle_root_sha256": root,
            }
        )

    first_manifest = first_checkpoint.archived_epoch_manifests[0]
    second_manifest = second_checkpoint.archived_epoch_manifests[0]
    overlapping_manifests = tuple(
        sorted(
            (first_manifest, second_manifest),
            key=lambda item: item.identity_key,
        )
    )
    overlapping_state = fixture.bank.to_state().model_copy(
        update={
            "checkpoints": (
                first_checkpoint,
                with_manifests(second_checkpoint, overlapping_manifests),
            )
        }
    )
    with pytest.raises(ValueError, match="checkpoint plan manifests overlap"):
        FactorBankV2(
            overlapping_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )

    forged_state = fixture.bank.to_state().model_copy(
        update={
            "checkpoints": (
                with_manifests(first_checkpoint, (second_manifest,)),
                with_manifests(second_checkpoint, (first_manifest,)),
            )
        }
    )

    with pytest.raises(
        ValueError,
        match="archived epoch manifest transition/owner closure",
    ):
        FactorBankV2(
            forged_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_accepted_gate_atomically_revokes_same_slot_sibling_pending() -> None:
    fixture = Fixture()
    sibling, sibling_target, sibling_plan = _add_sibling_transition_and_plan(
        fixture, "sibling"
    )
    _settle_candidate(
        fixture,
        suffix="first",
        transition=fixture.transition,
        target=fixture.target,
        plan=fixture.plan,
    )
    _settle_candidate(
        fixture,
        suffix="sibling",
        transition=sibling,
        target=sibling_target,
        plan=sibling_plan,
    )
    assert len(
        [item for item in fixture.bank.to_state().gate_opportunities if item.state == "pending"]
    ) == 2

    head = fixture.gate(True)

    sibling_opportunity = next(
        item
        for item in fixture.bank.to_state().gate_opportunities
        if item.plan_id == sibling_plan.plan_id
    )
    assert head is not None
    assert head.active_composition_id == fixture.target.composition_id
    assert sibling_opportunity.state == "revoked"
    assert not any(
        item.state == "pending"
        for item in fixture.bank.to_state().gate_opportunities
    )


def test_candidate_from_inactive_source_never_gets_gate_authority() -> None:
    fixture = Fixture()
    _settle_candidate(
        fixture,
        suffix="active",
        transition=fixture.transition,
        target=fixture.target,
        plan=fixture.plan,
    )
    fixture.gate(True)
    stale, stale_target, stale_plan = _add_sibling_transition_and_plan(
        fixture, "stale-source"
    )
    _settle_candidate(
        fixture,
        suffix="stale-source",
        transition=stale,
        target=stale_target,
        plan=stale_plan,
    )

    assert fixture.bank.assessments[stale_plan.plan_id].label == "candidate"
    assert not any(
        item.plan_id == stale_plan.plan_id and item.state == "pending"
        for item in fixture.bank.to_state().gate_opportunities
    )


def test_pending_gate_namespace_cap_is_enforced_and_revalidated() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(max_pending_gate_per_namespace=1)
    )
    sibling, sibling_target, sibling_plan = _add_sibling_transition_and_plan(
        fixture, "capacity-sibling"
    )
    _settle_candidate(
        fixture,
        suffix="capacity-first",
        transition=fixture.transition,
        target=fixture.target,
        plan=fixture.plan,
    )
    _settle_candidate(
        fixture,
        suffix="capacity-sibling",
        transition=sibling,
        target=sibling_target,
        plan=sibling_plan,
    )
    state = fixture.bank.to_state()
    pending = [item for item in state.gate_opportunities if item.state == "pending"]
    assert len(pending) == 1

    assessment = fixture.bank.assessments[sibling_plan.plan_id]
    head = fixture.bank.deployment_heads[
        fixture.bank.deployment_slot_id(fixture.namespace)
    ]
    overflow = pending[0].model_copy(
        update={
            "opportunity_id": "gate-overflow:one",
            "transition_id": sibling.transition_id,
            "plan_id": sibling_plan.plan_id,
            "settled_assessment_sha256": assessment.digest,
            "candidate_snapshot_sha256": fixture.bank._candidate_snapshot(
                assessment=assessment,
                head=head,
            ),
        }
    )
    invalid = state.model_copy(
        update={"gate_opportunities": (*state.gate_opportunities, overflow)}
    )
    with pytest.raises(ValueError, match="pending gate opportunities exceed"):
        FactorBankV2(
            invalid,
            state_key=fixture.key,
            direct_binding_verifier=lambda *_args: True,
            whole_operation_verifier=lambda *_args: True,
            plan_verifier=lambda _plan: True,
            assignment_verifier=lambda _receipt, _plan: True,
            runner_lease_verifier=lambda *_args: True,
            arm_receipt_verifier=lambda _receipt, _plan, _assignment: True,
            pair_execution_receipt_verifier=lambda *_args: True,
            cancellation_verifier=lambda _receipt, _attempt, _plan: True,
            gate_verifier=lambda _receipt, _state: True,
            base_snapshot_verifier=lambda _receipt, _state: True,
            rollback_verifier=lambda _trigger, _state: True,
            archive_verifier=lambda _digest, _attestation: True,
        )


def test_all_zero_cheaper_stream_is_settled_neutral() -> None:
    fixture = Fixture()
    for _ in range(4):
        fixture.complete("zero")
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.label == "neutral"
    assert assessment.all_zero_stream
    assert fixture.bank.to_state().gate_opportunities == ()


def test_both_algorithm_failures_are_null_not_cost_or_stage_win() -> None:
    fixture = Fixture()
    for _ in range(4):
        fixture.complete("both_algorithm_failure")
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.n_null == 4
    assert assessment.n_benefit == 0
    assert assessment.label == "neutral"


def test_target_algorithm_failure_is_catastrophic_harm() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure")
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.catastrophic_harm
    assert assessment.label == "harmful"
    assert fixture.bank.to_state().factors[1].structural_state == "live"


def test_six_infrastructure_attempts_terminate_without_negative_factor() -> None:
    fixture = Fixture()
    for _ in range(6):
        fixture.complete("infrastructure")
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.label == "infrastructure_exhausted"
    assert assessment.n_complete == 0
    before = fixture.bank.scientific_state_sha256
    with pytest.raises(ValueError, match="cannot open"):
        assignment = make_assignment_receipt_v2(
            plan=fixture.plan,
            ordinal=5,
            origin_pool_sha256=_h("origin-pool"),
            producer_epoch="assignment-producer:one",
            attestation_sha256=_h("late"),
        )
        fixture.bank.open_next_attempt(
            fixture.plan.plan_id,
            assignment,
            _runner_lease(fixture.plan, assignment, "late"),
        )
    assert fixture.bank.scientific_state_sha256 == before


def test_trusted_cancellation_consumes_assignment_without_scientific_vote() -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)
    old_assignment = attempt.assignment
    cancellation = _cancellation(fixture, attempt)

    cancelled = fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation)

    assert cancelled.state == "cancelled"
    assert cancelled.cancellation_receipt == cancellation
    assert cancelled.presented_root_ids == (
        cancellation.runner_event_root_sha256,
    )
    assert cancelled.presented_receipt_ids == (cancellation.cancellation_id,)
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.n_attempted == 1
    assert assessment.n_complete == 0
    assert assessment.vote_by_attempt == ()
    assert assessment.cancelled_attempt_ids == (attempt.attempt_id,)

    after_cancel = fixture.bank.to_state()
    assert fixture.bank.cancel_open_attempt(
        attempt.attempt_id, cancellation
    ) == cancelled
    assert fixture.bank.to_state() == after_cancel

    before_replay = fixture.bank.to_state()
    with pytest.raises(ValueError, match="frozen plan ordinal"):
        fixture.bank.open_next_attempt(
            fixture.plan.plan_id,
            old_assignment,
            _runner_lease(fixture.plan, old_assignment, "replayed-assignment"),
        )
    assert fixture.bank.to_state() == before_replay

    completed = fixture.complete("benefit")
    assert completed.ordinal == 1
    assert completed.source_receipt is not None
    assert completed.target_receipt is not None
    assert completed.pair_execution_receipt is not None
    before_late = fixture.bank.to_state()
    with pytest.raises(ValueError, match="only the unique open attempt"):
        fixture.bank.commit_attempt(
            cancelled.attempt_id,
            completed.source_receipt,
            completed.target_receipt,
            completed.pair_execution_receipt,
        )
    assert fixture.bank.to_state() == before_late


def test_forged_cancellation_is_state_and_file_atomic(tmp_path) -> None:
    trusted = _h("trusted-cancellation")
    fixture = Fixture(
        cancellation_verifier=lambda receipt, _attempt, _plan: (
            receipt.attestation_sha256 == trusted
        )
    )
    attempt = _open_next(fixture)
    path = tmp_path / "cancel-atomic.json"
    fixture.bank.save(path)
    before_state = fixture.bank.to_state()
    before_bytes = path.read_bytes()

    forged = _cancellation(
        fixture,
        attempt,
        attestation=_h("forged-cancellation"),
    )
    with pytest.raises(ValueError, match="verifier rejected"):
        fixture.bank.cancel_open_attempt(attempt.attempt_id, forged)

    assert fixture.bank.to_state() == before_state
    assert path.read_bytes() == before_bytes

    wrong_fence = _cancellation(
        fixture,
        attempt,
        attestation=trusted,
    ).model_copy(update={"expected_opened_seq": attempt.opened_seq - 1})
    with pytest.raises(ValueError, match="exact open attempt"):
        fixture.bank.cancel_open_attempt(attempt.attempt_id, wrong_fence)
    assert fixture.bank.to_state() == before_state
    assert path.read_bytes() == before_bytes


def test_six_trusted_cancellations_settle_infrastructure_and_release_capacity() -> None:
    fixture = Fixture()
    for ordinal in range(6):
        attempt = _open_next(fixture)
        assert attempt.ordinal == ordinal
        fixture.bank.cancel_open_attempt(
            attempt.attempt_id,
            _cancellation(fixture, attempt),
        )

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    reservation = next(
        item
        for item in fixture.bank.to_state().reservations
        if item.plan_id == fixture.plan.plan_id
    )
    assert assessment.settled
    assert assessment.label == "infrastructure_exhausted"
    assert assessment.n_attempted == 6
    assert assessment.n_complete == 0
    assert assessment.vote_by_attempt == ()
    assert reservation.state == "released"
    assert reservation.released_seq == fixture.bank.to_state().event_seq


def test_trusted_terminate_scope_cancellation_releases_capacity_immediately() -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)
    fixture.bank.cancel_open_attempt(
        attempt.attempt_id,
        _cancellation(fixture, attempt, terminate_scope=True),
    )

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    reservation = next(
        item
        for item in fixture.bank.to_state().reservations
        if item.plan_id == fixture.plan.plan_id
    )
    assert assessment.settled
    assert assessment.label == "infrastructure_exhausted"
    assert assessment.n_attempted == 1
    assert assessment.n_complete == 0
    assert reservation.state == "released"


def test_one_started_arm_abort_consumes_root_and_replay_quarantines() -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)
    started_root = _h("crash-started-source-root")
    cancellation = _cancellation(
        fixture,
        attempt,
        started_root_id=started_root,
    )

    cancelled = fixture.bank.cancel_open_attempt(
        attempt.attempt_id,
        cancellation,
    )

    assert cancelled.presented_root_ids == (
        started_root,
        cancellation.runner_event_root_sha256,
    )
    used_roots = dict(fixture.bank.to_state().used_roots)
    used_receipts = dict(fixture.bank.to_state().used_receipts)
    assert used_roots[started_root] == attempt.attempt_id
    assert used_roots[cancellation.runner_event_root_sha256] == attempt.attempt_id
    assert used_receipts[cancellation.cancellation_id] == attempt.attempt_id
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.label == "infrastructure_exhausted"
    assert assessment.vote_by_attempt == ()

    sibling, sibling_target, sibling_plan = _add_sibling_transition_and_plan(
        fixture, "cancel-root-replay"
    )
    replay = fixture.complete(
        "benefit",
        plan=sibling_plan,
        transition=sibling,
        target=sibling_target,
        physical_root_ids=(started_root, _h("new-target-root")),
    )
    assert replay.state == "quarantine"
    assert replay.disposition_reason == "reused_physical_root"
    assert dict(fixture.bank.to_state().used_roots)[started_root] == attempt.attempt_id


def test_one_started_abort_roots_and_id_survive_archive_checkpoint() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_infrastructure_epochs_per_edge=1
        )
    )
    attempt = _open_next(fixture)
    started_root = _h("archived-cancel-started-root")
    cancellation = _cancellation(
        fixture,
        attempt,
        started_root_id=started_root,
    )
    fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation)

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-cancel-checkpoint"),
        required_hot_slots=100,
        max_victims=1,
    )

    assert checkpoint is not None
    state = fixture.bank.to_state()
    assert dict(state.used_roots)[started_root] == checkpoint.checkpoint_id
    assert dict(state.used_roots)[
        cancellation.runner_event_root_sha256
    ] == checkpoint.checkpoint_id
    assert dict(state.used_receipts)[
        cancellation.cancellation_id
    ] == checkpoint.checkpoint_id
    assert all(item.attempt_id != attempt.attempt_id for item in state.attempts)

    sibling, sibling_target, sibling_plan = _add_sibling_transition_and_plan(
        fixture, "archived-cancel-root-replay"
    )
    replay = fixture.complete(
        "benefit",
        plan=sibling_plan,
        transition=sibling,
        target=sibling_target,
        physical_root_ids=(started_root, _h("archive-new-target-root")),
    )
    assert replay.state == "quarantine"
    assert replay.disposition_reason == "reused_physical_root"
    assert dict(fixture.bank.to_state().used_roots)[
        started_root
    ] == checkpoint.checkpoint_id


def test_runner_journal_verifier_rejects_omitted_started_root_atomically() -> None:
    journalled_root = _h("journalled-but-omitted-root")
    fixture = Fixture(
        cancellation_verifier=lambda receipt, _attempt, _plan: tuple(
            item.root_id for item in receipt.started_arm_roots
        )
        == (journalled_root,)
    )
    attempt = _open_next(fixture)
    forged_zero_start = _cancellation(fixture, attempt)
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="verifier rejected"):
        fixture.bank.cancel_open_attempt(
            attempt.attempt_id,
            forged_zero_start,
        )

    assert fixture.bank.to_state() == before


@pytest.mark.parametrize("partial", [False, True])
def test_terminal_abort_after_two_benefits_cannot_create_gate(partial: bool) -> None:
    fixture = Fixture()
    fixture.complete("benefit")
    fixture.complete("benefit")
    assert fixture.bank.assessments[fixture.plan.plan_id].label == "neutral"
    attempt = _open_next(fixture)
    cancellation = _cancellation(
        fixture,
        attempt,
        terminate_scope=True,
        started_root_id=(
            _h("partial-abort-root") if partial else None
        ),
    )

    fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation)

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.label == "infrastructure_exhausted"
    assert not any(
        item.plan_id == fixture.plan.plan_id and item.state == "pending"
        for item in fixture.bank.to_state().gate_opportunities
    )


def test_zero_start_attrition_cannot_lower_candidate_sample_target() -> None:
    fixture = Fixture()
    fixture.complete("benefit")
    fixture.complete("benefit")
    for _index in range(4):
        attempt = _open_next(fixture)
        fixture.bank.cancel_open_attempt(
            attempt.attempt_id,
            _cancellation(fixture, attempt, terminate_scope=False),
        )

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.n_complete == 2
    assert assessment.n_attempted == 6
    assert assessment.label == "infrastructure_exhausted"
    assert not any(
        item.plan_id == fixture.plan.plan_id and item.state == "pending"
        for item in fixture.bank.to_state().gate_opportunities
    )


def test_harm_quorum_stops_attrition_before_more_attempts() -> None:
    fixture = Fixture()
    fixture.complete("harm")
    fixture.complete("harm")

    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.n_complete == 2
    assert assessment.label == "harmful"
    assert assessment.settled
    reservation = next(
        item
        for item in fixture.bank.to_state().reservations
        if item.plan_id == fixture.plan.plan_id
    )
    assert reservation.state == "released"
    assert reservation.released_seq == fixture.bank.to_state().event_seq
    with pytest.raises(ValueError, match="harmful scientific transition"):
        _open_next(fixture)
    assert not any(
        item.plan_id == fixture.plan.plan_id and item.state == "pending"
        for item in fixture.bank.to_state().gate_opportunities
    )
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-harm-quorum"),
        required_hot_slots=100,
    )
    assert checkpoint is not None
    archived = next(
        item
        for item in fixture.bank.to_state().direct_transitions
        if item.transition_id == fixture.transition.transition_id
    )
    assert archived.structural_state == "tombstone"


def test_same_instance_terminal_mutations_have_one_linearization_winner() -> None:
    first_in_verifier = threading.Event()
    release_first = threading.Event()

    def verifier(receipt, _attempt, _plan):
        if receipt.attestation_sha256 == _h("concurrent-first-attestation"):
            first_in_verifier.set()
            assert release_first.wait(timeout=5)
        return True

    fixture = Fixture(cancellation_verifier=verifier)
    attempt = _open_next(fixture)
    first = _cancellation(
        fixture,
        attempt,
        attestation=_h("concurrent-first-attestation"),
    )
    second = _cancellation(
        fixture,
        attempt,
        attestation=_h("concurrent-second-attestation"),
    )
    successes = []
    failures = []
    second_started = threading.Event()

    def cancel(receipt, *, mark_started=False):
        if mark_started:
            second_started.set()
        try:
            successes.append(
                fixture.bank.cancel_open_attempt(attempt.attempt_id, receipt)
            )
        except Exception as exc:  # the losing terminal must observe the winner
            failures.append(exc)

    first_thread = threading.Thread(target=cancel, args=(first,))
    second_thread = threading.Thread(
        target=cancel,
        args=(second,),
        kwargs={"mark_started": True},
    )
    first_thread.start()
    assert first_in_verifier.wait(timeout=5)
    second_thread.start()
    assert second_started.wait(timeout=5)
    release_first.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive() and not second_thread.is_alive()
    assert len(successes) == 1
    assert len(failures) == 1
    assert "different cancellation terminal" in str(failures[0])
    terminal = fixture.bank.attempts[attempt.attempt_id]
    assert terminal.state == "cancelled"
    assert terminal.cancellation_receipt == first
    assert set(terminal.presented_root_ids).issubset(
        dict(fixture.bank.to_state().used_roots)
    )
    assert first.cancellation_id in dict(fixture.bank.to_state().used_receipts)


def test_public_reads_linearize_after_rejected_nested_bundle_rollback() -> None:
    fixture = Fixture()
    before = fixture.bank.to_state()
    provisional_entered = threading.Event()
    release_provisional = threading.Event()

    def blocking_reject(transition, *_args):
        if transition.binding_proof_id != "proof:provisional-read-escape":
            return True
        provisional_entered.set()
        assert release_provisional.wait(timeout=5)
        return False

    capabilities = _trusted_bank_capabilities()
    capabilities["direct_binding_verifier"] = blocking_reject
    bank = FactorBankV2(before, state_key=fixture.key, **capabilities)
    provisional_factor = FactorRevisionV2(
        revision_id="instruction:provisional-read-escape",
        logical_factor_id=fixture.old.logical_factor_id,
        namespace=fixture.namespace,
        carrier=fixture.old.carrier,
        locator=fixture.old.locator,
        binding_status=fixture.old.binding_status,
        content_sha256=_h("provisional-read-escape"),
        parent_revision_id=fixture.old.revision_id,
        origin_branch="mutate",
        created_seq=before.event_seq + 1,
    )
    provisional_composition = CompositionRevisionV2(
        composition_id="composition:provisional-read-escape",
        namespace=fixture.namespace,
        carrier=fixture.source.carrier,
        artifact_revision_id="artifact:provisional-read-escape",
        artifact_sha256=_h("provisional-read-escape-artifact"),
        bindings=(
            SlotBinding(
                slot_id="fixed_background",
                factor_revision_id=fixture.background.revision_id,
            ),
            SlotBinding(
                slot_id="instruction_slot",
                factor_revision_id=provisional_factor.revision_id,
            ),
        ),
        origin_branch="mutate",
        canonical_metadata_bytes=256,
        artifact_bytes=512,
        prompt_summary_tokens=32,
        created_seq=before.event_seq + 2,
    )
    mutation_errors: list[BaseException] = []

    def mutate_then_reject() -> None:
        try:
            bank.register_direct_bundle(
                factors=(provisional_factor,),
                compositions=(provisional_composition,),
                transition_fields={
                    "source_composition_id": fixture.source.composition_id,
                    "target_composition_id": provisional_composition.composition_id,
                    "slot_id": "instruction_slot",
                    "binding_proof_id": "proof:provisional-read-escape",
                    "binding_proof_sha256": _h("provisional-read-escape-proof"),
                    "masked_background_sha256": _h("masked-background"),
                    "binding_verifier_epoch": "binder:provisional-read-escape",
                    "origin_branch": "mutate",
                },
            )
        except BaseException as exc:  # diagnostic capture across the thread
            mutation_errors.append(exc)

    mutation_thread = threading.Thread(target=mutate_then_reject)
    mutation_thread.start()
    assert provisional_entered.wait(timeout=5)

    reads = {
        "factors": lambda: bank.factors,
        "compositions": lambda: bank.compositions,
        "direct_transitions": lambda: bank.direct_transitions,
        "whole_transitions": lambda: bank.whole_transitions,
        "plans": lambda: bank.plans,
        "attempts": lambda: bank.attempts,
        "assessments": lambda: bank.assessments,
        "gate_opportunities": lambda: bank.gate_opportunities,
        "deployment_heads": lambda: bank.deployment_heads,
        "retrieve": lambda: bank.retrieve(fixture.namespace),
        "to_state": bank.to_state,
        "read_only_snapshot": bank.read_only_snapshot,
        "scientific_state_sha256": lambda: bank.scientific_state_sha256,
    }
    barrier = threading.Barrier(len(reads) + 1)
    attempting = {name: threading.Event() for name in reads}
    any_finished = threading.Event()
    results = {}
    read_errors: list[BaseException] = []

    def read(name, operation) -> None:
        barrier.wait()
        attempting[name].set()
        try:
            results[name] = operation()
        except BaseException as exc:  # diagnostic capture across the thread
            read_errors.append(exc)
        finally:
            any_finished.set()

    reader_threads = [
        threading.Thread(target=read, args=(name, operation))
        for name, operation in reads.items()
    ]
    for thread in reader_threads:
        thread.start()
    barrier.wait()
    assert all(event.wait(timeout=5) for event in attempting.values())
    assert not any_finished.wait(timeout=0.1)

    release_provisional.set()
    mutation_thread.join(timeout=5)
    for thread in reader_threads:
        thread.join(timeout=5)

    assert not mutation_thread.is_alive()
    assert all(not thread.is_alive() for thread in reader_threads)
    assert len(mutation_errors) == 1
    assert "rejected the canonical bundle" in str(mutation_errors[0])
    assert not read_errors
    assert bank.to_state() == before
    assert provisional_factor.revision_id not in results["factors"]
    assert provisional_composition.composition_id not in results["compositions"]
    assert results["to_state"] == before
    assert results["scientific_state_sha256"] == before.digest
    assert results["read_only_snapshot"].scientific_state_sha256 == before.digest
    assert results["read_only_snapshot"].retrieve(fixture.namespace) == [fixture.source]
    assert results["retrieve"] == [fixture.source]


def test_branch_assignment_is_one_shot_and_recomputed_from_namespace_history() -> None:
    fixture = Fixture()
    first_opportunity = _record_algorithm_failure(fixture, "one")
    assert first_opportunity is not None

    first = fixture.bank.allocate_branch(first_opportunity.opportunity_id)
    assert first.repair_opportunity_sha256 == first_opportunity.digest
    assert first.namespace_digest == fixture.namespace.digest
    assert first.source_composition_id == fixture.target.composition_id
    assert first.assigned_counts_before == (
        ("reuse", 0),
        ("mutate", 0),
        ("fresh", 0),
    )

    before_repeat = fixture.bank.to_state()
    with pytest.raises(ValueError, match="already owns"):
        fixture.bank.allocate_branch(first_opportunity.opportunity_id)
    assert fixture.bank.to_state() == before_repeat

    second_opportunity = _record_algorithm_failure(fixture, "two")
    assert second_opportunity is not None
    second = fixture.bank.allocate_branch(second_opportunity.opportunity_id)
    counts = dict(second.assigned_counts_before)
    assert sum(counts.values()) == 1
    assert counts[first.branch] == 1


def test_proposal_counter_capacity_cannot_exceed_decision_capacity() -> None:
    with pytest.raises(
        ValueError,
        match="lifetime-counter capacity exceeds decision capacity",
    ):
        CapacityPolicyV1(
            max_proposal_decisions=1,
            max_proposal_lifetime_counters=2,
        )


def test_proposal_decision_byte_capacity_is_frozen() -> None:
    policy = CapacityPolicyV1()
    assert policy.max_proposal_decision_bytes == 96 * 1024
    assert policy.max_proposal_decision_bytes == MAX_PROPOSAL_DECISION_BYTES
    with pytest.raises(ValueError, match="Input should be 98304"):
        CapacityPolicyV1(max_proposal_decision_bytes=MAX_PROPOSAL_DECISION_BYTES - 1)


def test_exact_proposal_decision_cap_rejects_before_publication_or_file_write(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "decision-byte-preflight",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    path = tmp_path / "decision-byte-preflight.json"
    fixture.bank.save(path)
    file_before = path.read_bytes()
    state_before = fixture.bank.to_state()
    observed = []

    def force_oversized_exact_decision(decision) -> int:
        observed.append(decision)
        return MAX_PROPOSAL_DECISION_BYTES + 1

    with monkeypatch.context() as scoped:
        scoped.setattr(
            factor_bank_v2_module,
            "_proposal_decision_canonical_bytes",
            force_oversized_exact_decision,
        )
        with pytest.raises(
            ValueError,
            match="exceeds frozen 98304-byte capacity",
        ):
            fixture.bank.screen_and_allocate_branch(
                opportunity.opportunity_id,
                proposal,
                producer_epoch="proposal-host:decision-byte-preflight",
                attestation_sha256=_h("decision-byte-preflight-attestation"),
            )

    assert len(observed) == 1
    assert observed[0].proposal_receipt == proposal
    assert fixture.bank.to_state() == state_before
    assert path.read_bytes() == file_before


def test_save_load_and_full_replay_share_exact_proposal_decision_cap(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "decision-byte-persistence",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:decision-byte-persistence",
        attestation_sha256=_h("decision-byte-persistence-attestation"),
    )
    assert assignment is not None and action is not None
    actual_bytes = factor_bank_v2_module._proposal_decision_canonical_bytes(
        decision
    )
    assert actual_bytes < MAX_PROPOSAL_DECISION_BYTES

    path = tmp_path / "decision-byte-persistence.json"
    fixture.bank.save(path)
    file_before = path.read_bytes()
    state_before = fixture.bank.to_state()

    with monkeypatch.context() as scoped:
        scoped.setattr(
            factor_bank_v2_module,
            "_proposal_decision_canonical_bytes",
            lambda _decision: MAX_PROPOSAL_DECISION_BYTES + 1,
        )
        with pytest.raises(
            ValueError,
            match="exceeds frozen 98304-byte capacity",
        ):
            fixture.bank.save(path)
        assert path.read_bytes() == file_before
        with pytest.raises(
            ValueError,
            match="exceeds frozen 98304-byte capacity",
        ):
            FactorBankV2.load(
                path,
                state_key=fixture.key,
                **_trusted_bank_capabilities(),
            )

    assert fixture.bank.to_state() == state_before
    assert path.read_bytes() == file_before


def test_proposal_counter_root_is_exact_cell_isolated() -> None:
    cell_a = _h("proposal-cell:A")
    cell_b = _h("proposal-cell:B")
    counter_a = ProposalLifetimeCounterV1(
        cell_sha256=cell_a,
        target_factor_key_sha256=_h("proposal-target:A"),
        unknown_selection_count=1,
        single_safe_unknown_selection_count=1,
    )
    counter_b = ProposalLifetimeCounterV1(
        cell_sha256=cell_b,
        target_factor_key_sha256=_h("proposal-target:B"),
        unknown_selection_count=1,
        single_safe_unknown_selection_count=1,
    )
    assert _proposal_lifetime_counter_root(
        (counter_a,),
        cell_sha256=cell_a,
    ) == _proposal_lifetime_counter_root(
        (counter_a, counter_b),
        cell_sha256=cell_a,
    )


def test_authenticated_counter_table_tamper_cannot_survive_full_replay(
    tmp_path,
) -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "counter-state-tamper",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:counter-tamper",
        attestation_sha256=_h("proposal-counter-tamper-attestation"),
    )
    path = tmp_path / "proposal-counter-tamper.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["proposal_lifetime_counters"][0][
        "unknown_selection_count"
    ] = 2
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="lifetime-counter state does not replay"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_proposal_conditioned_reuse_is_one_atomic_assignment_action_and_zero_credit(
    tmp_path,
) -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "reuse-action",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)

    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:one",
        attestation_sha256=_h("proposal-action-attestation"),
    )

    assert assignment is not None and assignment.branch == "reuse"
    assert action is not None and action.state == "prepared"
    assert decision.cursor_committed
    state_after_decision = fixture.bank.to_state()
    assert len(state_after_decision.proposal_lifetime_counters) == 1
    counter = state_after_decision.proposal_lifetime_counters[0]
    assert counter.unknown_selection_count == 1
    assert counter.single_safe_unknown_selection_count == 1
    assert decision.committed_counter_delta is not None
    assert decision.proposal_counter_state_before_sha256 != (
        decision.proposal_counter_state_after_sha256
    )
    path = tmp_path / "proposal-counter-replay.json"
    fixture.bank.save(path)
    reloaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    assert reloaded.to_state().proposal_lifetime_counters == (
        state_after_decision.proposal_lifetime_counters
    )
    assert assignment.proposal_decision_sha256 == decision.digest
    assert action.proposal_decision_sha256 == decision.digest
    assert action.action_intent_sha256 in (
        action.exact_additional_input_root_commitments
    )
    assert not any(
        item.transition_id == action.transition_id
        for item in fixture.bank.to_state().assessments
    )

    before_replay = fixture.bank.to_state()
    with pytest.raises(ValueError, match="already owns"):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch="proposal-host:one",
            attestation_sha256=_h("proposal-action-attestation"),
        )
    assert fixture.bank.to_state() == before_replay

    proof_sha256 = _h("phase-proposal-proof")
    transition = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:proposal:reuse",
        binding_proof_sha256=proof_sha256,
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:proposal",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    committed = fixture.bank.finalize_proposal_action(
        action.action_id,
        transition_id=transition.transition_id,
        phase_terminal_sha256=proof_sha256,
    )
    assert committed.state == "committed"
    assert committed.transition_id == transition.transition_id
    assert not any(
        item.transition_id == transition.transition_id
        for item in fixture.bank.to_state().assessments
    )
    with pytest.raises(ValueError, match="different credit owner"):
        fixture.bank.seal_probe_plan(
            transition_id=transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:reuse-action-alias",
            unit_commitments=tuple(
                _h(f"reuse-action-alias-unit-{index}")
                for index in range(6)
            ),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("reuse-action-alias-manifest"),
            runner_version="runner:reuse-action-alias",
            budget=_budget(),
        )
    terminal = fixture.bank.to_state()
    assert fixture.bank.finalize_proposal_action(
        action.action_id,
        transition_id=transition.transition_id,
        phase_terminal_sha256=proof_sha256,
    ) == committed
    assert fixture.bank.to_state() == terminal


def test_no_safe_reuse_is_removed_before_branch_choice_and_advances_cursor() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure")
    opportunity = _repair_opportunity(
        fixture,
        "no-safe",
        feasible_branches=("reuse", "fresh"),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    context = _generation_context(fixture, opportunity, proposal, tag="no-safe")

    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:no-safe",
        attestation_sha256=_h("proposal-no-safe-attestation"),
        generation_context=context,
    )

    assert decision.effective_feasible_branches == ("fresh",)
    assert decision.cursor_committed
    assert decision.proposal_receipt.projected_cursor.lifetime_ordinal == 1
    assert assignment is not None and assignment.branch == "fresh"
    assert action is not None and action.branch == "fresh"
    assert action.generation_request is not None


def test_target_storage_alias_cannot_flip_fresh_reuse_branch_tie() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "branch-storage-alias",
        feasible_branches=("reuse", "fresh"),
    )
    base = _proposal_receipt(fixture, opportunity)
    original = base.candidate_manifest[0].candidate
    alias = original.model_copy(
        update={
            "target_revision_id": "instruction:storage-alias-for-branch",
            "lineage_niche": original.lineage_niche.model_copy(
                update={
                    "root_revision_id": "instruction:storage-alias-lineage",
                    "provenance_family_sha256": _h(
                        "storage-alias-provenance-for-branch"
                    ),
                }
            ),
        }
    )
    aliased = select_exact_edge_proposal(
        _host_proposal_input(
            fixture,
            request=base.request,
            cursor=base.cursor_before,
            candidates=(alias,),
        )
    )
    assert base.digest != aliased.digest
    assert base.proposal_scheduler_decision_sha256 == (
        aliased.proposal_scheduler_decision_sha256
    )

    branches = ("reuse", "fresh")

    def legacy_choice(seed: int, receipt) -> str:
        return max(
            branches,
            key=lambda branch: _canonical_hash(
                {
                    "seed": seed,
                    "opportunity": opportunity.opportunity_id,
                    "proposal_receipt": receipt.digest,
                    "branch": branch,
                }
            ),
        )

    witness_seed = next(
        seed
        for seed in range(10_000)
        if legacy_choice(seed, base) != legacy_choice(seed, aliased)
    )
    assert {
        legacy_choice(witness_seed, base),
        legacy_choice(witness_seed, aliased),
    } == {"reuse", "fresh"}

    universe_sha256 = _h("alias-free-host-universe")

    def current_choice(receipt) -> str:
        host_decision_sha256 = _host_proposal_scheduler_decision_sha256(
            receipt=receipt,
            candidate_universe_sha256=universe_sha256,
            candidate_universe_count=1,
        )
        return max(
            branches,
            key=lambda branch: _proposal_conditioned_branch_tiebreak_sha256(
                public_seed=witness_seed,
                proposal_scheduler_decision_sha256=host_decision_sha256,
                branch=branch,
            ),
        )

    assert current_choice(base) == current_choice(aliased)


def test_host_sparse_21_max_id_universe_is_bounded_and_dump_load_replays(
    tmp_path,
) -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_hot_compositions_per_namespace=32,
        )
    )

    def max_id(ordinal: int) -> str:
        stem = f"instruction:{ordinal}:"
        return stem + "x" * (128 - len(stem))

    for index in range(20):
        factor = fixture._factor(
            max_id(index),
            f"sparse-host-value-{index}",
        )
        composition = fixture._composition(
            f"composition:sparse-host:{index}",
            factor.revision_id,
            f"sparse-host-artifact-{index}",
        )
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=composition.composition_id,
            slot_id="instruction_slot",
            binding_proof_id=f"proof:sparse-host:{index}",
            binding_proof_sha256=_h(f"sparse-host-proof-{index}"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch=f"binder:sparse-host:{index}",
            origin_branch="mutate",
        )

    opportunity = _repair_opportunity(
        fixture,
        "sparse-host-universe",
        feasible_branches=("reuse",),
    )
    locus = ExactFactorLocusV1(
        carrier=fixture.old.carrier,
        slot_id="instruction_slot",
        logical_factor_id=fixture.old.logical_factor_id,
        locator_surface=fixture.old.locator.surface,
        locator_path=fixture.old.locator.path,
        locator_version=fixture.old.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=fixture.old.revision_id,
        canonical_from_factor_key_sha256=(
            fixture.bank._factor_carrier_key_sha256(fixture.old)
        ),
        canonical_background_sha256=(
            fixture.bank._canonical_direct_background_sha256(
                fixture.bank.to_state(),
                source=fixture.source,
                source_factor=fixture.old,
                slot_id=locus.slot_id,
            )
        ),
    )
    slate, universe_sha256, universe_count = fixture.bank._proposal_candidate_slate(
        opportunity=opportunity,
        source_factor=fixture.old,
        slot_id=locus.slot_id,
    )
    assert universe_count == 21
    assert len(slate) == 16
    assert sum(len(item.target_revision_id) == 128 for item in slate) >= 15
    receipt = select_exact_edge_proposal(
        _host_proposal_input(
            fixture,
            request=ProposalRequestV1(
                opportunity_id=opportunity.opportunity_id,
                cell=cell,
            ),
            cursor=ProposalCursorV1.empty(cell),
            candidates=slate,
        )
    )
    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        receipt,
        producer_epoch="proposal-host:sparse-21",
        attestation_sha256=_h("proposal-host-sparse-21-attestation"),
    )
    assert assignment is not None and assignment.branch == "reuse"
    assert action is not None
    assert decision.candidate_universe_sha256 == universe_sha256
    assert decision.candidate_slate_scheduler_sha256 == (
        receipt.candidate_slate_scheduler_sha256
    )

    path = tmp_path / "sparse-21-bank.json"
    fixture.bank.save(path)
    loaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    assert loaded.to_state().proposal_decisions[-1] == decision


def test_comparator_storage_alias_is_excluded_from_host_proposal_slate() -> None:
    fixture = Fixture()
    source_alias = fixture.old.model_copy(
        update={
            "revision_id": "instruction:000-comparator-storage-alias",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_factor(source_alias)
    source_composition_alias = fixture.source.model_copy(
        update={
            "composition_id": "composition:000-comparator-storage-alias",
            "artifact_revision_id": "artifact:000-comparator-storage-alias",
            "bindings": tuple(
                SlotBinding(
                    slot_id=item.slot_id,
                    factor_revision_id=(
                        source_alias.revision_id
                        if item.slot_id == "instruction_slot"
                        else item.factor_revision_id
                    ),
                )
                for item in fixture.source.bindings
            ),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(source_composition_alias)
    assert fixture.bank._factor_carrier_key_sha256(
        source_alias
    ) == fixture.bank._factor_carrier_key_sha256(fixture.old)
    observation = FailureObservationV2(
        failure_id="failure:comparator-storage-alias",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=source_composition_alias.composition_id,
        artifact_sha256=source_composition_alias.artifact_sha256,
        created_seq=fixture.bank.to_state().event_seq + 1,
    )
    opportunity = fixture.bank.record_failure(
        observation,
        feasible_branches=("reuse",),
    )
    assert opportunity is not None
    locus = ExactFactorLocusV1(
        carrier="phase_program",
        slot_id="instruction_slot",
        logical_factor_id=source_alias.logical_factor_id,
        locator_surface="phase_field",
        locator_path=source_alias.locator.path,
        locator_version=source_alias.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=source_alias.revision_id,
        canonical_from_factor_key_sha256=(
            fixture.bank._factor_carrier_key_sha256(source_alias)
        ),
        canonical_background_sha256=(
            fixture.bank._canonical_direct_background_sha256(
                fixture.bank.to_state(),
                source=source_composition_alias,
                source_factor=source_alias,
                slot_id=locus.slot_id,
            )
        ),
    )
    slate, _universe_sha256, _universe_count = (
        fixture.bank._proposal_candidate_slate(
            opportunity=opportunity,
            source_factor=source_alias,
            slot_id=locus.slot_id,
        )
    )
    assert slate
    assert all(
        candidate.target_factor_key_sha256
        != cell.canonical_from_factor_key_sha256
        for candidate in slate
    )
    receipt = select_exact_edge_proposal(
        _host_proposal_input(
            fixture,
            request=ProposalRequestV1(
                opportunity_id=opportunity.opportunity_id,
                cell=cell,
            ),
            cursor=ProposalCursorV1.empty(cell),
            candidates=slate,
        )
    )
    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        receipt,
        producer_epoch="proposal-host:comparator-storage-alias",
        attestation_sha256=_h("comparator-storage-alias-attestation"),
    )
    assert decision.cursor_committed
    assert assignment is not None and assignment.branch == "reuse"
    assert action is not None and action.state == "prepared"


def test_earliest_content_owner_freezes_lineage_across_later_storage_alias() -> None:
    fixture = Fixture()
    fixture._factor(
        "instruction:lineage-control-target",
        "lineage-control-value",
        parent=fixture.old.revision_id,
    )
    opportunity = _repair_opportunity(
        fixture,
        "lineage-owner-freeze",
        feasible_branches=("reuse",),
    )
    locus = ExactFactorLocusV1(
        carrier="phase_program",
        slot_id="instruction_slot",
        logical_factor_id=fixture.old.logical_factor_id,
        locator_surface="phase_field",
        locator_path=fixture.old.locator.path,
        locator_version=fixture.old.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=fixture.old.revision_id,
        canonical_from_factor_key_sha256=(
            fixture.bank._factor_carrier_key_sha256(fixture.old)
        ),
        canonical_background_sha256=(
            fixture.bank._canonical_direct_background_sha256(
                fixture.bank.to_state(),
                source=fixture.source,
                source_factor=fixture.old,
                slot_id=locus.slot_id,
            )
        ),
    )

    def select_from_host_slate():
        slate, _universe, _count = fixture.bank._proposal_candidate_slate(
            opportunity=opportunity,
            source_factor=fixture.old,
            slot_id=locus.slot_id,
        )
        return slate, select_exact_edge_proposal(
            _host_proposal_input(
                fixture,
                request=ProposalRequestV1(
                    opportunity_id=opportunity.opportunity_id,
                    cell=cell,
                ),
                cursor=ProposalCursorV1.empty(cell),
                candidates=slate,
            )
        )

    before_slate, before_receipt = select_from_host_slate()
    frozen_lineage = fixture.bank._proposal_lineage_niche(fixture.new)
    alias = fixture.new.model_copy(
        update={
            "revision_id": "instruction:000-later-lineage-alias",
            "parent_revision_id": None,
            "origin_branch": "fresh",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_factor(alias)
    after_slate, after_receipt = select_from_host_slate()

    assert [item.target_revision_id for item in before_slate] == [
        item.target_revision_id for item in after_slate
    ]
    target = next(
        item for item in after_slate
        if item.target_factor_key_sha256
        == fixture.bank._factor_carrier_key_sha256(fixture.new)
    )
    assert target.target_revision_id == fixture.new.revision_id
    assert target.lineage_niche == frozen_lineage
    before_selected = next(
        item.candidate.target_factor_key_sha256
        for item in before_receipt.candidate_manifest
        if item.candidate.target_revision_id
        == before_receipt.selected_target_revision_id
    )
    after_selected = next(
        item.candidate.target_factor_key_sha256
        for item in after_receipt.candidate_manifest
        if item.candidate.target_revision_id
        == after_receipt.selected_target_revision_id
    )
    assert after_selected == before_selected


@pytest.mark.parametrize(
    ("branch", "dependencies"),
    (("mutate", ("instruction:a",)), ("fresh", ())),
)
def test_generated_assignment_prepare_is_atomic_for_mutate_and_fresh(
    branch,
    dependencies,
) -> None:
    fixture = Fixture()
    _opportunity, _proposal, context, decision, assignment, action = (
        _prepare_generated_action(fixture, branch, f"prepare-{branch}")
    )

    assert decision.generation_context == context
    assert decision.generation_context_sha256 == context.digest
    assert assignment.branch == action.branch == branch
    assert action.state == "prepared"
    assert action.dependency_factor_ids == dependencies
    assert action.selected_target_revision_id is None
    assert action.generation_request is not None
    assert action.generation_request.action_id == action.action_id
    assert action.generation_request.dependency_factor_ids == dependencies
    assert action.generation_request.digest in (
        action.exact_additional_input_root_commitments
    )
    reservation = _carrier_reservation_for_action(fixture.bank, action)
    assert action.carrier_capacity_reservation_id == reservation.reservation_id
    assert reservation.state == "reserved"
    assert reservation.created_seq == action.prepared_seq
    assert reservation.namespace_digest == action.namespace_digest
    assert reservation.capacity_policy_sha256 == (
        fixture.bank.to_state().capacity_policy.digest
    )
    assert reservation.reserved_factor_records == 1
    assert reservation.reserved_composition_records == 1
    assert reservation.reserved_transition_records == 1
    assert reservation.reserved_admission_records == 1
    assert len(
        [
            item for item in fixture.bank.to_state().proposal_actions
            if item.assignment_id == assignment.assignment_id
        ]
    ) == 1


@pytest.mark.parametrize(
    ("branch", "forged_dependencies"),
    (("mutate", ()), ("fresh", ("instruction:a",))),
)
def test_generated_request_rejects_wrong_parent_or_fresh_dependency(
    branch,
    forged_dependencies,
) -> None:
    fixture = Fixture()
    *_prefix, action = _prepare_generated_action(
        fixture, branch, f"dependency-{branch}"
    )
    assert action.generation_request is not None
    forged = action.generation_request.model_copy(
        update={"dependency_factor_ids": forged_dependencies}
    )

    with pytest.raises(ValueError, match="branch dependency"):
        ProposalGenerationRequestV1.model_validate(
            forged.model_dump(mode="python")
        )


def test_generation_context_verifier_failure_is_byte_atomic() -> None:
    observed = []

    def reject(context, opportunity, receipt, source, source_factor, state):
        observed.append(
            (
                context.digest,
                opportunity.opportunity_id,
                receipt.digest,
                source.composition_id,
                source_factor.revision_id,
                state.digest,
            )
        )
        return False

    fixture = Fixture(proposal_generation_context_verifier=reject)
    opportunity = _repair_opportunity(
        fixture,
        "context-reject",
        feasible_branches=("mutate", "fresh"),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    context = _generation_context(
        fixture, opportunity, proposal, tag="context-reject"
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="generation-context verifier"):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch="proposal-host:context-reject",
            attestation_sha256=_h("proposal-context-reject"),
            generation_context=context,
        )

    assert observed and fixture.bank.to_state() == before


def test_generation_context_cannot_replay_across_failure_opportunities() -> None:
    fixture = Fixture()
    first = _repair_opportunity(
        fixture,
        "context-first",
        feasible_branches=("fresh",),
    )
    first_proposal = _proposal_receipt(fixture, first)
    first_context = _generation_context(
        fixture, first, first_proposal, tag="context-first"
    )
    second = _repair_opportunity(
        fixture,
        "context-second",
        feasible_branches=("fresh",),
    )
    second_proposal = _proposal_receipt(fixture, second)
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="Bank opportunity"):
        fixture.bank.screen_and_allocate_branch(
            second.opportunity_id,
            second_proposal,
            producer_epoch="proposal-host:context-replay",
            attestation_sha256=_h("proposal-context-replay"),
            generation_context=first_context,
        )

    assert fixture.bank.to_state() == before


def test_begin_generation_is_generation1_single_start_and_idempotent() -> None:
    seen_started_seq = []

    def verify(lease, action, state):
        seen_started_seq.append((lease.started_seq, action.state, state.event_seq))
        return True

    fixture = Fixture(proposal_generation_lease_verifier=verify)
    *_prefix, action = _prepare_generated_action(
        fixture, "mutate", "single-start"
    )
    lease = _generation_lease(action, "single-start")
    executing = fixture.bank.begin_proposal_generation(action.action_id, lease)

    assert executing.state == "executing"
    assert executing.generation_lease is not None
    assert executing.generation_lease.started_seq == executing.updated_seq
    assert seen_started_seq[0] == (
        executing.updated_seq,
        "prepared",
        executing.updated_seq - 1,
    )
    assert all(
        item[0] == executing.updated_seq and item[1] == "prepared"
        for item in seen_started_seq
    )
    assert _carrier_reservation_for_action(
        fixture.bank,
        executing,
    ).state == "reserved"
    terminal = fixture.bank.to_state()
    assert fixture.bank.begin_proposal_generation(action.action_id, lease) == executing
    assert fixture.bank.to_state() == terminal

    conflicting = _generation_lease(action, "conflicting-start")
    with pytest.raises(ValueError, match="another lease"):
        fixture.bank.begin_proposal_generation(action.action_id, conflicting)
    assert fixture.bank.to_state() == terminal


def test_generated_action_load_rejects_actionless_and_state_mismatch(
    tmp_path,
) -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture, "mutate", "load-invariants"
    )
    executing = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "load-invariants"),
    )
    path = tmp_path / "generated-executing-v5.json"
    fixture.bank.save(path)
    loaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    assert loaded.scientific_state_sha256 == fixture.bank.scientific_state_sha256

    actionless = fixture.bank.to_state().model_copy(
        update={"proposal_actions": ()}
    )
    with pytest.raises(ValueError, match="lacks its exact action"):
        FactorBankV2(
            actionless,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )

    mismatched = executing.model_copy(update={"state": "prepared"})
    mismatched_state = fixture.bank.to_state().model_copy(
        update={"proposal_actions": (mismatched,)}
    )
    with pytest.raises(ValueError, match="prepared proposal action"):
        FactorBankV2(
            mismatched_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_prepared_reservation_survives_reload_and_authorizes_exact_start(
    tmp_path,
) -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "prepared-reservation-reload",
    )
    path = tmp_path / "prepared-reservation-v9.json"
    fixture.bank.save(path)
    loaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    held = _carrier_reservation_for_action(loaded, prepared)
    assert held.state == "reserved"
    assert held.reservation_id == prepared.carrier_capacity_reservation_id

    executing = loaded.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "prepared-reservation-reload"),
    )
    assert executing.state == "executing"
    assert _carrier_reservation_for_action(loaded, executing) == held


def test_authenticated_reload_rejects_carrier_reservation_policy_tamper(
    tmp_path,
) -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "mutate",
        "reservation-policy-tamper",
    )
    path = tmp_path / "reservation-policy-tamper.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    reservation = next(
        item
        for item in payload["state"]["proposal_carrier_reservations"]
        if item["action_id"] == prepared.action_id
    )
    reservation["capacity_policy_sha256"] = _h("forged-capacity-policy")
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="reservation identity"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_started_generation_lost_response_aborts_without_restart() -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture, "fresh", "lost-response"
    )
    lease = _generation_lease(prepared, "lost-response")
    executing = fixture.bank.begin_proposal_generation(prepared.action_id, lease)
    abort = make_proposal_action_abort_receipt_v2(
        action=executing,
        reason="generation_runner_crash",
        safe_failure_code="lost_generation_response",
        verifier_epoch="proposal-abort-verifier:one",
        attestation_sha256=_h("lost-response-abort"),
    )
    caller_owned_seq = abort.model_copy(
        update={"emitted_seq": fixture.bank.to_state().event_seq + 1}
    )
    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="Bank-owned"):
        fixture.bank.abort_proposal_action(executing.action_id, caller_owned_seq)
    assert fixture.bank.to_state() == before

    aborted = fixture.bank.abort_proposal_action(executing.action_id, abort)
    assert aborted.state == "aborted"
    assert aborted.generation_lease == executing.generation_lease
    assert aborted.abort_receipt is not None
    assert aborted.abort_receipt.emitted_seq == aborted.updated_seq
    released = _carrier_reservation_for_action(fixture.bank, aborted)
    assert released.state == "released"
    assert released.released_seq == aborted.updated_seq
    assert released.materialized_seq is None
    with pytest.raises(ValueError, match="prepared generated action"):
        fixture.bank.begin_proposal_generation(prepared.action_id, lease)
    assert not any(
        item.proposal_action_id == prepared.action_id
        for item in fixture.bank.to_state().direct_transitions
    )


@pytest.mark.parametrize("branch", ("mutate", "fresh"))
def test_generated_action_projects_one_inert_edge_and_finalizes_exactly(
    branch,
) -> None:
    expected_terminal = {"sha256": None}

    def terminal_verifier(action, transition, state):
        return bool(
            action.state == "committed"
            and action.branch == transition.origin_branch == branch
            and action.generation_terminal_sha256
            == expected_terminal["sha256"]
            and action.resolved_to_revision_id == transition.to_revision_id
            and transition.proposal_action_committed_seq == action.updated_seq
            and state.event_seq == action.updated_seq
        )

    fixture = Fixture(proposal_action_terminal_verifier=terminal_verifier)
    *_prefix, prepared = _prepare_generated_action(
        fixture, branch, f"finalize-{branch}"
    )
    executing = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, f"finalize-{branch}"),
    )
    tag = f"finalize-carrier-{branch}"
    generated, target = _uninstalled_generated_carrier(
        fixture,
        branch,
        tag,
    )
    before_wrong_branch = fixture.bank.to_state()
    wrong_branch = "fresh" if branch == "mutate" else "mutate"
    with pytest.raises(ValueError, match="prepared proposal action"):
        _register_action_bundle(
            fixture,
            action=executing,
            branch=wrong_branch,
            tag=f"wrong-{tag}",
            generated=generated,
            target=target,
            proof_sha256=_h(f"generated-proof:wrong:{branch}"),
        )
    assert fixture.bank.to_state() == before_wrong_branch

    proof_sha256 = _h(f"generated-proof:{branch}")
    transition = _register_action_bundle(
        fixture,
        action=executing,
        branch=branch,
        tag=tag,
        generated=generated,
        target=target,
        proof_sha256=proof_sha256,
    )
    materialized = _carrier_reservation_for_action(fixture.bank, executing)
    assert materialized.state == "materialized"
    assert materialized.materialized_seq == transition.created_seq
    assert transition.proposal_action_committed_seq is None
    staged_admission = _admission_for_edge(fixture.bank, transition)
    assert staged_admission.state == "staged"
    assert not staged_admission.factor_independently_eligible_before
    assert not staged_admission.composition_independently_eligible_before
    opportunity = next(
        item for item in fixture.bank.to_state().repair_opportunities
        if item.opportunity_id
        == next(
            decision.repair_opportunity_id
            for decision in fixture.bank.to_state().proposal_decisions
            if decision.decision_id == executing.proposal_decision_id
        )
    )
    staged_slate, _universe, _count = fixture.bank._proposal_candidate_slate(
        opportunity=opportunity,
        source_factor=fixture.old,
        slot_id="instruction_slot",
    )
    assert generated.revision_id not in {
        item.target_revision_id for item in staged_slate
    }
    with pytest.raises(ValueError, match="already owns a local edge"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id=f"proof:generated:duplicate:{branch}",
            binding_proof_sha256=_h(f"generated-proof:duplicate:{branch}"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:generated",
            origin_branch=branch,
            proposal_action_id=executing.action_id,
            proposal_action_intent_sha256=executing.action_intent_sha256,
        )

    terminal_sha256 = _h(f"generation-terminal:{branch}")
    expected_terminal["sha256"] = terminal_sha256
    before_wrong_target = fixture.bank.to_state()
    with pytest.raises(ValueError, match="does not join"):
        fixture.bank.finalize_proposal_action(
            executing.action_id,
            transition_id=transition.transition_id,
            phase_terminal_sha256=proof_sha256,
            generation_terminal_sha256=terminal_sha256,
            resolved_to_revision_id=fixture.new.revision_id,
            resolved_target_content_sha256=fixture.new.content_sha256,
        )
    assert fixture.bank.to_state() == before_wrong_target

    before_wrong_terminal = fixture.bank.to_state()
    with pytest.raises(ValueError, match="terminal verifier"):
        fixture.bank.finalize_proposal_action(
            executing.action_id,
            transition_id=transition.transition_id,
            phase_terminal_sha256=proof_sha256,
            generation_terminal_sha256=_h(f"wrong-terminal:{branch}"),
            resolved_to_revision_id=generated.revision_id,
            resolved_target_content_sha256=generated.content_sha256,
        )
    assert fixture.bank.to_state() == before_wrong_terminal

    committed = fixture.bank.finalize_proposal_action(
        executing.action_id,
        transition_id=transition.transition_id,
        phase_terminal_sha256=proof_sha256,
        generation_terminal_sha256=terminal_sha256,
        resolved_to_revision_id=generated.revision_id,
        resolved_target_content_sha256=generated.content_sha256,
    )
    assert committed.state == "committed"
    assert committed.resolved_to_revision_id == generated.revision_id
    assert fixture.bank.direct_transitions[
        transition.transition_id
    ].proposal_action_committed_seq == committed.updated_seq
    admitted = _admission_for_edge(fixture.bank, transition)
    assert admitted.state == "admitted"
    assert admitted.terminal_seq == committed.updated_seq
    assert admitted.terminal_sha256 is not None
    consumed = _carrier_reservation_for_action(fixture.bank, committed)
    assert consumed.state == "consumed"
    assert consumed.materialized_seq == transition.created_seq
    assert consumed.consumed_seq == committed.updated_seq
    assert not any(
        item.transition_id == transition.transition_id
        for item in fixture.bank.to_state().assessments
    )


def test_committed_action_first_member_becomes_its_edge_credit_owner() -> None:
    fixture = Fixture()
    action, generated, target, edge, proof = _project_generated_edge(
        fixture,
        "mutate",
        "action-first-credit-owner",
    )
    with pytest.raises(ValueError, match="inert until action finalization"):
        fixture.bank.seal_probe_plan(
            transition_id=edge.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:action-first-before-commit",
            unit_commitments=tuple(
                _h(f"action-first-before-commit-{index}")
                for index in range(6)
            ),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("action-first-before-commit-manifest"),
            runner_version="runner:action-first",
            budget=_budget(),
        )
    committed = fixture.bank.finalize_proposal_action(
        action.action_id,
        transition_id=edge.transition_id,
        phase_terminal_sha256=proof,
        generation_terminal_sha256=_h("action-first-generation-terminal"),
        resolved_to_revision_id=generated.revision_id,
        resolved_target_content_sha256=generated.content_sha256,
    )
    assert committed.state == "committed"
    plan = fixture.bank.seal_probe_plan(
        transition_id=edge.transition_id,
        owner_kind="direct_factor",
        epoch_id="epoch:action-first-after-commit",
        unit_commitments=tuple(
            _h(f"action-first-after-commit-{index}")
            for index in range(6)
        ),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_h("action-first-after-commit-manifest"),
        runner_version="runner:action-first",
        budget=_budget(),
    )
    assert plan.transition_id == edge.transition_id
    assert plan.credit_owner_transition_id == edge.transition_id
    assert plan.canonical_scientific_edge_key_sha256 == (
        fixture.bank._canonical_scientific_edge_sha256(
            fixture.bank.to_state(),
            fixture.bank.direct_transitions[edge.transition_id],
        )
    )
    assert target.composition_id in fixture.bank.compositions


def test_archive_protects_executing_generated_action_and_pending_edge() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            unknown_structural_reserve=0,
            max_infrastructure_epochs_per_edge=1,
        )
    )
    attempt = _open_next(fixture)
    fixture.bank.cancel_open_attempt(
        attempt.attempt_id,
        _cancellation(fixture, attempt, terminate_scope=True),
    )
    *_prefix, prepared = _prepare_generated_action(
        fixture, "mutate", "archive-executing"
    )
    executing = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "archive-executing"),
    )
    generated, target = _uninstalled_generated_carrier(
        fixture,
        "mutate",
        "archive-generated",
    )
    proof_sha256 = _h("archive-generated-proof")
    edge = _register_action_bundle(
        fixture,
        action=executing,
        branch="mutate",
        tag="archive-generated",
        generated=generated,
        target=target,
        proof_sha256=proof_sha256,
    )

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-executing-action"),
        required_hot_slots=100,
        max_victims=1,
    )

    assert checkpoint is not None
    assert edge.transition_id not in checkpoint.subject_ids
    assert fixture.bank.compositions[
        executing.source_composition_id
    ].structural_state == "live"
    assert fixture.bank.compositions[target.composition_id].structural_state == "live"
    assert fixture.bank.factors[fixture.old.revision_id].structural_state == "live"
    assert fixture.bank.factors[generated.revision_id].structural_state == "live"
    committed = fixture.bank.finalize_proposal_action(
        executing.action_id,
        transition_id=edge.transition_id,
        phase_terminal_sha256=proof_sha256,
        generation_terminal_sha256=_h("archive-generation-terminal"),
        resolved_to_revision_id=generated.revision_id,
        resolved_target_content_sha256=generated.content_sha256,
    )
    assert committed.state == "committed"


@pytest.mark.parametrize("branch", ("mutate", "fresh"))
def test_rejected_generated_terminal_recovers_exact_edge_after_reload_and_releases_capacity(
    tmp_path,
    branch,
) -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(max_transition_records=2),
        proposal_action_terminal_verifier=lambda *_args: False,
    )
    executing, generated, target, transition, proof_sha256 = (
        _project_generated_edge(fixture, branch, f"recover-{branch}")
    )
    before_terminal = fixture.bank.to_state()
    with pytest.raises(ValueError, match="terminal verifier"):
        fixture.bank.finalize_proposal_action(
            executing.action_id,
            transition_id=transition.transition_id,
            phase_terminal_sha256=proof_sha256,
            generation_terminal_sha256=_h(f"rejected-terminal:{branch}"),
            resolved_to_revision_id=generated.revision_id,
            resolved_target_content_sha256=generated.content_sha256,
        )
    assert fixture.bank.to_state() == before_terminal

    path = tmp_path / f"generated-edge-crash-{branch}.json"
    fixture.bank.save(path)
    verifier_views: list[str] = []

    def exact_abort_verifier(receipt, predecessor, state):
        assert receipt.expected_action_sha256 == predecessor.digest
        assert receipt.cleanup_action_intent_sha256 == predecessor.action_intent_sha256
        action = next(
            item for item in state.proposal_actions
            if item.action_id == predecessor.action_id
        )
        edges = [
            item for item in state.direct_transitions
            if item.transition_id == receipt.cleanup_transition_id
        ]
        verifier_views.append(action.state)
        if action.state == "executing":
            return bool(
                len(edges) == 1
                and edges[0].proposal_action_id == predecessor.action_id
                and edges[0].proposal_action_intent_sha256
                == predecessor.action_intent_sha256
                and _canonical_hash(edges[0])
                == receipt.cleanup_transition_sha256
            )
        return bool(
            action.state == "aborted"
            and not edges
            and action.abort_receipt == receipt
        )

    capabilities = _trusted_bank_capabilities()
    capabilities["proposal_abort_verifier"] = exact_abort_verifier
    recovered = FactorBankV2.load(path, state_key=fixture.key, **capabilities)
    recovered_action = next(
        item for item in recovered.to_state().proposal_actions
        if item.action_id == executing.action_id
    )
    recovered_edge = recovered.direct_transitions[transition.transition_id]
    abort = make_proposal_action_abort_receipt_v2(
        action=recovered_action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof_sha256,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:recovery",
        attestation_sha256=_h(f"cleanup-abort:{branch}"),
        cleanup_transition=recovered_edge,
        cleanup_admission=_admission_for_edge(recovered, recovered_edge),
    )
    before_abort_seq = recovered.to_state().event_seq
    aborted = recovered.abort_proposal_action(recovered_action.action_id, abort)

    assert aborted.state == "aborted"
    assert aborted.fencing_generation == 2
    assert aborted.abort_receipt is not None
    assert aborted.abort_receipt.cleanup_transition_id == transition.transition_id
    assert recovered.to_state().event_seq == before_abort_seq + 1
    assert transition.transition_id not in recovered.direct_transitions
    assert len(recovered.direct_transitions) == 1
    # Post-edge rejection consumes the reservation and retains the rows under
    # explicit quarantine; negative evidence never returns hot capacity.
    assert generated.revision_id in recovered.factors
    assert target.composition_id in recovered.compositions
    quarantined = _admission_for_edge(recovered, transition)
    assert quarantined.state == "quarantined"
    assert not quarantined.factor_independently_eligible_before
    assert not quarantined.composition_independently_eligible_before
    consumed = _carrier_reservation_for_action(recovered, aborted)
    assert consumed.state == "consumed"
    assert consumed.materialized_seq == transition.created_seq
    assert consumed.consumed_seq == aborted.updated_seq
    assert {"executing", "aborted"}.issubset(set(verifier_views))

    replay_state = recovered.to_state()
    assert recovered.abort_proposal_action(recovered_action.action_id, abort) == aborted
    assert recovered.to_state() == replay_state

    before_launder = recovered.to_state()
    with pytest.raises(ValueError, match="cannot launder"):
        recovered.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id=f"proof:launder-rejected:{branch}",
            binding_proof_sha256=_h(f"launder-rejected-proof:{branch}"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:launder-rejected",
            origin_branch=branch,
        )
    assert recovered.to_state() == before_launder

    replacement_factor = fixture.new.model_copy(
        update={
            "revision_id": f"instruction:capacity-released:{branch}",
            "content_sha256": _h(f"capacity-released-content:{branch}"),
            "created_seq": recovered.to_state().event_seq + 1,
        }
    )
    recovered.add_factor(replacement_factor)
    replacement_target = fixture.target.model_copy(
        update={
            "composition_id": f"composition:capacity-released:{branch}",
            "artifact_revision_id": f"artifact:capacity-released:{branch}",
            "artifact_sha256": _h(f"capacity-released-artifact:{branch}"),
            "bindings": (
                fixture.target.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=replacement_factor.revision_id,
                ),
            ),
            "created_seq": recovered.to_state().event_seq + 1,
        }
    )
    recovered.add_composition(replacement_target)
    replacement = recovered.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=replacement_target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id=f"proof:capacity-released:{branch}",
        binding_proof_sha256=_h(f"capacity-released-proof:{branch}"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:capacity-released",
        origin_branch=branch,
    )
    assert len(recovered.direct_transitions) == 2

    reloaded = FactorBankV2.load(path, state_key=fixture.key, **capabilities)
    reloaded_action = next(
        item for item in reloaded.to_state().proposal_actions
        if item.action_id == executing.action_id
    )
    assert reloaded_action.state == "aborted"
    assert transition.transition_id not in reloaded.direct_transitions
    assert replacement.transition_id in reloaded.direct_transitions
    assert generated.revision_id in reloaded.factors
    assert target.composition_id in reloaded.compositions


def test_generated_cleanup_rejects_wrong_edge_committed_action_and_plan_owner() -> None:
    fixture = Fixture()
    executing, generated, _target, transition, proof_sha256 = (
        _project_generated_edge(fixture, "mutate", "cleanup-rejections")
    )
    cleanup = make_proposal_action_abort_receipt_v2(
        action=executing,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof_sha256,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:rejections",
        attestation_sha256=_h("cleanup-rejections"),
        cleanup_transition=transition,
        cleanup_admission=_admission_for_edge(fixture.bank, transition),
    )
    wrong_edge = _retarget_cleanup_receipt(
        cleanup,
        fixture.transition,
        _admission_for_edge(fixture.bank, transition),
    )
    before_wrong = fixture.bank.to_state()
    with pytest.raises(ValueError, match="exact generated inert edge"):
        fixture.bank.abort_proposal_action(executing.action_id, wrong_edge)
    assert fixture.bank.to_state() == before_wrong

    terminal_sha256 = _h("accepted-terminal:cleanup-rejections")
    committed = fixture.bank.finalize_proposal_action(
        executing.action_id,
        transition_id=transition.transition_id,
        phase_terminal_sha256=proof_sha256,
        generation_terminal_sha256=terminal_sha256,
        resolved_to_revision_id=generated.revision_id,
        resolved_target_content_sha256=generated.content_sha256,
    )
    assert committed.state == "committed"
    committed_state = fixture.bank.to_state()
    with pytest.raises(ValueError, match="prepared or executing"):
        fixture.bank.abort_proposal_action(executing.action_id, cleanup)
    assert fixture.bank.to_state() == committed_state

    blocked = Fixture()
    blocked_action, _generated, _target, blocked_edge, blocked_proof = (
        _project_generated_edge(blocked, "fresh", "cleanup-plan-owner")
    )
    blocked_receipt = make_proposal_action_abort_receipt_v2(
        action=blocked_action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=blocked_proof,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:plan-owner",
        attestation_sha256=_h("cleanup-plan-owner"),
        cleanup_transition=blocked_edge,
        cleanup_admission=_admission_for_edge(blocked.bank, blocked_edge),
    )
    valid_state = blocked.bank._state
    forged_plan = blocked.plan.model_copy(
        update={
            "plan_id": "plan:cleanup-blocker",
            "transition_id": blocked_edge.transition_id,
        }
    )
    blocked.bank._state = valid_state.model_copy(
        update={"plans": (*valid_state.plans, forged_plan)}
    )
    try:
        with pytest.raises(ValueError, match="downstream owners: plan"):
            blocked.bank.abort_proposal_action(
                blocked_action.action_id,
                blocked_receipt,
            )
        assert blocked.bank._state == valid_state.model_copy(
            update={"plans": (*valid_state.plans, forged_plan)}
        )
    finally:
        blocked.bank._state = valid_state
    assert blocked.bank.to_state() == valid_state


def test_generated_cleanup_abort_verifier_rejection_is_atomic() -> None:
    fixture = Fixture(proposal_abort_verifier=lambda *_args: False)
    executing, _generated, _target, transition, proof_sha256 = (
        _project_generated_edge(fixture, "fresh", "cleanup-verifier-reject")
    )
    receipt = make_proposal_action_abort_receipt_v2(
        action=executing,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof_sha256,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:reject",
        attestation_sha256=_h("cleanup-verifier-reject"),
        cleanup_transition=transition,
        cleanup_admission=_admission_for_edge(fixture.bank, transition),
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="abort verifier rejected"):
        fixture.bank.abort_proposal_action(executing.action_id, receipt)

    assert fixture.bank.to_state() == before
    assert transition.transition_id in fixture.bank.direct_transitions


@pytest.mark.parametrize(
    ("failure_class", "feasible_branches"),
    (
        ("infrastructure", None),
        ("infrastructure", ("reuse",)),
        ("harness", None),
        ("harness", ("fresh",)),
        ("algorithm", None),
        ("algorithm", ("mutate",)),
    ),
)
def test_staged_action_edge_rejects_every_failure_owner_before_and_after_reload(
    tmp_path,
    failure_class,
    feasible_branches,
) -> None:
    fixture = Fixture()
    action, _factor, target, edge, _proof = _project_generated_edge(
        fixture,
        "fresh",
        f"failure-guard-{failure_class}-{bool(feasible_branches)}",
    )
    path = tmp_path / f"failure-guard-{failure_class}-{bool(feasible_branches)}.json"
    fixture.bank.save(path)
    bank = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    before = bank.to_state()
    observation = FailureObservationV2(
        failure_id=f"failure:inert:{failure_class}:{bool(feasible_branches)}",
        failure_class=failure_class,
        failed_stage="execute",
        safe_failure_code=f"inert_{failure_class}",
        composition_id=target.composition_id,
        transition_id=edge.transition_id,
        artifact_sha256=target.artifact_sha256,
        created_seq=before.event_seq + 1,
    )

    with pytest.raises(ValueError, match="no failure authority"):
        bank.record_failure(
            observation,
            feasible_branches=feasible_branches,
        )

    assert bank.to_state() == before
    assert next(
        item for item in before.proposal_actions if item.action_id == action.action_id
    ).state == "executing"
    assert _admission_for_edge(bank, edge).state == "staged"


def test_staged_exclusive_composition_rejects_transitionless_failure_owner() -> None:
    fixture = Fixture()
    _action, _factor, target, edge, _proof = _project_generated_edge(
        fixture,
        "mutate",
        "transitionless-failure",
    )
    before = fixture.bank.to_state()
    observation = FailureObservationV2(
        failure_id="failure:inert:transitionless",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="inert_transitionless",
        composition_id=target.composition_id,
        transition_id=None,
        artifact_sha256=target.artifact_sha256,
        created_seq=before.event_seq + 1,
    )

    with pytest.raises(ValueError, match="no failure authority"):
        fixture.bank.record_failure(
            observation,
            feasible_branches=("reuse", "mutate", "fresh"),
        )

    assert fixture.bank.to_state() == before
    assert _admission_for_edge(fixture.bank, edge).state == "staged"


def test_exact_prepared_reuse_rejection_cleans_once_and_preserves_shared_authority(
    tmp_path,
) -> None:
    fixture = Fixture(proposal_action_terminal_verifier=lambda *_args: False)
    opportunity = _repair_opportunity(
        fixture,
        "reuse-cleanup",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:reuse-cleanup",
        attestation_sha256=_h("reuse-cleanup-action"),
    )
    assert action is not None and action.state == "prepared"
    proof = _h("reuse-cleanup-phase-terminal")
    edge = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:reuse-cleanup",
        binding_proof_sha256=proof,
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:reuse-cleanup",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    admission = _admission_for_edge(fixture.bank, edge)
    assert admission.state == "staged"
    assert admission.factor_independently_eligible_before
    assert admission.composition_independently_eligible_before
    before_rejected_terminal = fixture.bank.to_state()
    with pytest.raises(ValueError, match="terminal verifier"):
        fixture.bank.finalize_proposal_action(
            action.action_id,
            transition_id=edge.transition_id,
            phase_terminal_sha256=proof,
        )
    assert fixture.bank.to_state() == before_rejected_terminal

    path = tmp_path / "reuse-cleanup.json"
    fixture.bank.save(path)
    bank = FactorBankV2.load(
        path,
        state_key=fixture.key,
        proposal_action_terminal_verifier=lambda *_args: False,
        **{
            key: value
            for key, value in _trusted_bank_capabilities().items()
            if key != "proposal_action_terminal_verifier"
        },
    )
    loaded_action = next(
        item for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    loaded_edge = bank.direct_transitions[edge.transition_id]
    receipt = make_proposal_action_abort_receipt_v2(
        action=loaded_action,
        reason="phase_rejected",
        phase_terminal_sha256=proof,
        safe_failure_code="phase_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:reuse-cleanup",
        attestation_sha256=_h("reuse-cleanup-abort"),
        cleanup_transition=loaded_edge,
        cleanup_admission=_admission_for_edge(bank, loaded_edge),
    )
    before_seq = bank.to_state().event_seq
    results: list[ProposalActionV2] = []
    errors: list[BaseException] = []

    def clean() -> None:
        try:
            results.append(bank.abort_proposal_action(action.action_id, receipt))
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [threading.Thread(target=clean) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors and len(results) == 2 and results[0] == results[1]
    assert bank.to_state().event_seq == before_seq + 1
    assert edge.transition_id not in bank.direct_transitions
    quarantined = _admission_for_edge(bank, edge)
    assert quarantined.state == "quarantined"
    assert quarantined.terminal_seq == results[0].updated_seq
    assert quarantined.terminal_sha256 is not None
    slate, _universe, _count = bank._proposal_candidate_slate(
        opportunity=opportunity,
        source_factor=bank.factors[fixture.old.revision_id],
        slot_id="instruction_slot",
    )
    assert fixture.new.revision_id in {
        item.target_revision_id for item in slate
    }
    assert fixture.transition.transition_id in bank.direct_transitions
    before_duplicate = bank.to_state()
    with pytest.raises(ValueError, match="already has a credit owner"):
        bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=fixture.target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:reuse-shared-authority",
            binding_proof_sha256=_h("reuse-shared-authority-proof"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:reuse-shared-authority",
            origin_branch="reuse",
        )
    assert bank.to_state() == before_duplicate
    terminal = bank.to_state()
    with pytest.raises(ValueError, match="commit state"):
        bank.finalize_proposal_action(
            action.action_id,
            transition_id=edge.transition_id,
            phase_terminal_sha256=proof,
        )
    assert bank.to_state() == terminal
    reloaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        proposal_action_terminal_verifier=lambda *_args: False,
        **{
            key: value
            for key, value in _trusted_bank_capabilities().items()
            if key != "proposal_action_terminal_verifier"
        },
    )
    assert _admission_for_edge(reloaded, edge).state == "quarantined"


def test_two_loaded_cleaners_are_fenced_by_file_cas_with_admission_rollback(
    tmp_path,
) -> None:
    fixture = Fixture()
    action, _factor, _target, edge, proof = _project_generated_edge(
        fixture,
        "fresh",
        "two-loaded-cleaners",
    )
    path = tmp_path / "two-loaded-cleaners.json"
    fixture.bank.save(path)
    first = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    second = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    first_action = next(
        item for item in first.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    first_edge = first.direct_transitions[edge.transition_id]
    receipt = make_proposal_action_abort_receipt_v2(
        action=first_action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:two-loaded-cleaners",
        attestation_sha256=_h("two-loaded-cleaners-abort"),
        cleanup_transition=first_edge,
        cleanup_admission=_admission_for_edge(first, first_edge),
    )
    second_before = second.to_state()

    committed = first.abort_proposal_action(action.action_id, receipt)
    with pytest.raises(RuntimeError, match="compare-and-swap"):
        second.abort_proposal_action(action.action_id, receipt)

    assert committed.state == "aborted"
    assert second.to_state() == second_before
    assert _admission_for_edge(second, edge).state == "staged"
    reloaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **_trusted_bank_capabilities(),
    )
    assert _admission_for_edge(reloaded, edge).state == "quarantined"


def test_cleanup_rejects_stale_or_substituted_admission_digest_atomically() -> None:
    fixture = Fixture()
    action, _factor, _target, edge, proof = _project_generated_edge(
        fixture,
        "mutate",
        "stale-admission",
    )
    actual = _admission_for_edge(fixture.bank, edge)
    substituted = _rewrite_admission(
        actual,
        target_factor_sha256=_h("substituted-admission-factor"),
    )
    stale = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:stale-admission",
        attestation_sha256=_h("stale-admission-abort"),
        cleanup_transition=edge,
        cleanup_admission=substituted,
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="exact generated inert edge"):
        fixture.bank.abort_proposal_action(action.action_id, stale)

    assert fixture.bank.to_state() == before
    assert _admission_for_edge(fixture.bank, edge) == actual


def test_external_post_prepare_rows_cannot_claim_preexisting_authority() -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "external-row",
    )
    action = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "external-row"),
    )
    generated = fixture._factor(
        "instruction:external-post-prepare",
        "external-post-prepare-value",
    )
    target = fixture._composition(
        "composition:external-post-prepare",
        generated.revision_id,
        "external-post-prepare-artifact",
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="independent carrier authority"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:external-post-prepare",
            binding_proof_sha256=_h("external-post-prepare-proof"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:external-post-prepare",
            origin_branch="fresh",
            proposal_action_id=action.action_id,
            proposal_action_intent_sha256=action.action_intent_sha256,
        )

    assert fixture.bank.to_state() == before


def test_active_action_fences_post_prepare_ordinary_bundle_atomically() -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "active-action-ordinary-bundle",
    )
    action = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "active-action-ordinary-bundle"),
    )
    generated, target = _uninstalled_generated_carrier(
        fixture,
        "fresh",
        "active-action-ordinary-bundle",
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="active proposal action locus"):
        fixture.bank.register_direct_bundle(
            factors=(generated,),
            compositions=(target,),
            transition_fields={
                "source_composition_id": fixture.source.composition_id,
                "target_composition_id": target.composition_id,
                "slot_id": "instruction_slot",
                "binding_proof_id": "proof:active-action-ordinary-bundle",
                "binding_proof_sha256": _h(
                    "active-action-ordinary-bundle-proof"
                ),
                "masked_background_sha256": _h("masked-background"),
                "binding_verifier_epoch": "binder:active-action-ordinary-bundle",
                "origin_branch": "fresh",
            },
        )

    assert action.state == "executing"
    assert fixture.bank.to_state() == before
    assert generated.revision_id not in fixture.bank.factors
    assert target.composition_id not in fixture.bank.compositions


def test_active_action_fence_cannot_be_bypassed_by_canonical_source_alias() -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "active-action-source-alias",
    )
    fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "active-action-source-alias"),
    )
    old_alias = fixture.old.model_copy(
        update={
            "revision_id": "instruction:active-action-source-alias",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_factor(old_alias)
    source_alias = fixture.source.model_copy(
        update={
            "composition_id": "composition:active-action-source-alias",
            "artifact_revision_id": "artifact:active-action-source-alias",
            "bindings": (
                fixture.source.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=old_alias.revision_id,
                ),
            ),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(source_alias)
    generated, target = _uninstalled_generated_carrier(
        fixture,
        "fresh",
        "active-action-source-alias",
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="active proposal action locus"):
        fixture.bank.register_direct_bundle(
            factors=(generated,),
            compositions=(target,),
            transition_fields={
                "source_composition_id": source_alias.composition_id,
                "target_composition_id": target.composition_id,
                "slot_id": "instruction_slot",
                "binding_proof_id": "proof:active-action-source-alias",
                "binding_proof_sha256": _h("active-action-source-alias-proof"),
                "masked_background_sha256": _h("masked-background"),
                "binding_verifier_epoch": "binder:active-action-source-alias",
                "origin_branch": "fresh",
            },
        )

    assert fixture.bank.to_state() == before
    assert old_alias.revision_id in fixture.bank.factors
    assert source_alias.composition_id in fixture.bank.compositions
    assert generated.revision_id not in fixture.bank.factors
    assert target.composition_id not in fixture.bank.compositions


def test_pre_prepare_canonical_source_alias_cannot_split_credit_owner() -> None:
    fixture = Fixture()
    source_alias = fixture.source.model_copy(
        update={
            "composition_id": "composition:pre-prepare-source-alias",
            "artifact_revision_id": "artifact:pre-prepare-source-alias",
            "bindings": (
                fixture.source.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=fixture.old.revision_id,
                ),
            ),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(source_alias)
    before_alias = fixture.bank.to_state()
    with pytest.raises(ValueError, match="already has a credit owner"):
        fixture.bank.register_direct_transition(
            source_composition_id=source_alias.composition_id,
            target_composition_id=fixture.target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:pre-prepare-source-alias",
            binding_proof_sha256=_h("pre-prepare-source-alias-proof"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:pre-prepare-source-alias",
            origin_branch="reuse",
        )
    assert fixture.bank.to_state() == before_alias
    opportunity = _repair_opportunity(
        fixture,
        "pre-prepare-source-alias",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:pre-prepare-source-alias",
        attestation_sha256=_h("pre-prepare-source-alias-action"),
    )

    assert assignment is not None and action is not None
    assert fixture.transition.created_seq < action.prepared_seq
    assert fixture.transition.transition_id in fixture.bank.direct_transitions


def test_active_action_fences_post_prepare_ordinary_whole_owner() -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "active-action-ordinary-whole",
    )
    fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "active-action-ordinary-whole"),
    )
    generated, target = _uninstalled_generated_carrier(
        fixture,
        "fresh",
        "active-action-ordinary-whole",
    )
    fixture.bank.add_factor(generated)
    fixture.bank.add_composition(target)
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="active proposal action locus"):
        fixture.bank.register_whole_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=target.composition_id,
            operation_receipt_sha256=_h("active-action-ordinary-whole-receipt"),
            operation_verifier_epoch="whole-verifier:active-action-window",
            origin_branch="fresh",
        )

    assert fixture.bank.to_state() == before


def test_pre_prepare_ordinary_owner_is_frozen_at_action_cutoff() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "pre-prepare-owner-cutoff",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:pre-prepare-owner-cutoff",
        attestation_sha256=_h("pre-prepare-owner-cutoff-action"),
    )
    assert assignment is not None and action is not None
    proof = _h("pre-prepare-owner-cutoff-proof")
    edge = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:pre-prepare-owner-cutoff",
        binding_proof_sha256=proof,
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:pre-prepare-owner-cutoff",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    staged = _admission_for_edge(fixture.bank, edge)

    assert fixture.transition.created_seq < action.prepared_seq
    assert staged.independent_authority_cutoff_seq == action.prepared_seq
    assert staged.factor_independently_eligible_before
    assert staged.composition_independently_eligible_before

    fixture.bank.abort_proposal_action(
        action.action_id,
        make_proposal_action_abort_receipt_v2(
            action=action,
            reason="phase_rejected",
            phase_terminal_sha256=proof,
            safe_failure_code="phase_rejected",
            verifier_epoch="proposal-abort-verifier:pre-prepare-owner-cutoff",
            attestation_sha256=_h("pre-prepare-owner-cutoff-abort"),
            cleanup_transition=edge,
            cleanup_admission=staged,
        ),
    )

    assert fixture.transition.transition_id in fixture.bank.direct_transitions
    assert edge.transition_id not in fixture.bank.direct_transitions
    assert _admission_for_edge(fixture.bank, edge).state == "quarantined"


def test_storage_only_rows_are_not_pre_prepare_authority_and_need_owner() -> None:
    fixture = Fixture()
    storage_factor = fixture._factor(
        "instruction:storage-only",
        "storage-only-content",
    )
    storage_target = fixture._composition(
        "composition:storage-only",
        storage_factor.revision_id,
        "storage-only-artifact",
    )
    candidate_opportunity = _repair_opportunity(
        fixture,
        "storage-only-candidate",
        feasible_branches=("reuse",),
    )
    before_slate, _universe, _count = fixture.bank._proposal_candidate_slate(
        opportunity=candidate_opportunity,
        source_factor=fixture.old,
        slot_id="instruction_slot",
    )
    assert storage_factor.revision_id not in {
        item.target_revision_id for item in before_slate
    }
    assert not fixture.bank._row_is_carrier_eligible(
        fixture.bank.to_state(),
        row_kind="factor",
        row_id=storage_factor.revision_id,
    )
    assert not fixture.bank._row_is_carrier_eligible(
        fixture.bank.to_state(),
        row_kind="composition",
        row_id=storage_target.composition_id,
    )
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "storage-only-authority",
    )
    action = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "storage-only-authority"),
    )
    proof = _h("storage-only-authority-proof")
    assert storage_factor.created_seq < prepared.prepared_seq
    assert storage_target.created_seq < prepared.prepared_seq
    before_projection = fixture.bank.to_state()
    with pytest.raises(ValueError, match="lacks independent carrier authority"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=storage_target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:storage-only-authority",
            binding_proof_sha256=proof,
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:storage-only-authority",
            origin_branch="fresh",
            proposal_action_id=action.action_id,
            proposal_action_intent_sha256=action.action_intent_sha256,
        )
    assert fixture.bank.to_state() == before_projection

    aborted = fixture.bank.abort_proposal_action(
        action.action_id,
        make_proposal_action_abort_receipt_v2(
            action=action,
            reason="generation_invalid_output",
            safe_failure_code="storage_only_target_not_owned",
            verifier_epoch="proposal-abort-verifier:storage-only-authority",
            attestation_sha256=_h("storage-only-authority-abort"),
        ),
    )
    assert aborted.state == "aborted"
    ordinary = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=storage_target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:storage-only-first-owner",
        binding_proof_sha256=_h("storage-only-first-owner-proof"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:storage-only-first-owner",
        origin_branch="fresh",
    )
    assert ordinary.transition_id in fixture.bank.direct_transitions
    assert fixture.bank._row_is_carrier_eligible(
        fixture.bank.to_state(),
        row_kind="factor",
        row_id=storage_factor.revision_id,
    )
    after_slate, _universe, _count = fixture.bank._proposal_candidate_slate(
        opportunity=candidate_opportunity,
        source_factor=fixture.old,
        slot_id="instruction_slot",
    )
    assert storage_factor.revision_id in {
        item.target_revision_id for item in after_slate
    }


def test_verified_whole_transition_can_be_first_storage_owner() -> None:
    fixture = Fixture()
    storage_factor = fixture._factor(
        "instruction:whole-first-owner",
        "whole-first-owner-content",
    )
    storage_target = fixture._composition(
        "composition:whole-first-owner",
        storage_factor.revision_id,
        "whole-first-owner-artifact",
    )
    assert not fixture.bank._composition_has_carrier_authority(
        fixture.bank.to_state(),
        storage_target,
    )

    transition = fixture.bank.register_whole_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=storage_target.composition_id,
        operation_receipt_sha256=_h("whole-first-owner-receipt"),
        operation_verifier_epoch="whole-verifier:first-owner",
        origin_branch="fresh",
    )

    assert transition.transition_id in fixture.bank.whole_transitions
    assert fixture.bank._composition_has_carrier_authority(
        fixture.bank.to_state(),
        storage_target,
    )


def test_authenticated_replay_rejects_historical_action_window_owner(
    tmp_path,
) -> None:
    fixture = Fixture()
    ordinary_transition = fixture.transition
    opportunity = _repair_opportunity(
        fixture,
        "historical-action-window-owner",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:historical-action-window-owner",
        attestation_sha256=_h("historical-action-window-owner-action"),
    )
    assert assignment is not None and action is not None
    path = tmp_path / "historical-action-window-owner.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    ordinary = next(
        item
        for item in payload["state"]["direct_transitions"]
        if item["transition_id"] == ordinary_transition.transition_id
    )
    ordinary["created_seq"] = action.prepared_seq + 1
    payload["state"]["event_seq"] = action.prepared_seq + 1
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="proposal action window"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_admission_capacity_preflight_rejects_before_action_or_start() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(max_proposal_carrier_admissions=0)
    )
    opportunity = _repair_opportunity(
        fixture,
        "admission-capacity",
        feasible_branches=("fresh",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    context = _generation_context(
        fixture,
        opportunity,
        proposal,
        tag="admission-capacity",
    )
    before = fixture.bank.to_state()

    with pytest.raises(RuntimeError, match="carrier_capacity: admission preflight"):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch="proposal-host:admission-capacity",
            attestation_sha256=_h("admission-capacity-action"),
            generation_context=context,
        )

    assert fixture.bank.to_state() == before
    assert not fixture.bank.to_state().proposal_actions
    assert not fixture.bank.to_state().proposal_carrier_reservations


def test_generated_prepare_holds_last_structural_slots_against_ordinary_writers() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_factor_records=4,
            max_composition_records=3,
            max_transition_records=2,
            max_proposal_carrier_admissions=1,
            max_hot_compositions_per_namespace=3,
            unknown_structural_reserve=0,
            max_hot_metadata_bytes=1536,
            max_generated_target_metadata_bytes=1024,
            max_hot_artifact_bytes_per_namespace=2048,
            max_generated_target_artifact_bytes=1024,
            max_prompt_summary_tokens_per_namespace=128,
            max_generated_target_prompt_summary_tokens=64,
        )
    )
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "held-last-slots",
    )
    held = _carrier_reservation_for_action(fixture.bank, prepared)
    assert held.state == "reserved"

    ordinary_factor = fixture.old.model_copy(
        update={
            "revision_id": "instruction:ordinary-capacity-thief",
            "content_sha256": _h("ordinary-capacity-thief"),
            "parent_revision_id": fixture.old.revision_id,
            "origin_branch": "mutate",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    before_factor = fixture.bank.to_state()
    with pytest.raises(RuntimeError, match="factor record capacity"):
        fixture.bank.add_factor(ordinary_factor)
    assert fixture.bank.to_state() == before_factor

    ordinary_composition = fixture.source.model_copy(
        update={
            "composition_id": "composition:ordinary-capacity-thief",
            "artifact_revision_id": "artifact:ordinary-capacity-thief",
            "artifact_sha256": _h("ordinary-capacity-thief-artifact"),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    before_composition = fixture.bank.to_state()
    with pytest.raises(RuntimeError, match="composition record capacity"):
        fixture.bank.add_composition(ordinary_composition)
    assert fixture.bank.to_state() == before_composition


def test_ordinary_composition_cannot_steal_held_artifact_bytes() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_composition_records=4,
            max_hot_compositions_per_namespace=4,
            unknown_structural_reserve=0,
            max_hot_artifact_bytes_per_namespace=2048,
            max_generated_target_artifact_bytes=1024,
        )
    )
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "mutate",
        "held-artifact-bytes",
    )
    assert _carrier_reservation_for_action(
        fixture.bank,
        prepared,
    ).reserved_artifact_bytes == 1024
    ordinary = fixture.source.model_copy(
        update={
            "composition_id": "composition:artifact-byte-thief",
            "artifact_revision_id": "artifact:artifact-byte-thief",
            "artifact_sha256": _h("artifact-byte-thief"),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    before = fixture.bank.to_state()
    with pytest.raises(RuntimeError, match="artifact-byte capacity"):
        fixture.bank.add_composition(ordinary)
    assert fixture.bank.to_state() == before


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("canonical_metadata_bytes", 1025),
        ("artifact_bytes", 1025),
        ("prompt_summary_tokens", 65),
    ),
)
def test_over_bound_generated_carrier_rejects_atomically_then_releases(
    field,
    value,
) -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_generated_target_metadata_bytes=1024,
            max_generated_target_artifact_bytes=1024,
            max_generated_target_prompt_summary_tokens=64,
        )
    )
    tag = f"over-bound-{field}"
    *_prefix, prepared = _prepare_generated_action(fixture, "fresh", tag)
    executing = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, tag),
    )
    generated, target = _uninstalled_generated_carrier(
        fixture,
        "fresh",
        tag,
    )
    target = target.model_copy(update={field: value})
    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="exceeds its pre-START reservation"):
        _register_action_bundle(
            fixture,
            action=executing,
            branch="fresh",
            tag=tag,
            generated=generated,
            target=target,
            proof_sha256=_h(f"over-bound-proof:{field}"),
        )
    assert fixture.bank.to_state() == before
    assert generated.revision_id not in fixture.bank.factors
    assert target.composition_id not in fixture.bank.compositions

    receipt = make_proposal_action_abort_receipt_v2(
        action=executing,
        reason="generation_invalid_output",
        safe_failure_code=f"over_bound_{field}",
        verifier_epoch="proposal-abort-verifier:over-bound",
        attestation_sha256=_h(f"over-bound-abort:{field}"),
    )
    aborted = fixture.bank.abort_proposal_action(executing.action_id, receipt)
    released = _carrier_reservation_for_action(fixture.bank, aborted)
    assert released.state == "released"
    assert released.released_seq == aborted.updated_seq


@pytest.mark.parametrize(
    ("policy", "message"),
    (
        (
            CapacityPolicyV1(
                max_hot_artifact_bytes_per_namespace=2047,
                max_generated_target_artifact_bytes=1024,
            ),
            "artifact-byte preflight",
        ),
        (
            CapacityPolicyV1(max_generated_owner_slab_bytes=16 * 1024),
            "owner-slab preflight",
        ),
    ),
)
def test_generated_capacity_shortage_rejects_before_action_publication(
    policy,
    message,
) -> None:
    fixture = Fixture(capacity_policy=policy)
    tag = (
        "artifact_capacity"
        if "artifact" in message
        else "owner_slab_capacity"
    )
    opportunity = _repair_opportunity(
        fixture,
        tag,
        feasible_branches=("fresh",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    context = _generation_context(
        fixture,
        opportunity,
        proposal,
        tag=tag,
    )
    before = fixture.bank.to_state()
    with pytest.raises(RuntimeError, match=message):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch="proposal-host:capacity-preflight",
            attestation_sha256=_h(f"capacity-preflight:{message}"),
            generation_context=context,
        )
    assert fixture.bank.to_state() == before
    assert not fixture.bank.to_state().proposal_actions
    assert not fixture.bank.to_state().proposal_carrier_reservations


def test_quarantined_carriers_remain_charged_and_block_third_start() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_hot_compositions_per_namespace=4,
            unknown_structural_reserve=0,
        )
    )
    quarantined_compositions = []
    for ordinal in range(2):
        tag = f"quarantine_capacity_{ordinal}"
        executing, _generated, target, transition, proof = (
            _project_generated_edge(fixture, "fresh", tag)
        )
        receipt = make_proposal_action_abort_receipt_v2(
            action=executing,
            reason="generation_terminal_rejected",
            phase_terminal_sha256=proof,
            safe_failure_code="generated_terminal_rejected",
            verifier_epoch="proposal-abort-verifier:quarantine-capacity",
            attestation_sha256=_h(f"quarantine-capacity:{ordinal}"),
            cleanup_transition=transition,
            cleanup_admission=_admission_for_edge(fixture.bank, transition),
        )
        aborted = fixture.bank.abort_proposal_action(
            executing.action_id,
            receipt,
        )
        reservation = _carrier_reservation_for_action(fixture.bank, aborted)
        assert reservation.state == "consumed"
        assert target.composition_id in fixture.bank.compositions
        quarantined_compositions.append(target.composition_id)

    opportunity = _repair_opportunity(
        fixture,
        "quarantine_capacity_third",
        feasible_branches=("fresh",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    context = _generation_context(
        fixture,
        opportunity,
        proposal,
        tag="quarantine_capacity_third",
    )
    before = fixture.bank.to_state()
    with pytest.raises(RuntimeError, match="hot-composition preflight"):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch="proposal-host:quarantine-capacity-third",
            attestation_sha256=_h("quarantine-capacity-third"),
            generation_context=context,
        )
    assert fixture.bank.to_state() == before
    assert set(quarantined_compositions).issubset(fixture.bank.compositions)


def test_materialized_reservation_keeps_terminal_byte_slack() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(max_proposal_action_bytes=64 * 1024)
    )
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "materialized-terminal-slack",
    )
    action = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "materialized-terminal-slack"),
    )
    generated, target = _uninstalled_generated_carrier(
        fixture,
        "fresh",
        "materialized-terminal-slack",
    )
    proof = _h("materialized-terminal-slack-proof")
    edge = _register_action_bundle(
        fixture,
        action=action,
        branch="fresh",
        tag="materialized-terminal-slack",
        generated=generated,
        target=target,
        proof_sha256=proof,
    )
    admission = _admission_for_edge(fixture.bank, edge)
    reservation = _carrier_reservation_for_action(fixture.bank, action)
    assert reservation.state == "materialized"

    accepted_fillers = 0
    locus = ExactFactorLocusV1(
        carrier="phase_program",
        slot_id="instruction_slot",
        logical_factor_id=fixture.old.logical_factor_id,
        locator_surface="phase_field",
        locator_path=fixture.old.locator.path,
        locator_version=fixture.old.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=fixture.old.revision_id,
        canonical_from_factor_key_sha256=(
            fixture.bank._factor_carrier_key_sha256(fixture.old)
        ),
        canonical_background_sha256=(
            fixture.bank._canonical_direct_background_sha256(
                fixture.bank.to_state(),
                source=fixture.source,
                source_factor=fixture.old,
                slot_id=locus.slot_id,
            )
        ),
    )
    cursor = ProposalCursorV1.empty(cell)
    for ordinal in range(8):
        opportunity = _repair_opportunity(
            fixture,
            f"materialized-terminal-filler-{ordinal}",
            feasible_branches=("reuse",),
        )
        candidate_slate, _universe, _count = (
            fixture.bank._proposal_candidate_slate(
                opportunity=opportunity,
                source_factor=fixture.old,
                slot_id=locus.slot_id,
            )
        )
        proposal = select_exact_edge_proposal(
            _host_proposal_input(
                fixture,
                request=ProposalRequestV1(
                    opportunity_id=opportunity.opportunity_id,
                    cell=cell,
                ),
                cursor=cursor,
                candidates=candidate_slate,
            )
        )
        before = fixture.bank.to_state()
        try:
            fixture.bank.screen_and_allocate_branch(
                opportunity.opportunity_id,
                proposal,
                producer_epoch=f"proposal-host:terminal-filler-{ordinal}",
                attestation_sha256=_h(f"terminal-filler-{ordinal}"),
            )
        except ValueError as exc:
            assert "proposal/action bytes exceed capacity" in str(exc)
            assert fixture.bank.to_state() == before
            break
        accepted_fillers += 1
        cursor = proposal.projected_cursor
    else:
        pytest.fail("terminal byte hold did not stop proposal growth")
    assert accepted_fillers >= 1

    aborted = fixture.bank.abort_proposal_action(
        action.action_id,
        make_proposal_action_abort_receipt_v2(
            action=action,
            reason="generation_terminal_rejected",
            phase_terminal_sha256=proof,
            safe_failure_code="terminal_slack_control",
            verifier_epoch="proposal-abort-verifier:terminal-slack",
            attestation_sha256=_h("terminal-slack-abort"),
            cleanup_transition=edge,
            cleanup_admission=admission,
        ),
    )
    assert aborted.state == "aborted"
    assert _carrier_reservation_for_action(fixture.bank, aborted).state == "consumed"
    assert len(fixture.bank.to_state().proposal_actions) == 2


def test_generated_bundle_verifier_cannot_observe_staged_registry_rows() -> None:
    fixture = Fixture()
    observed = []
    bank_holder = {"bank": None}

    def inspect_registry(transition, *_args):
        bank = bank_holder["bank"]
        if (
            bank is not None
            and not observed
            and transition.binding_proof_id.startswith(
                "proof:generated-recovery:atomic-verifier"
            )
        ):
            snapshot = bank.to_state()
            observed.append(snapshot.digest)
            assert transition.to_revision_id not in {
                item.revision_id for item in snapshot.factors
            }
            assert transition.target_composition_id not in {
                item.composition_id for item in snapshot.compositions
            }
        return True

    capabilities = _trusted_bank_capabilities()
    capabilities["direct_binding_verifier"] = inspect_registry
    fixture.bank = FactorBankV2(
        fixture.bank.to_state(),
        state_key=fixture.key,
        **capabilities,
    )
    bank_holder["bank"] = fixture.bank
    executing, generated, target, transition, _proof = _project_generated_edge(
        fixture,
        "fresh",
        "atomic-verifier",
    )
    assert observed
    assert generated.revision_id in fixture.bank.factors
    assert target.composition_id in fixture.bank.compositions
    assert transition.transition_id in fixture.bank.direct_transitions
    assert _carrier_reservation_for_action(
        fixture.bank,
        executing,
    ).state == "materialized"


def test_non_action_bundle_keeps_full_canonical_import_compatibility() -> None:
    bank = FactorBankV2(
        state_key=b"factor-bank-v7-full-bundle" * 2,
        **_trusted_bank_capabilities(),
    )
    namespace = _namespace(background="full-bundle")
    locator = FactorLocator(
        surface="phase_field",
        path="/phases/0/instruction",
        locator_version="facts-phase-leaf-v2",
    )
    old = FactorRevisionV2(
        revision_id="instruction:full-bundle-old",
        logical_factor_id="instruction",
        namespace=namespace,
        carrier="phase_program",
        locator=locator,
        binding_status="proven_factorized",
        content_sha256=_h("full-bundle-old"),
        created_seq=1,
    )
    new = old.model_copy(
        update={
            "revision_id": "instruction:full-bundle-new",
            "content_sha256": _h("full-bundle-new"),
            "parent_revision_id": old.revision_id,
            "origin_branch": "mutate",
            "created_seq": 2,
        }
    )
    background = FactorRevisionV2(
        revision_id="background:full-bundle",
        logical_factor_id="background",
        namespace=namespace,
        carrier="constraint",
        locator=FactorLocator(
            surface="atomic_artifact",
            path="/background",
            locator_version="facts-phase-leaf-v2",
        ),
        binding_status="locked_atomic",
        content_sha256=_h("full-bundle-background"),
        created_seq=3,
    )
    source = CompositionRevisionV2(
        composition_id="composition:full-bundle-source",
        namespace=namespace,
        carrier="phase_program",
        artifact_revision_id="artifact:full-bundle-source",
        artifact_sha256=_h("full-bundle-source"),
        bindings=(
            SlotBinding(
                slot_id="fixed_background",
                factor_revision_id=background.revision_id,
            ),
            SlotBinding(
                slot_id="instruction_slot",
                factor_revision_id=old.revision_id,
            ),
        ),
        canonical_metadata_bytes=256,
        artifact_bytes=512,
        prompt_summary_tokens=32,
        created_seq=4,
    )
    target = source.model_copy(
        update={
            "composition_id": "composition:full-bundle-target",
            "artifact_revision_id": "artifact:full-bundle-target",
            "artifact_sha256": _h("full-bundle-target"),
            "bindings": (
                source.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=new.revision_id,
                ),
            ),
            "parent_composition_id": source.composition_id,
            "origin_branch": "mutate",
            "created_seq": 5,
        }
    )

    edge = bank.register_direct_bundle(
        factors=(old, new, background),
        compositions=(source, target),
        transition_fields={
            "source_composition_id": source.composition_id,
            "target_composition_id": target.composition_id,
            "slot_id": "instruction_slot",
            "binding_proof_id": "proof:full-bundle",
            "binding_proof_sha256": _h("full-bundle-proof"),
            "masked_background_sha256": _h("full-bundle-masked-background"),
            "binding_verifier_epoch": "binder:full-bundle",
            "origin_branch": "mutate",
        },
    )

    assert bank.to_state().event_seq == 6
    assert edge.transition_id in bank.direct_transitions
    assert not bank.to_state().proposal_carrier_admissions


def test_quarantined_carrier_key_blocks_revision_and_composition_alias_laundering() -> None:
    fixture = Fixture()
    action, generated, target, edge, proof = _project_generated_edge(
        fixture,
        "fresh",
        "alias-quarantine",
    )
    receipt = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:alias-quarantine",
        attestation_sha256=_h("alias-quarantine-abort"),
        cleanup_transition=edge,
        cleanup_admission=_admission_for_edge(fixture.bank, edge),
    )
    fixture.bank.abort_proposal_action(action.action_id, receipt)
    alias = generated.model_copy(
        update={
            "revision_id": "instruction:000-quarantined-alias",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_factor(alias)
    alias_target = target.model_copy(
        update={
            "composition_id": "composition:000-quarantined-alias",
            "artifact_revision_id": "artifact:000-quarantined-alias",
            "artifact_sha256": _h("quarantined-alias-artifact"),
            "bindings": tuple(
                SlotBinding(
                    slot_id=item.slot_id,
                    factor_revision_id=(
                        alias.revision_id
                        if item.slot_id == "instruction_slot"
                        else item.factor_revision_id
                    ),
                )
                for item in target.bindings
            ),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(alias_target)
    opportunity = fixture.bank.to_state().repair_opportunities[-1]
    slate, _universe, _count = fixture.bank._proposal_candidate_slate(
        opportunity=opportunity,
        source_factor=fixture.old,
        slot_id="instruction_slot",
    )
    candidate_ids = {item.target_revision_id for item in slate}
    assert generated.revision_id not in candidate_ids
    assert alias.revision_id not in candidate_ids

    before_direct = fixture.bank.to_state()
    with pytest.raises(ValueError, match="cannot launder"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=alias_target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:quarantined-alias",
            binding_proof_sha256=_h("quarantined-alias-proof"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:quarantined-alias",
            origin_branch="fresh",
        )
    assert fixture.bank.to_state() == before_direct
    with pytest.raises(ValueError, match="cannot launder"):
        fixture.bank.register_whole_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=alias_target.composition_id,
            operation_receipt_sha256=_h("quarantined-alias-whole"),
            operation_verifier_epoch="whole-verifier:quarantined-alias",
            origin_branch="fresh",
        )
    assert fixture.bank.to_state() == before_direct
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "fresh",
        "alias-bundle-retry",
    )
    retry_action = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "alias-bundle-retry"),
    )
    next_seq = fixture.bank.to_state().event_seq + 1
    retry_factor = generated.model_copy(
        update={
            "revision_id": "instruction:quarantined-alias-bundle-retry",
            "created_seq": next_seq,
        }
    )
    retry_target = target.model_copy(
        update={
            "composition_id": "composition:quarantined-alias-bundle-retry",
            "artifact_revision_id": "artifact:quarantined-alias-bundle-retry",
            "artifact_sha256": _h("quarantined-alias-bundle-retry-artifact"),
            "bindings": tuple(
                SlotBinding(
                    slot_id=item.slot_id,
                    factor_revision_id=(
                        retry_factor.revision_id
                        if item.slot_id == "instruction_slot"
                        else item.factor_revision_id
                    ),
                )
                for item in target.bindings
            ),
            "created_seq": next_seq + 1,
        }
    )
    before_bundle_retry = fixture.bank.to_state()
    with pytest.raises(ValueError, match="duplicates an existing carrier key"):
        _register_action_bundle(
            fixture,
            action=retry_action,
            branch="fresh",
            tag="alias-bundle-retry",
            generated=retry_factor,
            target=retry_target,
            proof_sha256=_h("alias-bundle-retry-proof"),
        )
    assert fixture.bank.to_state() == before_bundle_retry


def test_canonical_scientific_edge_rejects_storage_alias_credit_owner() -> None:
    fixture = Fixture()
    factor_alias = fixture.new.model_copy(
        update={
            "revision_id": "instruction:canonical-target-alias",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_factor(factor_alias)
    target_alias = fixture.target.model_copy(
        update={
            "composition_id": "composition:canonical-target-alias",
            "artifact_revision_id": "artifact:canonical-target-alias",
            "bindings": (
                fixture.target.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=factor_alias.revision_id,
                ),
            ),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(target_alias)
    assert fixture.bank._factor_carrier_key_sha256(
        fixture.new
    ) == fixture.bank._factor_carrier_key_sha256(factor_alias)
    assert fixture.bank._composition_carrier_key_sha256(
        fixture.bank.to_state(),
        fixture.target,
    ) == fixture.bank._composition_carrier_key_sha256(
        fixture.bank.to_state(),
        target_alias,
    )

    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="already has a credit owner"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=target_alias.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:canonical-target-alias",
            binding_proof_sha256=_h("proof-one"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:canonical-target-alias",
            origin_branch="mutate",
        )
    assert fixture.bank.to_state() == before


def test_whole_transition_storage_alias_cannot_split_credit_owner() -> None:
    fixture = Fixture()
    whole = fixture.bank.register_whole_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        operation_receipt_sha256=_h("whole-canonical-owner"),
        operation_verifier_epoch="whole-verifier:canonical-owner",
        origin_branch="reuse",
    )
    factor_alias = fixture.new.model_copy(
        update={
            "revision_id": "instruction:whole-canonical-alias",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_factor(factor_alias)
    target_alias = fixture.target.model_copy(
        update={
            "composition_id": "composition:whole-canonical-alias",
            "artifact_revision_id": "artifact:whole-canonical-alias",
            "bindings": (
                fixture.target.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=factor_alias.revision_id,
                ),
            ),
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(target_alias)

    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="already has a credit owner"):
        fixture.bank.register_whole_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=target_alias.composition_id,
            operation_receipt_sha256=_h("whole-canonical-alias"),
            operation_verifier_epoch="whole-verifier:canonical-alias",
            origin_branch="reuse",
        )
    assert fixture.bank.to_state() == before
    assert whole.transition_id in fixture.bank.whole_transitions


def test_harm_between_reuse_prepare_and_projection_blocks_action_alias() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "harm-before-reuse-projection",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:harm-before-reuse-projection",
        attestation_sha256=_h("harm-before-reuse-projection-action"),
    )
    assert action is not None and action.state == "prepared"
    fixture.complete("target_algorithm_failure")

    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="has verified harm"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=fixture.target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:harm-before-reuse-projection",
            binding_proof_sha256=_h("harm-before-reuse-projection-proof"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:harm-before-reuse-projection",
            origin_branch="reuse",
            proposal_action_id=action.action_id,
            proposal_action_intent_sha256=action.action_intent_sha256,
        )
    assert fixture.bank.to_state() == before
    aborted = fixture.bank.abort_proposal_action(
        action.action_id,
        make_proposal_action_abort_receipt_v2(
            action=action,
            reason="phase_rejected",
            safe_failure_code="canonical_edge_became_harmful",
            verifier_epoch="proposal-abort-verifier:harm-before-projection",
            attestation_sha256=_h("harm-before-projection-abort"),
        ),
    )
    assert aborted.state == "aborted"


def test_capacity_archive_closes_entire_canonical_action_alias_group() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(unknown_structural_reserve=0)
    )
    opportunity = _repair_opportunity(
        fixture,
        "canonical-group-archive",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:canonical-group-archive",
        attestation_sha256=_h("canonical-group-archive-action"),
    )
    assert action is not None
    proof = _h("canonical-group-archive-proof")
    alias = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:canonical-group-archive",
        binding_proof_sha256=proof,
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:canonical-group-archive",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    fixture.bank.finalize_proposal_action(
        action.action_id,
        transition_id=alias.transition_id,
        phase_terminal_sha256=proof,
    )
    assert fixture.bank._canonical_scientific_edge_sha256(
        fixture.bank.to_state(),
        fixture.transition,
    ) == fixture.bank._canonical_scientific_edge_sha256(
        fixture.bank.to_state(),
        fixture.bank.direct_transitions[alias.transition_id],
    )
    fixture.complete("target_algorithm_failure")

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("canonical-group-archive-attestation"),
        max_victims=1,
    )

    assert checkpoint is not None
    assert set(checkpoint.subject_ids) == {
        fixture.transition.transition_id,
        alias.transition_id,
    }
    archived = {
        item.transition_id: item.structural_state
        for item in fixture.bank.to_state().direct_transitions
        if item.transition_id in checkpoint.subject_ids
    }
    assert archived[fixture.transition.transition_id] == "tombstone"
    assert archived[alias.transition_id] == "cold"
    assert set(archived) <= fixture.bank._harmful_transition_ids()


def test_portable_pair_harm_does_not_veto_a_different_exact_background() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure")
    other_background = fixture._factor(
        "background:independent-context",
        "independent-background",
        carrier="constraint",
        surface="atomic_artifact",
        path="/background",
        status="locked_atomic",
    )
    source = CompositionRevisionV2(
        composition_id="composition:independent-context-source",
        namespace=fixture.namespace,
        carrier="phase_program",
        artifact_revision_id="artifact:independent-context-source",
        artifact_sha256=_h("independent-context-source"),
        bindings=(
            SlotBinding(
                slot_id="fixed_background",
                factor_revision_id=other_background.revision_id,
            ),
            SlotBinding(
                slot_id="instruction_slot",
                factor_revision_id=fixture.old.revision_id,
            ),
        ),
        origin_branch="migration",
        canonical_metadata_bytes=256,
        artifact_bytes=512,
        prompt_summary_tokens=32,
        created_seq=fixture.bank.to_state().event_seq + 1,
    )
    fixture.bank.add_composition(source)
    target = source.model_copy(
        update={
            "composition_id": "composition:independent-context-target",
            "artifact_revision_id": "artifact:independent-context-target",
            "artifact_sha256": _h("independent-context-target"),
            "bindings": (
                source.bindings[0],
                SlotBinding(
                    slot_id="instruction_slot",
                    factor_revision_id=fixture.new.revision_id,
                ),
            ),
            "parent_composition_id": source.composition_id,
            "origin_branch": "reuse",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(target)

    edge = fixture.bank.register_direct_transition(
        source_composition_id=source.composition_id,
        target_composition_id=target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:independent-context",
        binding_proof_sha256=_h("proof-independent-context"),
        masked_background_sha256=_h("masked-independent-context"),
        binding_verifier_epoch="binder:independent-context",
        origin_branch="reuse",
    )

    assert fixture.bank._portable_pair_sha256(
        fixture.transition
    ) == fixture.bank._portable_pair_sha256(edge)
    assert fixture.bank._canonical_scientific_edge_sha256(
        fixture.bank.to_state(),
        fixture.transition,
    ) != fixture.bank._canonical_scientific_edge_sha256(
        fixture.bank.to_state(),
        edge,
    )


def test_quarantined_composition_key_blocks_alias_when_factor_is_shared() -> None:
    fixture = Fixture()
    *_prefix, prepared = _prepare_generated_action(
        fixture,
        "mutate",
        "shared-factor-new-composition",
    )
    action = fixture.bank.begin_proposal_generation(
        prepared.action_id,
        _generation_lease(prepared, "shared-factor-new-composition"),
    )
    next_seq = fixture.bank.to_state().event_seq + 1
    generated_target = fixture.target.model_copy(
        update={
            "composition_id": "composition:shared-factor-generated",
            "artifact_revision_id": "artifact:shared-factor-generated",
            "artifact_sha256": _h("shared-factor-generated-artifact"),
            "parent_composition_id": fixture.source.composition_id,
            "origin_branch": "mutate",
            "created_seq": next_seq,
        }
    )
    proof = _h("shared-factor-generated-proof")
    edge = fixture.bank.register_direct_bundle(
        factors=(),
        compositions=(generated_target,),
        transition_fields={
            "source_composition_id": fixture.source.composition_id,
            "target_composition_id": generated_target.composition_id,
            "slot_id": "instruction_slot",
            "binding_proof_id": "proof:shared-factor-generated",
            "binding_proof_sha256": proof,
            "masked_background_sha256": _h("masked-background"),
            "binding_verifier_epoch": "binder:shared-factor-generated",
            "origin_branch": "mutate",
            "proposal_action_id": action.action_id,
            "proposal_action_intent_sha256": action.action_intent_sha256,
        },
    )
    admission = _admission_for_edge(fixture.bank, edge)
    assert admission.factor_independently_eligible_before
    assert not admission.composition_independently_eligible_before
    receipt = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:shared-factor",
        attestation_sha256=_h("shared-factor-abort"),
        cleanup_transition=edge,
        cleanup_admission=admission,
    )
    fixture.bank.abort_proposal_action(action.action_id, receipt)
    alias = generated_target.model_copy(
        update={
            "composition_id": "composition:000-shared-factor-alias",
            "artifact_revision_id": "artifact:000-shared-factor-alias",
            "created_seq": fixture.bank.to_state().event_seq + 1,
        }
    )
    fixture.bank.add_composition(alias)
    assert fixture.bank._row_is_carrier_eligible(
        fixture.bank.to_state(),
        row_kind="factor",
        row_id=fixture.new.revision_id,
    )
    assert not fixture.bank._row_is_carrier_eligible(
        fixture.bank.to_state(),
        row_kind="composition",
        row_id=alias.composition_id,
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="cannot launder"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=alias.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:shared-factor-alias",
            binding_proof_sha256=_h("shared-factor-alias-proof"),
            masked_background_sha256=_h("masked-background"),
            binding_verifier_epoch="binder:shared-factor-alias",
            origin_branch="mutate",
        )
    assert fixture.bank.to_state() == before
    with pytest.raises(ValueError, match="cannot launder"):
        fixture.bank.register_whole_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=alias.composition_id,
            operation_receipt_sha256=_h("shared-factor-alias-whole"),
            operation_verifier_epoch="whole-verifier:shared-factor-alias",
            origin_branch="mutate",
        )
    assert fixture.bank.to_state() == before


@pytest.mark.parametrize(
    "updates",
    (
        {"projected_transition_sha256": _h("forged-projected-edge")},
        {"target_factor_sha256": _h("forged-factor")},
        {"target_factor_carrier_key_sha256": _h("forged-carrier-key")},
        {"target_composition_sha256": _h("forged-composition")},
        {
            "target_composition_carrier_key_sha256": _h(
                "forged-composition-carrier-key"
            )
        },
        {"factor_independently_eligible_before": False},
        {"composition_independently_eligible_before": False},
        {"independent_authority_cutoff_seq": 0},
        {"namespace_digest": _h("forged-namespace")},
    ),
)
def test_replay_rejects_every_tampered_staged_admission_join(updates) -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "admission-tamper",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:admission-tamper",
        attestation_sha256=_h("admission-tamper-action"),
    )
    assert action is not None
    edge = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:admission-tamper",
        binding_proof_sha256=_h("admission-tamper-proof"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:admission-tamper",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    original = _admission_for_edge(fixture.bank, edge)
    forged = _rewrite_admission(original, **updates)
    state = fixture.bank.to_state().model_copy(
        update={
            "proposal_carrier_admissions": tuple(
                forged if item.admission_id == original.admission_id else item
                for item in fixture.bank.to_state().proposal_carrier_admissions
            )
        }
    )

    with pytest.raises(ValueError, match="carrier admission"):
        FactorBankV2(
            state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_authenticated_reload_rejects_tampered_admission_even_with_recomputed_hmac(
    tmp_path,
) -> None:
    fixture = Fixture()
    action, _factor, _target, edge, _proof = _project_generated_edge(
        fixture,
        "fresh",
        "admission-envelope-tamper",
    )
    assert action.state == "executing"
    path = tmp_path / "admission-envelope-tamper.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["proposal_carrier_admissions"][0][
        "projected_transition_sha256"
    ] = _h("envelope-forged-projection")
    admission_payload = payload["state"]["proposal_carrier_admissions"][0]
    identity = dict(admission_payload)
    for field in ("admission_id", "state", "terminal_seq", "terminal_sha256"):
        identity.pop(field)
    admission_payload["admission_id"] = f"pca:{_canonical_hash(identity)[:24]}"
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="admission edge closure"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


@pytest.mark.parametrize(
    ("collection", "message"),
    (
        ("factors", "factor revision is future-dated"),
        ("compositions", "composition revision is future-dated"),
        ("direct_transitions", "direct transition is future-dated"),
        ("whole_transitions", "whole transition is future-dated"),
    ),
)
def test_authenticated_reload_rejects_future_dated_structural_rows(
    tmp_path,
    collection,
    message,
) -> None:
    fixture = Fixture()
    if collection == "whole_transitions":
        fixture.bank.register_whole_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=fixture.target.composition_id,
            operation_receipt_sha256=_h("future-dated-whole-receipt"),
            operation_verifier_epoch="whole-verifier:future-dated",
            origin_branch="reuse",
        )
    path = tmp_path / f"future-dated-{collection}.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"][collection][0]["created_seq"] = (
        payload["state"]["event_seq"] + 1
    )
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("base_not_after_composition", "base receipt predates"),
        ("snapshot_future", "deployment snapshot has invalid causal time"),
        ("head_future", "deployment head is future-dated"),
    ),
)
def test_authenticated_reload_rejects_noncausal_deployment_authority(
    tmp_path,
    case,
    message,
) -> None:
    fixture = Fixture()
    path = tmp_path / f"noncausal-deployment-{case}.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if case == "base_not_after_composition":
        source_seq = next(
            item["created_seq"]
            for item in payload["state"]["compositions"]
            if item["composition_id"] == fixture.source.composition_id
        )
        payload["state"]["base_receipts"][0]["emitted_seq"] = source_seq
    elif case == "snapshot_future":
        snapshot = payload["state"]["deployment_snapshots"][0]
        snapshot["created_seq"] = payload["state"]["event_seq"] + 100
        payload["state"]["deployment_heads"][0][
            "active_snapshot_sha256"
        ] = _canonical_hash(snapshot)
    else:
        payload["state"]["deployment_heads"][0]["updated_seq"] = (
            payload["state"]["event_seq"] + 100
        )
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_replay_rejects_noncausal_factor_and_composition_order() -> None:
    fixture = Fixture()
    state = fixture.bank.to_state()
    child = fixture.new.model_copy(
        update={"created_seq": fixture.old.created_seq}
    )
    forged_factor_state = state.model_copy(
        update={
            "factors": tuple(
                child if item.revision_id == child.revision_id else item
                for item in state.factors
            )
        }
    )
    with pytest.raises(ValueError, match="factor parent does not causally precede"):
        FactorBankV2(
            forged_factor_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )

    target = fixture.target.model_copy(
        update={"created_seq": fixture.new.created_seq}
    )
    forged_composition_state = state.model_copy(
        update={
            "compositions": tuple(
                target if item.composition_id == target.composition_id else item
                for item in state.compositions
            )
        }
    )
    with pytest.raises(
        ValueError,
        match="composition binding does not causally precede",
    ):
        FactorBankV2(
            forged_composition_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_replay_rejects_noncausal_direct_and_whole_edge_inputs() -> None:
    fixture = Fixture()
    state = fixture.bank.to_state()
    late_target = fixture.target.model_copy(
        update={"created_seq": fixture.transition.created_seq}
    )
    forged_direct_state = state.model_copy(
        update={
            "compositions": tuple(
                late_target
                if item.composition_id == late_target.composition_id
                else item
                for item in state.compositions
            )
        }
    )
    with pytest.raises(
        ValueError,
        match="direct transition inputs do not causally precede",
    ):
        FactorBankV2(
            forged_direct_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )

    whole_factor = fixture._factor(
        "instruction:whole-causal-order",
        "whole-causal-order-content",
    )
    whole_target = fixture._composition(
        "composition:whole-causal-order",
        whole_factor.revision_id,
        "whole-causal-order-artifact",
    )
    whole = fixture.bank.register_whole_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=whole_target.composition_id,
        operation_receipt_sha256=_h("whole-causal-order-receipt"),
        operation_verifier_epoch="whole-verifier:causal-order",
        origin_branch="fresh",
    )
    state = fixture.bank.to_state()
    late_whole_target = whole_target.model_copy(
        update={"created_seq": whole.created_seq}
    )
    forged_whole_state = state.model_copy(
        update={
            "compositions": tuple(
                late_whole_target
                if item.composition_id == late_whole_target.composition_id
                else item
                for item in state.compositions
            )
        }
    )
    with pytest.raises(
        ValueError,
        match="whole transition inputs do not causally precede",
    ):
        FactorBankV2(
            forged_whole_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_replay_rejects_cleanup_receipt_with_missing_quarantined_admission() -> None:
    fixture = Fixture()
    action, _factor, _target, edge, proof = _project_generated_edge(
        fixture,
        "fresh",
        "missing-quarantined-admission",
    )
    receipt = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=proof,
        safe_failure_code="generated_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:missing-admission",
        attestation_sha256=_h("missing-admission-abort"),
        cleanup_transition=edge,
        cleanup_admission=_admission_for_edge(fixture.bank, edge),
    )
    fixture.bank.abort_proposal_action(action.action_id, receipt)
    forged = fixture.bank.to_state().model_copy(
        update={"proposal_carrier_admissions": ()}
    )

    with pytest.raises(ValueError, match="lacks its quarantined admission"):
        FactorBankV2(
            forged,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_load_rejects_action_edge_branch_mismatch() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "load-branch-mismatch",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:load-branch-mismatch",
        attestation_sha256=_h("load-branch-mismatch-action"),
    )
    assert action is not None
    edge = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:load:branch-mismatch",
        binding_proof_sha256=_h("load-branch-mismatch-proof"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:proposal",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    forged_edge = edge.model_copy(update={"origin_branch": "mutate"})
    forged_state = fixture.bank.to_state().model_copy(
        update={"direct_transitions": (
            *tuple(
                item for item in fixture.bank.to_state().direct_transitions
                if item.transition_id != edge.transition_id
            ),
            forged_edge,
        )}
    )

    with pytest.raises(ValueError, match="admission edge closure|branch/intent join"):
        FactorBankV2(
            forged_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_load_rejects_duplicate_generated_terminal_commitment() -> None:
    fixture = Fixture()
    first = _prepare_generated_action(fixture, "fresh", "terminal-owner-one")[-1]
    second = _prepare_generated_action(fixture, "fresh", "terminal-owner-two")[-1]
    first = fixture.bank.begin_proposal_generation(
        first.action_id,
        _generation_lease(first, "terminal-owner-one"),
    )
    second = fixture.bank.begin_proposal_generation(
        second.action_id,
        _generation_lease(second, "terminal-owner-two"),
    )

    committed = []
    for index, action in enumerate((first, second), start=1):
        tag = f"terminal-owner-{index}"
        factor, composition = _uninstalled_generated_carrier(
            fixture,
            "fresh",
            tag,
        )
        proof = _h(f"terminal-owner-proof:{index}")
        edge = _register_action_bundle(
            fixture,
            action=action,
            branch="fresh",
            tag=tag,
            generated=factor,
            target=composition,
            proof_sha256=proof,
        )
        committed.append(
            fixture.bank.finalize_proposal_action(
                action.action_id,
                transition_id=edge.transition_id,
                phase_terminal_sha256=proof,
                generation_terminal_sha256=_h(
                    f"terminal-owner-generation-terminal:{index}"
                ),
                resolved_to_revision_id=factor.revision_id,
                resolved_target_content_sha256=factor.content_sha256,
            )
        )

    forged_second = committed[1].model_copy(
        update={
            "generation_terminal_sha256": committed[0].generation_terminal_sha256
        }
    )
    forged_state = fixture.bank.to_state().model_copy(
        update={"proposal_actions": (committed[0], forged_second)}
    )
    with pytest.raises(ValueError, match="duplicate proposal generation terminal"):
        FactorBankV2(
            forged_state,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_caller_cannot_omit_a_bank_eligible_proposal_candidate() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "omitted-candidate",
        feasible_branches=("reuse", "fresh"),
    )
    omitted = _proposal_receipt(
        fixture,
        opportunity,
        include_target=False,
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="exact host-derived candidate slate"):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            omitted,
            producer_epoch="proposal-host:omitted",
            attestation_sha256=_h("proposal-omitted-attestation"),
        )

    assert fixture.bank.to_state() == before


def test_bank_rejects_selector_receipt_with_caller_asserted_portable_sign() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "forged-sign",
        feasible_branches=("reuse",),
    )
    forged_sign = PortableBackgroundSignV1(
        fixed_background_sha256=_h("unobserved-background"),
        sign="benefit",
        evidence_root_sha256=_h("unobserved-evidence"),
    )
    proposal = _proposal_receipt(
        fixture,
        opportunity,
        background_signs=(forged_sign,),
    )
    before = fixture.bank.to_state()

    with pytest.raises(ValueError, match="exact host-derived candidate slate"):
        fixture.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch="proposal-host:forged",
            attestation_sha256=_h("proposal-forged-attestation"),
        )

    assert fixture.bank.to_state() == before


def test_proposal_action_abort_is_authenticated_fenced_and_load_replayed() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "abort",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:abort",
        attestation_sha256=_h("proposal-abort-prepare"),
    )
    assert action is not None
    abort = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="phase_noop",
        phase_terminal_sha256=_h("phase-noop-terminal"),
        safe_failure_code="same_execution_image",
        verifier_epoch="proposal-abort-verifier:one",
        attestation_sha256=_h("proposal-abort-attestation"),
    )

    aborted = fixture.bank.abort_proposal_action(action.action_id, abort)
    assert aborted.state == "aborted"
    assert aborted.fencing_generation == 2
    state = fixture.bank.to_state()
    assert fixture.bank.abort_proposal_action(action.action_id, abort) == aborted
    assert fixture.bank.to_state() == state

    capabilities = {
        "direct_binding_verifier": lambda *_args: True,
        "whole_operation_verifier": lambda *_args: True,
        "plan_verifier": lambda *_args: True,
        "assignment_verifier": lambda *_args: True,
        "runner_lease_verifier": lambda *_args: True,
        "arm_receipt_verifier": lambda *_args: True,
        "pair_execution_receipt_verifier": lambda *_args: True,
        "cancellation_verifier": lambda *_args: True,
        "gate_verifier": lambda *_args: True,
        "base_snapshot_verifier": lambda *_args: True,
        "rollback_verifier": lambda *_args: True,
        "archive_verifier": lambda *_args: True,
        "repair_opportunity_verifier": lambda *_args: True,
    }
    with pytest.raises(RuntimeError, match="proposal abort requires"):
        FactorBankV2(state, state_key=fixture.key, **capabilities)
    loaded = FactorBankV2(
        state,
        state_key=fixture.key,
        proposal_abort_verifier=lambda *_args: True,
        **capabilities,
    )
    assert loaded.scientific_state_sha256 == fixture.bank.scientific_state_sha256


def test_pre_cleanup_v5_abort_receipt_identity_remains_projection_compatible() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "legacy-abort-identity",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:legacy-abort-identity",
        attestation_sha256=_h("legacy-abort-identity-action"),
    )
    assert action is not None
    receipt = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="phase_noop",
        phase_terminal_sha256=_h("legacy-abort-identity-terminal"),
        safe_failure_code="legacy_abort_identity",
        verifier_epoch="proposal-abort-verifier:legacy-identity",
        attestation_sha256=_h("legacy-abort-identity-attestation"),
    )
    old_body = receipt.model_dump(
        mode="python",
        exclude={
            "abort_id",
            "emitted_seq",
            "cleanup_transition_id",
            "cleanup_transition_sha256",
            "cleanup_action_intent_sha256",
            "cleanup_admission_id",
            "cleanup_admission_sha256",
        },
    )
    old_abort_id = f"pab:{_canonical_hash(old_body)[:24]}"
    assert receipt.abort_id == old_abort_id

    legacy_payload = {"abort_id": old_abort_id, **old_body}
    validated = ProposalActionAbortReceiptV2.model_validate(legacy_payload)
    assert validated.cleanup_transition_id is None
    assert validated.cleanup_transition_sha256 is None
    assert validated.cleanup_action_intent_sha256 is None
    assert fixture.bank.abort_proposal_action(action.action_id, validated).state == "aborted"


def test_branch_balancing_does_not_cross_execution_namespace() -> None:
    fixture = Fixture()
    first_opportunity = _record_algorithm_failure(fixture, "primary")
    assert first_opportunity is not None
    fixture.bank.allocate_branch(first_opportunity.opportunity_id)

    other_namespace = _namespace(background="large")
    other_background = FactorRevisionV2(
        revision_id="other:background",
        logical_factor_id="background",
        namespace=other_namespace,
        carrier="constraint",
        locator=FactorLocator(
            surface="atomic_artifact",
            path="/background",
            locator_version="facts-phase-leaf-v2",
        ),
        binding_status="locked_atomic",
        content_sha256=_h("other-background"),
        created_seq=fixture.bank.to_state().event_seq + 1,
    )
    fixture.bank.add_factor(other_background)
    other_instruction = FactorRevisionV2(
        revision_id="other:instruction",
        logical_factor_id="instruction",
        namespace=other_namespace,
        carrier="phase_program",
        locator=FactorLocator(
            surface="phase_field",
            path="/phases/0/instruction",
            locator_version="facts-phase-leaf-v2",
        ),
        binding_status="proven_factorized",
        content_sha256=_h("other-instruction"),
        created_seq=fixture.bank.to_state().event_seq + 1,
    )
    fixture.bank.add_factor(other_instruction)
    other_composition = CompositionRevisionV2(
        composition_id="other:composition",
        namespace=other_namespace,
        carrier="phase_program",
        artifact_revision_id="artifact:other",
        artifact_sha256=_h("other-artifact"),
        bindings=(
            SlotBinding(
                slot_id="fixed_background",
                factor_revision_id=other_background.revision_id,
            ),
            SlotBinding(
                slot_id="instruction_slot",
                factor_revision_id=other_instruction.revision_id,
            ),
        ),
        canonical_metadata_bytes=256,
        artifact_bytes=512,
        prompt_summary_tokens=32,
        created_seq=fixture.bank.to_state().event_seq + 1,
    )
    fixture.bank.add_composition(other_composition)
    fixture.bank.register_base_snapshot(
        BaseSnapshotReceiptV2(
            receipt_id="base:other-namespace",
            deployment_slot_id=fixture.bank.deployment_slot_id(other_namespace),
            namespace_digest=other_namespace.digest,
            composition_id=other_composition.composition_id,
            loaded_artifact_sha256=other_composition.artifact_sha256,
            binding_map_sha256=_canonical_hash(
                sorted(other_composition.binding_map.items())
            ),
            runtime_version=other_namespace.runtime_version,
            verifier_epoch="base-verifier:other-namespace",
            attestation_sha256=_h("base-attestation:other-namespace"),
            emitted_seq=fixture.bank.to_state().event_seq + 1,
        )
    )
    opportunity = _record_algorithm_failure(
        fixture,
        "other",
        composition=other_composition,
        transition_id=None,
    )
    assert opportunity is not None

    assignment = fixture.bank.allocate_branch(opportunity.opportunity_id)
    assert assignment.namespace_digest == other_namespace.digest
    assert assignment.assigned_counts_before == (
        ("reuse", 0),
        ("mutate", 0),
        ("fresh", 0),
    )


def test_branch_assignment_load_validation_rejects_forged_selector_state() -> None:
    fixture = Fixture()
    opportunity = _record_algorithm_failure(fixture, "load")
    assert opportunity is not None
    assignment = fixture.bank.allocate_branch(opportunity.opportunity_id)
    forged = assignment.model_copy(
        update={"public_tiebreak_sha256": _h("forged-branch-choice")}
    )
    state = fixture.bank.to_state().model_copy(
        update={"branch_assignments": (forged,)}
    )

    with pytest.raises(ValueError, match="reproducible one-shot decision"):
        FactorBankV2(
            state,
            state_key=fixture.key,
            direct_binding_verifier=lambda *_args: True,
            whole_operation_verifier=lambda *_args: True,
            plan_verifier=lambda _plan: True,
            assignment_verifier=lambda *_args: True,
            runner_lease_verifier=lambda *_args: True,
            arm_receipt_verifier=lambda *_args: True,
            pair_execution_receipt_verifier=lambda *_args: True,
            cancellation_verifier=lambda *_args: True,
            gate_verifier=lambda *_args: True,
            base_snapshot_verifier=lambda *_args: True,
                rollback_verifier=lambda *_args: True,
                archive_verifier=lambda *_args: True,
                repair_opportunity_verifier=lambda *_args: True,
            )


def test_wrong_assignment_body_fails_before_opening_attempt() -> None:
    fixture = Fixture()
    assignment = make_assignment_receipt_v2(
        plan=fixture.plan,
        ordinal=0,
        origin_pool_sha256=_h("origin-pool"),
        producer_epoch="assignment-producer:one",
        attestation_sha256=_h("assignment"),
    ).model_copy(update={"unit_commitment": _h("different")})
    before = fixture.bank.scientific_state_sha256
    with pytest.raises(ValueError, match="frozen plan"):
        fixture.bank.open_next_attempt(
            fixture.plan.plan_id,
            assignment,
            _runner_lease(fixture.plan, assignment, "wrong-assignment"),
        )
    assert fixture.bank.scientific_state_sha256 == before


def test_forged_observed_arm_order_is_quarantined_without_scientific_vote() -> None:
    fixture = Fixture()

    attempt = fixture.complete(
        "benefit",
        source_updates={"observed_arm_order": "BA"},
    )

    assert attempt.state == "quarantine"
    assert attempt.disposition_reason == "inconsistent_observed_arm_order"
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.label == "quarantine"
    assert assessment.n_complete == 0


def test_physical_runner_order_cannot_be_replaced_by_assignment_echo() -> None:
    fixture = Fixture()

    attempt = fixture.complete(
        "benefit",
        physical_arm_order="BA",  # ordinal zero was scheduled AB
    )

    assert attempt.assignment.arm_order == "AB"
    assert attempt.pair_execution_receipt is not None
    assert attempt.pair_execution_receipt.observed_arm_order == "BA"
    assert attempt.state == "quarantine"
    assert attempt.disposition_reason == "physical_arm_order_violation"
    assert fixture.bank.assessments[fixture.plan.plan_id].n_complete == 0


def test_unverified_terminal_pair_receipt_cannot_contribute_scientific_vote() -> None:
    fixture = Fixture(
        pair_execution_receipt_verifier=lambda *_args: False
    )

    attempt = fixture.complete("benefit")

    assert attempt.state == "quarantine"
    assert attempt.disposition_reason == "unverified_pair_execution_receipt"
    assert fixture.bank.assessments[fixture.plan.plan_id].n_complete == 0


def test_overlapping_runner_arm_spans_are_rejected_before_bank_commit() -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)

    with pytest.raises(ValueError, match="overlap"):
        make_pair_execution_receipt_v2(
            attempt=attempt,
            source_root_id=_h("overlap-source"),
            target_root_id=_h("overlap-target"),
            source_started_seq=1,
            source_finished_seq=4,
            target_started_seq=2,
            target_finished_seq=3,
            verifier_epoch="pair-runner:one",
            attestation_sha256=_h("overlap-attestation"),
        )


def test_derived_pair_binding_is_not_a_lifetime_runner_root() -> None:
    fixture = Fixture()
    first = fixture.complete("benefit", tag="pair-root-first")
    assert first.source_receipt is not None
    old_pair_root = first.source_receipt.paired_execution_root_sha256

    second = fixture.complete(
        "benefit",
        tag="pair-root-second",
        source_updates={"paired_execution_root_sha256": old_pair_root},
        target_updates={"paired_execution_root_sha256": old_pair_root},
    )

    assert second.state == "quarantine"
    assert second.disposition_reason == "paired_execution_root_mismatch"
    used_roots = dict(fixture.bank.to_state().used_roots)
    assert old_pair_root not in used_roots
    assert first.pair_execution_receipt is not None
    assert used_roots[
        first.pair_execution_receipt.runner_event_root_sha256
    ] == first.attempt_id
    assert fixture.bank.assessments[fixture.plan.plan_id].n_complete == 1


def test_attrition_with_three_to_one_completed_order_cannot_candidate() -> None:
    fixture = Fixture()
    for kind in (
        "benefit",       # AB complete
        "infrastructure",  # BA missing
        "benefit",       # AB complete
        "infrastructure",  # BA missing
        "benefit",       # AB complete
    ):
        fixture.complete(kind)
    before_last = fixture.bank.assessments[fixture.plan.plan_id]
    assert not before_last.settled
    assert (before_last.n_complete_ab, before_last.n_complete_ba) == (3, 0)

    fixture.complete("benefit")  # BA complete, but the final set is still 3:1.
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert not assessment.counterbalanced
    assert (assessment.n_complete_ab, assessment.n_complete_ba) == (3, 1)
    assert assessment.label == "infrastructure_exhausted"
    assert fixture.bank.to_state().gate_opportunities == ()


def test_reserves_may_restore_exact_two_to_two_counterbalance() -> None:
    fixture = Fixture()
    for kind in (
        "benefit",       # AB complete
        "infrastructure",  # BA missing
        "benefit",       # AB complete
        "benefit",       # BA complete
        "infrastructure",  # AB missing
    ):
        fixture.complete(kind)
    before_last = fixture.bank.assessments[fixture.plan.plan_id]
    assert not before_last.settled
    assert (before_last.n_complete_ab, before_last.n_complete_ba) == (2, 1)

    fixture.complete("benefit")  # reserve BA restores 2:2.
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled
    assert assessment.counterbalanced
    assert (assessment.n_complete_ab, assessment.n_complete_ba) == (2, 2)
    assert assessment.label == "candidate"
    assert len(
        [item for item in fixture.bank.to_state().gate_opportunities if item.state == "pending"]
    ) == 1


def test_persistence_is_authenticated_and_compare_and_swap(tmp_path) -> None:
    fixture = Fixture()
    fixture.complete("benefit")
    path = tmp_path / "sft-bank.json"
    fixture.bank.save(path)
    loaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        direct_binding_verifier=lambda *_args: True,
        whole_operation_verifier=lambda *_args: True,
        plan_verifier=lambda _plan: True,
        assignment_verifier=lambda _receipt, _plan: True,
        runner_lease_verifier=lambda *_args: True,
        arm_receipt_verifier=lambda _receipt, _plan, _assignment: True,
        pair_execution_receipt_verifier=lambda *_args: True,
        cancellation_verifier=lambda _receipt, _attempt, _plan: True,
        gate_verifier=lambda _receipt, _state: True,
        base_snapshot_verifier=lambda _receipt, _state: True,
        rollback_verifier=lambda _trigger, _state: True,
        archive_verifier=lambda _digest, _attestation: True,
    )
    assert loaded.scientific_state_sha256 == fixture.bank.scientific_state_sha256
    with pytest.raises(RuntimeError, match="pair receipt requires"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            direct_binding_verifier=lambda *_args: True,
            whole_operation_verifier=lambda *_args: True,
            plan_verifier=lambda _plan: True,
            assignment_verifier=lambda *_args: True,
            runner_lease_verifier=lambda *_args: True,
            arm_receipt_verifier=lambda *_args: True,
            cancellation_verifier=lambda *_args: True,
            gate_verifier=lambda *_args: True,
            base_snapshot_verifier=lambda *_args: True,
            rollback_verifier=lambda *_args: True,
            archive_verifier=lambda *_args: True,
        )
    with pytest.raises(ValueError, match="HMAC"):
        FactorBankV2.load(
            path,
            state_key=b"wrong-state-key" * 3,
            direct_binding_verifier=lambda *_args: True,
            plan_verifier=lambda _plan: True,
            assignment_verifier=lambda _receipt, _plan: True,
            runner_lease_verifier=lambda *_args: True,
            arm_receipt_verifier=lambda *_args: True,
            pair_execution_receipt_verifier=lambda *_args: True,
            cancellation_verifier=lambda *_args: True,
            base_snapshot_verifier=lambda *_args: True,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["assessments"][0]["label"] = "harmful"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest|HMAC"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            direct_binding_verifier=lambda *_args: True,
            plan_verifier=lambda _plan: True,
            assignment_verifier=lambda _receipt, _plan: True,
            runner_lease_verifier=lambda *_args: True,
            arm_receipt_verifier=lambda *_args: True,
            pair_execution_receipt_verifier=lambda *_args: True,
            cancellation_verifier=lambda *_args: True,
            base_snapshot_verifier=lambda *_args: True,
        )


def test_persisted_cancellation_requires_and_replays_trusted_capability(tmp_path) -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)
    fixture.bank.cancel_open_attempt(
        attempt.attempt_id,
        _cancellation(fixture, attempt),
    )
    path = tmp_path / "cancelled-bank.json"
    fixture.bank.save(path)
    capabilities = {
        "direct_binding_verifier": lambda *_args: True,
        "whole_operation_verifier": lambda *_args: True,
        "plan_verifier": lambda _plan: True,
        "assignment_verifier": lambda _receipt, _plan: True,
        "runner_lease_verifier": lambda *_args: True,
        "arm_receipt_verifier": lambda _receipt, _plan, _assignment: True,
        "pair_execution_receipt_verifier": lambda *_args: True,
        "gate_verifier": lambda _receipt, _state: True,
        "base_snapshot_verifier": lambda _receipt, _state: True,
        "rollback_verifier": lambda _trigger, _state: True,
        "archive_verifier": lambda _digest, _attestation: True,
        "repair_opportunity_verifier": lambda *_args: True,
    }

    with pytest.raises(RuntimeError, match="cancellation requires"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **capabilities,
        )

    observed = []

    def verify(receipt, open_attempt, plan):
        observed.append((receipt, open_attempt, plan))
        return open_attempt.state == "open" and (
            receipt.expected_open_attempt_sha256 == _canonical_hash(open_attempt)
        )

    loaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        cancellation_verifier=verify,
        **capabilities,
    )
    assert loaded.scientific_state_sha256 == fixture.bank.scientific_state_sha256
    assert observed
    assert all(item[1].cancellation_receipt is None for item in observed)

    with pytest.raises(ValueError, match="cancellation receipt was rejected"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            cancellation_verifier=lambda *_args: False,
            **capabilities,
        )


def test_loaded_bank_mutation_returns_only_after_file_cas(tmp_path) -> None:
    fixture = Fixture()
    path = tmp_path / "sft-bank-authoritative.json"
    fixture.bank.save(path)
    capabilities = {
        "direct_binding_verifier": lambda *_args: True,
        "whole_operation_verifier": lambda *_args: True,
        "plan_verifier": lambda _plan: True,
        "assignment_verifier": lambda _receipt, _plan: True,
        "runner_lease_verifier": lambda *_args: True,
        "arm_receipt_verifier": lambda _receipt, _plan, _assignment: True,
        "pair_execution_receipt_verifier": lambda *_args: True,
        "cancellation_verifier": lambda _receipt, _attempt, _plan: True,
        "gate_verifier": lambda _receipt, _state: True,
        "base_snapshot_verifier": lambda _receipt, _state: True,
        "rollback_verifier": lambda _trigger, _state: True,
        "archive_verifier": lambda _digest, _attestation: True,
        "repair_opportunity_verifier": lambda *_args: True,
    }
    first = FactorBankV2.load(path, state_key=fixture.key, **capabilities)
    stale = FactorBankV2.load(path, state_key=fixture.key, **capabilities)
    assignment = make_assignment_receipt_v2(
        plan=fixture.plan,
        ordinal=0,
        origin_pool_sha256=_h("origin-pool"),
        producer_epoch="assignment-producer:one",
        attestation_sha256=_h("authoritative-assignment"),
    )
    stale_before = stale.to_state()

    lease = _runner_lease(fixture.plan, assignment, "authoritative")
    assert first.open_next_attempt(
        fixture.plan.plan_id, assignment, lease
    ).state == "open"
    with pytest.raises(RuntimeError, match="compare-and-swap"):
        stale.open_next_attempt(fixture.plan.plan_id, assignment, lease)

    assert stale.to_state() == stale_before
    reloaded = FactorBankV2.load(path, state_key=fixture.key, **capabilities)
    assert len(reloaded.to_state().attempts) == 1


def test_same_instance_explicit_save_is_linearized_with_mutation(tmp_path) -> None:
    fixture = Fixture()
    path = tmp_path / "sft-bank-save-linearization.json"
    fixture.bank.save(path)
    initial_bytes = path.read_bytes()
    original_to_state = fixture.bank.to_state
    stale_thread_ids: list[int] = []
    save_owned_mutation_lock: list[bool] = []
    stale_snapshot_captured = threading.Event()
    mutation_started = threading.Event()
    mutation_done = threading.Event()
    save_errors: list[BaseException] = []
    mutation_errors: list[BaseException] = []
    opened_attempts = []

    def controlled_to_state():
        state = original_to_state()
        if threading.get_ident() in stale_thread_ids:
            owns_lock = bool(fixture.bank._mutation_lock._is_owned())
            save_owned_mutation_lock.append(owns_lock)
            stale_snapshot_captured.set()
            assert mutation_started.wait(timeout=5)
            # On the unfenced implementation, force the mutation to publish
            # first so this already-captured snapshot deterministically writes
            # last.  With the fix the save owns the lock, publishes first, and
            # the waiting mutation must be the final writer.
            if not owns_lock:
                assert mutation_done.wait(timeout=5)
        return state

    fixture.bank.to_state = controlled_to_state

    def explicit_save() -> None:
        stale_thread_ids.append(threading.get_ident())
        try:
            fixture.bank.save(path)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            save_errors.append(exc)

    def mutate() -> None:
        mutation_started.set()
        try:
            opened_attempts.append(_open_next(fixture))
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            mutation_errors.append(exc)
        finally:
            mutation_done.set()

    save_thread = threading.Thread(target=explicit_save)
    save_thread.start()
    assert stale_snapshot_captured.wait(timeout=5)
    mutation_thread = threading.Thread(target=mutate)
    mutation_thread.start()
    save_thread.join(timeout=5)
    mutation_thread.join(timeout=5)

    assert not save_thread.is_alive() and not mutation_thread.is_alive()
    assert not save_errors and not mutation_errors
    assert save_owned_mutation_lock == [True]
    assert len(opened_attempts) == 1
    assert path.read_bytes() != initial_bytes

    capabilities = {
        "direct_binding_verifier": lambda *_args: True,
        "whole_operation_verifier": lambda *_args: True,
        "plan_verifier": lambda _plan: True,
        "assignment_verifier": lambda _receipt, _plan: True,
        "runner_lease_verifier": lambda *_args: True,
        "arm_receipt_verifier": lambda *_args: True,
        "pair_execution_receipt_verifier": lambda *_args: True,
        "cancellation_verifier": lambda *_args: True,
        "gate_verifier": lambda *_args: True,
        "base_snapshot_verifier": lambda *_args: True,
        "rollback_verifier": lambda *_args: True,
        "archive_verifier": lambda *_args: True,
        "repair_opportunity_verifier": lambda *_args: True,
    }
    reloaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **capabilities,
    )
    assert len(reloaded.to_state().attempts) == 1


def test_read_only_snapshot_has_no_writer_surface() -> None:
    fixture = Fixture()
    terminal = fixture.bank.read_only_snapshot()
    before = terminal.scientific_state_sha256

    assert terminal.retrieve(fixture.namespace)[0].composition_id == (
        fixture.source.composition_id
    )
    assert not hasattr(terminal, "commit_attempt")
    assert not hasattr(terminal, "record_failure")
    assert terminal.scientific_state_sha256 == before

def test_rollback_restores_exact_predecessor_without_positive_credit() -> None:
    fixture = Fixture()
    for vote in ("benefit", "benefit", "null", "benefit"):
        fixture.complete(vote)
    active = fixture.gate(True)
    assert active is not None
    before_assessment = fixture.bank.to_state().assessments
    before_attempts = fixture.bank.to_state().attempts

    record = fixture.bank.apply_rollback(
        RollbackTriggerV2(
            trigger_id="rollback-trigger:one",
            kind="train_monitor_harm",
            deployment_slot_id=active.deployment_slot_id,
            expected_head_generation=active.generation,
            active_snapshot_id=active.active_snapshot_id,
            safe_failure_code="monitor_harm",
            evidence_or_support_sha256=_h("monitor-evidence"),
            verifier_epoch="rollback-verifier:one",
            attestation_sha256=_h("rollback-attestation"),
            emitted_seq=fixture.bank.to_state().event_seq + 1,
        )
    )

    assert record.disposition == "restored_predecessor"
    assert fixture.bank.retrieve(fixture.namespace)[0].composition_id == (
        fixture.source.composition_id
    )
    assert fixture.bank.to_state().assessments == before_assessment
    assert fixture.bank.to_state().attempts == before_attempts


def test_train_monitor_rollback_poisons_canonical_alias_group_and_proposal() -> None:
    fixture = Fixture()
    opportunity = _repair_opportunity(
        fixture,
        "rollback-canonical-harm",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:rollback-canonical-harm",
        attestation_sha256=_h("rollback-canonical-harm-action"),
    )
    assert action is not None
    proof = _h("rollback-canonical-harm-proof")
    alias = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:rollback-canonical-harm",
        binding_proof_sha256=proof,
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:rollback-canonical-harm",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    fixture.bank.finalize_proposal_action(
        action.action_id,
        transition_id=alias.transition_id,
        phase_terminal_sha256=proof,
    )
    for vote in ("benefit", "benefit", "null", "benefit"):
        fixture.complete(vote)
    active = fixture.gate(True)
    assert active is not None

    fixture.bank.apply_rollback(
        RollbackTriggerV2(
            trigger_id="rollback-trigger:canonical-harm",
            kind="train_monitor_harm",
            deployment_slot_id=active.deployment_slot_id,
            expected_head_generation=active.generation,
            active_snapshot_id=active.active_snapshot_id,
            safe_failure_code="monitor_harm",
            evidence_or_support_sha256=_h("canonical-harm-monitor-evidence"),
            verifier_epoch="rollback-verifier:canonical-harm",
            attestation_sha256=_h("canonical-harm-rollback-attestation"),
            emitted_seq=fixture.bank.to_state().event_seq + 1,
        )
    )

    harmful = fixture.bank._harmful_transition_ids()
    assert {fixture.transition.transition_id, alias.transition_id} <= harmful
    signs = fixture.bank._proposal_portable_signs(
        slot_id="instruction_slot",
        from_revision_id=fixture.old.revision_id,
        to_revision_id=fixture.new.revision_id,
    )
    current_background = fixture.bank._canonical_direct_background_sha256(
        fixture.bank.to_state(),
        source=fixture.source,
        source_factor=fixture.old,
        slot_id="instruction_slot",
    )
    assert {
        sign.sign
        for sign in signs
        if sign.fixed_background_sha256 == current_background
    } == {"harm"}
    after = _proposal_receipt(fixture, opportunity)
    summary = after.candidate_manifest[0].pair_summary
    assert summary.current_background_sign == "harm"
    assert summary.proposal_class == "veto"
    assert after.selection_mode == "no_safe_reuse"


def test_monitor_rollback_revokes_downstream_pending_gate_atomically() -> None:
    fixture = Fixture()
    for index, vote in enumerate(("benefit", "benefit", "null", "benefit")):
        fixture.complete(vote, tag=f"upstream-{index}")
    active = fixture.gate(True)
    assert active is not None
    downstream_factor = fixture._factor(
        "instruction:downstream-rollback",
        "value-downstream-rollback",
        parent=fixture.new.revision_id,
    )
    downstream_target = fixture._composition(
        "composition:downstream-rollback",
        downstream_factor.revision_id,
        "artifact-downstream-rollback",
    )
    downstream = fixture.bank.register_direct_transition(
        source_composition_id=fixture.target.composition_id,
        target_composition_id=downstream_target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:downstream-rollback",
        binding_proof_sha256=_h("proof-downstream-rollback"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:downstream-rollback",
        origin_branch="mutate",
    )
    plan = fixture.bank.seal_probe_plan(
        transition_id=downstream.transition_id,
        owner_kind="direct_factor",
        epoch_id="epoch:downstream-rollback",
        unit_commitments=tuple(
            _h(f"downstream-rollback-unit-{index}") for index in range(6)
        ),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_h("downstream-rollback-manifest"),
        runner_version="runner:downstream-rollback",
        budget=_budget(),
    )
    for index, vote in enumerate(("benefit", "benefit", "null", "benefit")):
        fixture.complete(
            vote,
            tag=f"downstream-rollback-{index}",
            plan=plan,
            transition=downstream,
            source=fixture.target,
            target=downstream_target,
        )
    pending = next(
        item for item in fixture.bank.to_state().gate_opportunities
        if item.plan_id == plan.plan_id and item.state == "pending"
    )

    record = fixture.bank.apply_rollback(
        RollbackTriggerV2(
            trigger_id="rollback-trigger:downstream-pending",
            kind="train_monitor_harm",
            deployment_slot_id=active.deployment_slot_id,
            expected_head_generation=active.generation,
            active_snapshot_id=active.active_snapshot_id,
            safe_failure_code="monitor_harm",
            evidence_or_support_sha256=_h("downstream-pending-monitor-evidence"),
            verifier_epoch="rollback-verifier:downstream-pending",
            attestation_sha256=_h("downstream-pending-rollback-attestation"),
            emitted_seq=fixture.bank.to_state().event_seq + 1,
        )
    )

    assert record.disposition == "restored_predecessor"
    terminal = next(
        item for item in fixture.bank.to_state().gate_opportunities
        if item.opportunity_id == pending.opportunity_id
    )
    assert terminal.state == "revoked"
    assert fixture.bank.retrieve(fixture.namespace)[0] == fixture.source


def test_rollback_history_replay_rejects_self_consistent_wrong_snapshot() -> None:
    fixture = Fixture()
    for vote in ("benefit", "benefit", "null", "benefit"):
        fixture.complete(vote)
    active = fixture.gate(True)
    assert active is not None
    fixture.bank.apply_rollback(
        RollbackTriggerV2(
            trigger_id="rollback-trigger:chronology",
            kind="train_monitor_harm",
            deployment_slot_id=active.deployment_slot_id,
            expected_head_generation=active.generation,
            active_snapshot_id=active.active_snapshot_id,
            safe_failure_code="monitor_harm",
            evidence_or_support_sha256=_h("chronology-monitor-evidence"),
            verifier_epoch="rollback-verifier:chronology",
            attestation_sha256=_h("chronology-rollback-attestation"),
            emitted_seq=fixture.bank.to_state().event_seq + 1,
        )
    )
    state = fixture.bank.to_state()
    trigger = state.rollback_triggers[0].model_copy(
        update={"active_snapshot_id": fixture.base.snapshot_id}
    )
    record = state.rollback_records[0].model_copy(
        update={
            "old_snapshot_id": fixture.base.snapshot_id,
            "restored_snapshot_id": fixture.base.snapshot_id,
            "disposition": "restored_base",
        }
    )
    forged = state.model_copy(
        update={
            "rollback_triggers": (trigger,),
            "rollback_records": (record,),
        }
    )

    with pytest.raises(ValueError, match="does not replay from the active head"):
        FactorBankV2(
            forged,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_legacy_v1_state_is_explicitly_rejected(tmp_path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema_version": "pif_shadow_v1"}), encoding="utf-8")
    with pytest.raises(LegacyStateRejected):
        FactorBankV2.load(path, state_key=b"factor-bank-v2-test-key" * 2)


def test_v14_state_signed_under_v13_domain_is_rejected(tmp_path) -> None:
    fixture = Fixture()
    path = tmp_path / "v14-state-v13-domain.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v13\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="HMAC mismatch"):
        FactorBankV2.load(
            path,
            state_key=fixture.key,
            **_trusted_bank_capabilities(),
        )


def test_authenticated_v4_state_is_rejected_without_implicit_migration(
    tmp_path,
) -> None:
    fixture = Fixture()
    path = tmp_path / "authenticated-v4.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["schema_version"] = "sft_factor_transition_v4"
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LegacyStateRejected, match="explicit migration"):
        FactorBankV2.load(path, state_key=fixture.key)


def test_authenticated_v5_state_is_rejected_after_cleanup_schema_bump(
    tmp_path,
) -> None:
    fixture = Fixture()
    path = tmp_path / "authenticated-v5.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["schema_version"] = "sft_factor_transition_v5"
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LegacyStateRejected, match="explicit migration"):
        FactorBankV2.load(path, state_key=fixture.key)


def test_authenticated_v6_state_is_rejected_after_admission_schema_bump(
    tmp_path,
) -> None:
    fixture = Fixture()
    path = tmp_path / "authenticated-v6.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["schema_version"] = "sft_factor_transition_v6"
    payload["state"].pop("proposal_carrier_admissions", None)
    payload["state"]["capacity_policy"].pop(
        "max_proposal_carrier_admissions",
        None,
    )
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LegacyStateRejected, match="explicit migration"):
        FactorBankV2.load(path, state_key=fixture.key)


@pytest.mark.parametrize(
    "legacy_schema",
    (
        "sft_factor_transition_v7",
        "sft_factor_transition_v8",
        "sft_factor_transition_v9",
        "sft_factor_transition_v10",
        "sft_factor_transition_v11",
        "sft_factor_transition_v12",
        "sft_factor_transition_v13",
    ),
)
def test_authenticated_pre_counter_state_rejected_after_v14_bump(
    tmp_path,
    legacy_schema,
) -> None:
    fixture = Fixture()
    path = tmp_path / f"authenticated-{legacy_schema}.json"
    fixture.bank.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["schema_version"] = legacy_schema
    state_bytes = json.dumps(
        payload["state"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["state_sha256"] = hashlib.sha256(state_bytes).hexdigest()
    payload["state_hmac_sha256"] = hmac.new(
        fixture.key,
        b"sft-bank-state-v14\0" + state_bytes,
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LegacyStateRejected, match="explicit migration"):
        FactorBankV2.load(path, state_key=fixture.key)


def test_capacity_archive_is_harm_before_unknown_and_compacts_edge_evidence() -> None:
    fixture = Fixture()
    harmful_attempt = fixture.complete("target_algorithm_failure")
    consumed_roots = harmful_attempt.presented_root_ids
    consumed_receipts = harmful_attempt.presented_receipt_ids
    harmful_id = fixture.transition.transition_id
    harmful_plan_id = fixture.plan.plan_id

    unknown_factor = fixture._factor(
        "instruction:unknown",
        "unknown-value",
        parent=fixture.old.revision_id,
    )
    unknown_target = fixture._composition(
        "composition:unknown",
        unknown_factor.revision_id,
        "artifact-unknown",
    )
    unknown_transition = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=unknown_target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:unknown",
        binding_proof_sha256=_h("proof-unknown"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:one",
        origin_branch="fresh",
    )

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-attestation"),
        max_victims=1,
    )

    assert checkpoint is not None
    assert checkpoint.subject_ids == (harmful_id,)
    state = fixture.bank.to_state()
    harmful = next(
        item for item in state.direct_transitions if item.transition_id == harmful_id
    )
    unknown = next(
        item
        for item in state.direct_transitions
        if item.transition_id == unknown_transition.transition_id
    )
    assert harmful.structural_state == "tombstone"
    assert unknown.structural_state == "live"
    assert fixture.bank.factors[fixture.new.revision_id].structural_state == "tombstone"
    assert fixture.bank.factors[fixture.background.revision_id].structural_state == "live"
    assert harmful_plan_id not in {item.plan_id for item in state.plans}
    assert all(item.plan_id != harmful_plan_id for item in state.attempts)
    assert all(item.plan_id != harmful_plan_id for item in state.assessments)
    assert len(state.tombstones) == 1
    assert all(dict(state.used_roots)[item] == checkpoint.checkpoint_id for item in consumed_roots)
    assert all(
        dict(state.used_receipts)[item] == checkpoint.checkpoint_id
        for item in consumed_receipts
    )
    assert all(
        (harmful_plan_id != plan_id)
        for plan_id in {item.plan_id for item in state.plans}
    )
    assert all(
        (
            fixture.plan.canonical_scientific_edge_key_sha256,
            _h(f"unit-{index}"),
        )
        in set(state.used_unit_commitments)
        for index in range(6)
    )
    assert fixture.bank.retrieve(fixture.namespace)[0].composition_id == (
        fixture.source.composition_id
    )


def test_archived_selector_evidence_replays_prior_decision_and_rejects_forged_leaf(
    tmp_path,
) -> None:
    fixture = Fixture()
    for index in range(4):
        fixture.complete("benefit", tag=f"portable-benefit-{index}")
    assessment = fixture.bank.assessments[fixture.plan.plan_id]
    assert assessment.settled and assessment.label == "candidate"

    repair = _repair_opportunity(
        fixture,
        "archive-replay",
        feasible_branches=("fresh",),
    )
    proposal = _proposal_receipt(fixture, repair)
    context = _generation_context(fixture, repair, proposal, tag="archive-replay")
    assert proposal.candidate_manifest[0].candidate.background_signs[0].sign == (
        "benefit"
    )
    decision, assignment, action = fixture.bank.screen_and_allocate_branch(
        repair.opportunity_id,
        proposal,
        producer_epoch="proposal-host:archive-replay",
        attestation_sha256=_h("proposal-archive-replay-attestation"),
        generation_context=context,
    )
    assert decision.selected_branch == "fresh"
    assert assignment is not None and action is not None

    fixture.gate(False)
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-portable-evidence"),
        required_hot_slots=16,
        max_victims=1,
    )
    assert checkpoint is not None
    state = fixture.bank.to_state()
    assert state.assessments == ()
    assert len(state.portable_evidence_leaves) == 1
    leaf = state.portable_evidence_leaves[0]
    assert leaf.sign == "benefit"
    assert leaf.source_revision_seq < decision.created_seq < leaf.created_seq

    path = tmp_path / "sft-portable-evidence.json"
    fixture.bank.save(path)
    capabilities = {
        "direct_binding_verifier": lambda *_args: True,
        "whole_operation_verifier": lambda *_args: True,
        "plan_verifier": lambda _plan: True,
        "assignment_verifier": lambda *_args: True,
        "runner_lease_verifier": lambda *_args: True,
        "arm_receipt_verifier": lambda *_args: True,
        "pair_execution_receipt_verifier": lambda *_args: True,
        "cancellation_verifier": lambda *_args: True,
        "proposal_abort_verifier": lambda *_args: True,
        "proposal_generation_context_verifier": lambda *_args: True,
        "gate_verifier": lambda *_args: True,
        "base_snapshot_verifier": lambda *_args: True,
        "rollback_verifier": lambda *_args: True,
        "archive_verifier": lambda *_args: True,
        "repair_opportunity_verifier": lambda *_args: True,
    }
    loaded = FactorBankV2.load(
        path,
        state_key=fixture.key,
        **capabilities,
    )
    assert loaded.scientific_state_sha256 == fixture.bank.scientific_state_sha256

    forged_leaf = leaf.model_copy(
        update={"bank_attestation_sha256": _h("forged-portable-leaf")}
    )
    forged_state = state.model_copy(
        update={"portable_evidence_leaves": (forged_leaf,)}
    )
    with pytest.raises(ValueError, match="portable evidence leaf closure"):
        FactorBankV2(
            forged_state,
            state_key=fixture.key,
            **capabilities,
        )


def test_archived_physical_roots_remain_consumed_and_replay_quarantines() -> None:
    fixture = Fixture()
    harmful_attempt = fixture.complete("target_algorithm_failure")
    old_arm_roots = harmful_attempt.presented_root_ids[:2]
    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-replay-attestation"),
        max_victims=1,
    )
    assert checkpoint is not None
    sibling, sibling_target, sibling_plan = _add_sibling_transition_and_plan(
        fixture, "root-replay"
    )

    replay = fixture.complete(
        "benefit",
        plan=sibling_plan,
        transition=sibling,
        target=sibling_target,
        physical_root_ids=(old_arm_roots[0], old_arm_roots[1]),
    )

    assert replay.state == "quarantine"
    assert replay.disposition_reason == "reused_physical_root"
    used_roots = dict(fixture.bank.to_state().used_roots)
    assert used_roots[old_arm_roots[0]] == checkpoint.checkpoint_id
    assert used_roots[old_arm_roots[1]] == checkpoint.checkpoint_id


def test_harm_tombstone_capacity_refuses_washout_instead_of_fifo_drop() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(max_recent_tombstones=1)
    )
    fixture.complete("target_algorithm_failure")
    first_id = fixture.transition.transition_id
    first_checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-first-harm"),
        max_victims=1,
    )
    assert first_checkpoint is not None

    second, second_target, second_plan = _add_sibling_transition_and_plan(
        fixture, "second-harm"
    )
    fixture.complete(
        "target_algorithm_failure",
        plan=second_plan,
        transition=second,
        target=second_target,
    )
    before = fixture.bank.to_state()
    with pytest.raises(RuntimeError, match="durable negative-tombstone capacity"):
        fixture.bank.archive_for_capacity(
            fixture.namespace,
            archive_attestation_sha256=_h("archive-second-harm"),
            max_victims=1,
        )
    after = fixture.bank.to_state()
    assert after == before
    assert len(after.tombstones) == 1
    assert after.tombstones[0].subject_id == first_id


def test_duplicate_content_revision_cannot_bypass_canonical_edge_owner() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure")
    alias = fixture._factor(
        "instruction:alias",
        "value-b",
        parent=fixture.old.revision_id,
    )
    alias_target = fixture._composition(
        "composition:alias",
        alias.revision_id,
        "artifact-b",
    )

    with pytest.raises(ValueError, match="already has a credit owner"):
        fixture.bank.register_direct_transition(
            source_composition_id=fixture.source.composition_id,
            target_composition_id=alias_target.composition_id,
            slot_id="instruction_slot",
            binding_proof_id="proof:alias",
            binding_proof_sha256=_h("proof-alias"),
            masked_background_sha256=_h("masked-background-alias"),
            binding_verifier_epoch="binder:one",
            origin_branch="fresh",
        )


def test_lifetime_identity_capacity_is_reserved_before_plan_execution() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(
            max_consumed_root_ids=18,
            max_consumed_receipt_ids=18,
        )
    )
    for vote in ("benefit", "benefit", "null", "benefit"):
        fixture.complete(vote)
    factor = fixture._factor(
        "instruction:capacity",
        "value-capacity",
        parent=fixture.old.revision_id,
    )
    target = fixture._composition(
        "composition:capacity", factor.revision_id, "artifact-capacity"
    )
    transition = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:capacity",
        binding_proof_sha256=_h("proof-capacity"),
        masked_background_sha256=_h("masked-background-capacity"),
        binding_verifier_epoch="binder:one",
        origin_branch="mutate",
    )

    with pytest.raises(RuntimeError, match="lifetime reservation"):
        fixture.bank.seal_probe_plan(
            transition_id=transition.transition_id,
            owner_kind="direct_factor",
            epoch_id="epoch:capacity",
            unit_commitments=tuple(_h(f"capacity-unit-{index}") for index in range(6)),
            arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
            assignment_manifest_sha256=_h("assignment-manifest-capacity"),
            runner_version="runner:one",
            budget=_budget(),
        )


def test_archive_rejection_is_atomic_and_active_transition_is_protected() -> None:
    fixture = Fixture()
    fixture.complete("target_algorithm_failure")
    fixture.bank._archive_verifier = lambda _root, _attestation: False
    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="archive verifier rejected"):
        fixture.bank.archive_for_capacity(
            fixture.namespace,
            archive_attestation_sha256=_h("rejected-archive"),
        )
    assert fixture.bank.to_state() == before

    active = Fixture()
    for vote in ("benefit", "benefit", "null", "benefit"):
        active.complete(vote)
    active.gate(True)
    assert active.bank.archive_for_capacity(
        active.namespace,
        archive_attestation_sha256=_h("protected-archive"),
    ) is None


def test_runner_lease_generation_and_terminal_token_are_hard_fences() -> None:
    fixture = Fixture()
    assignment = make_assignment_receipt_v2(
        plan=fixture.plan,
        ordinal=0,
        origin_pool_sha256=_h("lease-origin"),
        producer_epoch="assignment-producer:lease",
        attestation_sha256=_h("lease-assignment"),
    )
    lease = _runner_lease(fixture.plan, assignment, "lease-generation")
    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="fencing_generation"):
        fixture.bank.open_next_attempt(
            fixture.plan.plan_id,
            assignment,
            lease.model_copy(update={"fencing_generation": 2}),
        )
    assert fixture.bank.to_state() == before

    attempt = fixture.bank.open_next_attempt(fixture.plan.plan_id, assignment, lease)
    cancellation = _cancellation(fixture, attempt)
    forged = cancellation.model_copy(
        update={"runner_lease_token_sha256": _h("wrong-terminal-token")}
    )
    with pytest.raises(ValueError, match="schedule commitment"):
        fixture.bank.cancel_open_attempt(attempt.attempt_id, forged)


def test_pair_and_cancel_policy_bits_are_bound_into_raw_terminal_roots() -> None:
    fixture = Fixture()
    complete = fixture.complete("benefit", tag="terminal-commitment")
    assert complete.pair_execution_receipt is not None
    pair = complete.pair_execution_receipt
    pair_forged = pair.model_copy(
        update={"source_started_event_id": "pair-event:forged"}
    )
    with pytest.raises(ValueError, match="terminal event root"):
        pair.__class__.model_validate(pair_forged.model_dump(mode="python"))

    attempt = _open_next(fixture)
    cancellation = _cancellation(fixture, attempt, terminate_scope=True)
    for update in (
        {"cancel_kind": "harness"},
        {"terminate_scope": False},
    ):
        forged = cancellation.model_copy(update=update)
        with pytest.raises(ValueError, match="terminal event root"):
            cancellation.__class__.model_validate(forged.model_dump(mode="python"))


@pytest.mark.parametrize("scheduled_order", ["AB", "BA"])
def test_two_start_abort_consumes_three_roots_and_never_votes(
    scheduled_order: str,
) -> None:
    fixture = Fixture()
    if scheduled_order == "BA":
        first = _open_next(fixture)
        assert first.assignment.arm_order == "AB"
        fixture.bank.cancel_open_attempt(
            first.attempt_id, _cancellation(fixture, first, terminate_scope=False)
        )
    attempt = _open_next(fixture)
    assert attempt.assignment.arm_order == scheduled_order
    first_root = _h(f"two-start-{scheduled_order}-first")
    second_root = _h(f"two-start-{scheduled_order}-second")
    cancellation = _cancellation(
        fixture,
        attempt,
        started_root_id=first_root,
        second_started_root_id=second_root,
    )

    cancelled = fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation)

    assert cancelled.presented_root_ids == (
        first_root,
        second_root,
        cancellation.runner_event_root_sha256,
    )
    assert fixture.bank.assessments[fixture.plan.plan_id].vote_by_attempt == ()
    assert fixture.bank.assessments[fixture.plan.plan_id].label == (
        "infrastructure_exhausted"
    )
    used = dict(fixture.bank.to_state().used_roots)
    assert all(used[root] == attempt.attempt_id for root in cancelled.presented_root_ids)


def test_signed_cancel_survives_unrelated_bank_mutation_and_retries_exactly() -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)
    cancellation = _cancellation(fixture, attempt)
    signed_at_seq = fixture.bank.to_state().event_seq
    assert _record_algorithm_failure(fixture, "cancel-unrelated") is not None
    assert fixture.bank.to_state().event_seq > signed_at_seq

    cancelled = fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation)
    assert cancelled.settled_seq == fixture.bank.to_state().event_seq
    terminal = fixture.bank.to_state()
    assert fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation) == cancelled
    assert fixture.bank.to_state() == terminal


def test_raw_pair_terminal_root_replay_is_quarantined_with_first_owner() -> None:
    fixture = Fixture()
    first = fixture.complete("benefit", tag="raw-pair-owner")
    assert first.source_receipt is not None
    assert first.target_receipt is not None
    assert first.pair_execution_receipt is not None
    raw_root = first.pair_execution_receipt.runner_event_root_sha256
    second = _open_next(fixture)

    before = fixture.bank.to_state()
    with pytest.raises(ValueError, match="consumed raw journal root"):
        fixture.bank.commit_attempt(
            second.attempt_id,
            first.source_receipt,
            first.target_receipt,
            first.pair_execution_receipt,
        )

    assert fixture.bank.to_state() == before
    assert dict(fixture.bank.to_state().used_roots)[raw_root] == first.attempt_id
    assert fixture.bank.assessments[fixture.plan.plan_id].n_complete == 1


def test_raw_cancel_terminal_root_replay_as_pair_is_quarantined() -> None:
    fixture = Fixture()
    attempt = _open_next(fixture)
    cancellation = _cancellation(fixture, attempt)
    fixture.bank.cancel_open_attempt(attempt.attempt_id, cancellation)

    replay = fixture.complete(
        "benefit",
        tag="cancel-terminal-as-arm",
        physical_root_ids=(
            cancellation.runner_event_root_sha256,
            _h("cancel-terminal-new-target"),
        ),
    )
    assert replay.state == "quarantine"
    assert replay.disposition_reason == "reused_physical_root"
    assert dict(fixture.bank.to_state().used_roots)[
        cancellation.runner_event_root_sha256
    ] == attempt.attempt_id


def test_receipt_capacity_reserves_twenty_four_records_per_active_plan() -> None:
    fixture = Fixture()
    siblings = [
        _add_sibling_transition_and_plan(fixture, f"capacity-{index}")
        for index in range(3)
    ]
    active = [
        item for item in fixture.bank.to_state().reservations if item.state == "active"
    ]
    assert len(active) == 4
    assert sum(item.reserved_receipt_slots for item in active) == 96

    capped = Fixture(capacity_policy=CapacityPolicyV1(max_receipt_records=95))
    _add_sibling_transition_and_plan(capped, "cap95-one")
    _add_sibling_transition_and_plan(capped, "cap95-two")
    with pytest.raises(RuntimeError, match="receipt capacity reservation"):
        _add_sibling_transition_and_plan(capped, "cap95-three")

    all_plans = [
        (fixture.transition, fixture.target, fixture.plan),
        *siblings,
    ]
    for plan_index, (transition, target, plan) in enumerate(all_plans):
        for ordinal in range(6):
            fixture.complete(
                "infrastructure",
                tag=f"capacity-{plan_index}-{ordinal}",
                plan=plan,
                transition=transition,
                target=target,
            )
    state = fixture.bank.to_state()
    materialized = sum(
        1
        + int(item.source_receipt is not None)
        + int(item.target_receipt is not None)
        + int(item.pair_execution_receipt is not None)
        + int(item.cancellation_receipt is not None)
        for item in state.attempts
    )
    assert len(state.attempts) == 24
    assert materialized == state.capacity_policy.max_receipt_records == 96


def test_prepared_proposal_edge_and_carrier_closure_are_archive_protected() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(unknown_structural_reserve=0)
    )
    opportunity = _repair_opportunity(
        fixture,
        "archive-prepared-action",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:archive-protection",
        attestation_sha256=_h("proposal-archive-protection"),
    )
    assert action is not None and action.state == "prepared"
    pending = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:proposal:archive-protection",
        binding_proof_sha256=_h("phase-pending-proof"),
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:proposal:pending",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    before = fixture.bank.to_state()

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-pending-action"),
        required_hot_slots=100,
    )

    assert checkpoint is None
    after = fixture.bank.to_state()
    assert after == before
    assert next(
        item for item in after.direct_transitions
        if item.transition_id == pending.transition_id
    ).structural_state == "live"
    assert fixture.bank.compositions[pending.source_composition_id].structural_state == "live"
    assert fixture.bank.compositions[pending.target_composition_id].structural_state == "live"


def test_prepared_proposal_action_without_edge_protects_archive_closure() -> None:
    fixture = Fixture(
        capacity_policy=CapacityPolicyV1(unknown_structural_reserve=0)
    )
    attempt = _open_next(fixture)
    fixture.bank.cancel_open_attempt(
        attempt.attempt_id,
        _cancellation(fixture, attempt, terminate_scope=True),
    )
    assert fixture.bank.assessments[fixture.plan.plan_id].settled

    opportunity = _repair_opportunity(
        fixture,
        "archive-preedge-action",
        feasible_branches=("reuse",),
    )
    proposal = _proposal_receipt(fixture, opportunity)
    _decision, _assignment, action = fixture.bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:preedge-archive",
        attestation_sha256=_h("proposal-preedge-archive"),
    )
    assert action is not None and action.state == "prepared"
    assert not any(
        item.proposal_action_id == action.action_id
        for item in fixture.bank.to_state().direct_transitions
    )

    checkpoint = fixture.bank.archive_for_capacity(
        fixture.namespace,
        archive_attestation_sha256=_h("archive-preedge-action"),
        required_hot_slots=100,
        max_victims=1,
    )

    assert checkpoint is None
    assert fixture.bank.compositions[
        action.source_composition_id
    ].structural_state == "live"
    assert fixture.bank.compositions[
        fixture.target.composition_id
    ].structural_state == "live"
    assert fixture.bank.factors[action.from_revision_id].structural_state == "live"
    assert fixture.bank.factors[action.to_revision_id].structural_state == "live"

    phase_terminal_sha256 = _h("phase-terminal-after-preedge-archive")
    projected = fixture.bank.register_direct_transition(
        source_composition_id=fixture.source.composition_id,
        target_composition_id=fixture.target.composition_id,
        slot_id="instruction_slot",
        binding_proof_id="proof:proposal:after-preedge-archive",
        binding_proof_sha256=phase_terminal_sha256,
        masked_background_sha256=_h("masked-background"),
        binding_verifier_epoch="binder:proposal:after-preedge-archive",
        origin_branch="reuse",
        proposal_action_id=action.action_id,
        proposal_action_intent_sha256=action.action_intent_sha256,
    )
    committed = fixture.bank.finalize_proposal_action(
        action.action_id,
        transition_id=projected.transition_id,
        phase_terminal_sha256=phase_terminal_sha256,
    )
    assert committed.state == "committed"
    assert committed.transition_id == projected.transition_id
