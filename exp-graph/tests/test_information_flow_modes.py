"""Structural information-flow + mode-aware graph validation/repair tests.

Covers the spec's structural half: temporal knowledge propagation semantics,
sink vs all_agents pass conditions (gather-only star, gather+broadcast,
one-way chain), mode-dispatched validation/repair (all_agents graphs get a
dissemination phase, never just the sink repair), the two architect prompts
being genuinely different and audit-clean, the de-generalized JSON shape, and
the no-named-fallback failure contract of plan_free_graph.
"""
# ============================================================
# 【模块导读】结构信息流 + 按模式分派的图校验/修复测试（exp-graph 侧）。
# ============================================================

from __future__ import annotations

import hashlib
import json

import pytest
from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphGenerationError,
    GraphValidationOptions,
    build_all_agents_graph_prompt,
    build_free_graph_prompt,
    build_sink_graph_prompt,
    plan_free_graph,
    repair_graph_plan,
    validate_graph_plan,
)
from exp_graph.mas.information_flow import (
    agents_without_full_information,
    all_agents_covered,
    coverage_by_agent,
    propagate_knowledge,
    sink_covered,
)
from exp_graph.mas.leakage_audit import (
    PromptLeakageError,
    assert_prompt_clean,
    find_leakage_tokens,
)
from exp_graph.mas.schemas import MASRuntimeConfig, ObjectiveSpec, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols.schedules import build_protocol_schedule
from exp_graph.tasks import CountFrequencyTaskAdapter


def _request(n_agents: int = 5) -> PlannerRequest:
    return PlannerRequest(
        task_family="silo",
        n_agents=n_agents,
        objective=ObjectiveSpec.from_name("accuracy_first"),
        planner_mode="graph_generate",
    )


@pytest.mark.parametrize("n_agents", [2, 3, 5, 8, 10])
@pytest.mark.parametrize(
    "topology",
    ["one_peer_exponential_dag", "static_exponential"],
)
def test_all_agents_hot_start_exponential_graphs_reach_every_agent(
    topology: str,
    n_agents: int,
) -> None:
    schedule = build_protocol_schedule(topology, n_agents)
    knowledge = propagate_knowledge(
        n_agents,
        [step.transmissions for step in schedule],
    )
    assert coverage_by_agent(knowledge) == [1.0] * n_agents
    assert all_agents_covered(knowledge)


# --------------------------------------------------------------------------- #
# Propagation semantics: simultaneous steps, copy-then-merge, self retention.
# --------------------------------------------------------------------------- #
def test_propagation_is_simultaneous_and_retains_state():
    # 同步语义：一步内 0->1 与 1->2 同时发生，2 收到的是 1 的“旧”知识。
    knowledge = propagate_knowledge(3, [[(0, 1), (1, 2)]])
    assert knowledge[1] == {0, 1}
    assert knowledge[2] == {1, 2}  # NOT {0,1,2}: simultaneous, not sequential
    # 两步链才把 0 的知识带到 2。
    knowledge = propagate_knowledge(3, [[(0, 1)], [(1, 2)]])
    assert knowledge[2] == {0, 1, 2}
    # 发送者保留自身状态。
    assert knowledge[0] == {0}


def test_gather_only_star_structural_pass_conditions():
    star = [[(i, 0) for i in range(1, 5)]]
    knowledge = propagate_knowledge(5, star)
    assert sink_covered(knowledge, 0) is True
    assert all_agents_covered(knowledge) is False
    assert agents_without_full_information(knowledge) == [1, 2, 3, 4]


def test_gather_then_broadcast_structural_pass_conditions():
    steps = [[(i, 0) for i in range(1, 5)], [(0, i) for i in range(1, 5)]]
    knowledge = propagate_knowledge(5, steps)
    assert sink_covered(knowledge, 0) is True
    assert all_agents_covered(knowledge) is True
    assert coverage_by_agent(knowledge) == [1.0] * 5


def test_one_way_chain_structural_pass_conditions():
    chain = [[(0, 1)], [(1, 2)], [(2, 3)], [(3, 4)]]
    knowledge = propagate_knowledge(5, chain)
    assert sink_covered(knowledge, 4) is True  # 末端 sink 可通过
    assert all_agents_covered(knowledge) is False
    assert coverage_by_agent(knowledge)[0] == 0.2


# --------------------------------------------------------------------------- #
# Mode-dispatched validation: the same graph validates differently per goal.
# --------------------------------------------------------------------------- #
def _star_plan(n: int = 4) -> GeneratedGraphPlan:
    return GeneratedGraphPlan(
        candidate_id="c0",
        name="gather_star",
        n_agents=n,
        steps=[
            GeneratedGraphStep(
                description="gather", edges=[(i, 0) for i in range(1, n)]
            )
        ],
        selected_primary=0,
    )


def test_validation_dispatches_on_information_goal():
    sink_opts = GraphValidationOptions(
        n_agents=4, require_full_sink_coverage=True, information_goal="sink"
    )
    all_opts = sink_opts.model_copy(update={"information_goal": "all_agents"})
    star = _star_plan()
    assert validate_graph_plan(star, sink_opts).valid is True
    result = validate_graph_plan(star, all_opts)
    assert result.valid is False
    assert any("without full information" in e for e in result.errors)


