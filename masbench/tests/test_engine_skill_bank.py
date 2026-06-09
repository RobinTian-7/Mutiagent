"""run_instance must thread a caller-supplied skill_bank all the way into
plan_free_graph, so the evolved arm can have the emperor DESIGN a DAG from the
evolved skills (not generate cold with an empty bank). With no bank supplied the
generator still gets a fresh empty bank (the plain graphgen behaviour).
"""
from pathlib import Path
from types import SimpleNamespace

from masbench import engine
from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.llm.fake import BenchmarkFakeLLMClient
from exp_graph.mas.skill_bank import SkillBank

DATA = Path(__file__).parent / "data"


def _instance():
    return list(
        SiloBenchAdapter(DATA).iter_instances(
            levels=["I"], agent_counts=[2], cases=["I-01"]
        )
    )[0]


def _cfg():
    return RunConfig(
        use_planner=True, planner_mode="graph_generate", llm_provider="fake",
        merge_mode="deterministic", init_mode="deterministic", n_agents=2,
        objective="accuracy_first",
    )


def _spy_plan_free_graph(monkeypatch, captured):
    cfg = _cfg()

    def fake(**kwargs):
        captured["skill_bank"] = kwargs["skill_bank"]
        plan, _ = engine._plan_topology_select(cfg, n_agents=2)  # a valid plan
        return SimpleNamespace(plan=plan, fallback_reason=None)

    monkeypatch.setattr(engine, "plan_free_graph", fake)
    return cfg


def test_run_instance_threads_skill_bank_into_plan_free_graph(monkeypatch):
    captured = {}
    cfg = _spy_plan_free_graph(monkeypatch, captured)
    bank = SkillBank()
    engine.run_instance(
        _instance(), cfg, llm_client=BenchmarkFakeLLMClient(), skill_bank=bank
    )
    assert captured["skill_bank"] is bank


def test_graph_generate_defaults_to_empty_bank(monkeypatch):
    captured = {}
    cfg = _spy_plan_free_graph(monkeypatch, captured)
    engine.run_instance(_instance(), cfg, llm_client=BenchmarkFakeLLMClient())
    assert isinstance(captured["skill_bank"], SkillBank)
    assert len(captured["skill_bank"]) == 0
