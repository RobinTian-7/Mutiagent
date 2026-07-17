from __future__ import annotations

import hashlib
import json

import pytest

from exp_graph.mas.factor_bank import (
    DenseOutcome,
    ExecutionBudget,
    ExecutionNamespace,
    ExecutionUsage,
)
from exp_graph.mas.factor_bank_v2 import (
    BaseSnapshotReceiptV2,
    FailureObservationV2,
    FactorBankV2,
    GateReceiptV2,
    make_arm_receipt_v2,
    make_assignment_receipt_v2,
    make_pair_execution_receipt_v2,
    make_proposal_action_abort_receipt_v2,
    make_proposal_generation_context_v1,
    make_proposal_generation_lease_v1,
    make_runner_lease_grant_v1,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FULL_FACTOR_BINDER_VERSION,
    NoOpMaterialization,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    PhaseGenerationTerminalV1,
    SourceManifest,
    phase_generated_scalar_sha256,
    phase_materialization_event_sha256_v1,
    phase_mutable_factor_paths_v3,
)
from exp_graph.mas.phase_factor_binding_v2 import (
    make_phase_v2_proposal_action_terminal_verifier,
    reconcile_phase_proposal_action_v2,
    register_phase_materialization_v2,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    PHASE_FULL_FACTOR_SKELETON_SLOT_ID,
    make_phase_v3_binding_verifier,
    make_phase_v3_proposal_action_terminal_verifier,
    make_phase_v3_repair_opportunity_verifier,
    reconcile_phase_proposal_action_v3,
    register_phase_materialization_v3,
)
from exp_graph.mas.phase_program import PhaseProgram, PhaseProgramLimits
from exp_graph.mas.sft_proposal import (
    ExactFactorLocusV1,
    ExactProposalCellV1,
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


def _program(*, phases=None) -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": phases
            or [
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": "gather",
                },
                {
                    "kind": "broadcast",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": "broadcast",
                },
            ],
        }
    )


class Fixture:
    def __init__(self, *, n_agents: int = 4, limits: PhaseProgramLimits | None = None):
        self.manifest = SourceManifest(
            manifest_sha256=_h("full-v3-manifest"),
            split="TRAIN_UPDATE",
            source_catalog_sha256=_h("full-v3-catalog"),
            policy_sha256=_h("full-v3-policy"),
            producer_version="full-v3-test-host",
        )
        self.registry = PhaseArtifactRegistry(
            registry_key=b"phase-full-v3-registry-key" * 2,
            manifests=(self.manifest,),
            manifest_verifier=lambda candidate: candidate == self.manifest,
            branch_receipt_verifier=lambda _body: True,
        )
        self.namespace = ExecutionNamespace(
            task_family="synthetic_full_phase",
            objective="balanced",
            information_goal="sink",
            planner_mode="program_generate",
            payload_format="phase_program_skill_v1",
            worker_contract="not_applicable",
            n_agents=n_agents,
            array_size_bucket="small",
            budget_level="normal",
            model_name="gpt-4o-mini",
            runtime_version="full-phase-runtime-v3",
            binder_version=PHASE_FULL_FACTOR_BINDER_VERSION,
            compiler_version="1",
        )
        self.profile = self.registry.register_runtime_profile(
            namespace=self.namespace,
            limits=limits or PhaseProgramLimits(),
        )
        self.ingress = self.registry.issue_ingress(self.manifest.manifest_sha256)

    def ingest(self, program: PhaseProgram | None = None):
        return self.registry.ingest_program(
            program or _program(),
            runtime_profile=self.profile,
            ingress=self.ingress,
        )

    def mutate(self, source, *, locator: str, value, tag: str):
        extracted = self.registry.extract_factor(source, locator=locator)
        receipt = self.registry.register_branch_receipt(
            branch="mutate",
            source_artifact=source,
            locator=locator,
            mutation_parent_factor=extracted.factor,
            additional_input_root_commitments=(_h(f"root:{tag}"),),
            producer_epoch="full-v3-test-branch",
            attestation_sha256=_h(f"attestation:{tag}"),
        )
        seal = self.registry.seal_operation(branch_receipt=receipt)
        generated = self.registry.register_generated_value(
            value,
            operation_seal=seal,
            ingress=self.ingress,
        )
        proof = self.registry.materialize(
            operation_seal=seal,
            target_factor=generated.factor,
        )
        assert isinstance(proof, PhaseBindingProofHandle)
        return proof

    def bank(self) -> FactorBankV2:
        return FactorBankV2(
            state_key=b"phase-full-v3-factor-bank-key" * 2,
            direct_binding_verifier=make_phase_v3_binding_verifier(self.registry),
            proposal_action_terminal_verifier=(
                make_phase_v3_proposal_action_terminal_verifier(self.registry)
            ),
            repair_opportunity_verifier=(
                make_phase_v3_repair_opportunity_verifier(self.registry)
            ),
            proposal_abort_verifier=lambda *_args: True,
            proposal_generation_context_verifier=lambda *_args: True,
            proposal_generation_lease_verifier=lambda *_args: True,
            plan_verifier=lambda *_args: True,
            assignment_verifier=lambda *_args: True,
            runner_lease_verifier=lambda *_args: True,
            arm_receipt_verifier=lambda *_args: True,
            pair_execution_receipt_verifier=lambda *_args: True,
            base_snapshot_verifier=lambda *_args: True,
            gate_verifier=lambda *_args: True,
        )


