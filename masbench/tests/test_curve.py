"""Evolution learning curves: disjoint TRAIN/TEST case split, a data-amount curve
and a rounds curve, with baselines on the held-out set. Offline (fake) Silo is
topology-invariant so scores are flat; these pin the STRUCTURE.
"""
from pathlib import Path

import pytest

from masbench import curve
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig

BENCH = Path(__file__).parent.parent / "third_party" / "acl26-silo-bench" / "benchmarks"


def test_split_cases_is_disjoint():
    assert curve._split_cases(["a", "b", "c", "d"], 0.5) == (["a", "b"], ["c", "d"])
    assert curve._split_cases(["a", "b", "c"], 0.34) == (["a", "b"], ["c"])
    tr, te = curve._split_cases(["only"], 0.5)
    assert tr == te == ["only"]  # single case -> reuse (degenerate)


def test_merge_motif_weighted():
    a = {"x": {"mean_loss": 0.0, "n": 2}}
    b = {"x": {"mean_loss": 1.0, "n": 2}, "y": {"mean_loss": 0.5, "n": 1}}
    m = curve._merge_motif(a, b)
    assert m["x"] == {"mean_loss": 0.5, "n": 4}  # weighted mean across rounds
    assert m["y"] == {"mean_loss": 0.5, "n": 1}


@pytest.mark.skipif(not BENCH.exists(), reason="silo benchmarks submodule not present")
def test_run_curves_structure():
    cfg = RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate", num_graph_candidates=2,
    )
    res = curve.run_curves(
        SiloBenchAdapter(str(BENCH)), cfg, n_agents=2, seeds=[1, 2], levels=["I"],
        cases=["I-01", "I-02", "I-03", "I-04"], holdout_frac=0.5, data_points=2, rounds=2,
    )
    assert set(res["train_cases"]).isdisjoint(res["test_cases"]) and res["test_cases"]
    assert {"select", "graphgen"} <= set(res["baselines"])
    assert res["data_curve"][0]["k_cases"] == 0 and len(res["data_curve"]) >= 2
    assert res["rounds_curve"][0]["round"] == 0 and len(res["rounds_curve"]) == 3
    for pt in res["data_curve"] + res["rounds_curve"]:
        assert isinstance(pt["score"], float)


@pytest.mark.skipif(not BENCH.exists(), reason="silo benchmarks submodule not present")
def test_run_curves_workers_match_sequential():
    """workers>1 only fans out independent units -> identical curves offline."""
    kw = dict(
        n_agents=2, seeds=[1, 2], levels=["I"],
        cases=["I-01", "I-02", "I-03", "I-04"], holdout_frac=0.5,
        data_points=2, rounds=2,
    )

    def _curve(workers):
        cfg = RunConfig(
            llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
            objective="accuracy_first", evolved_mode="graph_generate", num_graph_candidates=2,
        )
        return curve.run_curves(SiloBenchAdapter(str(BENCH)), cfg, workers=workers, **kw)

    seq, par = _curve(1), _curve(4)
    assert seq["baselines"] == par["baselines"]
    assert [p["score"] for p in seq["data_curve"]] == [p["score"] for p in par["data_curve"]]
    assert [p["score"] for p in seq["rounds_curve"]] == [p["score"] for p in par["rounds_curve"]]
