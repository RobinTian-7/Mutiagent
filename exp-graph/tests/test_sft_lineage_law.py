"""Semantics of the ported verified-lineage law."""

import json
from pathlib import Path

import pytest

from exp_graph.sft_lineage.law import (
    LineageBank,
    TournamentLog,
    envelope_cases,
    envelope_cost_ratio,
    mint_task_sequence,
    retire_round_dir,
    review_cases,
    review_verdict,
    round_status,
    round_verdict,
    seed_vote,
    structure_diff,
)

BY_TIER = {
    "I": ["I-cf00", "I-cf01", "I-cf02"],
    "II": ["II-cf00", "II-cf01", "II-cf02"],
    "III": ["III-cf00", "III-cf01", "III-cf02"],
}
TIER_ORDER = ["I", "II", "III"]


def _row(S=1.0, stage=1.0, C=100.0, **extra):
    row = {
        "infra": None,
        "execution_class": "completed",
        "success": S >= 1.0,
        "S": S,
        "stage_score": stage,
        "C": C,
    }
    row.update(extra)
    return row


def test_mint_sequence_leads_with_hardest_tier():
    sequence = mint_task_sequence(BY_TIER, TIER_ORDER)
    assert sequence[:3] == ["III-cf00", "II-cf00", "I-cf00"]
    assert len(sequence) == 9
    assert len(set(sequence)) == 9


def test_envelope_starts_with_mint_case_and_balances_tiers():
    cases = envelope_cases("II-cf01", 0, BY_TIER, TIER_ORDER, width=3)
    assert cases[0] == "II-cf01"
    assert len(cases) == 3
    tiers = sorted(case.split("-")[0] for case in cases)
    assert tiers == ["I", "II", "III"]


def test_envelope_width_six_gives_two_per_tier():
    cases = envelope_cases("III-cf00", 2, BY_TIER, TIER_ORDER, width=6)
    tiers = [case.split("-")[0] for case in cases]
    assert len(cases) == 6
    assert all(tiers.count(tier) == 2 for tier in TIER_ORDER)


def test_review_cases_disjoint_from_envelope_hardest_first():
    envelope = ("III-cf00", "II-cf00", "I-cf00")
    fresh = review_cases(envelope, 0, BY_TIER, TIER_ORDER, width=2)
    assert len(fresh) == 2
    assert not set(fresh) & set(envelope)
    assert fresh[0].startswith("III-")


def test_seed_vote_quality_before_cost():
    assert seed_vote(_row(S=1.0), _row(S=0.9, C=1.0)) == "quality_win"
    assert seed_vote(_row(S=0.8), _row(S=0.9)) == "quality_loss"
    assert seed_vote(_row(stage=0.9), _row(stage=0.8, C=1.0)) == "quality_win"
    assert seed_vote(_row(C=90.0), _row(C=100.0)) == "cost_win"
    assert seed_vote(_row(C=96.0), _row(C=100.0)) == "tie"
    assert seed_vote(_row(C=110.0), _row(C=100.0)) == "cost_loss"


def test_seed_vote_failures_and_voids():
    failed = _row(S=0.0, stage=0.0)
    failed["execution_class"] = "algorithm_failure"
    assert seed_vote(failed, _row()) == "catastrophic"
    assert seed_vote(_row(), failed) == "quality_win"
    assert seed_vote(failed, dict(failed)) == "tie"
    assert seed_vote({"infra": "boom"}, _row()) == "void"


def test_round_verdict_quality_dominates_cost():
    assert round_verdict(["quality_win", "cost_loss", "cost_loss"]) == "win"
    assert round_verdict(["quality_loss", "cost_win", "cost_win"]) == "loss"
    assert round_verdict(["catastrophic", "quality_win"]) == "loss"
    assert round_verdict(["tie", "cost_win", "tie"]) == "win"
    assert round_verdict(["tie", "tie"]) == "neutral"


