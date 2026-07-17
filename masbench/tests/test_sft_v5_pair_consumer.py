"""Stage 5 closure tests: TRAIN arm adapter + single-use pair consumer.

One complete fake pair — real engine attestations over the generated v3 edge,
real isolated-scorer receipts, authority-signed arm receipts — enters
FactorBankV2 exactly once, gives the transition exactly one vote, replays
idempotently, and every forged/crossed/raw input is rejected before a receipt
can exist.
"""

from __future__ import annotations

import hashlib

import pytest

from exp_graph.mas.factor_bank import DenseOutcome, ExecutionUsage
from exp_graph.mas.phase_factor_binding_v3 import RegisteredPhaseFactorEdgeV3
from masbench.engine import register_exact_phase_execution_result
from masbench.sft_pilot.execution_attestation import (
    PilotExecutionAttestor,
    PilotFinalValOutcomeReceiptV1,
    PilotOutcomeScorer,
)
from masbench.sft_pilot.pair_adapter import make_phase_v3_factor_arm_receipt
from masbench.sft_pilot.pair_consumer import consume_phase_v3_pair_once
from masbench.sft_pilot.scientific_runner import reserve_scheduled_execution

from sft_v5_fixtures import V5Harness

import test_sft_execution_attestation as base


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _metrics(v: float, c: float) -> DenseOutcome:
    return DenseOutcome(
        V=v, K=v, U=v, P=v, S=v, stage_score=v, C=c, D=2.0
    )


def _usage() -> ExecutionUsage:
    return ExecutionUsage(
        messages=1,
        model_calls=1,
        input_tokens=20,
        output_tokens=5,
        wall_time_ms=100,
        cost_microusd=400,
    )


class _PairHarness(V5Harness):
    """Extends the shared harness with one executed probe pair."""

    def probe_arms(self, ordinal: int):
        protocol = self.experiment.protocol
        source = next(
            item
            for item in protocol.authorized_logical_arms
            if item.operation_kind == "source_probe"
            and item.execution_ordinal == ordinal
        )
        target = next(
            item
            for item in protocol.authorized_logical_arms
            if item.operation_kind == "target_probe"
            and item.execution_ordinal == ordinal
        )
        return source, target

    def run_probe_pair(self, *, tag: str):
        edge = self.commit_mutate_edge(tag=tag)
        assert isinstance(edge, RegisteredPhaseFactorEdgeV3)
        action = next(
            item
            for item in self.bank.to_state().proposal_actions
            if item.state == "committed"
        )
        transition = edge.transition
        plan = self.bank.seal_probe_plan(
            transition_id=transition.transition_id,
            owner_kind="direct_factor",
            epoch_id=self.authority.epoch_id_for(
                transition_id=transition.transition_id
            ),
            unit_commitments=self.authority.unit_commitments,
            arm_orders=self.authority.arm_orders,
            assignment_manifest_sha256=self.authority.assignment_manifest_sha256,
            runner_version=self.authority.runner_version,
            budget=self.authority.plan_budget,
        )
        assignment = self.authority.make_assignment(plan, ordinal=0)
        runner_lease = self.authority.make_runner_lease(
            plan=plan,
            assignment=assignment,
            runner_session_id=f"v5-probe-runner:{tag}",
            runner_lease_token_sha256=_sha(f"probe-token:{tag}"),
            journal_anchor_sha256=_sha(f"probe-journal:{tag}"),
        )
        attempt = self.bank.open_next_attempt(
            plan.plan_id, assignment, runner_lease
        )
        source_arm, target_arm = self.probe_arms(0)
        for arm in (source_arm, target_arm):
            reserve_scheduled_execution(
                self.store,
                schedule=self.experiment.seal.execution_schedule,
                logical_arm=arm,
                logical_execution_key=f"probe-{tag}-{arm.pair_arm}",
                action_id=action.action_id,
            )
        self.checkpoint()
        assert (
            self.loaded.snapshot.checkpoint.checkpoint_kind
            == "probe_attempt_open"
        )
        recovery_root = self.loaded.snapshot.recovery_root_sha256

        snapshot = base._verified_pair_snapshot(
            self.experiment.root,
            protocol=self.experiment.protocol,
            registry=self.registry,
            edge=edge,
            pair_arm=source_arm,
            tag=tag,
        )
        schedule = self.experiment.seal.execution_schedule
        executions = {}
        for arm in (source_arm, target_arm):
            key = f"probe-{tag}-{arm.pair_arm}"
            entry = schedule.entry_for(arm)
            scheduled_call = entry.calls[0]
            call_key = f"probe-call-{tag}-{arm.pair_arm}"
            self.store.reserve_call(
                operation_id=f"reserve-{call_key}",
                operation_request_sha256=_sha(f"reserve:{call_key}"),
                call_key=call_key,
                logical_execution_key=key,
                call_slot=0,
                call_request_sha256=scheduled_call.request_envelope_sha256,
                input_tokens_reserved=scheduled_call.input_tokens_reserved,
                output_tokens_reserved=scheduled_call.output_tokens_reserved,
                expected_component_recovery_root_sha256=recovery_root,
            )
            authorization = self.store.start_call(
                call_key,
                operation_id=f"start-{call_key}",
                operation_request_sha256=_sha(f"start:{call_key}"),
                call_request_sha256=scheduled_call.request_envelope_sha256,
                expected_component_recovery_root_sha256=recovery_root,
            )
            assert authorization.may_invoke_sdk
            self.store.complete_call(
                call_key,
                operation_id=f"complete-{call_key}",
                operation_request_sha256=_sha(f"complete:{call_key}"),
                call_request_sha256=scheduled_call.request_envelope_sha256,
                output_envelope_sha256=_sha(f"output:{call_key}"),
                provider_usage_known=True,
                input_tokens_used=20,
                output_tokens_used=5,
            )
            self.store.complete_execution(
                key,
                operation_id=f"complete-{key}",
                operation_request_sha256=_sha(f"complete:{key}"),
            )
            capability = register_exact_phase_execution_result(
                protocol=self.experiment.protocol,
                logical_arm=arm,
                registry=self.registry,
                registered_edge=edge,
                store=self.store,
                logical_execution_key=key,
                call_keys=(call_key,),
                journal_snapshot=snapshot,
                engine_key=self.experiment.runtime_role_key(
                    "exact_phase_engine"
                ),
            )
            executions[arm.pair_arm] = capability

        attestor = PilotExecutionAttestor(
            self.experiment.protocol,
            engine_key=self.experiment.runtime_role_key("exact_phase_engine"),
        )
        scorer = PilotOutcomeScorer(
            self.experiment.protocol,
            scorer_key=self.experiment.runtime_role_key("train_scorer"),
            execution_attestor=attestor,
            scorer_id="sft-v5-train-scorer",
            scorer_version_sha256=_sha("sft-v5-train-scorer-code"),
        )
        attestations = {
            arm_name: attestor.issue(capability)
            for arm_name, capability in executions.items()
        }
        outcomes = {
            "source": scorer.score_train_update(
                attestations["source"], _metrics(0.5, 25.0)
            ),
            "target": scorer.score_train_update(
                attestations["target"], _metrics(0.6, 9.0)
            ),
        }
        pair_receipt = self.authority.make_pair_execution(
            plan=plan,
            attempt=attempt,
            source_root_id=_sha(f"physical:{tag}:source"),
            target_root_id=_sha(f"physical:{tag}:target"),
            source_started_seq=1,
            source_finished_seq=2,
            target_started_seq=3,
            target_finished_seq=4,
        )
        receipts = {
            arm_name: make_phase_v3_factor_arm_receipt(
                authority=self.authority,
                registry=self.registry,
                registered=edge,
                plan=plan,
                attempt=attempt,
                pair_execution_receipt=pair_receipt,
                execution=attestations[arm_name],
                outcome_receipt=outcomes[arm_name],
                execution_attestor=attestor,
                scorer=scorer,
                usage=_usage(),
            )
            for arm_name in ("source", "target")
        }
        return {
            "edge": edge,
            "plan": plan,
            "attempt": attempt,
            "pair_receipt": pair_receipt,
            "receipts": receipts,
            "attestations": attestations,
            "outcomes": outcomes,
            "attestor": attestor,
            "scorer": scorer,
        }