def test_same_source_two_loci_have_one_full_composition_identity() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    first = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="changed instruction",
        tag="instruction",
    )
    second = fixture.mutate(
        source,
        locator="/phases/0/pattern",
        value="star",
        tag="pattern",
    )
    bank = fixture.bank()
    first_edge = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=first,
    )
    second_edge = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=second,
    )

    assert first_edge.source_composition == second_edge.source_composition
    assert first_edge.transition.slot_id != second_edge.transition.slot_id
    expected_paths = phase_mutable_factor_paths_v3(_program())
    assert len(first_edge.source_composition.bindings) == len(expected_paths) + 1
    assert PHASE_FULL_FACTOR_SKELETON_SLOT_ID in (
        first_edge.source_composition.binding_map
    )


def _budget() -> ExecutionBudget:
    return ExecutionBudget(
        max_messages=32,
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


def _outcome(score: float) -> DenseOutcome:
    return DenseOutcome(
        V=score,
        K=0.8,
        U=0.8,
        P=0.8,
        S=0.8,
        stage_score=score,
        C=10.0,
        D=1.0,
    )


def _proposal_input(bank, *, request, cursor, candidates) -> SFTProposalInputV1:
    state = bank.to_state()
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
        candidate_counter_witnesses=bank._proposal_counter_witnesses(
            state,
            cell_sha256=request.cell.scheduler_key_sha256,
            candidates=candidates,
        ),
    )


def _authorize_source(bank: FactorBankV2, composition) -> None:
    if any(
        item.composition_id == composition.composition_id
        for item in bank.to_state().base_receipts
    ):
        return
    _install_base(bank, composition)


