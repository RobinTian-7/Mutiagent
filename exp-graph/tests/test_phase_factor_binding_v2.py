from __future__ import annotations

import hashlib
import hmac
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
    make_assignment_receipt_v2,
    make_pair_execution_receipt_v2,
    make_proposal_action_abort_receipt_v2,
    make_proposal_generation_context_v1,
    make_proposal_generation_lease_v1,
    make_runner_lease_grant_v1,
)
from exp_graph.mas.phase_artifact_registry import (
    PHASE_FACTOR_BINDER_VERSION,
    NoOpMaterialization,
    PhaseArtifactRegistry,
    PhaseBindingProofHandle,
    PhaseGenerationTerminalV1,
    SourceManifest,
    phase_generated_scalar_sha256,
    phase_materialization_event_sha256_v1,
)
from exp_graph.mas.phase_factor_binding_v2 import (
    AbortedPhaseProposalActionV2,
    make_phase_v2_arm_receipt_verifier,
    make_phase_v2_binding_verifier,
    make_phase_v2_proposal_action_terminal_verifier,
    make_phase_v2_repair_opportunity_verifier,
    make_registered_phase_arm_receipt_v2,
    reconcile_phase_proposal_action_v2,
    reconcile_phase_reuse_proposal_action_v1,
    register_phase_materialization_v2,
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


def _host_proposal_input(bank, *, request, cursor, candidates):
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


_RUNNER_KEY = b"phase-v2-test-runner-attestation-key"


def _runner_mac(receipt, proof) -> str:
    body = receipt.model_dump(mode="json", exclude={"attestation_sha256"})
    payload = json.dumps(
        {"receipt": body, "proof": proof.handle.proof_sha256},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(_RUNNER_KEY, payload, hashlib.sha256).hexdigest()


def _trusted_runner_verifier(receipt, proof) -> bool:
    return hmac.compare_digest(receipt.attestation_sha256, _runner_mac(receipt, proof))


def _program(instruction: str, *, pattern: str = "tree") -> PhaseProgram:
    return PhaseProgram.model_validate(
        {
            "format": "phase_program_v1",
            "information_goal": "sink",
            "selected_primary": 0,
            "phases": [
                {
                    "kind": "gather",
                    "hub": 0,
                    "pattern": pattern,
                    "instruction": instruction,
                }
            ],
        }
    )


class Fixture:
    def __init__(self) -> None:
        self.manifest = SourceManifest(
            manifest_sha256=_h("train-manifest-v2"),
            split="TRAIN_UPDATE",
            source_catalog_sha256=_h("catalog-v2"),
            policy_sha256=_h("policy-v2"),
            producer_version="test-host-v2",
        )
        self.registry = PhaseArtifactRegistry(
            registry_key=b"phase-binding-v2-registry-key" * 2,
            manifests=(self.manifest,),
            manifest_verifier=lambda candidate: candidate == self.manifest,
            branch_receipt_verifier=lambda _receipt: True,
        )
        self.namespace = ExecutionNamespace(
            task_family="synthetic_count",
            objective="balanced",
            information_goal="sink",
            planner_mode="program_generate",
            payload_format="phase_program_skill_v1",
            worker_contract="not_applicable",
            n_agents=4,
            array_size_bucket="small",
            budget_level="normal",
            model_name="gpt-4o-mini",
            runtime_version="shadow-runtime-v2",
            binder_version=PHASE_FACTOR_BINDER_VERSION,
            compiler_version="1",
        )
        self.profile = self.registry.register_runtime_profile(
            namespace=self.namespace,
            limits=PhaseProgramLimits(),
        )
        self.ingress = self.registry.issue_ingress(self.manifest.manifest_sha256)

    def mutation(
        self,
        *,
        source_artifact=None,
        target: str,
        receipt: str,
    ) -> PhaseBindingProofHandle:
        if source_artifact is None:
            source_artifact = self.registry.ingest_program(
                _program("a"),
                runtime_profile=self.profile,
                ingress=self.ingress,
            )
        extracted = self.registry.extract_factor(
            source_artifact, locator="/phases/0/instruction"
        )
        branch_receipt = self.registry.register_branch_receipt(
            branch="mutate",
            source_artifact=source_artifact,
            locator="/phases/0/instruction",
            mutation_parent_factor=extracted.factor,
            additional_input_root_commitments=(_h(f"input-root:{receipt}"),),
            producer_epoch="branch-host:phase-v2",
            attestation_sha256=_h(f"branch-attestation:{receipt}"),
        )
        seal = self.registry.seal_operation(branch_receipt=branch_receipt)
        generated = self.registry.register_generated_value(
            target,
            operation_seal=seal,
            ingress=self.ingress,
        )
        proof = self.registry.materialize(
            operation_seal=seal,
            target_factor=generated.factor,
        )
        assert isinstance(proof, PhaseBindingProofHandle)
        return proof

    def bank(
        self,
        *,
        accept_bundle: bool = True,
        with_probe_capabilities: bool = False,
    ) -> FactorBankV2:
        verifier = (
            make_phase_v2_binding_verifier(self.registry)
            if accept_bundle
            else lambda *_args: False
        )
        capabilities = {}
        if with_probe_capabilities:
            capabilities = {
                "plan_verifier": lambda _plan: True,
                "assignment_verifier": lambda _receipt, _plan: True,
                "runner_lease_verifier": lambda _lease, _assignment, _plan: True,
                "arm_receipt_verifier": make_phase_v2_arm_receipt_verifier(
                    self.registry,
                    trusted_runner_verifier=_trusted_runner_verifier,
                ),
                "pair_execution_receipt_verifier": lambda *_args: True,
            }
        capabilities["base_snapshot_verifier"] = lambda _receipt, _state: True
        return FactorBankV2(
            state_key=b"phase-binding-v2-bank-key" * 2,
            direct_binding_verifier=verifier,
            proposal_action_terminal_verifier=(
                make_phase_v2_proposal_action_terminal_verifier(
                    self.registry
                )
            ),
            repair_opportunity_verifier=(
                make_phase_v2_repair_opportunity_verifier(self.registry)
            ),
            proposal_abort_verifier=lambda *_args: True,
            proposal_generation_context_verifier=lambda *_args: True,
            proposal_generation_lease_verifier=lambda *_args: True,
            **capabilities,
        )


def _authorize_phase_source(bank: FactorBankV2, composition) -> None:
    state = bank.to_state()
    admitted_transition_ids = {
        item.transition_id
        for item in state.proposal_carrier_admissions
        if item.state == "admitted"
    }
    if any(
        item.transition_id in admitted_transition_ids
        and item.target_composition_id == composition.composition_id
        for item in state.direct_transitions
    ):
        return
    if any(
        item.composition_id == composition.composition_id
        for item in state.base_receipts
    ):
        return
    bank.register_base_snapshot(
        BaseSnapshotReceiptV2(
            receipt_id=f"base:{composition.composition_id}",
            deployment_slot_id=bank.deployment_slot_id(composition.namespace),
            namespace_digest=composition.namespace.digest,
            composition_id=composition.composition_id,
            loaded_artifact_sha256=composition.artifact_sha256,
            binding_map_sha256=_canonical_hash(
                sorted(composition.binding_map.items())
            ),
            runtime_version=composition.namespace.runtime_version,
            verifier_epoch="base-verifier:phase-v3",
            attestation_sha256=_h(
                f"base-attestation:{composition.composition_id}"
            ),
            emitted_seq=bank.to_state().event_seq + 1,
        )
    )


def _register_phase_storage_alias(
    bank: FactorBankV2,
    edge,
    *,
    namespace: ExecutionNamespace,
    tag: str,
):
    factor_id_map: dict[str, str] = {}
    for index, original in enumerate(
        (edge.background_factor, edge.source_factor),
        start=1,
    ):
        alias_id = f"alias-factor:{tag}:{index}"
        factor_id_map[original.revision_id] = alias_id
        bank.add_factor(
            original.model_copy(
                update={
                    "revision_id": alias_id,
                    "logical_factor_id": f"alias-logical:{tag}:{index}",
                    "namespace": namespace,
                    "parent_revision_id": None,
                    "origin_branch": "migration",
                    "created_seq": bank.to_state().event_seq + 1,
                }
            )
        )
    alias = edge.source_composition.model_copy(
        update={
            "composition_id": f"alias-composition:{tag}",
            "namespace": namespace,
            "bindings": tuple(
                binding.model_copy(
                    update={
                        "factor_revision_id": factor_id_map[
                            binding.factor_revision_id
                        ]
                    }
                )
                for binding in edge.source_composition.bindings
            ),
            "parent_composition_id": None,
            "origin_branch": "migration",
            "created_seq": bank.to_state().event_seq + 1,
        }
    )
    bank.add_composition(alias)
    return alias


def _prepare_generated_phase_action(
    fixture: Fixture,
    *,
    bank: FactorBankV2,
    source_edge,
    branch: str,
    tag: str,
):
    _authorize_phase_source(bank, source_edge.source_composition)
    observation = FailureObservationV2(
        failure_id=f"failure:phase-generated:{tag}",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=source_edge.source_composition.composition_id,
        artifact_sha256=source_edge.source_composition.artifact_sha256,
        created_seq=bank.to_state().event_seq + 1,
    )
    opportunity = bank.record_failure(
        observation,
        feasible_branches=(branch,),
    )
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
        canonical_background_sha256=(
            bank._canonical_direct_background_sha256(
                bank.to_state(),
                source=source_edge.source_composition,
                source_factor=source_edge.source_factor,
                slot_id=locus.slot_id,
            )
        ),
    )
    candidate_slate, _universe_sha256, _universe_count = (
        bank._proposal_candidate_slate(
            opportunity=opportunity,
            source_factor=source_edge.source_factor,
            slot_id=locus.slot_id,
        )
    )
    proposal = select_exact_edge_proposal(
        _host_proposal_input(
            bank,
            request=ProposalRequestV1(
                opportunity_id=opportunity.opportunity_id,
                cell=cell,
            ),
            cursor=ProposalCursorV1.empty(cell),
            candidates=candidate_slate,
        )
    )
    budget = ExecutionBudget(
        max_messages=1,
        max_model_calls=1,
        max_input_tokens=1024,
        max_output_tokens=64,
        max_wall_time_ms=30_000,
        max_cost_microusd=1_000,
    )
    context = make_proposal_generation_context_v1(
        opportunity=opportunity,
        failure=observation,
        proposal_receipt=proposal,
        source=source_edge.source_composition,
        source_factor=source_edge.source_factor,
        source_manifest_sha256=fixture.manifest.manifest_sha256,
        train_update_source_catalog_sha256=(
            fixture.manifest.source_catalog_sha256
        ),
        train_update_policy_sha256=fixture.manifest.policy_sha256,
        generation_policy_sha256=_h(f"generation-policy:{tag}"),
        prompt_template_sha256=_h(f"prompt-template:{tag}"),
        scalar_output_schema_sha256=_h(f"scalar-schema:{tag}"),
        budget=budget,
        verifier_epoch="generation-context-verifier:phase-v3",
        attestation_sha256=_h(f"generation-context-attestation:{tag}"),
    )
    _decision, assignment, prepared = bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:phase-v3",
        attestation_sha256=_h(f"proposal-action-attestation:{tag}"),
        generation_context=context,
    )
    assert assignment is not None and assignment.branch == branch
    assert prepared is not None and prepared.state == "prepared"
    lease = make_proposal_generation_lease_v1(
        action=prepared,
        runner_session_id=f"generation-runner:{tag}",
        runner_lease_token_sha256=_h(f"generation-lease-token:{tag}"),
        journal_anchor_sha256=_h(f"generation-journal:{tag}"),
        verifier_epoch="generation-lease-verifier:phase-v3",
        attestation_sha256=_h(f"generation-lease-attestation:{tag}"),
    )
    return bank.begin_proposal_generation(prepared.action_id, lease)


