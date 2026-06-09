"""The evolved arm's self-design mode (evolved_mode='graph_generate'):

* run_evolution exposes its evolved skill bank (serialized) so the eval can
  rebuild it across the cache/parallel boundary;
* in graph_generate mode the eval GENERATES a DAG via run_instance using that
  evolved bank, instead of running a fixed named topology;
* in the default topology_select mode the eval never generates (unchanged).

All offline via --llm fake (deterministic merge/init -> no network).
"""
from pathlib import Path

import masbench.bench as bench
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution
from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

DATA = Path(__file__).parent / "data"


def _cfg(**over) -> RunConfig:
    return RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", **over,
    )


def test_run_evolution_exposes_evolved_skills():
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[1], cfg=_cfg(), levels=["I"],
        seed_incumbent_topology="mesh_star",
    )
    assert "evolved_skills" in summary
    skills = summary["evolved_skills"]
    assert isinstance(skills, list)
    # Round-trips back into a SkillBank whose ids match the reported final bank.
    bank = SkillBank(skills=[SkillCard.model_validate(s) for s in skills])
    assert sorted(s.skill_id for s in bank) == summary["skill_ids_after"]


def test_evolved_generate_mode_evaluates_via_generation(monkeypatch, tmp_path):
    seen = {"calls": 0, "banks": []}
    orig = bench.run_instance

    def spy(inst, cfg, *, llm_client=None, motif_stats=None, skill_bank=None):
        seen["calls"] += 1
        seen["banks"].append(skill_bank)
        return orig(inst, cfg, llm_client=llm_client, motif_stats=motif_stats, skill_bank=skill_bank)

    monkeypatch.setattr(bench, "run_instance", spy)
    bench.run_benchmark(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], seeds=[1],
        arms=["evolved"], cfg_base=_cfg(evolved_mode="graph_generate"),
        out=tmp_path / "gen", workers=1,
    )
    # The eval generated a DAG (run_instance called) using a non-empty evolved bank.
    assert seen["calls"] >= 1
    assert any(b is not None and len(b) >= 1 for b in seen["banks"])


def test_evolved_select_mode_does_not_generate(monkeypatch, tmp_path):
    seen = {"calls": 0}
    orig = bench.run_instance

    def spy(*a, **k):
        seen["calls"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(bench, "run_instance", spy)
    bench.run_benchmark(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], seeds=[1],
        arms=["evolved"], cfg_base=_cfg(),  # default evolved_mode=topology_select
        out=tmp_path / "sel", workers=1,
    )
    assert seen["calls"] == 0  # select mode evaluates a fixed topology, never generates