def _prepare_action(
    fixture: Fixture,
    *,
    bank: FactorBankV2,
    source_edge,
    branch: str,
    tag: str,
):
    _authorize_source(bank, source_edge.source_composition)
    observation = FailureObservationV2(
        failure_id=f"failure:full-v3:{tag}",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=source_edge.source_composition.composition_id,
        artifact_sha256=source_edge.source_composition.artifact_sha256,
        created_seq=bank.to_state().event_seq + 1,
    )
    opportunity = bank.record_failure(observation, feasible_branches=(branch,))
    assert opportunity is not None
    locus = ExactFactorLocusV1(
        carrier="phase_program",
        slot_id=source_edge.transition.slot_id,
        logical_factor_id=source_edge.source_factor.logical_factor_id,
        locator_surface="phase_field",
        locator_path=source_edge.source_factor.locator.path,
        locator_version=source_edge.source_factor.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=source_edge.source_factor.revision_id,
        canonical_from_factor_key_sha256=(
            bank._factor_carrier_key_sha256(source_edge.source_factor)
        ),
        canonical_background_sha256=bank._canonical_direct_background_sha256(
            bank.to_state(),
            source=source_edge.source_composition,
            source_factor=source_edge.source_factor,
            slot_id=locus.slot_id,
        ),
    )
    candidates, _universe_sha256, _universe_count = bank._proposal_candidate_slate(
        opportunity=opportunity,
        source_factor=source_edge.source_factor,
        slot_id=locus.slot_id,
    )
    proposal = select_exact_edge_proposal(
        _proposal_input(
            bank,
            request=ProposalRequestV1(
                opportunity_id=opportunity.opportunity_id,
                cell=cell,
            ),
            cursor=ProposalCursorV1.empty(cell),
            candidates=candidates,
        )
    )
    context = None
    if branch in {"mutate", "fresh"}:
        context = make_proposal_generation_context_v1(
            opportunity=opportunity,
            failure=observation,
            proposal_receipt=proposal,
            source=source_edge.source_composition,
            source_factor=source_edge.source_factor,
            source_manifest_sha256=fixture.manifest.manifest_sha256,
            train_update_source_catalog_sha256=fixture.manifest.source_catalog_sha256,
            train_update_policy_sha256=fixture.manifest.policy_sha256,
            generation_policy_sha256=_h(f"generation-policy:{tag}"),
            prompt_template_sha256=_h(f"prompt-template:{tag}"),
            scalar_output_schema_sha256=_h(f"scalar-schema:{tag}"),
            budget=_budget(),
            verifier_epoch="full-v3-generation-context",
            attestation_sha256=_h(f"generation-context:{tag}"),
        )
    _decision, assignment, prepared = bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="full-v3-proposal-host",
        attestation_sha256=_h(f"proposal-action:{tag}"),
        generation_context=context,
    )
    assert assignment is not None and assignment.branch == branch
    assert prepared is not None and prepared.state == "prepared"
    if branch == "reuse":
        return prepared
    lease = make_proposal_generation_lease_v1(
        action=prepared,
        runner_session_id=f"generation-runner:{tag}",
        runner_lease_token_sha256=_h(f"generation-token:{tag}"),
        journal_anchor_sha256=_h(f"generation-journal:{tag}"),
        verifier_epoch="full-v3-generation-lease",
        attestation_sha256=_h(f"generation-lease:{tag}"),
    )
    return bank.begin_proposal_generation(prepared.action_id, lease)


def _generation_terminal(action, *, value, tag: str) -> PhaseGenerationTerminalV1:
    request = action.generation_request
    lease = action.generation_lease
    assert request is not None and lease is not None and lease.started_seq is not None
    return PhaseGenerationTerminalV1(
        terminal_id=f"terminal:{tag}",
        action_transaction_id=action.action_id,
        action_intent_sha256=action.action_intent_sha256,
        branch=action.branch,
        generation_request_id=request.request_id,
        generation_request_sha256=request.digest,
        generation_lease_id=lease.lease_id,
        generation_lease_sha256=lease.digest,
        runner_lease_token_sha256=lease.runner_lease_token_sha256,
        generation_lease_started_sequence=lease.started_seq,
        runtime_version=request.runtime_version,
        budget=request.budget,
        budget_sha256=request.budget_sha256,
        usage=ExecutionUsage(
            messages=1,
            model_calls=1,
            input_tokens=100,
            output_tokens=8,
            wall_time_ms=500,
            cost_microusd=20,
        ),
        generated_scalar_sha256=phase_generated_scalar_sha256(value),
        response_envelope_sha256=_h(f"generation-response:{tag}"),
        terminal_event_id=f"generation-event:{tag}",
        terminal_event_sequence=lease.started_seq + 1,
        verifier_epoch="full-v3-generation-terminal",
        attestation_sha256=_h(f"generation-terminal:{tag}"),
    )