def _phase_generation_terminal(action, *, value, tag: str) -> PhaseGenerationTerminalV1:
    request = action.generation_request
    lease = action.generation_lease
    assert request is not None and lease is not None and lease.started_seq is not None
    usage = ExecutionUsage(
        messages=1,
        model_calls=1,
        input_tokens=100,
        output_tokens=8,
        wall_time_ms=500,
        cost_microusd=20,
    )
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
        usage=usage,
        generated_scalar_sha256=phase_generated_scalar_sha256(value),
        response_envelope_sha256=_h(f"generation-response:{tag}"),
        terminal_event_id=f"generation-event:{tag}",
        terminal_event_sequence=lease.started_seq + 1,
        verifier_epoch="generation-terminal-verifier:phase-v3",
        attestation_sha256=_h(f"generation-terminal-attestation:{tag}"),
    )


def test_registry_proof_projects_one_complete_canonical_v2_edge() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:ab")
    bank = fixture.bank()

    result = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )

    assert result.transition.origin_branch == "mutate"
    assert result.transition.binding_proof_id == proof.handle_id
    assert result.source_composition.binding_map["fixed_background"] == (
        result.background_factor.revision_id
    )
    assert result.target_composition.binding_map["fixed_background"] == (
        result.background_factor.revision_id
    )
    assert result.source_composition.binding_map[result.transition.slot_id] == (
        result.source_factor.revision_id
    )
    assert result.target_composition.binding_map[result.transition.slot_id] == (
        result.target_factor.revision_id
    )
    assert bank.to_state().attempts == ()
    assert bank.to_state().assessments == ()

    # A proof registered outside a proposal action is authority for an
    # unowned edge only.  Caller-supplied action fields cannot relabel it.
    verifier = make_phase_v2_binding_verifier(fixture.registry)
    forged_action_owner = result.transition.model_copy(
        update={
            "proposal_action_id": "ptx:forged-phase-owner",
            "proposal_action_intent_sha256": _h("forged-phase-intent"),
        }
    )
    assert not verifier(
        forged_action_owner,
        result.source_composition,
        result.target_composition,
        result.source_factor,
        result.target_factor,
        (result.background_factor,),
    )


