"""Graceful degradation: a failure in the heavy evolution pre-run (which happens
SERIALLY, outside the per-run isolation that protects pool eval units) must NOT
abort the whole grid. The evolved arm for that n_agents is skipped + left
un-recorded (so --resume retries it once the provider recovers); every other arm
still completes.
"""
from __future__ import annotations

from pathlib import Path

import masbench.bench as bench
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig

DATA = Path(__file__).parent / "data"


def _cfg() -> RunConfig:
    return RunConfig(
        use_planner=False,
        llm_provider="fake",
        merge_mode="deterministic",
        init_mode="deterministic",
        objective="accuracy_first",
    )


def _boom(*_a, **_k):
    raise RuntimeError("simulated total provider outage")


def _run(out: Path, *, workers: int) -> dict:
    return bench.run_benchmark(
        SiloBenchAdapter(DATA),
        cases=["I-01", "III-21"],
        agent_counts=[2],
        seeds=[1, 2],
        arms=["fixed", "evolved"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=out,
        workers=workers,
    )


def test_evolution_failure_does_not_abort_parallel_grid(tmp_path, monkeypatch):
    # Parallel path pre-runs evolution via _compute_evolution_summary.
    monkeypatch.setattr(bench, "_compute_evolution_summary", _boom)
    results = _run(tmp_path / "par", workers=4)

    arms = {r["arm"] for r in results["runs"]}
    assert "fixed" in arms  # other arms still completed
    assert "evolved" not in arms  # skipped, not crashed


def test_evolution_failure_does_not_abort_sequential_grid(tmp_path, monkeypatch):
    # Sequential path calls run_evolution directly inside _run_evolved_arm.
    monkeypatch.setattr(bench, "run_evolution", _boom)
    results = _run(tmp_path / "seq", workers=1)

    arms = {r["arm"] for r in results["runs"]}
    assert "fixed" in arms
    assert "evolved" not in arms