def _settle_candidate(bank: FactorBankV2, edge, proof, *, tag: str):
    plan = bank.seal_probe_plan(
        transition_id=edge.transition.transition_id,
        owner_kind="direct_factor",
        epoch_id=f"epoch:{tag}",
        unit_commitments=tuple(_h(f"unit:{tag}:{index}") for index in range(6)),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_h(f"assignments:{tag}"),
        runner_version="full-v3-test-runner",
        budget=_budget(),
    )
    for ordinal, benefit in enumerate((True, True, False, True)):
        assignment = make_assignment_receipt_v2(
            plan=plan,
            ordinal=ordinal,
            origin_pool_sha256=_h(f"pool:{tag}"),
            producer_epoch="full-v3-assignment-host",
            attestation_sha256=_h(f"assignment:{tag}:{ordinal}"),
        )
        lease = make_runner_lease_grant_v1(
            plan=plan,
            assignment=assignment,
            runner_session_id=f"session:{tag}:{ordinal}",
            runner_lease_token_sha256=_h(f"token:{tag}:{ordinal}"),
            journal_anchor_sha256=_h(f"journal:{tag}:{ordinal}"),
            verifier_epoch="full-v3-runner-lease",
            attestation_sha256=_h(f"lease:{tag}:{ordinal}"),
        )
        attempt = bank.open_next_attempt(plan.plan_id, assignment, lease)
        source_root = _h(f"source:{tag}:{ordinal}")
        target_root = _h(f"target:{tag}:{ordinal}")
        if assignment.arm_order == "AB":
            source_started, source_finished, target_started, target_finished = 1, 2, 3, 4
        else:
            target_started, target_finished, source_started, source_finished = 1, 2, 3, 4
        pair = make_pair_execution_receipt_v2(
            attempt=attempt,
            source_root_id=source_root,
            target_root_id=target_root,
            source_started_seq=source_started,
            source_finished_seq=source_finished,
            target_started_seq=target_started,
            target_finished_seq=target_finished,
            verifier_epoch="full-v3-pair-runner",
            attestation_sha256=_h(f"pair:{tag}:{ordinal}"),
        )

        def receipt(arm: str, outcome: DenseOutcome):
            return make_arm_receipt_v2(
                plan=plan,
                attempt=attempt,
                composition=(
                    edge.source_composition if arm == "source" else edge.target_composition
                ),
                transition=edge.transition,
                arm=arm,
                root_id=source_root if arm == "source" else target_root,
                paired_arm_root_id=target_root if arm == "source" else source_root,
                pair_execution_receipt=pair,
                runtime_profile_id=proof.runtime_profile.handle_id,
                materialization_event_id=proof.event.handle_id,
                activation_trace_root=_h(f"activation:{tag}:{ordinal}:{arm}"),
                usage=_usage(),
                execution_class="completed",
                outcome=outcome,
                producer_epoch="full-v3-receipt-host",
                attestation_sha256=_h(f"receipt:{tag}:{ordinal}:{arm}"),
            )

        before = _outcome(0.5)
        after = _outcome(0.6) if benefit else before
        bank.commit_attempt(
            attempt.attempt_id,
            receipt("source", before),
            receipt("target", after),
            pair,
        )
    return plan


def _install_base(bank: FactorBankV2, composition) -> None:
    receipt = BaseSnapshotReceiptV2(
        receipt_id="base:full-v3",
        deployment_slot_id=bank.deployment_slot_id(composition.namespace),
        namespace_digest=composition.namespace.digest,
        composition_id=composition.composition_id,
        loaded_artifact_sha256=composition.artifact_sha256,
        binding_map_sha256=_canonical_hash(sorted(composition.binding_map.items())),
        runtime_version=composition.namespace.runtime_version,
        verifier_epoch="full-v3-base",
        attestation_sha256=_h("full-v3-base-attestation"),
        emitted_seq=bank.to_state().event_seq + 1,
    )
    bank.register_base_snapshot(receipt)


def _accept_pending_gate(bank: FactorBankV2, plan, *, tag: str) -> None:
    opportunity = next(
        item
        for item in bank.to_state().gate_opportunities
        if item.plan_id == plan.plan_id and item.state == "pending"
    )
    assessment = bank.assessments[plan.plan_id]
    head = bank.deployment_heads[opportunity.deployment_slot_id]
    incumbent = next(
        item
        for item in bank.to_state().deployment_snapshots
        if item.snapshot_id == head.active_snapshot_id
    )
    bank.apply_gate(
        GateReceiptV2(
            decision_id=f"gate:{tag}",
            opportunity_id=opportunity.opportunity_id,
            deployment_slot_id=opportunity.deployment_slot_id,
            accepted=True,
            incumbent_snapshot_sha256=_canonical_hash(incumbent),
            candidate_snapshot_sha256=opportunity.candidate_snapshot_sha256,
            settled_assessment_sha256=assessment.digest,
            gate_config_sha256=_h(f"gate-config:{tag}"),
            aggregate_summary_sha256=_canonical_hash(assessment.strict_summary),
            verifier_epoch="full-v3-gate",
            verification_attestation_sha256=_h(f"gate-attestation:{tag}"),
            emitted_seq=bank.to_state().event_seq + 1,
        )
    )