def test_registry_proof_projection_is_idempotent_after_crash_retry() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:idempotent")
    bank = fixture.bank()

    first = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    after_first = bank.to_state()
    replay = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )

    assert replay == first
    assert bank.to_state() == after_first


def test_prepared_proposal_reuse_saga_commits_phase_once_and_local_edge_at_zero() -> None:
    fixture = Fixture()
    source_a = fixture.registry.ingest_program(
        _program("a"),
        runtime_profile=fixture.profile,
        ingress=fixture.ingress,
    )
    proof_ac = fixture.mutation(
        source_artifact=source_a,
        target="c",
        receipt="generation:ac",
    )
    source_d = fixture.registry.ingest_program(
        _program("d", pattern="star"),
        runtime_profile=fixture.profile,
        ingress=fixture.ingress,
    )
    proof_db = fixture.mutation(
        source_artifact=source_d,
        target="b",
        receipt="generation:db",
    )
    bank = fixture.bank()
    edge_ac = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof_ac,
    )
    edge_db = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof_db,
    )
    _authorize_phase_source(bank, edge_ac.source_composition)
    observation = FailureObservationV2(
        failure_id="failure:phase-proposal",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=edge_ac.source_composition.composition_id,
        artifact_sha256=edge_ac.source_composition.artifact_sha256,
        created_seq=bank.to_state().event_seq + 1,
    )
    opportunity = bank.record_failure(
        observation,
        feasible_branches=("reuse",),
    )
    assert opportunity is not None
    locus = ExactFactorLocusV1(
        carrier="phase_program",
        slot_id=edge_ac.transition.slot_id,
        logical_factor_id=edge_ac.source_factor.logical_factor_id,
        locator_surface="phase_field",
        locator_path=edge_ac.source_factor.locator.path,
        locator_version=edge_ac.source_factor.locator.locator_version,
    )
    cell = ExactProposalCellV1(
        namespace=fixture.namespace,
        locus=locus,
        from_revision_id=edge_ac.source_factor.revision_id,
        canonical_from_factor_key_sha256=(
            bank._factor_carrier_key_sha256(edge_ac.source_factor)
        ),
        canonical_background_sha256=(
            bank._canonical_direct_background_sha256(
                bank.to_state(),
                source=edge_ac.source_composition,
                source_factor=edge_ac.source_factor,
                slot_id=locus.slot_id,
            )
        ),
    )
    candidate_slate, _universe_sha256, _universe_count = (
        bank._proposal_candidate_slate(
            opportunity=opportunity,
            source_factor=edge_ac.source_factor,
            slot_id=locus.slot_id,
        )
    )
    proposal = select_exact_edge_proposal(
        _host_proposal_input(
            bank,
            request=ProposalRequestV1(
                opportunity_id=opportunity.opportunity_id,
                cell=cell,
            ),
            cursor=ProposalCursorV1.empty(cell),
            candidates=candidate_slate,
        )
    )
    _decision, assignment, action = bank.screen_and_allocate_branch(
        opportunity.opportunity_id,
        proposal,
        producer_epoch="proposal-host:phase",
        attestation_sha256=_h("proposal-phase-attestation"),
    )
    assert assignment is not None and assignment.branch == "reuse"
    assert action is not None and action.state == "prepared"

    registered = reconcile_phase_reuse_proposal_action_v1(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
    )
    assert not isinstance(registered, tuple)
    assert registered.transition.origin_branch == "reuse"
    committed = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    assert committed.state == "committed"
    assert committed.transition_id == registered.transition.transition_id
    assert not any(
        item.transition_id == registered.transition.transition_id
        for item in bank.to_state().assessments
    )

    # Conversely, an action-bound Phase proof cannot be stripped of its
    # transaction/intent pair and replayed as an ordinary unowned edge.
    verifier = make_phase_v2_binding_verifier(fixture.registry)
    forged_unowned = registered.transition.model_copy(
        update={
            "proposal_action_id": None,
            "proposal_action_intent_sha256": None,
        }
    )
    assert not verifier(
        forged_unowned,
        registered.source_composition,
        registered.target_composition,
        registered.source_factor,
        registered.target_factor,
        (registered.background_factor,),
    )

    bank_after = bank.to_state()
    registry_after = fixture.registry.to_state()
    replay = reconcile_phase_reuse_proposal_action_v1(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
    )
    assert replay == registered
    assert bank.to_state() == bank_after
    assert fixture.registry.to_state() == registry_after
    reloaded = FactorBankV2(
        bank.to_state(),
        state_key=b"phase-binding-v2-bank-key" * 2,
        direct_binding_verifier=make_phase_v2_binding_verifier(
            fixture.registry
        ),
        proposal_action_terminal_verifier=(
            make_phase_v2_proposal_action_terminal_verifier(
                fixture.registry
            )
        ),
        repair_opportunity_verifier=(
            make_phase_v2_repair_opportunity_verifier(fixture.registry)
        ),
        base_snapshot_verifier=lambda *_args: True,
    )
    assert reloaded.scientific_state_sha256 == bank.scientific_state_sha256


