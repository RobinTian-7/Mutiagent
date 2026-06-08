"""Concurrency (``--workers N``) tests for ``masbench.bench`` (Plan 5 T3).

The paper-grade ``run_benchmark`` grid (instances x arms x seeds) is
embarrassingly parallel and I/O-bound (LLM calls release the GIL), so it can be
dispatched to a ``ThreadPoolExecutor``. These tests pin the guarantees added in
Plan 5 Task 3:

* **parallel == sequential aggregate** -- running the same grid with
  ``workers=1`` and ``workers=4`` (each into a fresh out dir) yields identical
  per-condition + overall success/partial means and the identical set of
  ``_run_key``s in ``runs.jsonl`` (aggregation is order-independent);
* **no double-append under races** -- with ``workers>1`` ``runs.jsonl`` has
  exactly one line per unique run-key (the checkpoint lock + up-front done-filter
  compose with the pool);
* **resume composes with the pool** -- a fully-checkpointed grid re-run with
  ``workers=4, resume=True`` executes nothing and leaves the aggregate unchanged.

All offline via ``--llm fake`` (deterministic, no network).
"""

from __future__ import annotations

import json
from pathlib import Path

import masbench.bench as bench
from masbench.bench import _run_key, run_benchmark
from masbench.core.config import RunConfig

from masbench.adapters.silo_bench import SiloBenchAdapter

DATA = Path(__file__).parent / "data"

# Cases that actually exist under tests/data (I-02 from the task brief does not).
CASES = ["I-01", "III-21"]
ARMS = ["fixed", "select", "graphgen"]
SEEDS = [1, 2]
AGENT_COUNTS = [2]
FIXED_TOPOLOGIES = ["tree", "chain"]


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


def _run(out: Path, *, workers: int, resume: bool = False) -> dict:
    return run_benchmark(
        _adapter(),
        cases=CASES,
        agent_counts=AGENT_COUNTS,
        seeds=SEEDS,
        arms=ARMS,
        cfg_base=_cfg(),
        fixed_topologies=FIXED_TOPOLOGIES,
        out=out,
        resume=resume,
        workers=workers,
    )


def _keys_in_jsonl(out: Path) -> list[tuple]:
    return [
        _run_key(json.loads(line))
        for line in (out / "runs.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _success_partial_means(results: dict) -> dict:
    """Flatten every per-condition x arm + overall x arm success/partial mean."""
    flat: dict[str, float] = {}
    for cond_key, block in results["conditions"].items():
        for arm, agg in block["arms"].items():
            flat[f"cond:{cond_key}:{arm}:success"] = agg["success"]["mean"]
            flat[f"cond:{cond_key}:{arm}:partial"] = agg["partial"]["mean"]
    for arm, agg in results["overall"].items():
        flat[f"overall:{arm}:success"] = agg["success"]["mean"]
        flat[f"overall:{arm}:partial"] = agg["partial"]["mean"]
    return flat


def test_workers_match_sequential(tmp_path) -> None:
    """workers=4 yields identical aggregates + run-key set as workers=1."""
    out_seq = tmp_path / "seq"
    out_par = tmp_path / "par"

    seq = _run(out_seq, workers=1)
    par = _run(out_par, workers=4)

    # Aggregates are order-independent: success/partial means match exactly.
    assert _success_partial_means(par) == _success_partial_means(seq)

    # The full set of produced run-keys is identical across worker counts.
    assert set(_keys_in_jsonl(out_par)) == set(_keys_in_jsonl(out_seq))
    # And the in-memory run set agrees too.
    assert {_run_key(r) for r in par["runs"]} == {_run_key(r) for r in seq["runs"]}


def test_workers_checkpoint_no_double_append(tmp_path) -> None:
    """workers=4: runs.jsonl has exactly one line per unique run-key (no races)."""
    out = tmp_path / "par"
    _run(out, workers=4)

    keys = _keys_in_jsonl(out)
    # Every run-key appears exactly once -> no duplicate appends from the pool.
    assert len(keys) == len(set(keys)), "duplicate run-keys in runs.jsonl"
    # Expected count: fixed (2 topo x 2 cases x 2 seeds = 8) + select (2x2=4)
    # + graphgen (2x2=4) = 16.
    assert len(keys) == 16


def test_workers_with_resume(tmp_path, monkeypatch) -> None:
    """A fully-checkpointed grid re-run with workers=4+resume executes nothing."""
    out = tmp_path / "par"
    first = _run(out, workers=4)

    # On resume, ANY execution of a run primitive is a bug -- everything is done.
    def _boom(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("run executed on resume but was already complete")

    monkeypatch.setattr(bench, "run_fixed_protocol", _boom)
    monkeypatch.setattr(bench, "run_instance", _boom)
    monkeypatch.setattr(bench, "run_evolution", _boom)

    second = _run(out, workers=4, resume=True)

    # Nothing re-ran; the aggregate matches the fresh parallel run.
    assert _success_partial_means(second) == _success_partial_means(first)
    assert {_run_key(r) for r in second["runs"]} == {_run_key(r) for r in first["runs"]}
    # runs.jsonl was not double-counted.
    keys = _keys_in_jsonl(out)
    assert len(keys) == len(set(keys)) == 16


def test_workers_evolved_arm_match_sequential(tmp_path) -> None:
    """The evolved arm (heavy run_evolution) matches across worker counts.

    run_evolution must run sequentially+once per n_agents before parallel eval
    dispatch; the eval run-units then go through the pool. The gate decision and
    eval aggregates must be identical to the sequential path.
    """
    out_seq = tmp_path / "seq"
    out_par = tmp_path / "par"

    common = dict(
        cases=["I-01", "III-21"],
        agent_counts=[2],
        seeds=[0],
        arms=["evolved"],
        cfg_base=_cfg(),
    )
    seq = run_benchmark(_adapter(), out=out_seq, workers=1, **common)
    par = run_benchmark(_adapter(), out=out_par, workers=4, **common)

    assert _success_partial_means(par) == _success_partial_means(seq)
    for key in ("I-01|n2", "III-21|n2"):
        gate_seq = seq["conditions"][key]["arms"]["evolved"]["gate"]
        gate_par = par["conditions"][key]["arms"]["evolved"]["gate"]
        assert gate_par == gate_seq
    assert set(_keys_in_jsonl(out_par)) == set(_keys_in_jsonl(out_seq))