def test_all_agents_repair_adds_dissemination_not_sink_repair():
    all_opts = GraphValidationOptions(
        n_agents=4,
        require_full_sink_coverage=True,
        information_goal="all_agents",
        max_steps=6,
        max_messages=32,
    )
    star = _star_plan()
    repaired, notes = repair_graph_plan(star, all_opts)
    # 修复必须是传播/共识阶段（hub 广播），不是 sink 补边。
    assert any("dissemination" in n or "broadcast" in n for n in notes)
    assert not any("routed uncovered agents to sink" in n for n in notes)
    knowledge = propagate_knowledge(4, [s.edges for s in repaired.steps])
    assert all_agents_covered(knowledge) is True
    assert validate_graph_plan(repaired, all_opts).valid is True


def test_all_agents_repair_rejects_when_budget_too_small():
    # 预算不足以补齐广播阶段：修复后仍不覆盖 -> 校验拒绝，而不是伪造通过。
    tight = GraphValidationOptions(
        n_agents=4,
        require_full_sink_coverage=True,
        information_goal="all_agents",
        max_steps=1,  # 无法追加任何传播步
        max_messages=8,
    )
    star = _star_plan()
    repaired, _notes = repair_graph_plan(star, tight)
    assert validate_graph_plan(repaired, tight).valid is False


# --------------------------------------------------------------------------- #
# 9 (architect half). The two architect prompts differ in content and hash,
#    pass the audit, and the JSON shape carries no copyable edge formula.
# --------------------------------------------------------------------------- #
def test_architect_prompts_differ_and_are_clean():
    opts = GraphValidationOptions(
        n_agents=5, require_full_sink_coverage=True, information_goal="sink"
    )
    sink_prompt = build_sink_graph_prompt(
        request=_request(), skills=[], options=opts, num_candidates=2,
        task_brief="Find the global maximum",
    )
    all_prompt = build_all_agents_graph_prompt(
        request=_request(), skills=[],
        options=opts.model_copy(update={"information_goal": "all_agents"}),
        num_candidates=2, task_brief="Find the global maximum",
    )
    h1 = hashlib.sha256(sink_prompt.encode()).hexdigest()
    h2 = hashlib.sha256(all_prompt.encode()).hexdigest()
    assert sink_prompt != all_prompt and h1 != h2
    assert find_leakage_tokens(sink_prompt) == []
    assert find_leakage_tokens(all_prompt) == []
    # 角色/目标/完成条件/自检确实不同。
    assert "SINGLE-SINKPOINT" in sink_prompt and "FULL-DISSEMINATION" in all_prompt
    assert "spread-back phase" in all_prompt
    assert "if ANY agent finishes without every other agent's information" in all_prompt
    assert "temporal path to the selected_primary sink" in sink_prompt
    # 形状只描述类型/语法：不存在可复制的具体拓扑边公式或对数/倍增示例。
    for banned in ("distance-doubling", "pow2", "ceil_log2", "floor_log2"):
        assert banned not in sink_prompt and banned not in all_prompt
    payload = json.loads(sink_prompt)
    shape = json.dumps(payload["required_json_shape"])
    assert "<int expression>" in shape and "% n_agents" not in shape
    # 分派器保持向后兼容。
    assert build_free_graph_prompt(
        request=_request(), skills=[], options=opts, num_candidates=2,
        information_goal="all_agents",
    ) == build_all_agents_graph_prompt(
        request=_request(), skills=[], options=opts, num_candidates=2,
    )


def test_leakage_audit_raises_on_forbidden_tokens():
    with pytest.raises(PromptLeakageError):
        assert_prompt_clean("here is the expected_output: 9")
    with pytest.raises(PromptLeakageError):
        assert_prompt_clean("use a one_peer distance-doubling schedule")
    assert assert_prompt_clean("clean text") == "clean text"
    assert assert_prompt_clean(
        "use a one_peer exponential seed",
        allowed_tokens=["one_peer", "exponential"],
    )
    with pytest.raises(PromptLeakageError):
        assert_prompt_clean(
            "expected_output plus one_peer",
            allowed_tokens=["one_peer", "exponential"],
        )


# --------------------------------------------------------------------------- #
# 10 (engine-independent half). plan_free_graph FAILS (raises) instead of
#     falling back to a named topology; artifacts record the failure.
# --------------------------------------------------------------------------- #
class _JunkLLM:
    def complete(self, prompt, model_name, temperature=None):
        return LLMResponse(
            text="TOTALLY NOT JSON",
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        )