@pytest.mark.parametrize("branch", ["mutate", "fresh"])
def test_generated_phase_action_commits_exact_dynamic_closure_and_replays(
    branch: str,
) -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt=f"generation:seed:{branch}")
    bank = fixture.bank()
    source_edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    action = _prepare_generated_phase_action(
        fixture,
        bank=bank,
        source_edge=source_edge,
        branch=branch,
        tag=branch,
    )
    value = f"generated-{branch}"
    terminal = _phase_generation_terminal(action, value=value, tag=branch)

    registered = reconcile_phase_proposal_action_v2(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value=value,
        ingress=fixture.ingress,
    )

    assert not isinstance(
        registered,
        (NoOpMaterialization, AbortedPhaseProposalActionV2),
    )
    assert registered.transition.origin_branch == branch
    assert registered.target_factor.parent_revision_id == (
        registered.source_factor.revision_id if branch == "mutate" else None
    )
    assert (
        registered.target_composition.parent_composition_id
        == registered.source_composition.composition_id
    )
    committed = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    assert committed.state == "committed"
    assert committed.generation_terminal_sha256 == terminal.digest
    receipt = next(
        item
        for item in fixture.registry.to_state().branch_receipts
        if item.body.action_transaction_id == action.action_id
    )
    assert set(action.exact_additional_input_root_commitments).issubset(
        receipt.body.input_root_commitments
    )
    assert {
        action.generation_request.digest,
        action.generation_lease.digest,
        terminal.digest,
    }.issubset(receipt.body.input_root_commitments)
    assert receipt.body.dependency_factor_ids == (
        (action.from_revision_id,) if branch == "mutate" else ()
    )

    bank_after = bank.to_state()
    registry_after = fixture.registry.to_state()
    replay = reconcile_phase_proposal_action_v2(
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

    terminal_verifier = make_phase_v2_proposal_action_terminal_verifier(
        fixture.registry
    )
    forged_terminal_owner = committed.model_copy(
        update={"generation_terminal_sha256": _h(f"forged:{branch}")}
    )
    assert not terminal_verifier(
        forged_terminal_owner,
        registered.transition,
        bank.to_state(),
    )


def test_admitted_generated_target_can_be_exact_source_of_next_action() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:seed:chain")
    bank = fixture.bank()
    seed = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    first_action = _prepare_generated_phase_action(
        fixture,
        bank=bank,
        source_edge=seed,
        branch="mutate",
        tag="chain:first",
    )
    first_terminal = _phase_generation_terminal(
        first_action,
        value="chain-first",
        tag="chain:first",
    )
    first = reconcile_phase_proposal_action_v2(
        registry=fixture.registry,
        bank=bank,
        action_id=first_action.action_id,
        generation_terminal=first_terminal,
        generated_value="chain-first",
        ingress=fixture.ingress,
    )
    assert not isinstance(
        first,
        (NoOpMaterialization, AbortedPhaseProposalActionV2),
    )
    next_source = first.model_copy(
        update={
            "source_factor": first.target_factor,
            "source_composition": first.target_composition,
        }
    )
    second_action = _prepare_generated_phase_action(
        fixture,
        bank=bank,
        source_edge=next_source,
        branch="mutate",
        tag="chain:second",
    )
    second_terminal = _phase_generation_terminal(
        second_action,
        value="chain-second",
        tag="chain:second",
    )
    second = reconcile_phase_proposal_action_v2(
        registry=fixture.registry,
        bank=bank,
        action_id=second_action.action_id,
        generation_terminal=second_terminal,
        generated_value="chain-second",
        ingress=fixture.ingress,
    )
    assert not isinstance(
        second,
        (NoOpMaterialization, AbortedPhaseProposalActionV2),
    )
    assert second.source_factor == first.target_factor
    assert second.target_factor.parent_revision_id == first.target_factor.revision_id
    assert second.source_composition == first.target_composition


def test_generated_noop_uses_public_terminal_digest_and_typed_abort() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:seed:noop")
    bank = fixture.bank()
    source_edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    action = _prepare_generated_phase_action(
        fixture,
        bank=bank,
        source_edge=source_edge,
        branch="mutate",
        tag="noop",
    )
    terminal = _phase_generation_terminal(action, value="a", tag="noop")
    result = reconcile_phase_proposal_action_v2(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value="a",
        ingress=fixture.ingress,
    )
    assert isinstance(result, NoOpMaterialization)
    event = fixture.registry.resolve_event(result.event)
    public_terminal_sha256 = phase_materialization_event_sha256_v1(event)
    assert public_terminal_sha256 != _canonical_hash(event)

    current = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    wrong_receipt = make_proposal_action_abort_receipt_v2(
        action=current,
        reason="phase_noop",
        phase_terminal_sha256=_canonical_hash(event),
        safe_failure_code="phase_noop",
        verifier_epoch="proposal-abort-verifier:phase-v3",
        attestation_sha256=_h("proposal-noop-abort:wrong"),
    )
    before_wrong = bank.to_state()
    with pytest.raises(ValueError, match="does not join its Phase terminal"):
        reconcile_phase_proposal_action_v2(
            registry=fixture.registry,
            bank=bank,
            action_id=action.action_id,
            generation_terminal=terminal,
            generated_value="a",
            ingress=fixture.ingress,
            noop_abort_receipt=wrong_receipt,
        )
    assert bank.to_state() == before_wrong

    receipt = make_proposal_action_abort_receipt_v2(
        action=current,
        reason="phase_noop",
        phase_terminal_sha256=public_terminal_sha256,
        safe_failure_code="phase_noop",
        verifier_epoch="proposal-abort-verifier:phase-v3",
        attestation_sha256=_h("proposal-noop-abort:exact"),
    )
    replay = reconcile_phase_proposal_action_v2(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value="a",
        ingress=fixture.ingress,
        noop_abort_receipt=receipt,
    )
    assert replay == result
    aborted = next(
        item
        for item in bank.to_state().proposal_actions
        if item.action_id == action.action_id
    )
    assert aborted.state == "aborted"
    assert not any(
        item.proposal_action_id == action.action_id
        for item in bank.to_state().direct_transitions
    )


def test_generated_terminal_rejection_cleans_only_its_staged_edge() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:seed:rejected")
    bank = fixture.bank()
    source_edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    action = _prepare_generated_phase_action(
        fixture,
        bank=bank,
        source_edge=source_edge,
        branch="mutate",
        tag="rejected",
    )
    value = "generated-rejected"
    terminal = _phase_generation_terminal(action, value=value, tag="rejected")
    registry_state = fixture.registry.to_state()
    source_record = next(
        item
        for item in registry_state.artifacts
        if item.handle.handle_id == action.source_artifact_id
    )
    parent_record = next(
        item
        for item in registry_state.factors
        if item.handle.handle_id == action.from_revision_id
    )
    roots = tuple(
        sorted(
            {
                *action.exact_additional_input_root_commitments,
                action.generation_request.digest,
                action.generation_lease.digest,
                terminal.digest,
            }
        )
    )
    phase_result = fixture.registry.materialize_action_idempotent(
        action_transaction_id=action.action_id,
        action_intent_sha256=action.action_intent_sha256,
        branch="mutate",
        source_artifact=source_record.handle,
        locator=action.locator_path,
        dependency_factor=parent_record.handle,
        exact_additional_input_root_commitments=roots,
        producer_epoch=action.producer_epoch,
        attestation_sha256=action.attestation_sha256,
        generation_terminal=terminal,
        generated_value=value,
        ingress=fixture.ingress,
    )
    assert isinstance(phase_result, PhaseBindingProofHandle)
    staged = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=phase_result,
    )
    admission = next(
        item
        for item in bank.to_state().proposal_carrier_admissions
        if item.transition_id == staged.transition.transition_id
    )
    assert admission.state == "staged"
    rejection = make_proposal_action_abort_receipt_v2(
        action=action,
        reason="generation_terminal_rejected",
        phase_terminal_sha256=phase_result.proof_sha256,
        cleanup_transition=staged.transition,
        cleanup_admission=admission,
        safe_failure_code="generation_terminal_rejected",
        verifier_epoch="proposal-abort-verifier:phase-v3",
        attestation_sha256=_h("proposal-terminal-rejection:exact"),
    )

    result = reconcile_phase_proposal_action_v2(
        registry=fixture.registry,
        bank=bank,
        action_id=action.action_id,
        generation_terminal=terminal,
        generated_value=value,
        ingress=fixture.ingress,
        terminal_abort_receipt=rejection,
    )

    assert isinstance(result, AbortedPhaseProposalActionV2)
    assert result.action.state == "aborted"
    assert result.phase_terminal_sha256 == phase_result.proof_sha256
    assert staged.transition.transition_id not in bank.direct_transitions
    quarantined = next(
        item
        for item in bank.to_state().proposal_carrier_admissions
        if item.admission_id == admission.admission_id
    )
    assert quarantined.state == "quarantined"


