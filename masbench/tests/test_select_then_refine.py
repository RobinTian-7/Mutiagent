"""select_then_refine evolved mode: evidence via topology_select (so the bank's
minister skills carry the WORKING topologies' reference protocol_specs), then the
eval GENERATES a DAG the emperor refines from those references (anchor-on-what-
works, vs from-scratch graph_generate).
"""
from pathlib import Path

import masbench.bench as bench
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig

DATA = Path(__file__).parent / "data"


def test_select_then_refine_evidence_select_eval_generates(monkeypatch, tmp_path):
    seen = {"calls": 0, "banks": []}
    orig = bench.run_instance

    def spy(inst, cfg, *, llm_client=None, motif_stats=None, skill_bank=None):
        seen["calls"] += 1
        seen["banks"].append(skill_bank)
        return orig(inst, cfg, llm_client=llm_client, motif_stats=motif_stats, skill_bank=skill_bank)

    monkeypatch.setattr(bench, "run_instance", spy)
    cfg = RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="select_then_refine", num_graph_candidates=2,
    )
    bench.run_benchmark(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], seeds=[1],
        arms=["evolved"], cfg_base=cfg, out=tmp_path / "x", workers=1,
    )
    # The eval GENERATES (run_instance), anchored on a non-empty bank whose skills
    # carry the working topologies' reference protocol_specs (what it refines).
    assert seen["calls"] >= 1
    bank = next(b for b in seen["banks"] if b is not None)
    assert any("protocol_spec" in (sk.organization_policy or {}) for sk in bank)
