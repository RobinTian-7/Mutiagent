"""Offline end-to-end CF structure-lineage campaign (fake provider).

Runs the full train + TEST flow with deterministic operators and the
deterministic offline designs, so every law is exercised without a single
network call: duels decided on the cost axis, review confirmation, the
identical-design fast path, checkpoint resume, and the TEST read-only law.
"""

import json
from pathlib import Path

from exp_graph.sft_lineage.card_train_cf import (
    build_parser,
    run_single_structure_training,
)

TIER_SPEC = '{"I": [40, 1, 5], "II": [80, 1, 8], "III": [120, 1, 10]}'


def _run_campaign(root: Path) -> dict:
    args = build_parser().parse_args(
        [
            "--rounds", "4",
            "--envelope-cases", "3",
            "--review-cases", "1",
            "--agents", "5",
            "--cases-per-tier", "3",
            "--test-cases", "3",
            "--tier-spec", TIER_SPEC,
            "--parallel-tests", "1",
            "--root", str(root),
        ]
    )
    return run_single_structure_training(args)


def test_offline_campaign_end_to_end(tmp_path: Path):
    root = tmp_path / "campaign"
    campaign = _run_campaign(root)

    # Deterministic offline walkthrough: the seed (premix+star, 19 msgs)
    # loses on cost to premix+tree (14), which loses to bare star (4); the
    # round-3 challenger repeats star and dies on the identical fast path.
    lineage = campaign["lineage"]
    assert len(lineage["versions"]) == 5
    assert lineage["incumbent"] == 3
    assert lineage["versions"]["3"]["program"]["phases"] == [
        {"kind": "gather", "pattern": "star"}
    ]
    assert lineage["versions"]["4"]["state"] == "rejected"

    round_reports = [
        json.loads((root / f"round-{idx}" / "round-report.json").read_text())
        for idx in range(4)
    ]
    assert all(r["status"] == "completed" for r in round_reports)
    assert round_reports[0]["verdict"] == "win"
    assert round_reports[0]["review"]["confirmed"] is True
    assert round_reports[2]["verdict"] == "loss"
    assert round_reports[3]["identical_design"] is True
    assert round_reports[3]["votes"] == ["tie", "tie", "tie"]
    assert round_reports[3]["incumbent_rows"] == []  # no spend on identical

    envelope = round_reports[0]["envelope_cases"]
    assert len(envelope) == 3
    assert {case.split("-")[0] for case in envelope} == {"I", "II", "III"}

    per_task = round_reports[0]["autopsy"]["per_task"]
    assert all(entry["vote"] == "cost_win" for entry in per_task)
    assert all(entry["dC"] < 0 for entry in per_task)
    assert round_reports[0]["autopsy"]["changed"]

    test = campaign["test"]
    assert test["incumbent_version"] == 3
    assert test["aggregate"]["cases_total"] == 3
    assert test["aggregate"]["success_rate"] == 1.0
    assert test["aggregate"]["infra"] == 0
    assert "lineage:v1_seed" in test["baselines"]
    assert "structure:tree_sink" in test["baselines"]
    v1_mean_c = test["baselines"]["lineage:v1_seed"]["aggregate"]["mean_C"]
    assert v1_mean_c > test["aggregate"]["mean_C"]  # the rounds bought cost

    rows = test["rows"]
    assert {row["case_id"] for row in rows} == set(
        campaign["config"]["test_case_ids"]
    )
    assert all(row["answer_agent_ids"] == [4] for row in rows)

    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text().splitlines()
    ]
    assert events[0]["event"] == "lineage_open"
    assert sum(event["event"] == "duel" for event in events) == 4
    assert events[-1]["event"] == "test_sealed"


def test_offline_campaign_resume_hits_checkpoints(tmp_path: Path):
    root = tmp_path / "campaign"
    first = _run_campaign(root)
    lineage_bytes = (root / "lineage.json").read_bytes()

    second = _run_campaign(root)
    assert (root / "lineage.json").read_bytes() == lineage_bytes
    assert second["lineage"]["incumbent"] == first["lineage"]["incumbent"]
    assert len(second["lineage"]["versions"]) == len(
        first["lineage"]["versions"]
    )
    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text().splitlines()
    ]
    skipped = [e for e in events if e["event"] == "round_skipped"]
    assert len(skipped) == 4  # every round was a checkpoint hit on rerun
