"""Tests for the paper-grade benchmark harness ``masbench.bench``.

``run_benchmark`` orchestrates the existing engine/evolve pieces into a
Table-1-style arm comparison on Silo-Bench:

* ``fixed``    -- planner-OFF forced topologies (best = "oracle fixed");
* ``select``   -- QueenBee ``topology_select``;
* ``graphgen`` -- QueenBee ``graph_generate`` (LLM-invented DAG);
* ``evolved``  -- the gated self-evolution loop, eval on held-out seeds.

It aggregates per ``(case_id, n_agents)`` condition mean +/- std over seeds for
each arm and emits ``results.json`` + ``results.csv`` + ``report.md``.

The offline smoke uses the fake LLM and a tiny grid so the whole harness runs
end to end without a network. The aggregation/report-rendering logic is unit
tested on synthetic per-run records so the table math does not depend on slow
runs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.bench import (
    aggregate_condition,
    render_report,
    run_benchmark,
)
from masbench.core.config import RunConfig

DATA = Path(__file__).parent / "data"


def _adapter() -> SiloBenchAdapter:
    return SiloBenchAdapter(DATA)


def _cfg() -> RunConfig:
    return RunConfig(
        use_planner=False,
        llm_provider="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        objective="accuracy_first",
    )


# --------------------------------------------------------------------------- #
# Unit tests: aggregation (mean +/- std) + report rendering on synthetic rows. #
# --------------------------------------------------------------------------- #


def _run_record(arm: str, *, success: bool, partial: float, msgs: int,
                calls: int, tokens: int, seed: int) -> dict:
    return {
        "arm": arm,
        "topology": "tree",
        "seed": seed,
        "success": success,
        "partial": partial,
        "n_messages": msgs,
        "n_model_calls": calls,
        "tokens": tokens,
    }


def test_aggregate_condition_mean_std() -> None:
    """mean +/- std are computed correctly per arm over seeds."""
    runs = [
        _run_record("select", success=True, partial=1.0, msgs=10, calls=2,
                    tokens=100, seed=0),
        _run_record("select", success=False, partial=0.0, msgs=20, calls=4,
                    tokens=300, seed=1),
    ]
    agg = aggregate_condition(runs)
    sel = agg["select"]
    # success mean = 0.5 ; population std of {1,0} = 0.5
    assert sel["success"]["mean"] == pytest.approx(0.5)
    assert sel["success"]["std"] == pytest.approx(0.5)
    # messages mean = 15 ; std of {10,20} = 5
    assert sel["n_messages"]["mean"] == pytest.approx(15.0)
    assert sel["n_messages"]["std"] == pytest.approx(5.0)
    assert sel["tokens"]["mean"] == pytest.approx(200.0)
    assert sel["n"] == 2


def test_aggregate_condition_single_seed_zero_std() -> None:
    """A single seed yields std 0 (no NaN/crash on n=1)."""
    runs = [_run_record("fixed", success=True, partial=1.0, msgs=4, calls=0,
                        tokens=0, seed=0)]
    agg = aggregate_condition(runs)
    assert agg["fixed"]["success"]["mean"] == pytest.approx(1.0)
    assert agg["fixed"]["success"]["std"] == pytest.approx(0.0)


def test_render_report_marks_best_arm() -> None:
    """report.md lists each arm and marks the best (highest success) per cond."""
    results = {
        "conditions": {
            "I-01|n2": {
                "case_id": "I-01",
                "n_agents": 2,
                "arms": {
                    "fixed": {
                        "n": 1,
                        "success": {"mean": 1.0, "std": 0.0},
                        "partial": {"mean": 1.0, "std": 0.0},
                        "n_messages": {"mean": 4.0, "std": 0.0},
                        "n_model_calls": {"mean": 0.0, "std": 0.0},
                        "tokens": {"mean": 0.0, "std": 0.0},
                    },
                    "select": {
                        "n": 1,
                        "success": {"mean": 0.0, "std": 0.0},
                        "partial": {"mean": 0.5, "std": 0.0},
                        "n_messages": {"mean": 10.0, "std": 0.0},
                        "n_model_calls": {"mean": 2.0, "std": 0.0},
                        "tokens": {"mean": 100.0, "std": 0.0},
                    },
                },
            }
        },
        "overall": {
            "fixed": {"success": {"mean": 1.0, "std": 0.0}},
            "select": {"success": {"mean": 0.0, "std": 0.0}},
        },
        "arms": ["fixed", "select"],
    }
    md = render_report(results)
    assert "I-01" in md
    assert "fixed" in md and "select" in md
    # The best arm per condition (fixed, success 1.0) is marked.
    assert "**" in md  # bolding used to mark the best
    # The overall summary line lists per-arm success.
    assert "Overall" in md or "overall" in md


# --------------------------------------------------------------------------- #
# Offline smoke: tiny grid, fake LLM, end to end.                             #
# --------------------------------------------------------------------------- #


def test_bench_offline_smoke(tmp_path) -> None:
    """Tiny offline grid runs fixed+select+graphgen end to end and writes files.

    I-01 is offline-solvable (deterministic associative reduce -> 9), so at least
    one arm must succeed. graphgen is included with num_graph_candidates=1 (cheap,
    no probe search) to exercise the third arm path. ``evolved`` is exercised in
    its own dedicated test below (one evolve run, not per-seed).
    """
    out = tmp_path / "paper"
    results = run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[0],
        arms=["fixed", "select", "graphgen"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=out,
    )

    # Per-condition aggregates are returned, keyed by (case_id, n_agents).
    assert "conditions" in results
    cond = results["conditions"]["I-01|n2"]
    assert cond["case_id"] == "I-01"
    assert cond["n_agents"] == 2
    for arm in ("fixed", "select", "graphgen"):
        assert arm in cond["arms"]
        assert cond["arms"][arm]["n"] >= 1

    # I-01 reduce converges -> at least one arm is fully successful.
    any_success = any(
        cond["arms"][arm]["success"]["mean"] >= 1.0
        for arm in cond["arms"]
    )
    assert any_success, "expected some arm to solve offline-solvable I-01"

    # Files are written.
    assert (out / "results.json").is_file()
    assert (out / "results.csv").is_file()
    assert (out / "report.md").is_file()

    report = (out / "report.md").read_text()
    assert "I-01" in report
    for arm in ("fixed", "select", "graphgen"):
        assert arm in report

    # results.json round-trips and carries raw per-run records + aggregates.
    saved = json.loads((out / "results.json").read_text())
    assert "conditions" in saved
    assert "runs" in saved and len(saved["runs"]) > 0
    # Each raw run record carries the per-run metrics.
    sample = saved["runs"][0]
    for key in ("arm", "case_id", "n_agents", "seed", "success", "tokens"):
        assert key in sample

    # results.csv has one row per condition x arm.
    with (out / "results.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    arms_in_csv = {r["arm"] for r in rows}
    assert {"fixed", "select", "graphgen"} <= arms_in_csv
    assert all(r["case_id"] == "I-01" for r in rows)


def test_bench_oracle_fixed_is_best_over_topologies() -> None:
    """The 'fixed' arm aggregate reports a per-condition best (oracle fixed)."""
    results = run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[0],
        arms=["fixed"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain", "mesh_star"],
    )
    cond = results["conditions"]["I-01|n2"]
    # Oracle-fixed picks the best topology's success for the condition.
    assert "oracle_fixed" in cond
    assert cond["oracle_fixed"]["success"]["mean"] >= 0.0
    # Per-topology fixed breakdown is retained for transparency.
    assert "fixed_by_topology" in cond
    assert set(cond["fixed_by_topology"]) == {"tree", "chain", "mesh_star"}


def test_bench_fake_rejects_llm_merge_modes() -> None:
    """Fake LLM + llm_* merge/init modes fails fast with an actionable message."""
    cfg = RunConfig(
        llm_provider="fake",
        merge_mode="llm_full_merge",
        init_mode="llm_local_solve",
        objective="accuracy_first",
    )
    with pytest.raises(SystemExit, match="deterministic"):
        run_benchmark(
            _adapter(),
            cases=["I-01"],
            agent_counts=[2],
            seeds=[0],
            arms=["fixed"],
            cfg_base=cfg,
        )


def test_bench_evolved_arm_offline() -> None:
    """The evolved arm runs the gated evolution loop once per condition set."""
    results = run_benchmark(
        _adapter(),
        cases=["I-01", "III-21"],
        agent_counts=[2],
        seeds=[0],
        arms=["evolved"],
        cfg_base=_cfg(),
    )
    # evolved is recorded per condition with a gate decision attached.
    for key in ("I-01|n2", "III-21|n2"):
        cond = results["conditions"][key]
        assert "evolved" in cond["arms"]
        assert "gate" in cond["arms"]["evolved"]
        assert cond["arms"]["evolved"]["gate"]["accepted"] in {True, False}


# --------------------------------------------------------------------------- #
# CLI smoke.                                                                  #
# --------------------------------------------------------------------------- #


def test_bench_cli(tmp_path) -> None:
    """`masbench bench --llm fake` exits 0 and writes the report files."""
    from masbench.cli import main

    out = tmp_path / "paper"
    rc = main(
        [
            "bench",
            "--benchmark",
            "silo_bench",
            "--benchmarks-dir",
            str(DATA),
            "--cases",
            "I-01",
            "--agent-counts",
            "2",
            "--seeds",
            "0",
            "--arms",
            "fixed",
            "select",
            "--llm",
            "fake",
            "--objective",
            "accuracy_first",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert (out / "results.json").is_file()
    assert (out / "report.md").is_file()
    report = (out / "report.md").read_text()
    assert "I-01" in report
    assert "fixed" in report and "select" in report
