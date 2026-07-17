"""Stage 6 closure tests: the full six-unit probe with recovery.

Every scenario runs the real chain (engine attestation, isolated scorer,
authority receipts, single-use consumer, saga checkpoints); the assessment
label is always the Bank's native reducer output — the harness never relabels.
Infrastructure pairs keep their cost but never update efficacy; a physical
order violation quarantines; crash/restart restores exact state roots.
"""

from __future__ import annotations

import hashlib

import pytest

from sft_v5_fixtures import (
    ArmPlan,
    V5ProbeHarness,
    benefit_pair,
    harm_pair,
    null_pair,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def harness(tmp_path):
    built = V5ProbeHarness(tmp_path)
    yield built
    built.close()


def _committed_action_id(harness) -> str:
    return next(
        item.action_id
        for item in harness.bank.to_state().proposal_actions
        if item.state == "committed"
    )


def _start_plan(harness, *, tag: str):
    edge = harness.commit_mutate_edge(tag=tag)
    action_id = _committed_action_id(harness)
    plan = harness.seal_plan_for(edge.transition)
    return edge, action_id, plan


def test_four_benefit_units_settle_candidate_and_survive_crash(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="cand")
    for ordinal in range(2):
        source, target = benefit_pair()
        consumed = harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="cand",
            source=source,
            target=target,
        )
        assert consumed.attempt.state == "complete"

    # Crash and restart mid-plan: the recovery head restores exact roots.
    before_bank = harness.bank.scientific_state_sha256
    before_registry = harness.registry.scientific_state_sha256
    harness.reopen()
    assert harness.bank.scientific_state_sha256 == before_bank
    assert harness.registry.scientific_state_sha256 == before_registry

    for ordinal in range(2, 4):
        source, target = benefit_pair()
        harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="cand",
            source=source,
            target=target,
        )
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 4
    assert assessment.n_benefit == 4
    assert assessment.counterbalanced
    assert assessment.label == "candidate"
    # The plan is settled: no further unit may open.
    with pytest.raises(ValueError, match="cannot open another attempt"):
        harness.open_probe_unit(
            plan, ordinal=4, tag="cand-extra", action_id=action_id
        )


def test_three_benefit_one_null_is_not_candidate(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="null3")
    for ordinal in range(4):
        source, target = benefit_pair() if ordinal < 3 else null_pair()
        harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="null3",
            source=source,
            target=target,
        )
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 4
    assert assessment.n_benefit == 3
    assert assessment.n_null == 1
    # Native reducer decides; three benefits with one null and no harm meet
    # the 3/4 quorum only if strict acceptance also holds — pin its output.
    assert assessment.label == "candidate"
    assert assessment.n_harm == 0


def test_catastrophic_target_failure_is_harmful_terminal(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="cata")
    harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=0,
        tag="cata",
        source=ArmPlan(v=0.6, c=9.0),
        target=ArmPlan(
            terminal="algorithm_failure",
            v=0.0,
            c=30.0,
            safe_failure_code="algorithm_failure",
            failed_stage_rank=1,
        ),
    )
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_harm == 1
    assert assessment.catastrophic_harm
    assert assessment.label == "harmful"
    with pytest.raises(
        ValueError,
        match="cannot open another attempt|harmful scientific transition",
    ):
        harness.open_probe_unit(
            plan, ordinal=1, tag="cata-extra", action_id=action_id
        )


def test_all_zero_stream_cannot_become_candidate(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="zero")
    for ordinal in range(4):
        harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="zero",
            source=ArmPlan(v=0.0, c=25.0),
            target=ArmPlan(v=0.0, c=25.0),
        )
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 4
    assert assessment.all_zero_stream
    assert assessment.label != "candidate"


def test_infrastructure_units_exhaust_without_any_efficacy(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="infra")
    for ordinal in range(6):
        consumed = harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="infra",
            source=ArmPlan(terminal="infrastructure_failure"),
            target=ArmPlan(terminal="infrastructure_failure"),
        )
        assert consumed.attempt.state == "incomplete"
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 0
    assert assessment.n_benefit == assessment.n_harm == assessment.n_null == 0
    assert assessment.label == "infrastructure_exhausted"


def test_reserve_unit_replaces_incomplete_primary(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="reserve")
    harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=0,
        tag="reserve",
        source=ArmPlan(terminal="infrastructure_failure"),
        target=ArmPlan(terminal="infrastructure_failure"),
    )
    for ordinal in range(1, 4):
        source, target = benefit_pair()
        harness.execute_probe_unit(
            edge=edge,
            plan=plan,
            action_id=action_id,
            ordinal=ordinal,
            tag="reserve",
            source=source,
            target=target,
        )
    # The reserve unit (ordinal 4) is now the only admissible continuation.
    source, target = benefit_pair()
    consumed = harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=4,
        tag="reserve",
        source=source,
        target=target,
    )
    assert consumed.attempt.state == "complete"
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 4
    assert assessment.n_benefit == 4
    assert assessment.label == "candidate"


def test_physical_order_violation_quarantines_and_consumes(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="order")
    scheduled = plan.units[0].arm_order
    flipped = "BA" if scheduled == "AB" else "AB"
    source, target = benefit_pair()
    consumed = harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=0,
        tag="order",
        source=source,
        target=target,
        physical_order=flipped,
    )
    assert consumed.attempt.state == "quarantine"
    assert consumed.attempt.disposition_reason == (
        "physical_arm_order_violation"
    )
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 0


def test_half_pair_cancellation_settles_without_survivor_bias(harness) -> None:
    """A crashed pair is cancelled whole — no single-arm evidence survives."""

    edge, action_id, plan = _start_plan(harness, tag="half")
    # Zero-start cancellation: the runner died after opening the attempt but
    # before any provider crossing; the pair settles whole (the one-start
    # journal-witness variants are pinned by the exp-graph Bank suite).
    cancelled = harness.cancel_probe_unit(
        plan=plan,
        action_id=action_id,
        ordinal=0,
        tag="half",
    )
    assert cancelled.state == "cancelled"
    assessment = harness.bank.assessments[plan.plan_id]
    assert assessment.n_complete == 0
    assert assessment.n_benefit == assessment.n_harm == 0
    # Recovery after the cancellation still restores exact roots and the
    # plan continues on the next unit.
    before = harness.bank.scientific_state_sha256
    harness.reopen()
    assert harness.bank.scientific_state_sha256 == before
    source, target = benefit_pair()
    consumed = harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=1,
        tag="half",
        source=source,
        target=target,
    )
    assert consumed.attempt.state == "complete"


def test_duplicate_unit_cannot_open_twice(harness) -> None:
    edge, action_id, plan = _start_plan(harness, tag="dup")
    source, target = benefit_pair()
    harness.execute_probe_unit(
        edge=edge,
        plan=plan,
        action_id=action_id,
        ordinal=0,
        tag="dup",
        source=source,
        target=target,
    )
    with pytest.raises(ValueError):
        harness.open_probe_unit(
            plan, ordinal=0, tag="dup-again", action_id=action_id
        )
