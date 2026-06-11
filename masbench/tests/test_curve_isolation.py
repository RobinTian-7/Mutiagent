"""Curve eval per-run isolation (P2 confirmatory-2 infra failure).

A single LLMTimeoutError in one held-out eval run crashed the WHOLE curve
(CURVE_EXIT=1 after ~$1 of spend). Like the verify scripts' eval, a failed
curve eval run must count as a failure for ITS arm (score 0) and the curve
must continue.
"""
from pathlib import Path

import masbench.curve as curve
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig

DATA = Path(__file__).parent / "data"


def test_one_failed_eval_run_does_not_crash_the_curve(monkeypatch):
    calls = {"n": 0}
    orig = curve._run_one

    def flaky(inst, cfg, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("LLM call exceeded 120.0s")
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(curve, "_run_one", flaky)
    cfg = RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="select_then_refine",
        num_graph_candidates=2,
    )
    result = curve.run_curves(
        SiloBenchAdapter(DATA), cfg, n_agents=2, seeds=[1, 2],
        levels=["I"], cases=["I-01"], data_points=1, rounds=1, workers=1,
    )
    assert calls["n"] > 1, "the curve continued past the failure"
    assert result["rounds_curve"], "curve completed"