def test_repair_opportunity_exposes_only_canonical_host_supported_branches() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:seed:support")
    bank = fixture.bank()
    edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    _authorize_phase_source(bank, edge.source_composition)
    failure = FailureObservationV2(
        failure_id="failure:phase-branch-support",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=edge.source_composition.composition_id,
        artifact_sha256=edge.source_composition.artifact_sha256,
        created_seq=bank.to_state().event_seq + 1,
    )
    opportunity = bank.record_failure(
        failure,
        feasible_branches=("reuse", "fresh"),
    )
    assert opportunity is not None
    verifier = make_phase_v2_repair_opportunity_verifier(
        fixture.registry,
        supported_branches=("reuse", "fresh"),
    )
    assert verifier(opportunity, failure, edge.source_composition)
    assert not verifier(
        opportunity.model_copy(update={"feasible_branches": ("fresh", "reuse")}),
        failure,
        edge.source_composition,
    )
    with pytest.raises(ValueError, match="canonical"):
        make_phase_v2_repair_opportunity_verifier(
            fixture.registry,
            supported_branches=("fresh", "reuse"),
        )


@pytest.mark.parametrize(
    ("namespace_update", "tag"),
    [
        ({"information_goal": "all_agents"}, "all-agents"),
        ({"model_name": "profile-alias-model"}, "model"),
        ({"budget_level": "tight"}, "budget"),
        ({"runtime_version": "profile-alias-runtime"}, "runtime"),
    ],
)
def test_repair_authority_rejects_registry_artifact_under_profile_alias(
    namespace_update: dict[str, str],
    tag: str,
) -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt=f"generation:alias:{tag}")
    bank = fixture.bank()
    edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    alias_namespace = ExecutionNamespace.model_validate(
        fixture.namespace.model_copy(update=namespace_update).model_dump(mode="python")
    )
    alias = _register_phase_storage_alias(
        bank,
        edge,
        namespace=alias_namespace,
        tag=tag,
    )
    # The storage rows and base receipt are individually valid Bank records, but
    # the registry artifact belongs to fixture.profile, not this alias profile.
    _authorize_phase_source(bank, alias)
    before = bank.to_state()
    failure = FailureObservationV2(
        failure_id=f"failure:profile-alias:{tag}",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=alias.composition_id,
        artifact_sha256=alias.artifact_sha256,
        created_seq=before.event_seq + 1,
    )

    with pytest.raises(ValueError, match="repair-opportunity verifier rejected"):
        bank.record_failure(failure, feasible_branches=("fresh",))

    assert bank.to_state() == before


