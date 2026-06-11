"""A2: evidence rows carry the EXECUTED protocol spec -> skills store executable
schedules -> select_then_refine seeding actually fires.

Before this change the documented select_then_refine mechanism ("the bank's
minister skills carry the WORKING topologies' reference protocol_specs") was
unimplemented: ``summary_to_aggregate_row`` never emitted ``protocol_spec``, so
``_best_protocol_spec`` always returned None, ``organization_policy.protocol_spec``
was None on every skill, and ``_skill_seeded_graph_candidates`` (the replay /
refine anchor path) was dead code. The eval transferred knowledge only as prompt
context.
"""
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution
from masbench.llm.fake import BenchmarkFakeLLMClient
from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

DATA = Path(__file__).parent / "data"


def _cfg(planner_mode: str = "topology_select") -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode=planner_mode, merge_mode="deterministic",
        init_mode="deterministic", objective="accuracy_first",
        evolved_mode="select_then_refine", num_graph_candidates=2,
    )


def _instance():
    return next(
        iter(SiloBenchAdapter(DATA).iter_instances(levels=["I"], agent_counts=[2], cases=["I-01"]))
    )


def test_select_evidence_row_carries_executed_spec():
    cfg = _cfg()
    row = _run_one(
        _instance(), cfg, objective=evolution_objective_spec(cfg),
        skill_bank=SkillBank(), seed=1, llm_client=BenchmarkFakeLLMClient(),
    )
    spec = row.get("protocol_spec")
    assert isinstance(spec, dict), "select evidence must carry the executed schedule"
    assert spec.get("steps"), "spec must have steps"
    assert spec.get("n_agents") == 2
    assert isinstance(spec.get("metadata", {}).get("selected_primary"), int)


def test_evolved_skills_carry_executable_specs():
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"],
    )
    skills = [SkillCard.model_validate(s) for s in summary["evolved_skills"]]
    assert skills
    with_spec = [
        s for s in skills
        if isinstance((s.organization_policy or {}).get("protocol_spec"), dict)
        and (s.organization_policy or {}).get("protocol_spec", {}).get("steps")
    ]
    assert with_spec, "at least one learned skill must carry an executable spec"


def test_refine_eval_replays_stored_spec():
    """With executable specs in the bank, the eval's generation seeds replay
    candidates from them and (offline, no probe) selects the top-retrieved one --
    the run's topology is the stored spec's name, not a cold-generated graph."""
    summary = run_evolution(
        SiloBenchAdapter(DATA), cases=["I-01"], agent_counts=[2],
        train_seeds=[1], val_seeds=[2], cfg=_cfg(), levels=["I"],
    )
    bank = SkillBank(skills=[SkillCard.model_validate(s) for s in summary["evolved_skills"]])
    eval_cfg = _cfg(planner_mode="graph_generate")
    row = _run_one(
        _instance(), eval_cfg, objective=evolution_objective_spec(eval_cfg),
        skill_bank=bank, seed=9, llm_client=BenchmarkFakeLLMClient(),
    )
    stored_names = {
        (s.organization_policy or {}).get("protocol_spec", {}).get("name")
        for s in bank
        if isinstance((s.organization_policy or {}).get("protocol_spec"), dict)
    }
    topology = str(row["Topology"])
    assert topology.startswith("generated:")
    assert topology.removeprefix("generated:") in stored_names, (
        f"eval must replay a stored spec, got {topology} vs {stored_names}"
    )
