"""Round-2 stability fixes: LCB retrieval (M4a), LCB motif prior (M4b),
gate seed expansion + one-miss tolerance (M5).

Dev round 1 evidence: (a) a 1-row lucky explore organization displaced the
proven champion in raw-mean retrieval order (held-out II-15 88% -> 62%);
(b) the 3-sample binary gate rejected a genuinely-good round-1 bank
(cold 3/3 vs deployed 2/3).
"""

from __future__ import annotations

from pathlib import Path

import masbench.evolve as evolve
from exp_graph.mas.motifs import score_spec_by_motifs
from exp_graph.mas.schemas import PlannerRequest, ObjectiveSpec, SkillCard
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols.spec import ProtocolGraphSpec, ProtocolStepSpec
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import run_evolution

DATA = Path(__file__).parent / "data"


def _skill(skill_id: str, loss: float, n_rows: int) -> SkillCard:
    return SkillCard(
        skill_id=skill_id,
        objective="balanced",
        task_family="silo",
        trigger={"task_family": "silo", "min_agents": 1, "max_agents": 999},
        organization_policy={"topology_name": skill_id},
        expected_tradeoff={
            "mean_primary_loss": loss,
            "active_evidence_count": n_rows,
        },
        confidence={"seed_count": n_rows},
        tags=["mas", "silo"],
    )


def test_lcb_retrieval_veteran_beats_lucky_one_row():
    veteran = _skill("veteran", loss=0.25, n_rows=16)
    lucky = _skill("lucky", loss=0.0, n_rows=1)
    bank = SkillBank(skills=[lucky, veteran])
    request = PlannerRequest(
        task_family="silo", n_agents=5, objective=ObjectiveSpec.from_name("balanced")
    )
    order = [s.skill_id for s in bank.retrieve(request)]
    assert order.index("veteran") < order.index("lucky"), order


def test_cf_skills_without_loss_key_keep_raw_rmse_order():
    a = SkillCard(
        skill_id="cf_a", objective="balanced", task_family="count_frequency",
        trigger={"task_family": "count_frequency"},
        organization_policy={"topology_name": "tree"},
        expected_tradeoff={"mean_rmse": 0.1, "active_evidence_count": 1},
        tags=["mas"],
    )
    b = SkillCard(
        skill_id="cf_b", objective="balanced", task_family="count_frequency",
        trigger={"task_family": "count_frequency"},
        organization_policy={"topology_name": "mesh"},
        expected_tradeoff={"mean_rmse": 0.2, "active_evidence_count": 99},
        tags=["mas"],
    )
    bank = SkillBank(skills=[b, a])
    request = PlannerRequest(
        task_family="count_frequency", n_agents=4,
        objective=ObjectiveSpec.from_name("balanced"),
    )
    order = [s.skill_id for s in bank.retrieve(request)]
    # Raw mean_rmse ascending: the 1-row 0.1 still beats the 99-row 0.2 (no LCB).
    assert order.index("cf_a") < order.index("cf_b"), order


def _spec(name: str, edges: list[tuple[int, int]]) -> ProtocolGraphSpec:
    return ProtocolGraphSpec(
        name=name, n_agents=3,
        steps=[ProtocolStepSpec(transmissions=edges, description="s", operator="replay")],
        metadata={"graph_type": "temporal_dag"},
    )


def test_motif_lcb_penalizes_one_run_motifs():
    spec = _spec("x", [(0, 2), (1, 2)])
    keys = __import__("exp_graph.mas.motifs", fromlist=["spec_motif_keys"]).spec_motif_keys(spec)
    lucky_stats = {keys[0]: {"mean_loss": 0.0, "n": 1}}
    veteran_stats = {keys[0]: {"mean_loss": 0.2, "n": 16}}
    # kappa=0: historical behavior (lucky scores better).
    assert score_spec_by_motifs(spec, lucky_stats) < score_spec_by_motifs(spec, veteran_stats)
    # kappa=0.5: pessimism flips it (0+0.5 vs 0.2+0.125).
    assert score_spec_by_motifs(spec, lucky_stats, uncertainty_kappa=0.5) > \
        score_spec_by_motifs(spec, veteran_stats, uncertainty_kappa=0.5)


def _cfg(**kw) -> RunConfig:
    base = dict(
        llm_provider="fake", planner_mode="topology_select", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2, n_agents=2,
    )
    base.update(kw)
    return RunConfig(**base)


def test_gate_seed_expansion_and_one_miss_tolerance(monkeypatch):
    """factor=3 with 1 val seed x 1 val instance -> 3 samples per arm; a single
    extra miss (j_after - j_before = 1/3) is tolerated, two are not."""
    calls = {"gate:before": [], "gate:after": []}
    orig = evolve._run_one

    def fake_run_one(inst, cfg, **kwargs):
        phase = kwargs.get("diag_phase", "")
        if phase in calls:
            calls[phase].append(kwargs["seed"])
            if phase == "gate:before":
                return {"ExactMatchRate": 1.0, "mean_primary_loss": 0.0}
            # exactly one missed ROW across the whole gate:after grid
            # (M24: 2 singleton-bucket val instances x 3 derived seeds)
            miss = len(calls["gate:after"]) == 1
            return {"ExactMatchRate": 0.0 if miss else 1.0,
                    "mean_primary_loss": 1.0 if miss else 0.0}
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", fake_run_one)
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "ORD-50"], agent_counts=[2],
        train_seeds=[1, 2], val_seeds=[3], cfg=_cfg(gate_seed_factor=3),
        levels=["I", "ORD"],
    )
    gate = summary["gate"]
    # M5 seed expansion x3; M24 stratified carve puts BOTH singleton-bucket
    # cases (I-01=of, ORD-50=os) into val -> 2 instances x 3 gate seeds.
    assert gate["n_samples"] == 6
    assert sorted(set(calls["gate:before"])) == [3, 1012, 2021]
    assert abs(gate["j_after"] - 1.0 / 6.0) < 1e-9
    assert gate["accepted"] is True, gate  # one miss tolerated


def test_gate_two_misses_still_reject(monkeypatch):
    orig = evolve._run_one

    def fake_run_one(inst, cfg, **kwargs):
        phase = kwargs.get("diag_phase", "")
        if phase == "gate:before":
            return {"ExactMatchRate": 1.0, "mean_primary_loss": 0.0}
        if phase == "gate:after":
            return {"ExactMatchRate": 0.0, "mean_primary_loss": 1.0}
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", fake_run_one)
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "ORD-50"], agent_counts=[2],
        train_seeds=[1, 2], val_seeds=[3], cfg=_cfg(gate_seed_factor=3),
        levels=["I", "ORD"],
    )
    assert summary["gate"]["accepted"] is False
    assert summary["evolved_skills"] == []