def test_repair_authority_rejects_same_namespace_factor_and_composition_alias() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:storage-alias")
    bank = fixture.bank()
    edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    alias = _register_phase_storage_alias(
        bank,
        edge,
        namespace=fixture.namespace,
        tag="same-namespace",
    )
    _authorize_phase_source(bank, alias)
    before = bank.to_state()
    failure = FailureObservationV2(
        failure_id="failure:same-namespace-storage-alias",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=alias.composition_id,
        artifact_sha256=alias.artifact_sha256,
        created_seq=before.event_seq + 1,
    )

    with pytest.raises(ValueError, match="repair-opportunity verifier rejected"):
        bank.record_failure(failure, feasible_branches=("fresh",))

    assert bank.to_state() == before


def test_repair_verifier_closes_artifact_image_handle_and_complete_bindings() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:exact-authority")
    bank = fixture.bank()
    edge = register_phase_materialization_v2(
        registry=fixture.registry,
        bank=bank,
        proof=proof,
    )
    _authorize_phase_source(bank, edge.source_composition)
    failure = FailureObservationV2(
        failure_id="failure:exact-authority",
        failure_class="algorithm",
        failed_stage="execute",
        safe_failure_code="algorithm_failure",
        composition_id=edge.source_composition.composition_id,
        artifact_sha256=edge.source_composition.artifact_sha256,
        created_seq=bank.to_state().event_seq + 1,
    )
    opportunity = bank.record_failure(failure, feasible_branches=("fresh",))
    assert opportunity is not None
    verifier = make_phase_v2_repair_opportunity_verifier(fixture.registry)
    assert verifier(opportunity, failure, edge.source_composition)

    target_failure = failure.model_copy(
        update={
            "composition_id": edge.target_composition.composition_id,
            "artifact_sha256": edge.target_composition.artifact_sha256,
        }
    )
    target_opportunity = opportunity.model_copy(
        update={"source_composition_id": edge.target_composition.composition_id}
    )
    assert verifier(target_opportunity, target_failure, edge.target_composition)

    proof_record = fixture.registry.resolve_proof(proof)
    target_artifact = fixture.registry.resolve_artifact(proof_record.target_artifact)
    forged_image = edge.source_composition.model_copy(
        update={"artifact_sha256": _h("forged-execution-image")}
    )
    swapped_handle = edge.source_composition.model_copy(
        update={
            "artifact_revision_id": target_artifact.handle.handle_id,
            "artifact_sha256": target_artifact.execution_image_commitment,
        }
    )
    aliased_identity = edge.source_composition.model_copy(
        update={"composition_id": "pc:storage-alias"}
    )
    aliased_bindings = edge.source_composition.model_copy(
        update={
            "bindings": tuple(
                binding.model_copy(
                    update={
                        "factor_revision_id": (
                            edge.target_factor.revision_id
                            if binding.slot_id == edge.transition.slot_id
                            else binding.factor_revision_id
                        )
                    }
                )
                for binding in edge.source_composition.bindings
            )
        }
    )
    for forged in (
        forged_image,
        swapped_handle,
        aliased_identity,
        aliased_bindings,
    ):
        forged_failure = failure.model_copy(
            update={
                "composition_id": forged.composition_id,
                "artifact_sha256": forged.artifact_sha256,
            }
        )
        forged_opportunity = opportunity.model_copy(
            update={
                "source_composition_id": forged.composition_id,
                "namespace_digest": forged.namespace.digest,
            }
        )
        assert not verifier(forged_opportunity, forged_failure, forged)