@pytest.fixture
def pair(tmp_path):
    harness = _PairHarness(tmp_path)
    yield harness, harness.run_probe_pair(tag="pair-one")
    harness.close()


def test_one_complete_pair_gives_exactly_one_vote_and_replays_idempotently(
    pair,
) -> None:
    harness, built = pair
    consumed = consume_phase_v3_pair_once(
        loaded=harness.loaded,
        coordinator=harness.coordinator,
        attempt_id=built["attempt"].attempt_id,
        source_receipt=built["receipts"]["source"],
        target_receipt=built["receipts"]["target"],
        pair_execution_receipt=built["pair_receipt"],
        operation_id="consume-pair-one",
        operation_request_sha256=_sha("consume:pair-one"),
    )
    assert not consumed.replayed
    assert consumed.attempt.state == "complete"
    harness.loaded = consumed.loaded
    bank = harness.loaded.bank
    assessment = bank.assessments[built["plan"].plan_id]
    assert assessment.n_complete == 1
    assert assessment.n_benefit == 1
    # The label belongs to the Bank's native reducer; at one complete unit of
    # six it reports the current non-candidate state (no orchestrator label).
    assert assessment.label == "neutral"
    state_digest = bank.scientific_state_sha256

    replay = consume_phase_v3_pair_once(
        loaded=harness.loaded,
        coordinator=harness.coordinator,
        attempt_id=built["attempt"].attempt_id,
        source_receipt=built["receipts"]["source"],
        target_receipt=built["receipts"]["target"],
        pair_execution_receipt=built["pair_receipt"],
        operation_id="consume-pair-one-replay",
        operation_request_sha256=_sha("consume:pair-one-replay"),
    )
    assert replay.replayed
    assert harness.loaded.bank.scientific_state_sha256 == state_digest

    # Conflicting replay (different receipt bytes for a settled attempt).
    tampered = built["receipts"]["source"].model_copy(
        update={"attestation_sha256": "9" * 64}
    )
    with pytest.raises(ValueError, match="different pair evidence"):
        consume_phase_v3_pair_once(
            loaded=harness.loaded,
            coordinator=harness.coordinator,
            attempt_id=built["attempt"].attempt_id,
            source_receipt=tampered,
            target_receipt=built["receipts"]["target"],
            pair_execution_receipt=built["pair_receipt"],
            operation_id="consume-pair-one-conflict",
            operation_request_sha256=_sha("consume:pair-one-conflict"),
        )


