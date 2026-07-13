"""Tests for the masbench QueenBee self-evolution loop on Silo-Bench.

These exercise ``masbench.evolve.run_evolution`` end-to-end OFFLINE with the fake
LLM. The loop runs real Silo-Bench instances through the QueenBee planner +
ProtocolRunner, turns each run into an aggregate row, has the ResultAnalyst
minister propose patches, and applies them through the held-out *validation gate*
(``consolidate_skill_updates(gate=True)``) with the Plan-3 improvement knobs
(uncertainty/veto/floor) active on the planner requests.

Silo's deterministic offline path is topology-invariant on success (every
topology either solves a case or not), so the held-out distinguishing signal is
supplied as a small synthetic multi-topology held-out set; the gate decision
itself (J_before/J_after, accept/reject, and whether the bank mutates) is real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import (
    INCUMBENT_BASELINE_TOPOLOGY,
    accepting_held_out_rows,
    rejecting_held_out_rows,
    run_evolution,
)

DATA = Path(__file__).parent / "data"


def _adapter() -> SiloBenchAdapter:
    return SiloBenchAdapter(DATA)


def _cfg() -> RunConfig:
    return RunConfig(
        use_planner=True,
        use_skill_evolution=True,
        llm_provider="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        objective="accuracy_first",
    )


def test_evolution_loop_runs_offline() -> None:
    """run_evolution returns a real gate decision and only mutates on accept."""
    summary = run_evolution(
        _adapter(),
        cases=["I-01", "III-21"],
        agent_counts=[2],
        train_seeds=[0],
        val_seeds=[0],
        cfg=_cfg(),
    )

    # A real gate decision is reported.
    assert summary["gate"]["accepted"] in {True, False}
    assert isinstance(summary["gate"]["j_before"], float)
    assert isinstance(summary["gate"]["j_after"], float)

    # The loop actually ran real Silo planner runs and built rows from them.
    assert summary["n_train_rows"] > 0
    assert summary["n_val_rows"] > 0
    assert summary["train_success_rate"] >= 0.0
    assert summary["val_success_rate"] >= 0.0

    # The improvement knobs the loop activates are recorded for transparency.
    knobs = summary["objective_knobs"]
    assert knobs["uncertainty_weight"] > 0.0
    assert knobs["min_seeds"] >= 1
    assert knobs["enforce_avoid_veto"] is True
    assert knobs["risk_weight"] > 0.0

    # The held-out bank is mutated iff the gate accepted.
    if summary["gate"]["accepted"]:
        assert summary["skill_bank_size_after"] >= summary["skill_bank_size_before"]
        assert summary["skill_bank_mutated"] is True
    else:
        assert summary["skill_bank_mutated"] is False

    snapshots = summary["skill_bank_snapshots"]
    assert set(snapshots) == {"before", "candidate", "deployed"}
    assert snapshots["deployed"] == summary["evolved_skills"]
    if summary["gate"]["accepted"]:
        assert snapshots["candidate"] == snapshots["deployed"]

    # The post-evolution selection probe genuinely ran the E/F selection logic on
    # the populated bank: the breakdown carries the LCB (E) diagnostics and the
    # objective's uncertainty weight is the knob-on value.
    probe = summary["final_selection"]
    assert isinstance(probe["topology_name"], str) and probe["topology_name"]
    assert probe["score_breakdown"]["uncertainty_weight"] == knobs["uncertainty_weight"]
    assert "loss_lcb" in probe["score_breakdown"]


def test_evolution_gate_accepts_improving_update() -> None:
    """A held-out set where the incumbent is suboptimal yields a real ACCEPT."""
    summary = run_evolution(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        train_seeds=[0],
        val_seeds=[0],
        cfg=_cfg(),
        held_out_rows=accepting_held_out_rows(),
        seed_incumbent_topology=INCUMBENT_BASELINE_TOPOLOGY,
    )
    gate = summary["gate"]
    assert gate["accepted"] is True
    assert gate["j_after"] < gate["j_before"]
    assert summary["skill_bank_mutated"] is True


def test_evolution_gate_rejects_regressing_update() -> None:
    """A held-out set where the update would regress selection yields a REJECT."""
    summary = run_evolution(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        train_seeds=[0],
        val_seeds=[0],
        cfg=_cfg(),
        held_out_rows=rejecting_held_out_rows(),
        seed_incumbent_topology=INCUMBENT_BASELINE_TOPOLOGY,
    )
    gate = summary["gate"]
    assert gate["accepted"] is False
    assert gate["j_after"] > gate["j_before"]
    # On rejection the held-out bank is left untouched.
    assert summary["skill_bank_mutated"] is False
    assert summary["skill_bank_size_after"] == summary["skill_bank_size_before"]
    snapshots = summary["skill_bank_snapshots"]
    assert snapshots["deployed"] == snapshots["before"]
    assert snapshots["deployed"] == summary["evolved_skills"]


def test_evolution_loop_is_deterministic_offline() -> None:
    """Two offline runs with the same inputs produce identical gate decisions."""
    kwargs = dict(
        cases=["I-01", "III-21"],
        agent_counts=[2],
        train_seeds=[0],
        val_seeds=[0],
        cfg=_cfg(),
    )
    first = run_evolution(_adapter(), **kwargs)
    second = run_evolution(_adapter(), **kwargs)
    assert first["gate"] == second["gate"]
    assert first["n_train_rows"] == second["n_train_rows"]


def test_cli_evolve_writes_summary(tmp_path) -> None:
    """`masbench evolve` smoke: writes a summary json with the gate decision."""
    import json

    from masbench.cli import main

    out = tmp_path / "evolve"
    rc = main(
        [
            "evolve",
            "--benchmark",
            "silo_bench",
            "--benchmarks-dir",
            str(DATA),
            "--cases",
            "I-01",
            "III-21",
            "--agent-counts",
            "2",
            "--objective",
            "accuracy_first",
            "--llm",
            "fake",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text())
    assert "gate" in summary
    assert summary["gate"]["accepted"] in {True, False}
    assert isinstance(summary["gate"]["j_before"], float)
    assert isinstance(summary["gate"]["j_after"], float)
    assert summary["n_train_rows"] > 0