def test_a_b_c_keeps_b_factor_and_complete_composition_identity() -> None:
    fixture = Fixture()
    proof_ab = fixture.mutation(target="b", receipt="generation:ab")
    record_ab = fixture.registry.resolve_proof(proof_ab)
    proof_bc = fixture.mutation(
        source_artifact=record_ab.target_artifact,
        target="c",
        receipt="generation:bc",
    )
    bank = fixture.bank()

    edge_ab = register_phase_materialization_v2(
        registry=fixture.registry, bank=bank, proof=proof_ab
    )
    edge_bc = register_phase_materialization_v2(
        registry=fixture.registry, bank=bank, proof=proof_bc
    )

    assert edge_ab.target_factor.revision_id == edge_bc.source_factor.revision_id
    assert edge_ab.target_composition.composition_id == (
        edge_bc.source_composition.composition_id
    )
    assert edge_ab.background_factor.revision_id == edge_bc.background_factor.revision_id


def test_full_bundle_verifier_rejects_forged_background_and_composition() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:ab")
    bank = fixture.bank()
    edge = register_phase_materialization_v2(
        registry=fixture.registry, bank=bank, proof=proof
    )
    verifier = make_phase_v2_binding_verifier(fixture.registry)

    forged_background = edge.background_factor.model_copy(
        update={"content_sha256": _h("forged-background")}
    )
    assert not verifier(
        edge.transition,
        edge.source_composition,
        edge.target_composition,
        edge.source_factor,
        edge.target_factor,
        (forged_background,),
    )
    forged_source = edge.source_composition.model_copy(
        update={"composition_id": "pc:forged"}
    )
    assert not verifier(
        edge.transition,
        forged_source,
        edge.target_composition,
        edge.source_factor,
        edge.target_factor,
        (edge.background_factor,),
    )


def test_bundle_rejection_rolls_back_every_structural_row() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:ab")
    bank = fixture.bank(accept_bundle=False)
    before = bank.to_state()

    with pytest.raises(ValueError, match="canonical bundle"):
        register_phase_materialization_v2(
            registry=fixture.registry,
            bank=bank,
            proof=proof,
        )

    assert bank.to_state() == before


