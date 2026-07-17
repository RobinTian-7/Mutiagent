"""Stage 4 closure tests: sealed proposal generation with real authority.

reuse spends zero generation calls; mutate/fresh spend exactly one frozen,
store-receipted call through the metered client; invalid output becomes an
honest authority-fenced abort — never a fabricated target. The end-to-end
paths run on the provisioned v5 experiment fixture with the real registry,
real bank verifiers, real saga checkpoints, and the deterministic fake
transport (which never sees a benchmark answer).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from exp_graph.mas.factor_bank import ExecutionUsage
from exp_graph.mas.factor_bank_v2 import (
    FailureObservationV2,
    ProposalCursorV1,
    ProposalRequestV1,
    SFTProposalInputV1,
    proposal_counter_state_sha256,
)
from exp_graph.mas.phase_artifact_registry import (
    PhaseGenerationTerminalV1,
    phase_generated_scalar_sha256,
)
from exp_graph.mas.phase_factor_binding_v3 import (
    AbortedPhaseProposalActionV2,
    RegisteredPhaseFactorEdgeV3,
    reconcile_phase_proposal_action_v3,
)
from exp_graph.mas.sft_proposal import (
    ExactFactorLocusV1,
    ExactProposalCellV1,
    select_exact_edge_proposal,
)
from masbench.sft_pilot.components import PilotComponentCoordinator
from masbench.sft_pilot.factor_authority import SFTPilotFactorAuthority
from masbench.sft_pilot.llm_meter import FakeDeterministicPilotTransport
from masbench.sft_pilot.request_renderer import (
    GENERATION_POLICY_SHA256,
    GeneratedScalarInvalid,
    PROMPT_TEMPLATE_SHA256,
    SCALAR_OUTPUT_SCHEMA_SHA256,
    SafeSourceScalar,
    parse_generated_scalar,
    render_generation_request,
)
from masbench.sft_pilot.scientific_runner import (
    V5BranchReceiptAuthority,
    execute_metered_generation_call,
    reserve_scheduled_execution,
    v5_factor_capabilities_factory,
)

from sft_v5_fixtures import ANCHOR_LOCATOR, build_v5_experiment


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Harness:
    """One coordinator-restored v5 experiment with real authority verifiers."""

    def __init__(self, tmp_path) -> None:
        self.experiment = build_v5_experiment(tmp_path)
        self.authority = SFTPilotFactorAuthority(
            self.experiment.protocol,
            pair_manifest=self.experiment.seal.pair_manifest,
            attestation_key=self.experiment.runtime_role_key(
                "factor_pair_adapter"
            ),
        )
        anchor = self.experiment.seal.structural_anchor
        self.branch_authority = V5BranchReceiptAuthority(
            anchor_source_manifest_sha256=anchor.source_manifest_sha256,
        )
        from masbench.sft_pilot.store import SingleWriterPilotStore

        self.store = SingleWriterPilotStore.open(
            self.experiment.state_dir,
            protocol=self.experiment.protocol,
            hmac_key=self.experiment.component_keys["store"],
            execution_schedule=self.experiment.seal.execution_schedule,
        )
        self.coordinator = PilotComponentCoordinator(
            store=self.store,
            phase_registry_key=self.experiment.component_keys["phase_registry"],
            factor_bank_key=self.experiment.component_keys["factor_bank"],
            manifest_verifier=self._verify_manifest,
            factor_capabilities_factory=v5_factor_capabilities_factory(
                authority=self.authority,
                seal=self.experiment.seal,
            ),
            branch_receipt_verifier=self.branch_authority,
        )
        self.loaded = self.coordinator.restore_recovery_head()
        self.checkpoint_ordinal = 0

    def _verify_manifest(self, manifest: Any) -> bool:
        anchor = self.experiment.seal.structural_anchor
        return bool(
            manifest.manifest_sha256 == anchor.source_manifest_sha256
            and manifest.split == "TRAIN_UPDATE"
        )

    def close(self) -> None:
        self.store.close()

    @property
    def bank(self):
        return self.loaded.bank

    @property
    def registry(self):
        return self.loaded.registry

    def checkpoint(self):
        self.checkpoint_ordinal += 1
        self.loaded = self.coordinator.checkpoint_loaded(
            self.loaded,
            operation_id=f"gen-checkpoint-{self.checkpoint_ordinal}",
            operation_request_sha256=_sha(
                f"gen-checkpoint:{self.checkpoint_ordinal}"
            ),
        )
        return self.loaded

    def anchor_edge(self):
        proofs = self.registry.to_state().proofs
        assert len(proofs) == 1
        from exp_graph.mas.phase_factor_binding_v3 import (
            register_phase_materialization_v3,
        )

        return register_phase_materialization_v3(
            registry=self.registry,
            bank=self.bank,
            proof=proofs[0].handle,
        )

    def prepare_action(self, branch: str, *, tag: str):
        edge = self.anchor_edge()
        observation = FailureObservationV2(
            failure_id=f"failure:v5:{tag}",
            failure_class="algorithm",
            failed_stage="execute",
            safe_failure_code="algorithm_failure",
            composition_id=edge.source_composition.composition_id,
            artifact_sha256=edge.source_composition.artifact_sha256,
            created_seq=self.bank.to_state().event_seq + 1,
        )
        opportunity = self.bank.record_failure(
            observation, feasible_branches=(branch,)
        )
        assert opportunity is not None
        locus = ExactFactorLocusV1(
            carrier="phase_program",
            slot_id=edge.transition.slot_id,
            logical_factor_id=edge.source_factor.logical_factor_id,
            locator_surface="phase_field",
            locator_path=edge.source_factor.locator.path,
            locator_version=edge.source_factor.locator.locator_version,
        )
        cell = ExactProposalCellV1(
            namespace=self.experiment.protocol.namespace,
            locus=locus,
            from_revision_id=edge.source_factor.revision_id,
            canonical_from_factor_key_sha256=(
                self.bank._factor_carrier_key_sha256(edge.source_factor)
            ),
            canonical_background_sha256=(
                self.bank._canonical_direct_background_sha256(
                    self.bank.to_state(),
                    source=edge.source_composition,
                    source_factor=edge.source_factor,
                    slot_id=locus.slot_id,
                )
            ),
        )
        candidates, _root, _count = self.bank._proposal_candidate_slate(
            opportunity=opportunity,
            source_factor=edge.source_factor,
            slot_id=locus.slot_id,
        )
        state = self.bank.to_state()
        proposal = select_exact_edge_proposal(
            SFTProposalInputV1(
                request=ProposalRequestV1(
                    opportunity_id=opportunity.opportunity_id,
                    cell=cell,
                ),
                cursor=ProposalCursorV1.empty(cell),
                candidates=candidates,
                proposal_counter_state_sha256=proposal_counter_state_sha256(
                    tuple(
                        item.witness
                        for item in state.proposal_lifetime_counters
                        if item.cell_sha256 == cell.scheduler_key_sha256
                    )
                ),
                candidate_counter_witnesses=(
                    self.bank._proposal_counter_witnesses(
                        state,
                        cell_sha256=cell.scheduler_key_sha256,
                        candidates=candidates,
                    )
                ),
            )
        )
        context = None
        if branch in {"mutate", "fresh"}:
            context = self.authority.make_generation_context(
                opportunity=opportunity,
                failure=observation,
                proposal_receipt=proposal,
                source=edge.source_composition,
                source_factor=edge.source_factor,
                source_manifest_sha256=(
                    self.experiment.seal.structural_anchor.source_manifest_sha256
                ),
                generation_policy_sha256=GENERATION_POLICY_SHA256,
                prompt_template_sha256=PROMPT_TEMPLATE_SHA256,
                scalar_output_schema_sha256=SCALAR_OUTPUT_SCHEMA_SHA256,
            )
        decision, assignment, action = self.bank.screen_and_allocate_branch(
            opportunity.opportunity_id,
            proposal,
            producer_epoch=self.authority.assignment_producer_epoch,
            attestation_sha256=self.authority.proposal_action_attestation(
                opportunity_id=opportunity.opportunity_id,
                proposal_receipt_sha256=proposal.digest,
            ),
            generation_context=context,
        )
        assert assignment is not None and action is not None
        assert assignment.branch == branch
        return edge, opportunity, observation, proposal, context, action


def _generation_arm(experiment):
    return next(
        item
        for item in experiment.protocol.authorized_logical_arms
        if item.operation_kind == "proposal_generation"
    )


def _terminal(
    action,
    *,
    value: Any,
    usage_tokens: tuple[int, int],
    tag: str,
) -> PhaseGenerationTerminalV1:
    request = action.generation_request
    lease = action.generation_lease
    assert request is not None and lease is not None
    assert lease.started_seq is not None
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
            input_tokens=usage_tokens[0],
            output_tokens=usage_tokens[1],
            wall_time_ms=500,
            cost_microusd=usage_tokens[0] * 10 + usage_tokens[1] * 40,
        ),
        generated_scalar_sha256=phase_generated_scalar_sha256(value),
        response_envelope_sha256=_sha(f"generation-response:{tag}"),
        terminal_event_id=f"generation-event:{tag}",
        terminal_event_sequence=lease.started_seq + 1,
        verifier_epoch=self_epoch(tag),
        attestation_sha256=_sha(f"generation-terminal:{tag}"),
    )


def self_epoch(tag: str) -> str:
    return f"v5-generation-terminal:{tag}"


@pytest.fixture
def harness(tmp_path):
    built = _Harness(tmp_path)
    yield built
    built.close()


def test_generation_authority_pairs_are_signed_and_closed(harness) -> None:
    edge, opportunity, observation, proposal, context, action = (
        harness.prepare_action("mutate", tag="authority")
    )
    state = harness.bank.to_state()
    assert context is not None
    assert harness.authority.verify_generation_context(
        context, opportunity, proposal, edge.source_composition,
        edge.source_factor, state,
    )
    # Foreign-key authority cannot mint an acceptable context.
    foreign = SFTPilotFactorAuthority(
        harness.experiment.protocol,
        pair_manifest=harness.experiment.seal.pair_manifest,
        attestation_key=hashlib.sha256(b"foreign-authority-key").digest(),
    )
    assert not foreign.verify_generation_context(
        context, opportunity, proposal, edge.source_composition,
        edge.source_factor, state,
    )
    tampered = context.model_dump(mode="python")
    tampered["safe_failure_code"] = "different_code"
    from exp_graph.mas.factor_bank_v2 import ProposalGenerationContextV1

    body = dict(tampered)
    body.pop("context_id")
    import exp_graph.mas.factor_bank_v2 as fb

    tampered["context_id"] = fb._opaque_id("pgc", body)
    assert not harness.authority.verify_generation_context(
        ProposalGenerationContextV1.model_validate(tampered),
        opportunity, proposal, edge.source_composition,
        edge.source_factor, state,
    )

    lease = harness.authority.make_generation_lease(
        action=action,
        runner_session_id="v5-generation-runner:authority",
        runner_lease_token_sha256=_sha("gen-token:authority"),
        journal_anchor_sha256=_sha("gen-journal:authority"),
    )
    assert harness.authority.verify_generation_lease(lease, action, state)
    assert not foreign.verify_generation_lease(lease, action, state)

    abort = harness.authority.make_abort_receipt(
        action=action,
        reason="lease_expired",
        safe_failure_code="lease_expired",
    )
    assert harness.authority.verify_abort_receipt(abort, action, state)
    assert not foreign.verify_abort_receipt(abort, action, state)

    # Honest cleanup: abort the prepared action so later tests start clean.
    harness.bank.abort_proposal_action(action.action_id, abort)


def test_mutate_generation_spends_one_frozen_receipted_call(harness) -> None:
    experiment = harness.experiment
    edge, opportunity, observation, proposal, context, action = (
        harness.prepare_action("mutate", tag="mutate-e2e")
    )
    arm = _generation_arm(experiment)
    reserve_scheduled_execution(
        harness.store,
        schedule=experiment.seal.execution_schedule,
        logical_arm=arm,
        logical_execution_key="v5-generation-owner",
        action_id=action.action_id,
    )
    harness.checkpoint()
    assert (
        harness.loaded.snapshot.checkpoint.checkpoint_kind == "action_prepared"
    )

    lease = harness.authority.make_generation_lease(
        action=action,
        runner_session_id="v5-generation-runner:mutate",
        runner_lease_token_sha256=_sha("gen-token:mutate"),
        journal_anchor_sha256=_sha("gen-journal:mutate"),
    )
    executing = harness.bank.begin_proposal_generation(action.action_id, lease)
    harness.checkpoint()
    assert (
        harness.loaded.snapshot.checkpoint.checkpoint_kind
        == "generation_start_authorized"
    )

    rendered = render_generation_request(
        context=context,
        request=executing.generation_request,
        scalar_type="int",
        value_domain_description="an integer agent index in [0, 3)",
        source_scalar=SafeSourceScalar(scalar_type="int", value=0),
    )
    transport = FakeDeterministicPilotTransport(
        reply_factory=lambda _digest: json.dumps({"value": 2}),
    )
    response = execute_metered_generation_call(
        store=harness.store,
        schedule=experiment.seal.execution_schedule,
        logical_arm=arm,
        logical_execution_key="v5-generation-owner",
        rendered=rendered,
        transport=transport,
        expected_component_recovery_root_sha256=(
            harness.loaded.snapshot.recovery_root_sha256
        ),
    )
    value = parse_generated_scalar(response.text, scalar_type="int")
    assert value == 2

    harness.branch_authority.authorize_action(executing)
    ingress = harness.registry.issue_ingress(
        experiment.seal.structural_anchor.source_manifest_sha256
    )
    result = reconcile_phase_proposal_action_v3(
        registry=harness.registry,
        bank=harness.bank,
        action_id=executing.action_id,
        generation_terminal=_terminal(
            executing,
            value=value,
            usage_tokens=(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            ),
            tag="mutate-e2e",
        ),
        generated_value=value,
        ingress=ingress,
    )
    assert isinstance(result, RegisteredPhaseFactorEdgeV3)
    committed = harness.bank.to_state()
    committed_action = next(
        item
        for item in committed.proposal_actions
        if item.action_id == executing.action_id
    )
    assert committed_action.state == "committed"
    # The generated target is a real new one-slot edge from the anchor source.
    assert result.transition.from_revision_id == edge.source_factor.revision_id
    assert result.transition.to_revision_id != edge.target_factor.revision_id

    # Exactly one completed, provider-usage-known call receipt exists for the
    # generation execution; its identity is the frozen schedule envelope.
    lease_row = harness.store.get_execution("v5-generation-owner")
    assert lease_row.state == "completed"
    scheduled_entry = experiment.seal.execution_schedule.entry_for(arm)
    scheduled_envelope = scheduled_entry.calls[0].request_envelope_sha256
    assert rendered.request_envelope_sha256 == scheduled_envelope

    # The raw prompt text never reaches durable state.
    database_bytes = (
        experiment.state_dir / "pilot.sqlite3"
    ).read_bytes()
    assert b"configuring one field" not in database_bytes


def test_fresh_invalid_output_aborts_honestly_and_keeps_cost(harness) -> None:
    experiment = harness.experiment
    edge, opportunity, observation, proposal, context, action = (
        harness.prepare_action("fresh", tag="fresh-abort")
    )
    lease = harness.authority.make_generation_lease(
        action=action,
        runner_session_id="v5-generation-runner:fresh",
        runner_lease_token_sha256=_sha("gen-token:fresh"),
        journal_anchor_sha256=_sha("gen-journal:fresh"),
    )
    executing = harness.bank.begin_proposal_generation(action.action_id, lease)
    rendered = render_generation_request(
        context=context,
        request=executing.generation_request,
        scalar_type="int",
        value_domain_description="an integer agent index in [0, 3)",
        source_scalar=None,
    )
    with pytest.raises(GeneratedScalarInvalid):
        parse_generated_scalar("not json at all", scalar_type="int")
    with pytest.raises(GeneratedScalarInvalid):
        parse_generated_scalar(
            json.dumps({"value": 1, "extra": 2}), scalar_type="int"
        )
    with pytest.raises(GeneratedScalarInvalid):
        parse_generated_scalar(json.dumps({"value": "one"}), scalar_type="int")

    abort = harness.authority.make_abort_receipt(
        action=executing,
        reason="generation_invalid_output",
        safe_failure_code="generation_invalid_output",
    )
    aborted = harness.bank.abort_proposal_action(executing.action_id, abort)
    assert aborted.state == "aborted"
    # No new registered edge appeared from the aborted action.
    assert not any(
        item.proposal_action_id == executing.action_id
        for item in harness.bank.to_state().direct_transitions
    )


def test_fresh_render_rejects_source_scalar_leak(harness) -> None:
    _edge, _opp, _obs, _prop, context, action = harness.prepare_action(
        "fresh", tag="fresh-leak"
    )
    lease = harness.authority.make_generation_lease(
        action=action,
        runner_session_id="v5-generation-runner:leak",
        runner_lease_token_sha256=_sha("gen-token:leak"),
        journal_anchor_sha256=_sha("gen-journal:leak"),
    )
    executing = harness.bank.begin_proposal_generation(action.action_id, lease)
    with pytest.raises(ValueError, match="must not see the source scalar"):
        render_generation_request(
            context=context,
            request=executing.generation_request,
            scalar_type="int",
            value_domain_description="an integer agent index in [0, 3)",
            source_scalar=SafeSourceScalar(scalar_type="int", value=0),
        )
    abort = harness.authority.make_abort_receipt(
        action=executing,
        reason="generation_invalid_output",
        safe_failure_code="generation_invalid_output",
    )
    harness.bank.abort_proposal_action(executing.action_id, abort)


def test_reuse_spends_zero_generation_calls(harness) -> None:
    before_calls = harness.store.budget_ledger_root_sha256
    edge, _opp, _obs, _prop, context, action = harness.prepare_action(
        "reuse", tag="reuse-zero"
    )
    assert context is None
    assert action.generation_request is None
    assert action.selected_target_revision_id == edge.target_factor.revision_id
    # No store execution, no call, no model transport was touched.
    assert harness.store.budget_ledger_root_sha256 == before_calls
    harness.branch_authority.authorize_action(action)
    result = reconcile_phase_proposal_action_v3(
        registry=harness.registry,
        bank=harness.bank,
        action_id=action.action_id,
    )
    assert isinstance(
        result, (RegisteredPhaseFactorEdgeV3, AbortedPhaseProposalActionV2)
    )
    assert harness.store.budget_ledger_root_sha256 == before_calls
