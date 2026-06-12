"""M20: train-verified instruction exemplars anchor deploy-time rewrites.

dev-12b vs dev-13 forensics: Modify rewrites are a fresh stochastic draw
per deployment (6-7 distinct instruction sets per 8 seeds on the SAME
structure; EM tracked the draw -- 6/8 one draw-batch, 1/8 the next). M20
verifies an instruction set on a TRAIN anchor at evolution time, stores it
on the card, and the deployment view + rewrite prompt anchor on it.
"""

from __future__ import annotations

import json

import masbench.evolve as evolve
from exp_graph.llm.factory import create_llm_client
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    _graph_from_skill_protocol,
    _rewrite_replay_instructions,
)
from exp_graph.mas.schemas import MASRuntimeConfig, SkillCard
from exp_graph.mas.skill_bank import SkillBank
from masbench.core.config import RunConfig
from masbench.transfer import deployment_view


def _card(with_exemplar: bool, with_active: bool = False) -> SkillCard:
    policy = {
        "planner_mode": "graph_generate",
        "topology_name": "generated:test_org",
        "protocol_spec": {
            "name": "test_org",
            "n_agents": 2,
            "steps": [
                {"transmissions": [[0, 1]], "description": "d", "operator": "x"},
                {"transmissions": [[1, 0]], "description": "d", "operator": "x"},
            ],
            "operators": ["llm_generate_dag"],
            "metadata": {"selected_primary": 0},
        },
        "transfer_evidence": {
            "os": {"n": 4, "em_sum": 4.0, "cases": ["II-13", "II-14"]},
            "os#lossless-scalar": {"n": 4, "em_sum": 4.0, "cases": ["II-13", "II-14"]},
        },
    }
    if with_exemplar:
        policy["instruction_exemplars"] = {
            "os": {"steps": ["compute X", "forward Y"], "case": "II-13", "em": 1.0, "n": 2}
        }
    if with_active:
        policy["active_instruction_exemplar"] = ["compute X", "forward Y"]
    return SkillCard(
        skill_id="s1", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy=policy,
        expected_tradeoff={"mean_primary_loss": 0.0},
        confidence={}, tags=["mas"],
    )


def test_deployment_view_stamps_active_exemplar():
    bank = SkillBank(skills=[_card(with_exemplar=True)])
    view, _m, abstained, _t = deployment_view(
        bank, None, "os", kind="lossless-composite", mode="feature",
        fallback_tier=True,
    )
    assert not abstained
    skill = next(iter(view))
    assert skill.organization_policy["active_instruction_exemplar"] == [
        "compute X", "forward Y"
    ]
    # original bank card is NOT mutated (view is a deep copy)
    original = next(iter(bank))
    assert "active_instruction_exemplar" not in original.organization_policy


def test_graph_plan_carries_exemplar_and_prompt_anchors_on_it():
    from exp_graph.mas.graph_generation import ProtocolGraphSpec

    card = _card(with_exemplar=True, with_active=True)
    spec = ProtocolGraphSpec.model_validate(card.organization_policy["protocol_spec"])
    plan = _graph_from_skill_protocol(card, spec)
    assert plan.instruction_exemplar == ["compute X", "forward Y"]

    captured = {}

    class _Client:
        def complete(self, prompt, **kw):
            captured["prompt"] = prompt

            class R:
                text = json.dumps({"instructions": ["a1", "a2"]})

            return R()

    runtime = MASRuntimeConfig(
        llm_provider="openai", model_name="m", replay_instruction_rewrite=True
    )
    _rewrite_replay_instructions(
        [plan], runtime=runtime, llm_client=_Client(), task_brief="task brief"
    )
    assert "VERIFIED to work" in captured["prompt"]
    assert "compute X" in captured["prompt"]
    assert [s.instruction for s in plan.steps] == ["a1", "a2"]


def test_prompt_unchanged_without_exemplar():
    plan = GeneratedGraphPlan(
        candidate_id="skill_x", name="g", n_agents=2,
        steps=[GeneratedGraphStep(description="d", edges=[(0, 1)])],
    )
    captured = {}

    class _Client:
        def complete(self, prompt, **kw):
            captured["prompt"] = prompt

            class R:
                text = json.dumps({"instructions": ["a1"]})

            return R()

    runtime = MASRuntimeConfig(
        llm_provider="openai", model_name="m", replay_instruction_rewrite=True
    )
    _rewrite_replay_instructions(
        [plan], runtime=runtime, llm_client=_Client(), task_brief="task brief"
    )
    assert "VERIFIED to work" not in captured["prompt"]


def _bare_named_card() -> SkillCard:
    # a spec-less named/cf-style card that sorts FIRST in the bank: dev-14's
    # silent no-op picked exactly this shape and skipped without a trace
    return SkillCard(
        skill_id="a_first_named", objective="balanced", task_family="silo",
        trigger={"task_family": "silo"},
        organization_policy={
            "planner_mode": "topology_select",
            "topology_name": "peer_star",
            "transfer_evidence": {
                "os": {"n": 4, "em_sum": 4.0, "cases": ["II-13", "II-14"]},
                "os#lossless-scalar": {"n": 4, "em_sum": 4.0,
                                       "cases": ["II-13", "II-14"]},
            },
        },
        expected_tradeoff={"mean_primary_loss": 0.0},
        confidence={}, tags=["mas"],
    )


