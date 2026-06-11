"""Evidence cache: skip re-measuring bank-INDEPENDENT runs (opt-in).

Measured waste in dev rounds: rounds 2..R re-collect identical named-topology
evidence (empty bank, temp 0 -> deterministic), and the generation gate's
j_before (empty bank, cold) is recomputed every round. With
``MASBENCH_EVIDENCE_CACHE=<file>`` those runs are served from a persistent
JSON cache. Bank-DEPENDENT runs (explore, gate j_after, paired eval) are NEVER
cached. Env unset -> byte-identical behaviour.
"""
import json
from pathlib import Path

import masbench.evolve as evolve
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.cache import EvidenceCache
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution

DATA = Path(__file__).parent / "data"


def _cfg() -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="topology_select", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2,
    )


def _evolve(**kw):
    return run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"], **kw,
    )


def test_cache_roundtrip_and_persistence(tmp_path):
    path = tmp_path / "cache.json"
    cache = EvidenceCache(path)
    key = cache.key(case_id="I-01", n_agents=2, planner_mode="topology_select",
                    objective="accuracy_first", seed=1, cfg=_cfg())
    assert cache.get(key) is None
    cache.put(key, {"Topology": "tree", "ExactMatchRate": 1.0})
    assert cache.get(key)["Topology"] == "tree"
    # fresh instance reads the persisted file
    assert EvidenceCache(path).get(key)["ExactMatchRate"] == 1.0


def test_key_differs_by_condition_and_model():
    cache = EvidenceCache(None)
    base = dict(case_id="I-01", n_agents=2, planner_mode="topology_select",
                objective="accuracy_first", seed=1)
    k1 = cache.key(**base, cfg=_cfg())
    assert cache.key(**{**base, "seed": 2}, cfg=_cfg()) != k1
    assert cache.key(**{**base, "case_id": "I-02"}, cfg=_cfg()) != k1
    other_model = RunConfig(**{**_cfg().__dict__, "model_name": "gpt-99"})
    assert cache.key(**base, cfg=other_model) != k1


def test_second_evolution_reuses_named_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("MASBENCH_EVIDENCE_CACHE", str(tmp_path / "ev.json"))
    calls = {"n": 0}
    orig = evolve._run_one

    def counting(inst, cfg, **kwargs):
        if kwargs.get("diag_phase", "").startswith("evidence"):
            calls["n"] += 1
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", counting)
    _evolve()
    first = calls["n"]
    assert first > 0
    _evolve()  # same split+seeds -> every named evidence run served from cache
    assert calls["n"] == first, "second round must not re-run named evidence"


def test_explore_and_gate_after_never_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("MASBENCH_EVIDENCE_CACHE", str(tmp_path / "ev.json"))
    phases = []
    orig = evolve._run_one

    def tracking(inst, cfg, **kwargs):
        phases.append(kwargs.get("diag_phase", ""))
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", tracking)
    _evolve()
    explore_first = phases.count("explore")
    after_first = phases.count("gate:after")
    phases.clear()
    _evolve()
    assert phases.count("explore") == explore_first, "explore is bank-dependent, must re-run"
    assert phases.count("gate:after") == after_first, "j_after is bank-dependent, must re-run"
    assert phases.count("gate:before") == 0, "j_before (empty bank, cold) is cached"


def test_no_cache_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MASBENCH_EVIDENCE_CACHE", raising=False)
    calls = {"n": 0}
    orig = evolve._run_one

    def counting(inst, cfg, **kwargs):
        calls["n"] += 1
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", counting)
    _evolve()
    first = calls["n"]
    _evolve()
    assert calls["n"] == 2 * first, "without env the behaviour is unchanged"


def test_refine_mode_skips_val_evidence_collection():
    summary = _evolve()
    # single-gate refine: selection gate inactive -> val evidence rows are dead
    # weight; the pipeline must not collect them.
    assert summary["n_val_rows_real"] == 0
    assert summary["gate"]["mode"] == "generation"