def test_swapped_arms_fail_before_any_consumption(pair) -> None:
    harness, built = pair
    with pytest.raises(ValueError, match="one source and one target"):
        consume_phase_v3_pair_once(
            loaded=harness.loaded,
            coordinator=harness.coordinator,
            attempt_id=built["attempt"].attempt_id,
            source_receipt=built["receipts"]["target"],
            target_receipt=built["receipts"]["source"],
            pair_execution_receipt=built["pair_receipt"],
            operation_id="consume-swapped",
            operation_request_sha256=_sha("consume:swapped"),
        )
    # Nothing was consumed: the true pair still commits.
    consumed = consume_phase_v3_pair_once(
        loaded=harness.loaded,
        coordinator=harness.coordinator,
        attempt_id=built["attempt"].attempt_id,
        source_receipt=built["receipts"]["source"],
        target_receipt=built["receipts"]["target"],
        pair_execution_receipt=built["pair_receipt"],
        operation_id="consume-after-swap-reject",
        operation_request_sha256=_sha("consume:after-swap-reject"),
    )
    assert consumed.attempt.state == "complete"


def test_adapter_rejects_final_val_raw_and_forged_inputs(pair) -> None:
    harness, built = pair
    execution = built["attestations"]["source"]
    outcome = built["outcomes"]["source"]

    final_val_alias = PilotFinalValOutcomeReceiptV1.model_validate(
        {
            **outcome.model_dump(mode="python"),
            "receipt_kind": "final_val",
            "split": "FINAL_VAL",
        }
    )
    with pytest.raises(TypeError, match="TRAIN_UPDATE receipt type"):
        make_phase_v3_factor_arm_receipt(
            authority=harness.authority,
            registry=harness.registry,
            registered=built["edge"],
            plan=built["plan"],
            attempt=built["attempt"],
            pair_execution_receipt=built["pair_receipt"],
            execution=execution,
            outcome_receipt=final_val_alias,
            execution_attestor=built["attestor"],
            scorer=built["scorer"],
            usage=_usage(),
        )

    forged_execution = execution.model_copy(
        update={"execution_attestation_sha256": "8" * 64}
    )
    with pytest.raises(ValueError, match="unjoined receipt authorities"):
        make_phase_v3_factor_arm_receipt(
            authority=harness.authority,
            registry=harness.registry,
            registered=built["edge"],
            plan=built["plan"],
            attempt=built["attempt"],
            pair_execution_receipt=built["pair_receipt"],
            execution=forged_execution,
            outcome_receipt=outcome,
            execution_attestor=built["attestor"],
            scorer=built["scorer"],
            usage=_usage(),
        )

    # Swapping the transition endpoints makes the expected factor a
    # retrieved-but-not-activated revision: zero credit, loudly.
    edge_dump = built["edge"].model_dump(mode="python")
    transition = dict(edge_dump["transition"])
    transition["from_revision_id"], transition["to_revision_id"] = (
        transition["to_revision_id"],
        transition["from_revision_id"],
    )
    edge_dump["transition"] = transition
    swapped_edge = RegisteredPhaseFactorEdgeV3.model_validate(edge_dump)
    with pytest.raises(ValueError, match="retrieved-but-not-activated"):
        make_phase_v3_factor_arm_receipt(
            authority=harness.authority,
            registry=harness.registry,
            registered=swapped_edge,
            plan=built["plan"],
            attempt=built["attempt"],
            pair_execution_receipt=built["pair_receipt"],
            execution=execution,
            outcome_receipt=outcome,
            execution_attestor=built["attestor"],
            scorer=built["scorer"],
            usage=_usage(),
        )

    # A journal root that is not the attested physical root is rejected.
    foreign_pair = harness.authority.make_pair_execution(
        plan=built["plan"],
        attempt=built["attempt"],
        source_root_id=_sha("foreign-root-source"),
        target_root_id=_sha("foreign-root-target"),
        source_started_seq=1,
        source_finished_seq=2,
        target_started_seq=3,
        target_finished_seq=4,
    )
    with pytest.raises(ValueError, match="attested physical execution root"):
        make_phase_v3_factor_arm_receipt(
            authority=harness.authority,
            registry=harness.registry,
            registered=built["edge"],
            plan=built["plan"],
            attempt=built["attempt"],
            pair_execution_receipt=foreign_pair,
            execution=execution,
            outcome_receipt=outcome,
            execution_attestor=built["attestor"],
            scorer=built["scorer"],
            usage=_usage(),
        )