def test_exemplar_phase_stores_on_verified_success(monkeypatch):
    from pathlib import Path
    from masbench.adapters.silo_bench import SiloBenchAdapter

    inst = next(
        SiloBenchAdapter(Path(__file__).parent / "data").iter_instances(
            levels=["I"], agent_counts=[2], cases=["I-01"]
        )
    )
    card = _card(with_exemplar=False)
    # dev-14 regression: a spec-less trusted card ahead of the champion must
    # be skipped over, not silently abort the whole phase
    bank = SkillBank(skills=[_bare_named_card(), card])
    cfg = RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate", n_agents=2,
    )
    monkeypatch.setattr(evolve, "classify_task", lambda *a, **k: {})
    monkeypatch.setattr(evolve, "classification_bucket", lambda c: "os")
    monkeypatch.setattr(
        evolve, "classification_lossless_slot", lambda c: "lossless-scalar"
    )
    monkeypatch.setattr(
        evolve, "_rewrite_instructions_for_case",
        lambda spec, inst, cfg, llm_client: ["compute X", "forward Y"],
    )
    monkeypatch.setattr(
        evolve, "_run_spec_on_instance",
        lambda inst, cfg, *, spec, seed, llm_client: (1.0, {}),
    )
    traces, runs = evolve._exemplar_phase(
        [inst], cfg, skill_bank=bank, train_seeds=[1],
        llm_client=create_llm_client("fake"),
    )
    assert runs == 2 and traces and traces[0]["verified"]
    stored = card.organization_policy["instruction_exemplars"]
    bucket = traces[0]["bucket"]
    assert stored[bucket]["steps"] == ["compute X", "forward Y"]
    assert stored[bucket]["em"] == 1.0


def test_rewrite_helper_parses_real_response_shape():
    # dev-15 lesson: the earlier test monkeypatched the function under test
    # and missed a missing module import (every live rewrite died with a
    # swallowed NameError). This exercises the REAL helper end to end.
    from exp_graph.mas.graph_generation import ProtocolGraphSpec
    from masbench.evolve import _rewrite_instructions_for_case

    spec = ProtocolGraphSpec.model_validate({
        "name": "t", "n_agents": 2,
        "steps": [
            {"transmissions": [[0, 1]], "description": "d", "operator": "x"},
            {"transmissions": [[1, 0]], "description": "d", "operator": "x"},
        ],
        "operators": ["llm_generate_dag"], "metadata": {},
    })

    class _Client:
        def complete(self, prompt, **kw):
            class R:
                text = '{"instructions": ["step one", "step two"]}'

            return R()

    from pathlib import Path
    from masbench.adapters.silo_bench import SiloBenchAdapter

    inst = next(
        SiloBenchAdapter(Path(__file__).parent / "data").iter_instances(
            levels=["I"], agent_counts=[2], cases=["I-01"]
        )
    )
    cfg = RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate", n_agents=2,
    )
    out = _rewrite_instructions_for_case(spec, inst, cfg, _Client())
    assert out == ["step one", "step two"]


def test_exemplar_phase_rejects_failed_verification(monkeypatch):
    from pathlib import Path
    from masbench.adapters.silo_bench import SiloBenchAdapter

    inst = next(
        SiloBenchAdapter(Path(__file__).parent / "data").iter_instances(
            levels=["I"], agent_counts=[2], cases=["I-01"]
        )
    )
    card = _card(with_exemplar=False)
    bank = SkillBank(skills=[card])
    cfg = RunConfig(
        llm_provider="fake", planner_mode="graph_generate",
        merge_mode="deterministic", init_mode="deterministic",
        objective="accuracy_first", evolved_mode="graph_generate", n_agents=2,
    )
    monkeypatch.setattr(evolve, "classify_task", lambda *a, **k: {})
    monkeypatch.setattr(evolve, "classification_bucket", lambda c: "os")
    monkeypatch.setattr(
        evolve, "classification_lossless_slot", lambda c: "lossless-scalar"
    )
    monkeypatch.setattr(
        evolve, "_rewrite_instructions_for_case",
        lambda spec, inst, cfg, llm_client: ["bad", "bad"],
    )
    monkeypatch.setattr(
        evolve, "_run_spec_on_instance",
        lambda inst, cfg, *, spec, seed, llm_client: (0.0, {}),
    )
    traces, _runs = evolve._exemplar_phase(
        [inst], cfg, skill_bank=bank, train_seeds=[1],
        llm_client=create_llm_client("fake"),
    )
    assert traces and not traces[0]["verified"]
    assert "instruction_exemplars" not in card.organization_policy
