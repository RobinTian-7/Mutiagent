"""Offline end-to-end rehearsal of the Stage-12 real pilot driver.

Runs the full driver (author → provision → mutate generation → six-unit real
probe loop with a genuine pair journal → FINAL_VAL strict gate → frozen TEST →
baseline arm → effect table) with the fake transport and deterministic agent
modes.  This proves the arming mechanics only — never performance; the fake
path cannot read answers and the deterministic agents make zero model calls.
"""

from __future__ import annotations

import argparse
import json

import pytest

from masbench.sft_pilot.run_real_pilot import run_pilot, split_cases


def _args(root, **overrides):
    values = {
        "llm": "fake",
        "goal": "all_agents",
        "replicates": 1,
        "test_cases": 2,
        "agents": 5,
        "parallel_tests": 2,
        "max_parallel_agents": 2,
        "max_concurrent": 15,
        "request_timeout": 30.0,
        "fake_generated_value": 2,
        "benchmarks_dir": None,
        "bases": "gather_broadcast",
        "model": "gpt-4o-mini",
        "reasoning_effort": None,
        "paper_protocols": "",
        "rounds": 1,
        "strengthen_submission": False,
        "search_layer": "direct_factor",
        "root": str(root),
        "git_commit": "0" * 40,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_split_cases_is_disjoint_and_deterministic() -> None:
    ids = tuple(f"C-{index:02d}" for index in range(30))
    split = split_cases(ids, replicates=3, test_count=12)
    assert len(split.test_case_ids) == 12
    test_set = set(split.test_case_ids)
    for replicate in range(3):
        train_side = (
            set(split.replicate_probe[replicate])
            | {split.replicate_generation[replicate]}
            | set(split.replicate_final_val[replicate])
        )
        assert len(train_side) == 9
        assert not (train_side & test_set)
    assert split == split_cases(ids, replicates=3, test_count=12)


@pytest.mark.slow
def test_offline_pilot_rehearsal_end_to_end(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MASBENCH_SFT_STATE_KEY", raising=False)
    report = run_pilot(_args(tmp_path / "pilot"))

    assert len(report["replicates"]) == 1
    replicate = report["replicates"][0]
    assert replicate["status"] == "completed"
    assert replicate["generated_hub_value"] == 2
    assert replicate["assessment_label"] in {
        "candidate",
        "neutral",
        "harmful",
    }
    # Ledger holds the gate row (when a candidate settled) plus the TEST row.
    assert replicate["ledger_rows"] >= 1
    assert replicate["test"]["aggregate"]["cases_scored"] == 2.0
    assert report["baseline"]["aggregate"]["cases_scored"] == 2.0
    # The frozen TEST facade left scientific state intact and reported roots.
    assert len(replicate["scientific_state_sha256"]) == 64

    # The effect table and the machine report were persisted.
    table = (tmp_path / "pilot" / "effect_table.md").read_text(encoding="utf-8")
    assert "base:gather_broadcast" in table
    persisted = json.loads(
        (tmp_path / "pilot" / "pilot_report.json").read_text(encoding="utf-8")
    )
    assert persisted["replicates"][0]["experiment_id"] == (
        "sft-v5-gather_broadcast"
    )


@pytest.mark.slow
def test_offline_structural_round_end_to_end(tmp_path, monkeypatch) -> None:
    """Whole-composition golden: fake structural op → saga → probes → TEST.

    The fake transport proposes insert_phase(pairwise_exchange rotating ×2)
    after phase 0; the chain must register one ordinary whole transition
    (first checkpoint whole_edge_registered), run paired probes through the
    whole engine entry and receipts, settle an assessment, and finish the
    frozen TEST with the deployed head.
    """

    monkeypatch.delenv("MASBENCH_SFT_STATE_KEY", raising=False)
    report = run_pilot(
        _args(
            tmp_path / "pilot-structural",
            search_layer="whole_composition",
        )
    )

    assert len(report["replicates"]) == 1
    replicate = report["replicates"][0]
    assert replicate["status"] == "completed"
    operation = replicate["generated_operation"]
    assert operation["op_kind"] == "insert_phase"
    assert operation["phase"]["kind"] == "pairwise_exchange"
    assert replicate["transition_id"].startswith("wt:")
    assert replicate["assessment_label"] in {
        "candidate",
        "neutral",
        "harmful",
    }
    assert replicate["units"], "structural probes must have run"
    assert replicate["test"]["aggregate"]["cases_scored"] == 2.0
    assert len(replicate["scientific_state_sha256"]) == 64
    proofs = json.loads(
        (
            tmp_path
            / "pilot-structural"
            / "rep-gather_broadcast"
            / "structural_proofs.json"
        ).read_text(encoding="utf-8")
    )
    assert len(proofs) == 1


@pytest.mark.slow
def test_offline_pilot_duplicate_generation_degenerates_honestly(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("MASBENCH_SFT_STATE_KEY", raising=False)
    report = run_pilot(
        _args(tmp_path / "pilot-dup", fake_generated_value=1)
    )
    replicate = report["replicates"][0]
    # A generated value that duplicates registered content must abort the
    # sealed single-action experiment without fabricating probe evidence.
    assert replicate["status"] == "failed"
    assert "degenerate" in replicate.get("error", "")
    assert replicate.get("units", []) == []
    # The baseline arm still reports honestly.
    assert report["baseline"]["aggregate"]["cases_scored"] == 2.0
