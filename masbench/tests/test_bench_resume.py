"""Crash-safety / checkpoint / resume tests for ``masbench.bench`` (Plan 5 T2).

The paper-grade ``run_benchmark`` grid is long-running; a single hung or failing
run must not abort the whole grid or lose already-completed work. These tests
pin the three guarantees added in Plan 5 Task 2:

* **checkpoint** -- every run record (success or failed) is appended as one JSON
  line to ``out/runs.jsonl`` as it is produced, so a crash mid-grid keeps the
  finished runs on disk;
* **resume** -- re-running with ``resume=True`` reads ``out/runs.jsonl`` and
  SKIPS any run whose ``_run_key`` is already complete (nothing re-executes) while
  still including those records in the final aggregate;
* **isolation** -- any exception from an individual run (incl. ``LLMTimeoutError``)
  is caught and recorded as a FAILED run record; the rest of the grid completes
  and ``run_benchmark`` returns normally.

All offline via ``--llm fake`` (deterministic, no network).
"""

from __future__ import annotations

import json
from pathlib import Path

import masbench.bench as bench
from masbench.bench import run_benchmark
from masbench.core.config import RunConfig
from masbench.llm.timeout import LLMTimeoutError

from masbench.adapters.silo_bench import SiloBenchAdapter

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


def test_checkpoint_writes_runs_jsonl(tmp_path) -> None:
    """Each run is appended to out/runs.jsonl; results.json/report.md still made."""
    out = tmp_path / "paper"
    results = run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=out,
    )

    runs_jsonl = out / "runs.jsonl"
    assert runs_jsonl.is_file(), "checkpoint runs.jsonl must be written"

    lines = [
        line for line in runs_jsonl.read_text().splitlines() if line.strip()
    ]
    # fixed: 2 topologies x 1 seed = 2 ; select: 1 seed = 1 ; total = 3.
    assert len(lines) == len(results["runs"]) == 3
    # Every line is a well-formed run record carrying the per-run metric shape.
    for line in lines:
        rec = json.loads(line)
        for key in ("arm", "case_id", "n_agents", "seed", "success", "tokens"):
            assert key in rec

    # The normal final outputs are still produced.
    assert (out / "results.json").is_file()
    assert (out / "results.csv").is_file()
    assert (out / "report.md").is_file()


def test_resume_skips_completed(tmp_path, monkeypatch) -> None:
    """A resumed run re-executes nothing already in runs.jsonl, same aggregate."""
    out = tmp_path / "paper"
    first = run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=out,
    )

    # On the resumed pass, ANY actual execution of a run unit is a bug: every
    # (arm,case,n,seed,topology) is already checkpointed. Make the underlying
    # run primitives explode so a re-execution is caught immediately.
    def _boom(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("run executed on resume but was already complete")

    monkeypatch.setattr(bench, "run_fixed_protocol", _boom)
    monkeypatch.setattr(bench, "run_instance", _boom)

    second = run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=out,
        resume=True,
    )

    # Nothing re-ran, yet the aggregate is identical to the fresh run.
    assert len(second["runs"]) == len(first["runs"]) == 3
    assert second["overall"] == first["overall"]
    assert second["conditions"] == first["conditions"]
    # runs.jsonl was not double-counted (still exactly 3 lines).
    lines = [
        line
        for line in (out / "runs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(lines) == 3


def test_failed_run_is_isolated(tmp_path, monkeypatch) -> None:
    """A run that raises LLMTimeoutError is recorded failed; the grid completes."""
    out = tmp_path / "paper"

    real_run_fixed = bench.run_fixed_protocol

    def _maybe_boom(instance, cfg, *, topology, llm_client=None):
        # Only the 'tree' fixed run hangs; every other run is unaffected.
        if topology == "tree":
            raise LLMTimeoutError("LLM call exceeded 90.0s")
        return real_run_fixed(
            instance, cfg, topology=topology, llm_client=llm_client
        )

    monkeypatch.setattr(bench, "run_fixed_protocol", _maybe_boom)

    # The grid must NOT raise even though one run throws.
    results = run_benchmark(
        _adapter(),
        cases=["I-01"],
        agent_counts=[2],
        seeds=[1],
        arms=["fixed", "select"],
        cfg_base=_cfg(),
        fixed_topologies=["tree", "chain"],
        out=out,
    )

    # All runs are present (3 total): the failed 'tree' run + the rest.
    assert len(results["runs"]) == 3
    failed = [r for r in results["runs"] if not r["success"] and r["arm"] == "fixed"]
    assert len(failed) == 1
    rec = failed[0]
    # Failed record shape: zeroed metrics + an error string in extra.
    assert rec["fixed_topology"] == "tree"
    assert rec["partial"] == 0.0
    assert rec["n_messages"] == 0
    assert rec["n_model_calls"] == 0
    assert rec["tokens"] == 0
    assert rec["final_answer"] is None
    assert "error" in rec
    assert "LLMTimeoutError" in rec["error"]

    # The OTHER fixed run (chain) and the select run still executed for real.
    chain = [r for r in results["runs"] if r.get("fixed_topology") == "chain"]
    assert len(chain) == 1
    assert "error" not in chain[0]
    assert any(r["arm"] == "select" for r in results["runs"])

    # The failed record was also checkpointed to runs.jsonl.
    jsonl = [
        json.loads(line)
        for line in (out / "runs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any("error" in r for r in jsonl)
