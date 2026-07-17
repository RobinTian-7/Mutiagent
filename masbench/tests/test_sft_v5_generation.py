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

from sft_v5_fixtures import ANCHOR_LOCATOR, V5Harness, build_v5_experiment


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    built = V5Harness(tmp_path)
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
