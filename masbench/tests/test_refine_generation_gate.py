"""Gate alignment for select_then_refine (deployed mode = GENERATION).

The old behaviour gated refine-mode evolution on topology-SELECTION J, which is
vacuously tied on small held-out sets (j_before == j_after on every real run we
inspected) while the deployed eval GENERATES. The gate must measure what
deploys: held-out generation loss with vs without the learned state.

On rejection the summary must export the PRE state (the eval consumes
``evolved_skills`` unconditionally — e.g. the frozen verify_evolve.py — so a
rejected bank must never leak through that channel).

``gate_mode="off"`` (RunConfig field or MASBENCH_GATE_MODE env) disables the
held-out gate entirely — the drift-ablation arm.
"""
from pathlib import Path

import masbench.evolve as evolve
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution

DATA = Path(__file__).parent / "data"


def _cfg(**kw) -> RunConfig:
    base = dict(
        llm_provider="fake", planner_mode="topology_select", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2,
    )
    base.update(kw)
    return RunConfig(**base)


def _evolve(cfg, **kw):
    return run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=cfg, levels=["I"], **kw,
    )


def test_refine_mode_uses_generation_gate():
    summary = _evolve(_cfg())
    assert summary["gate"].get("mode") == "generation"
    # offline Silo is topology-invariant -> no regression -> accepted, bank kept
    assert summary["gate"]["accepted"] is True
    assert summary["evolved_skills"], "accepted evolution must export the bank"


def test_rejected_gate_exports_pre_state(monkeypatch):
    def reject(*args, **kwargs):
        return {"accepted": False, "j_before": 0.0, "j_after": 1.0,
                "epsilon": 0.0, "mode": "generation"}

    monkeypatch.setattr(evolve, "_generation_gate", reject)
    summary = _evolve(_cfg())
    assert summary["gate"]["accepted"] is False
    assert summary["evolved_skills"] == [], "rejected state must not be exported"
    assert summary["evolved_motif_stats"] == {}
    assert summary["skill_bank_mutated"] is False
    assert summary["rejected_skill_ids"], "diagnostics keep what was rejected"


def test_rejected_gate_restores_initial_skills(monkeypatch):
    initial = _evolve(_cfg())["evolved_skills"]
    assert initial

    def reject(*args, **kwargs):
        return {"accepted": False, "j_before": 0.0, "j_after": 1.0,
                "epsilon": 0.0, "mode": "generation"}

    monkeypatch.setattr(evolve, "_generation_gate", reject)
    summary = _evolve(_cfg(), initial_skills=initial)
    exported = {s["skill_id"] for s in summary["evolved_skills"]}
    assert exported == {s["skill_id"] for s in initial}, "pre-state = the initial bank"


def test_gate_off_skips_gate_and_keeps_state(monkeypatch):
    called = {"n": 0}

    def boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("gate must not run when off")

    monkeypatch.setattr(evolve, "_generation_gate", boom)
    summary = _evolve(_cfg(gate_mode="off"))
    assert called["n"] == 0
    assert summary["gate"]["mode"] == "off"
    assert summary["gate"]["accepted"] is True
    assert summary["evolved_skills"]


def test_gate_off_via_env(monkeypatch):
    monkeypatch.setenv("MASBENCH_GATE_MODE", "off")
    summary = _evolve(_cfg())
    assert summary["gate"]["mode"] == "off"
    assert summary["evolved_skills"]


def test_generation_gate_survives_failing_runs(monkeypatch):
    """A wedged provider call inside the gate must not abort evolution.

    A failed gate run is charged the maximum loss (1.0) for ITS arm -- a run
    that cannot complete IS a deployment failure -- and the loop continues
    (mirrors _collect_rows' per-run isolation).
    """
    calls = {"n": 0}
    orig = evolve._run_one

    def flaky(inst, cfg, **kwargs):
        if kwargs.get("diag_phase", "").startswith("gate:"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("wedged provider call")
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", flaky)
    summary = _evolve(_cfg())
    assert calls["n"] >= 2, "gate ran both arms despite the failure"
    gate = summary["gate"]
    assert gate["mode"] == "generation"
    # offline runs solve I-01 (loss 0); the one failed before-run is charged 1.0
    assert gate["j_before"] > gate["j_after"]


def test_graph_generate_rejection_also_exports_pre_state(monkeypatch):
    def reject(*args, **kwargs):
        return {"accepted": False, "j_before": 0.0, "j_after": 1.0,
                "epsilon": 0.0, "mode": "generation"}

    monkeypatch.setattr(evolve, "_generation_gate", reject)
    summary = _evolve(_cfg(planner_mode="graph_generate", evolved_mode="graph_generate"))
    assert summary["gate"]["accepted"] is False
    assert summary["evolved_skills"] == []
    assert summary["evolved_motif_stats"] == {}
