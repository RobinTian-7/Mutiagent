"""C: generation-aware gate. In graph_generate mode the evolution gate measures
held-out GENERATION loss with the PRE state (empty bank, no motif prior) vs the
POST state (evolved bank + motif_stats), accepting only if it doesn't regress.
This is what lets J actually move for self-design (vs the topology-select gate).

Offline (fake) Silo success is topology-invariant -> j_before == j_after ->
accepted; this checks the MECHANISM, not a real improvement.
"""
from pathlib import Path

import masbench.evolve as evolve
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution
from masbench.llm.fake import BenchmarkFakeLLMClient
from exp_graph.mas.schemas import ObjectiveSpec
from exp_graph.mas.skill_bank import SkillBank

DATA = Path(__file__).parent / "data"


def _cfg():
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first", num_graph_candidates=2,
    )


def test_generation_gate_shape_and_offline_accept():
    insts = list(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )
    gate = evolve._generation_gate(
        insts, _cfg(), val_seeds=[1], llm_client=BenchmarkFakeLLMClient(),
        evolved_bank=SkillBank(), motif_stats={}, epsilon=0.0,
        objective=ObjectiveSpec.from_name("accuracy_first"),
    )
    assert {"accepted", "j_before", "j_after"} <= set(gate)
    assert isinstance(gate["j_before"], float) and isinstance(gate["j_after"], float)
    assert gate["accepted"] is True  # topology-invariant offline -> no regression


def test_run_evolution_generate_uses_generation_gate():
    s = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2], train_seeds=[1],
        val_seeds=[2], cfg=_cfg(), levels=["I"],
    )
    assert s["gate"].get("mode") == "generation"