def test_sequential_cross_locus_edge_is_gate_eligible_after_first_deploys() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    first_proof_handle = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="first mutation",
        tag="first",
    )
    bank = fixture.bank()
    first_edge = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=first_proof_handle,
    )
    _install_base(bank, first_edge.source_composition)
    first_proof = fixture.registry.resolve_proof(first_proof_handle)
    first_plan = _settle_candidate(bank, first_edge, first_proof, tag="first")
    _accept_pending_gate(bank, first_plan, tag="first")
    assert next(iter(bank.deployment_heads.values())).active_composition_id == (
        first_edge.target_composition.composition_id
    )

    second_proof_handle = fixture.mutate(
        first_proof.target_artifact,
        locator="/phases/0/pattern",
        value="star",
        tag="second",
    )
    second_edge = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=second_proof_handle,
    )
    assert second_edge.source_composition == first_edge.target_composition
    second_proof = fixture.registry.resolve_proof(second_proof_handle)
    second_plan = _settle_candidate(bank, second_edge, second_proof, tag="second")
    assert any(
        item.plan_id == second_plan.plan_id and item.state == "pending"
        for item in bank.to_state().gate_opportunities
    )


def test_full_verifier_rejects_omission_reordering_two_slots_and_cross_namespace() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    proof_handle = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="changed",
        tag="tamper",
    )
    bank = fixture.bank()
    edge = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=proof_handle,
    )
    verifier = make_phase_v3_binding_verifier(fixture.registry)
    background = tuple(
        bank.factors[revision_id]
        for slot, revision_id in sorted(edge.source_composition.binding_map.items())
        if slot != edge.transition.slot_id
    )
    assert verifier(
        edge.transition,
        edge.source_composition,
        edge.target_composition,
        edge.source_factor,
        edge.target_factor,
        background,
    )

    omitted = edge.source_composition.model_copy(
        update={"bindings": edge.source_composition.bindings[1:]}
    )
    reordered = edge.source_composition.model_copy(
        update={"bindings": tuple(reversed(edge.source_composition.bindings))}
    )
    second_slot = next(
        item.slot_id
        for item in edge.source_composition.bindings
        if item.slot_id not in {edge.transition.slot_id, PHASE_FULL_FACTOR_SKELETON_SLOT_ID}
    )
    two_changed = edge.target_composition.model_copy(
        update={
            "bindings": tuple(
                item.model_copy(update={"factor_revision_id": edge.target_factor.revision_id})
                if item.slot_id == second_slot
                else item
                for item in edge.target_composition.bindings
            )
        }
    )
    crossed_namespace = edge.source_composition.model_copy(
        update={
            "namespace": edge.source_composition.namespace.model_copy(
                update={"information_goal": "all_agents"}
            )
        }
    )
    structure_changed = edge.source_composition.model_copy(
        update={
            "bindings": tuple(
                item.model_copy(
                    update={"factor_revision_id": edge.target_factor.revision_id}
                )
                if item.slot_id == PHASE_FULL_FACTOR_SKELETON_SLOT_ID
                else item
                for item in edge.source_composition.bindings
            )
        }
    )
    for changed_source, changed_target in (
        (omitted, edge.target_composition),
        (reordered, edge.target_composition),
        (edge.source_composition, two_changed),
        (crossed_namespace, edge.target_composition),
        (structure_changed, edge.target_composition),
    ):
        assert not verifier(
            edge.transition,
            changed_source,
            changed_target,
            edge.source_factor,
            edge.target_factor,
            background,
        )