def test_plan_free_graph_raises_instead_of_named_fallback(tmp_path):
    runtime = MASRuntimeConfig(
        llm_provider="openai",  # non-fake -> the architect LLM path
        model_name="junk",
        num_graph_candidates=1,
        information_goal="sink",
    )
    with pytest.raises(GraphGenerationError) as excinfo:
        plan_free_graph(
            request=_request(3),
            runtime=runtime,
            skill_bank=SkillBank(),
            seed=0,
            task_adapter=CountFrequencyTaskAdapter(),
            output_dir=tmp_path,
            llm_client=_JunkLLM(),
        )
    assert excinfo.value.reason
    summary = json.loads((tmp_path / "graph_validation_summary.json").read_text())
    assert summary["graph_generation_failed"]
    call = json.loads((tmp_path / "architect_call.json").read_text())
    assert call["graph_generation_failed"]
    # 选定方案文件为空对象：没有任何具名拓扑被选中。
    selected = json.loads((tmp_path / "selected_graph_plan.json").read_text())
    assert selected == {}


def test_fake_platform_candidates_carry_fake_provenance(tmp_path):
    runtime = MASRuntimeConfig(llm_provider="fake", num_graph_candidates=2)
    result = plan_free_graph(
        request=_request(4),
        runtime=runtime,
        skill_bank=SkillBank(),
        seed=0,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )
    assert result.plan.provenance == "fake"
    assert all(
        record.provenance == "fake" for record in result.candidates
    )
    # fake 候选也绝不使用 one_peer 具名兜底字符串。
    dumped = json.dumps([r.model_dump(mode="json") for r in result.candidates])
    assert "one_peer" not in dumped


# --------------------------------------------------------------------------- #
# Regression: the placeholder JSON shape must show repeat and step as two
# separately-nested objects (a merged placeholder made gpt-4o-mini put var/
# range inside the nested step and every candidate failed validation), and a
# single malformed candidate must not void a batch with a valid sibling.
# --------------------------------------------------------------------------- #
def test_required_json_shape_has_correctly_nested_repeat_and_step():
    opts = GraphValidationOptions(n_agents=5, information_goal="sink")
    prompt = build_sink_graph_prompt(
        request=_request(), skills=[], options=opts, num_candidates=1
    )
    body = json.loads(prompt)["required_json_shape"]["candidates"][0]["program"]["body"]
    repeat_obj = next(item for item in body if item.get("op") == "repeat")
    step_obj = next(item for item in body if item.get("op") == "step")
    # repeat 自身携带 var/range/body；step 携带 description/edges——层级不再混写。
    assert {"op", "var", "range", "body"} <= set(repeat_obj)
    assert "edges" not in repeat_obj and "description" not in repeat_obj
    assert {"op", "description", "edges"} <= set(step_obj)
    assert "var" not in step_obj and "range" not in step_obj
    # 语法说明明确 var/range 属于 repeat 本体。
    lang = json.loads(prompt)["topology_program_language"]["repeat"]
    assert "var and range belong to the repeat object" in lang


def test_parser_tolerates_one_malformed_candidate():
    from exp_graph.mas.graph_generation import parse_graph_candidates_response

    good = {
        "candidate_id": "ok",
        "name": "pair_relay",
        "graph_type": "temporal_dag",
        "n_agents": 3,
        "steps": [{"description": "s", "edges": [[0, 1], [1, 2]]}],
        "selected_primary": 2,
    }
    bad = {
        "candidate_id": "bad",
        "name": "broken",
        "graph_type": "temporal_dag",
        "n_agents": 3,
        # var/range 放错层级（真实 gpt-4o-mini 失败样本的形状）。
        "program": {
            "format": "topology_program_v1",
            "body": [{"op": "repeat", "body": [{"op": "step", "var": "i"}]}],
        },
    }
    parsed = parse_graph_candidates_response(
        json.dumps({"candidates": [bad, good]}), n_agents=3, expected_count=2
    )
    assert [g.candidate_id for g in parsed] == ["ok"]
    assert parsed[0].provenance == "llm_generated"
    # 全部无效仍然失败（绝无具名兜底）。
    with pytest.raises(ValueError, match="no parseable graph candidates"):
        parse_graph_candidates_response(
            json.dumps({"candidates": [bad]}), n_agents=3, expected_count=1
        )


def test_parser_tolerates_explicit_null_fields():
    """gpt-4o-mini emits "steps": null alongside a program; null keys must
    fall back to their pydantic defaults instead of voiding the candidate."""
    from exp_graph.mas.graph_generation import parse_graph_candidates_response

    candidate = {
        "candidate_id": "c0",
        "name": "staged_relay",
        "graph_type": "temporal_dag",
        "n_agents": 3,
        "steps": None,  # real gpt-4o-mini failure shape
        "selected_primary": None,
        "fallback_topology": None,
        "program": {
            "format": "topology_program_v1",
            "selected_primary": "n_agents - 1",
            "body": [
                {
                    "op": "step",
                    "description": "relay",
                    "operator_hint": "peer",
                    "edges": [
                        {
                            "src": "i",
                            "dst": "i + 1",
                            "when": "i + 1 < n_agents",
                            "for_each": [
                                {
                                    "var": "i",
                                    "range": {"start": 0, "stop": "n_agents - 1", "step": 1},
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }
    parsed = parse_graph_candidates_response(
        json.dumps({"candidates": [candidate]}), n_agents=3, expected_count=1
    )
    assert len(parsed) == 1 and parsed[0].program is not None
    assert parsed[0].steps == []  # null collapsed to the default empty list
