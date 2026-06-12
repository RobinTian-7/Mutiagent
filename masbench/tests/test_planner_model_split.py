"""M23: stronger architect, frozen workers (operator direction).

planner_model_name routes ONLY architect-side calls (emperor graph
generation via role profile, instruction rewrite, recipe proposals) to a
different model; worker runs keep model_name. None = byte-identical
historical behavior.
"""

from __future__ import annotations

from exp_graph.mas.graph_generation import ProtocolGraphSpec
from exp_graph.mas.role_llm import resolve_role_llm_config
from masbench.core.config import RunConfig
from masbench.engine import _plan_graph_generate  # noqa: F401  (import sanity)


def _cfg(planner: str | None) -> RunConfig:
    return RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate",
        num_graph_candidates=2, n_agents=2, planner_model_name=planner,
    )


def test_runtime_emperor_profile_resolves_to_planner_model():
    import masbench.engine as engine
    from exp_graph.mas.schemas import MASRuntimeConfig, RoleLLMConfig, RoleLLMProfiles

    # mirror the engine's construction logic for both settings
    cfg = _cfg("strong-architect")
    runtime = MASRuntimeConfig(
        llm_provider=cfg.llm_provider, model_name=cfg.model_name,
        role_llm_profiles=RoleLLMProfiles(
            emperor=RoleLLMConfig(platform=cfg.llm_provider,
                                  model_name=cfg.planner_model_name)
        ),
    )
    emperor = resolve_role_llm_config(runtime, "emperor")
    soldier = resolve_role_llm_config(runtime, "soldier")
    assert emperor.model_name == "strong-architect"
    assert soldier.model_name == cfg.model_name  # workers untouched

    runtime_off = MASRuntimeConfig(
        llm_provider=cfg.llm_provider, model_name=cfg.model_name,
        role_llm_profiles=None,
    )
    assert resolve_role_llm_config(runtime_off, "emperor").model_name == cfg.model_name


def test_rewrite_helper_uses_planner_model():
    from pathlib import Path

    from masbench.adapters.silo_bench import SiloBenchAdapter
    from masbench.evolve import _rewrite_instructions_for_case

    spec = ProtocolGraphSpec.model_validate({
        "name": "t", "n_agents": 2,
        "steps": [{"transmissions": [[0, 1]], "description": "d", "operator": "x"}],
        "operators": ["llm_generate_dag"], "metadata": {},
    })
    inst = next(
        SiloBenchAdapter(Path(__file__).parent / "data").iter_instances(
            levels=["I"], agent_counts=[2], cases=["I-01"]
        )
    )
    seen = {}

    class _Client:
        def complete(self, prompt, *, model_name, **kw):
            seen["model"] = model_name

            class R:
                text = '{"instructions": ["a"]}'

            return R()

    _rewrite_instructions_for_case(spec, inst, _cfg("strong-architect"), _Client())
    assert seen["model"] == "strong-architect"
    _rewrite_instructions_for_case(spec, inst, _cfg(None), _Client())
    assert seen["model"] == _cfg(None).model_name