def test_optional_and_phase_kind_domains_are_enumerated_without_caller_choice() -> None:
    program = PhaseProgram.model_validate(
        {
            "information_goal": "sink",
            "phases": [
                {"kind": "gather"},
                {"kind": "consensus"},
            ],
        }
    )
    assert phase_mutable_factor_paths_v3(program) == (
        "/selected_primary",
        "/phases/0/instruction",
        "/phases/0/send_mode",
        "/phases/0/hub",
        "/phases/0/pattern",
        "/phases/1/instruction",
        "/phases/1/send_mode",
        "/phases/1/pattern",
        "/phases/1/max_rounds",
        "/phases/1/stop_when",
    )
    assert program.phases[0].instruction is None
    assert program.phases[1].instruction is None


def test_full_v3_profile_rejects_leaf_v2_adapter_and_cross_mode_profile() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    proof = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="changed",
        tag="v2-reject",
    )
    with pytest.raises(ValueError, match="non-v2"):
        register_phase_materialization_v2(
            registry=fixture.registry,
            bank=FactorBankV2(
                state_key=b"leaf-v2-rejection-bank-key" * 2,
                direct_binding_verifier=lambda *_args: True,
            ),
            proof=proof,
        )

    invalid = fixture.namespace.model_copy(update={"planner_mode": "graph_generate"})
    with pytest.raises(ValueError, match="program_generate|planner/worker contract"):
        fixture.registry.register_runtime_profile(
            namespace=invalid,
            limits=PhaseProgramLimits(),
        )


def test_maximum_phase_statement_domain_fits_full_factor_capacity() -> None:
    fixture = Fixture(n_agents=2)
    phases = [
        {
            "kind": "consensus",
            "pattern": "rotating",
            "max_rounds": 1,
            "stop_when": "fixed_rounds",
            "instruction": f"phase-{index}",
        }
        for index in range(12)
    ]
    program = _program(phases=phases)
    source = fixture.ingest(program)
    proof = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="changed-first-phase",
        tag="capacity",
    )
    bank = fixture.bank()
    edge = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    paths = phase_mutable_factor_paths_v3(program)
    assert len(paths) == 61
    assert len(edge.source_composition.bindings) == 62
    assert len(bank.factors) == 63
    assert edge.source_composition.canonical_metadata_bytes < (
        bank.to_state().capacity_policy.max_hot_metadata_bytes
    )


@pytest.mark.parametrize("branch", ["mutate", "fresh"])
def test_full_v3_generated_action_commits_replays_and_consumes_reservation(
    branch: str,
) -> None:
    fixture = Fixture()
    source = fixture.ingest()
    seed_proof = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="seed target",
        tag=f"seed:{branch}",
    )
    bank = fixture.bank()
    seed = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=seed_proof,
    )
    action = _prepare_action(
        fixture,
        bank=bank,
        source_edge=seed,
        branch=branch,
        tag=branch,
    )
    value = f"generated full-v3 {branch}"
    terminal = _generation_terminal(action, value=value, tag=branch)

    before_cross_version = bank.to_state()
    with pytest.raises(ValueError, match="exact Phase binder"):
        reconcile_phase_proposal_action_v2(
            registry=fixture.registry,
            bank=bank,
            action_id=action.action_id,
            generation_terminal=terminal,
            generated_value=value,
            ingress=fixture.ingress,
        )
    assert bank.to_state() == before_cross_version

    registered = reconcile_phase_proposal_action_v3(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value=value,
        ingress=fixture.ingress,
    )
    assert registered.transition.origin_branch == branch
    assert registered.transition.proposal_action_id == action.action_id
    assert registered.target_factor.parent_revision_id == (
        registered.source_factor.revision_id if branch == "mutate" else None
    )
    assert registered.target_composition.parent_composition_id == (
        registered.source_composition.composition_id
    )
    committed = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    assert committed.state == "committed"
    reservation = next(
        item
        for item in bank.to_state().proposal_carrier_reservations
        if item.action_id == action.action_id
    )
    admission = next(
        item
        for item in bank.to_state().proposal_carrier_admissions
        if item.transition_id == registered.transition.transition_id
    )
    assert reservation.state == "consumed"
    assert admission.state == "admitted"

    bank_after = bank.to_state()
    registry_after = fixture.registry.to_state()
    replay = reconcile_phase_proposal_action_v3(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value=value,
        ingress=fixture.ingress,
    )
    assert replay == registered
    assert bank.to_state() == bank_after
    assert fixture.registry.to_state() == registry_after


