"""M1/M2/M3 wiring through run_evolution and the deployment path.

Offline (fake LLM) Silo is topology-invariant, so these tests pin MECHANISM:
rows carry feature buckets, skills accumulate per-bucket ledgers across
rounds, portfolio (chain) evidence reaches the minister with an executable
spec, deployment abstains to the exact cold inputs on uncovered buckets, and
the ratchet gate rejects a round that is worse than its incumbent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import masbench.evolve as evolve
from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import evolution_objective_spec, run_evolution
from masbench.transfer import TRANSFER_EVIDENCE_KEY

DATA = Path(__file__).parent / "data"
LEVELS = ["I", "ORD"]


def _cfg(**kw) -> RunConfig:
    base = dict(
        llm_provider="fake", planner_mode="topology_select", merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2, n_agents=2,
    )
    base.update(kw)
    return RunConfig(**base)


def _evolve(cfg=None, **kw):
    return run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "ORD-50"], agent_counts=[2],
        train_seeds=[1, 2], val_seeds=[3], cfg=cfg or _cfg(), levels=LEVELS, **kw,
    )


def _skill_with(summary, predicate):
    return [s for s in summary["evolved_skills"] if predicate(s)]


def test_skills_carry_bucket_ledgers_and_chain_portfolio():
    # 3 cases: even/odd instance split puts {I-01, ORD-50} in evolution-TRAIN
    # (III-21 -> val), so evidence covers both the 'of' and 'os' buckets.
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01", "III-21", "ORD-50"], agent_counts=[2],
        train_seeds=[1, 2], val_seeds=[3], cfg=_cfg(), levels=["I", "III", "ORD"],
    )
    assert summary["n_portfolio_rows"] > 0
    chain = _skill_with(
        summary,
        lambda s: (s.get("organization_policy") or {}).get("topology_name") == "chain",
    )
    assert chain, "portfolio chain evidence must produce a chain skill"
    spec = (chain[0]["organization_policy"] or {}).get("protocol_spec")
    assert isinstance(spec, dict) and spec.get("steps")
    ledgers = [
        (s["skill_id"], (s.get("organization_policy") or {}).get(TRANSFER_EVIDENCE_KEY))
        for s in summary["evolved_skills"]
        if (s.get("organization_policy") or {}).get(TRANSFER_EVIDENCE_KEY)
    ]
    assert ledgers, "skills must carry transfer_evidence ledgers"
    # I-01 evidence lands in 'of'; ORD-50 (Agent Ordering/CONSECUTIVE text) in 'os'.
    buckets = set()
    for _, ledger in ledgers:
        buckets.update(ledger)
    assert {"of", "os"} <= buckets


def test_ledger_accumulates_across_rounds():
    first = _evolve()
    chain1 = _skill_with(
        first, lambda s: (s.get("organization_policy") or {}).get("topology_name") == "chain"
    )[0]
    n1 = chain1["organization_policy"][TRANSFER_EVIDENCE_KEY]["of"]["n"]
    second = _evolve(initial_skills=first["evolved_skills"])
    chain2 = _skill_with(
        second, lambda s: (s.get("organization_policy") or {}).get("topology_name") == "chain"
    )[0]
    n2 = chain2["organization_policy"][TRANSFER_EVIDENCE_KEY]["of"]["n"]
    assert n2 > n1, "round-2 ledger must include round-1 counts plus fresh rows"


def _trusted_skill(skill_id: str, topology: str, bucket: str, n_agents: int = 2) -> SkillCard:
    return SkillCard(
        skill_id=skill_id,
        objective="balanced",
        task_family="silo",
        trigger={"task_family": "silo", "min_agents": 1, "max_agents": 999},
        organization_policy={
            "topology_name": topology,
            "protocol_spec": {
                "name": topology,
                "n_agents": n_agents,
                "steps": [
                    {"transmissions": [[0, 1]], "description": "fwd", "operator": "replay"}
                ],
                "metadata": {"graph_type": "temporal_dag", "selected_primary": 1},
            },
            TRANSFER_EVIDENCE_KEY: {bucket: {"n": 4, "em_sum": 4.0}},
        },
        expected_tradeoff={"mean_primary_loss": 0.0, "active_evidence_count": 4},
        confidence={"seed_count": 4},
        tags=["mas", "silo"],
    )


def _capture_plan_inputs(monkeypatch):
    captured = []
    orig = evolve._plan_graph_generate

    def spy(cfg, *, n_agents, task_adapter, client, skill_bank=None, motif_stats=None):
        captured.append((skill_bank, motif_stats))
        return orig(
            cfg, n_agents=n_agents, task_adapter=task_adapter, client=client,
            skill_bank=skill_bank, motif_stats=motif_stats,
        )

    monkeypatch.setattr(evolve, "_plan_graph_generate", spy)
    return captured


def _instances():
    adapter = SiloBenchAdapter(DATA)
    by_id = {
        inst.case_id: inst
        for inst in adapter.iter_instances(levels=LEVELS, agent_counts=[2])
    }
    return by_id["I-01"], by_id["ORD-50"]


def test_deployment_abstains_on_uncovered_bucket(monkeypatch):
    from exp_graph.llm.factory import create_llm_client

    i01, ord50 = _instances()
    cfg = _cfg(planner_mode="graph_generate")
    bank = SkillBank(skills=[_trusted_skill("of_champion", "tree", "of")])
    motif = {"of|fan_in:1": {"mean_loss": 0.0, "n": 4}}
    captured = _capture_plan_inputs(monkeypatch)
    client = create_llm_client("fake")
    objective = evolution_objective_spec(cfg)

    row = evolve._run_one(
        ord50, cfg, objective=objective, skill_bank=bank, seed=1,
        llm_client=client, motif_stats=motif,
    )
    assert row["task_features_key"] == "os"
    view_bank, view_motif = captured[-1]
    assert len(view_bank) == 0, "no os-trusted skill -> exact cold inputs"
    assert view_motif is None

    row = evolve._run_one(
        i01, cfg, objective=objective, skill_bank=bank, seed=1,
        llm_client=client, motif_stats=motif,
    )
    assert row["task_features_key"] == "of"
    view_bank, view_motif = captured[-1]
    assert [s.skill_id for s in view_bank] == ["of_champion"]
    assert view_motif == {"fan_in:1": {"mean_loss": 0.0, "n": 4}}


def test_transfer_gate_env_kill_switch(monkeypatch):
    from exp_graph.llm.factory import create_llm_client

    _, ord50 = _instances()
    monkeypatch.setenv("MASBENCH_TRANSFER_GATE", "off")
    cfg = _cfg(planner_mode="graph_generate")
    bank = SkillBank(skills=[_trusted_skill("of_champion", "tree", "of")])
    captured = _capture_plan_inputs(monkeypatch)
    client = create_llm_client("fake")
    evolve._run_one(
        ord50, cfg, objective=evolution_objective_spec(cfg), skill_bank=bank,
        seed=1, llm_client=client, motif_stats=None,
    )
    view_bank, _ = captured[-1]
    assert len(view_bank) == 1, "off mode must deploy the full bank (phase-2 behavior)"


def test_ratchet_gate_rejects_round_worse_than_incumbent(monkeypatch):
    """j_before must be the INCUMBENT bank's loss once a bank is inherited.

    Controlled losses: cold 1.0, incumbent 0.1, post-round 0.9. The old gate
    (vs cold) would accept 0.9 <= 1.0; the ratchet must reject (0.9 - 0.1
    far exceeds the one-miss noise floor) and export the incumbent state
    unchanged.
    """
    orig = evolve._run_one

    def fake_run_one(inst, cfg, **kwargs):
        phase = kwargs.get("diag_phase", "")
        if phase == "gate:incumbent":
            return {"ExactMatchRate": 0.9, "mean_primary_loss": 0.1}
        if phase == "gate:after":
            return {"ExactMatchRate": 0.1, "mean_primary_loss": 0.9}
        if phase == "gate:before":
            return {"ExactMatchRate": 0.0, "mean_primary_loss": 1.0}
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", fake_run_one)
    first = _evolve()
    initial = first["evolved_skills"]
    assert initial
    second = _evolve(initial_skills=initial)
    assert second["gate"]["mode"] == "generation_ratchet"
    assert second["gate"]["j_before"] == pytest.approx(0.1)
    assert second["gate"]["j_after"] == pytest.approx(0.9)
    assert second["gate"]["accepted"] is False
    assert second["skill_bank_mutated"] is False
    assert [s["skill_id"] for s in second["evolved_skills"]] == [
        s["skill_id"] for s in initial
    ], "rejected round must export the incumbent state"


def test_round1_gate_still_compares_to_cold(monkeypatch):
    orig = evolve._run_one

    def fake_run_one(inst, cfg, **kwargs):
        phase = kwargs.get("diag_phase", "")
        if phase == "gate:after":
            return {"ExactMatchRate": 0.5, "mean_primary_loss": 0.5}
        if phase == "gate:before":
            return {"ExactMatchRate": 0.0, "mean_primary_loss": 1.0}
        if phase == "gate:incumbent":
            raise AssertionError("round 1 has no incumbent")
        return orig(inst, cfg, **kwargs)

    monkeypatch.setattr(evolve, "_run_one", fake_run_one)
    summary = _evolve()
    assert summary["gate"]["mode"] == "generation"
    assert summary["gate"]["accepted"] is True