def test_only_runner_authenticated_activation_receipts_enter_edge_evidence() -> None:
    fixture = Fixture()
    proof = fixture.mutation(target="b", receipt="generation:ab")
    bank = fixture.bank(with_probe_capabilities=True)
    edge = register_phase_materialization_v2(
        registry=fixture.registry, bank=bank, proof=proof
    )
    slot_id = bank.deployment_slot_id(fixture.namespace)
    bank.register_base_snapshot(
        BaseSnapshotReceiptV2(
            receipt_id="base:phase-v2",
            deployment_slot_id=slot_id,
            namespace_digest=fixture.namespace.digest,
            composition_id=edge.source_composition.composition_id,
            loaded_artifact_sha256=edge.source_composition.artifact_sha256,
            binding_map_sha256=_canonical_hash(
                sorted(edge.source_composition.binding_map.items())
            ),
            runtime_version=fixture.namespace.runtime_version,
            verifier_epoch="base-verifier:phase-v2",
            attestation_sha256=_h("base-phase-v2"),
            emitted_seq=bank.to_state().event_seq + 1,
        )
    )
    budget = ExecutionBudget(
        max_messages=16,
        max_model_calls=8,
        max_input_tokens=8_000,
        max_output_tokens=2_000,
        max_wall_time_ms=60_000,
        max_cost_microusd=50_000,
    )
    plan = bank.seal_probe_plan(
        transition_id=edge.transition.transition_id,
        owner_kind="direct_factor",
        epoch_id="epoch:phase-v2",
        unit_commitments=tuple(_h(f"unit-phase-{index}") for index in range(6)),
        arm_orders=("AB", "BA", "AB", "BA", "AB", "BA"),
        assignment_manifest_sha256=_h("phase-assignment-manifest"),
        runner_version="runner:phase-v2",
        budget=budget,
    )
    usage = ExecutionUsage(
        messages=4,
        model_calls=2,
        input_tokens=1_000,
        output_tokens=200,
        wall_time_ms=2_000,
        cost_microusd=2_000,
    )

    def open_attempt(ordinal: int):
        assignment = make_assignment_receipt_v2(
            plan=plan,
            ordinal=ordinal,
            origin_pool_sha256=_h("origin-pool"),
            producer_epoch="assignment-producer:phase-v2",
            attestation_sha256=_h(f"assignment-{ordinal}"),
        )
        lease = make_runner_lease_grant_v1(
            plan=plan,
            assignment=assignment,
            runner_session_id=f"runner-session:phase:{ordinal}",
            runner_lease_token_sha256=_h(f"runner-lease-token:{ordinal}"),
            journal_anchor_sha256=_h(f"runner-journal-anchor:{ordinal}"),
            verifier_epoch="runner-lease-verifier:phase-v2",
            attestation_sha256=_h(f"runner-lease-attestation:{ordinal}"),
        )
        return bank.open_next_attempt(plan.plan_id, assignment, lease)

    def terminal_pair_receipt(attempt):
        if attempt.assignment.arm_order == "AB":
            source_started, source_finished = 1, 2
            target_started, target_finished = 3, 4
        else:
            target_started, target_finished = 1, 2
            source_started, source_finished = 3, 4
        return make_pair_execution_receipt_v2(
            attempt=attempt,
            source_root_id=_h(f"root-{attempt.ordinal}-source"),
            target_root_id=_h(f"root-{attempt.ordinal}-target"),
            source_started_seq=source_started,
            source_finished_seq=source_finished,
            target_started_seq=target_started,
            target_finished_seq=target_finished,
            verifier_epoch="pair-runner:phase-v2",
            attestation_sha256=_h(f"pair-attestation-{attempt.ordinal}"),
        )

    def signed_receipt(attempt, pair_receipt, arm: str, *, valid: bool):
        outcome = DenseOutcome(
            V=0.5 if arm == "source" else 0.6,
            K=0.8,
            U=0.8,
            P=0.8,
            S=0.8,
            stage_score=0.5 if arm == "source" else 0.6,
            C=10.0 if arm == "source" else 9.0,
            D=1.0,
        )
        receipt = make_registered_phase_arm_receipt_v2(
            registry=fixture.registry,
            registered=edge,
            plan=plan,
            attempt=attempt,
            arm=arm,
            root_id=_h(f"root-{attempt.ordinal}-{arm}"),
            paired_arm_root_id=_h(
                f"root-{attempt.ordinal}-{'target' if arm == 'source' else 'source'}"
            ),
            pair_execution_receipt=pair_receipt,
            activation_trace_root=_h(f"trace-{attempt.ordinal}-{arm}"),
            usage=usage,
            execution_class="completed",
            outcome=outcome,
            producer_epoch="runner-producer:phase-v2",
            attestation_sha256=_h("unsigned-placeholder"),
        )
        return receipt.model_copy(
            update={
                "attestation_sha256": (
                    _runner_mac(receipt, fixture.registry.resolve_proof(proof))
                    if valid
                    else proof.proof_sha256
                )
            }
        )

    valid_attempt = open_attempt(0)
    valid_pair = terminal_pair_receipt(valid_attempt)
    valid_source = signed_receipt(valid_attempt, valid_pair, "source", valid=True)
    valid_target = signed_receipt(valid_attempt, valid_pair, "target", valid=True)
    completed = bank.commit_attempt(
        valid_attempt.attempt_id, valid_source, valid_target, valid_pair
    )
    assert completed.state == "complete"
    assert bank.assessments[plan.plan_id].n_complete == 1

    forged_attempt = open_attempt(1)
    forged_pair = terminal_pair_receipt(forged_attempt)
    forged_source = signed_receipt(
        forged_attempt, forged_pair, "source", valid=True
    )
    forged_target = signed_receipt(
        forged_attempt, forged_pair, "target", valid=False
    )
    quarantined = bank.commit_attempt(
        forged_attempt.attempt_id, forged_source, forged_target, forged_pair
    )
    assert quarantined.state == "quarantine"
    # A receipt that merely echoes a public proof digest adds no evidence.
    assert bank.assessments[plan.plan_id].n_complete == 1
    assert bank.assessments[plan.plan_id].settled
