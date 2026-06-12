"""JSSP corroboration wiring: the learner core runs benchmark-routed.

evolve._run_one/_run_fixed_one hardwired SiloProtocolAdapter; for the
cross-benchmark generalization corroboration (operator: "可以引入其他
benchmark佐证") they now route through engine._protocol_adapter. Silo paths
are byte-identical (factory returns SiloProtocolAdapter, family constant
unchanged); jssp instances get the JSSP adapter and a "jssp" family so
ledgers/triggers never mix across benchmarks.
"""

from __future__ import annotations

from pathlib import Path

import masbench.evolve as evolve
from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.skill_bank import SkillBank
from masbench.adapters.jssp_bench import JSSPBenchAdapter
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import _run_one, _task_family, evolution_objective_spec, run_evolution

DATA = Path(__file__).parent / "data"


def _jssp_instance():
    return next(iter(JSSPBenchAdapter(DATA / "jssp").iter_instances(cases=["tiny2x2"])))


def _silo_instance():
    return next(
        SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"])
    )


def test_task_family_routing():
    assert _task_family(_silo_instance()) == "silo"
    assert _task_family(_jssp_instance()) == "jssp"


def _cfg(n_agents: int) -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate",
        num_graph_candidates=2, n_agents=n_agents,
    )


def test_run_one_on_jssp_instance_offline():
    inst = _jssp_instance()
    cfg = _cfg(inst.n_agents)
    row = _run_one(
        inst, cfg, objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(), seed=3,
        llm_client=create_llm_client("fake"), motif_stats=None,
    )
    assert row["case_id"] == "tiny2x2"
    assert row["task_family"] == "jssp"
    assert 0.0 <= float(row["ExactMatchRate"]) <= 1.0
    assert "MeanPrimaryMetric" in row


def test_run_evolution_machinery_on_jssp_offline():
    inst = _jssp_instance()
    cfg = _cfg(inst.n_agents)
    summ = run_evolution(
        JSSPBenchAdapter(DATA / "jssp"), cases=["tiny2x2"],
        agent_counts=[inst.n_agents], train_seeds=[1], val_seeds=[2],
        cfg=cfg, levels=None, llm_client=create_llm_client("fake"),
        workers=1, progress=False, initial_skills=[],
    )
    skills = summ.get("evolved_skills") or []
    assert isinstance(skills, list)
    # every emitted card lives in the jssp family -- no silo leakage
    for card in skills:
        fam = card.get("task_family")
        if fam is not None:
            assert fam == "jssp", card.get("skill_id")
    # recipe phase is silo-scoped: no recipe cards on jssp
    assert not [c for c in skills if "recipe" in str(c.get("skill_id", ""))]