def test_round_verdict_cost_inflation_brake():
    votes = ["quality_win", "tie", "tie"]
    assert round_verdict(votes, cost_ratio=3.0) == "win"  # brake disabled
    assert (
        round_verdict(votes, cost_ratio=3.0, max_cost_inflation=2.0)
        == "neutral"
    )


def test_review_verdict_rules():
    assert review_verdict(
        ["quality_loss"], require_quality_evidence=True
    ) == (False, "quality_regression_on_review")
    assert review_verdict(
        ["tie", "tie"], require_quality_evidence=True
    ) == (False, "quality_gain_did_not_reproduce")
    assert review_verdict(
        ["quality_win", "tie"], require_quality_evidence=True
    ) == (True, "quality_gain_confirmed")
    assert review_verdict(
        ["cost_loss", "tie"], require_quality_evidence=False
    ) == (False, "cost_saving_did_not_reproduce")
    assert review_verdict(
        ["void", "void"], require_quality_evidence=True
    ) == (True, "review_inconclusive_all_void")


def test_envelope_cost_ratio_skips_void_pairs():
    challenger = [_row(C=50.0), {"infra": "x"}, _row(C=150.0)]
    incumbent = [_row(C=100.0), _row(C=100.0), _row(C=100.0)]
    assert envelope_cost_ratio(challenger, incumbent) == pytest.approx(1.0)
    assert envelope_cost_ratio([{"infra": "x"}], [_row()]) is None


def test_lineage_bank_promotion_law(tmp_path: Path):
    lineage = LineageBank(tmp_path / "lineage.json")
    lineage.seed(origin="seed:x", title="X", program={"phases": []})
    assert lineage.incumbent()["version"] == 1

    rejected = lineage.record_duel(
        round_index=0,
        challenger_program={"phases": [1]},
        verdict="neutral",
        votes=["tie"],
    )
    assert rejected == 2
    assert lineage.incumbent()["version"] == 1
    assert lineage.state["versions"]["2"]["state"] == "rejected"

    promoted = lineage.record_duel(
        round_index=1,
        challenger_program={"phases": [2]},
        verdict="win",
        votes=["quality_win"],
    )
    assert promoted == 3
    assert lineage.incumbent()["version"] == 3
    assert lineage.state["versions"]["1"]["state"] == "superseded"

    reloaded = LineageBank(tmp_path / "lineage.json")
    assert reloaded.incumbent()["version"] == 3
    assert len(reloaded.incumbent()["duels"]) == 1


def test_tournament_log_hash_chain(tmp_path: Path):
    log = TournamentLog(tmp_path / "events.jsonl")
    first = log.append("open", {"a": 1})
    log.append("close", {"b": 2})
    lines = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    assert lines[0]["prev_sha"] == "0" * 64
    assert lines[1]["prev_sha"] == first
    resumed = TournamentLog(tmp_path / "events.jsonl")
    assert resumed.prev_sha == lines[1]["sha"]


def test_round_status_and_retire(tmp_path: Path):
    log = TournamentLog(tmp_path / "events.jsonl")
    assert round_status(tmp_path, 0) is None
    round_dir = tmp_path / "round-0"
    round_dir.mkdir()
    assert round_status(tmp_path, 0) == "partial"
    (round_dir / "round-report.json").write_text(
        json.dumps({"status": "completed"})
    )
    assert round_status(tmp_path, 0) == "completed"
    retire_round_dir(tmp_path, 0, log)
    assert not round_dir.exists()
    assert (tmp_path / "_retired" / "round-0.0").exists()


def test_structure_diff_reports_field_changes():
    incumbent = [
        {"kind": "premix", "pattern": "ring", "max_rounds": 2},
        {"kind": "gather", "pattern": "star"},
    ]
    challenger = [
        {"kind": "premix", "pattern": "ring", "max_rounds": 4},
        {"kind": "gather", "pattern": "tree"},
    ]
    changes = structure_diff(incumbent, challenger)
    assert any("max_rounds 2 -> 4" in change for change in changes)
    assert any("pattern star -> tree" in change for change in changes)
    assert structure_diff(incumbent, incumbent) == [
        "no field-level change detected"
    ]
