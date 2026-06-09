"""Component A of the evolved self-design learning loop: in graph_generate mode
the evolution evidence rows carry the GENERATED spec's structural motifs (+ a
loss), so the motif-credit loop can learn which structures win. select mode is
unchanged.

Offline (fake) the generation falls back deterministically and Silo success is
topology-invariant, so this verifies the MECHANISM (motifs attached + aggregable),
not a score difference.
"""
from pathlib import Path

import masbench.bench as bench
import masbench.evolve as evolve
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution
from masbench.llm.fake import BenchmarkFakeLLMClient
from exp_graph.mas.motifs import aggregate_motif_losses
from exp_graph.mas.schemas import ObjectiveSpec
from exp_graph.mas.skill_bank import SkillBank

DATA = Path(__file__).parent / "data"


def _instance(n=2):
    return list(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[n], cases=["I-01"])
    )[0]


def _row(planner_mode):
    cfg = RunConfig(
        llm_provider="fake", planner_mode=planner_mode, n_agents=2,
        objective="accuracy_first", merge_mode="deterministic", init_mode="deterministic",
        num_graph_candidates=2,
    )
    return evolve._run_one(
        _instance(), cfg, objective=ObjectiveSpec.from_name("accuracy_first"),
        skill_bank=SkillBank(), seed=0, llm_client=BenchmarkFakeLLMClient(),
    )


def test_generate_mode_attaches_structural_motif_evidence():
    row = _row("graph_generate")
    assert row.get("motif_keys"), "generated evidence row must carry structural motif keys"
    assert "mean_primary_loss" in row
    # The motif machinery can aggregate it (non-empty credit map).
    assert aggregate_motif_losses([row])


def test_select_mode_unchanged_no_motif_keys():
    row = _row("topology_select")
    assert "motif_keys" not in row  # select-mode evidence is untouched


def test_run_evolution_generate_exposes_motif_stats():
    # B1: the loop aggregates the generated evidence into a motif-credit map.
    cfg = RunConfig(
        llm_provider="fake", planner_mode="graph_generate", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first", num_graph_candidates=2,
    )
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], train_seeds=[1],
        val_seeds=[1], cfg=cfg, levels=["I"], seed_incumbent_topology="mesh_star",
    )
    assert "evolved_motif_stats" in summary
    assert summary["evolved_motif_stats"]  # non-empty motif credit from generated evidence


def test_evolved_generate_eval_threads_motif_stats(monkeypatch, tmp_path):
    # D: the eval generation receives the learned motif prior (not None).
    seen = []
    orig = bench.run_instance

    def spy(inst, cfg, *, llm_client=None, motif_stats=None, skill_bank=None):
        seen.append(motif_stats)
        return orig(inst, cfg, llm_client=llm_client, motif_stats=motif_stats, skill_bank=skill_bank)

    monkeypatch.setattr(bench, "run_instance", spy)
    cfg = RunConfig(
        llm_provider="fake", merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate", num_graph_candidates=2,
    )
    bench.run_benchmark(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], seeds=[1],
        arms=["evolved"], cfg_base=cfg, out=tmp_path / "x", workers=1,
    )
    assert seen and any(ms for ms in seen)  # eval generation got the learned motif prior