def test_full_v3_reuse_action_is_action_bound_and_cross_version_closed() -> None:
    fixture = Fixture()
    source_a = fixture.ingest()
    proof_ac = fixture.mutate(
        source_a,
        locator="/phases/0/instruction",
        value="candidate c",
        tag="reuse:ac",
    )
    source_d = fixture.ingest(
        _program(
            phases=[
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": "star",
                    "instruction": "source d",
                },
                {
                    "kind": "broadcast",
                    "hub": 0,
                    "pattern": "tree",
                    "instruction": "broadcast",
                },
            ]
        )
    )
    proof_db = fixture.mutate(
        source_d,
        locator="/phases/0/instruction",
        value="candidate b",
        tag="reuse:db",
    )
    bank = fixture.bank()
    edge_ac = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=proof_ac,
    )
    register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=proof_db,
    )
    python_alias = edge_ac.target_factor.model_copy(
        update={
            "revision_id": "factor:python-carrier-alias",
            "carrier": "python_source",
            "parent_revision_id": None,
            "origin_branch": "migration",
            "created_seq": bank.to_state().event_seq + 1,
        }
    )
    bank.add_factor(python_alias)
    action = _prepare_action(
        fixture,
        bank=bank,
        source_edge=edge_ac,
        branch="reuse",
        tag="reuse",
    )

    registered = reconcile_phase_proposal_action_v3(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
    )
    assert registered.transition.origin_branch == "reuse"
    assert registered.transition.proposal_action_id == action.action_id
    assert registered.target_factor.revision_id == action.selected_target_revision_id
    assert action.selected_target_revision_id != python_alias.revision_id
    assert registered.source_composition == edge_ac.source_composition
    committed = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    assert committed.state == "committed"
    assert committed.generation_terminal_sha256 is None
    assert not bank.to_state().proposal_carrier_reservations

    v3_terminal = make_phase_v3_proposal_action_terminal_verifier(fixture.registry)
    assert v3_terminal(committed, registered.transition, bank.to_state())
    assert not make_phase_v2_proposal_action_terminal_verifier(fixture.registry)(
        committed,
        registered.transition,
        bank.to_state(),
    )

    bank_after = bank.to_state()
    registry_after = fixture.registry.to_state()
    replay = reconcile_phase_proposal_action_v3(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
    )
    assert replay == registered
    assert bank.to_state() == bank_after
    assert fixture.registry.to_state() == registry_after


def test_full_v3_noop_abort_releases_generated_carrier_reservation() -> None:
    fixture = Fixture()
    source = fixture.ingest()
    seed_proof = fixture.mutate(
        source,
        locator="/phases/0/instruction",
        value="seed target",
        tag="noop:seed",
    )
    bank = fixture.bank()
    seed = register_phase_materialization_v3(
        registry=fixture.registry,
        bank=bank,
        proof=seed_proof,
    )
    action = _prepare_action(
        fixture,
        bank=bank,
        source_edge=seed,
        branch="mutate",
        tag="noop",
    )
    terminal = _generation_terminal(action, value="gather", tag="noop")
    result = reconcile_phase_proposal_action_v3(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value="gather",
        ingress=fixture.ingress,
    )
    assert isinstance(result, NoOpMaterialization)
    event = fixture.registry.resolve_event(result.event)
    terminal_sha256 = phase_materialization_event_sha256_v1(event)
    current = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    receipt = make_proposal_action_abort_receipt_v2(
        action=current,
        reason="phase_noop",
        phase_terminal_sha256=terminal_sha256,
        safe_failure_code="phase_noop",
        verifier_epoch="full-v3-proposal-abort",
        attestation_sha256=_h("full-v3-noop-abort"),
    )
    replay = reconcile_phase_proposal_action_v3(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value="gather",
        ingress=fixture.ingress,
        noop_abort_receipt=receipt,
    )
    assert replay == result
    aborted = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    reservation = next(
        item
        for item in bank.to_state().proposal_carrier_reservations
        if item.action_id == action.action_id
    )
    assert aborted.state == "aborted"
    assert reservation.state == "released"
    assert not any(
        item.proposal_action_id == action.action_id
        for item in bank.to_state().direct_transitions
    )
