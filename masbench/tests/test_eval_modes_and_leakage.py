"""Required tests for the leakage fixes + sink/all_agents evaluation modes.

Covers the spec's mandatory list on the masbench side:
answer/optimal-topology invisibility on a REAL task (II-12), private scoring,
mode-correct grading (gather-only star, one-wrong-agent, S=1, segmented),
graphgen parse failure without named fallback, clean-bank admission,
cross-mode skill isolation, mode-carrying cache keys/reports, persisted
architect audit artifacts without secrets, and the fake offline end-to-end
path in BOTH modes.
"""
# ============================================================
# 【模块导读】泄漏修复 + sink/all_agents 评测模式的必测清单（masbench 侧）。
# ============================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import masbench  # noqa: F401
import pytest
from exp_graph.agents.schemas import AgentState, BeliefState, BeliefStatus
from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.leakage_audit import find_leakage_tokens
from exp_graph.mas.schemas import ObjectiveSpec, PlannerRequest, SkillCard
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols.schedules import CommunicationStep

from masbench.adapters.silo_bench import SiloBenchAdapter, sanitize_task_description
from masbench.adapters.silo_protocol import (
    SiloProtocolAdapter,
    format_all_agents_protocol_init_prompt,
    format_all_agents_protocol_merge_prompt,
    format_sink_protocol_init_prompt,
    format_sink_protocol_merge_prompt,
    score_protocol_answer,
)
from masbench.bench import run_benchmark
from masbench.cache import EvidenceCache
from masbench.core.config import RunConfig
from masbench.core.task_bridge import private_answer_key
from masbench.engine import (
    _score_protocol_result,
    run_fixed_protocol,
    run_instance,
)

DATA = Path(__file__).parent / "data"
THIRD_PARTY = (
    Path(__file__).resolve().parents[1]
    / "third_party"
    / "acl26-silo-bench"
    / "benchmarks"
)


def _instance(case_id: str, n_agents: int = 2):
    adapter = SiloBenchAdapter(DATA)
    return next(iter(adapter.iter_instances(cases=[case_id], agent_counts=[n_agents])))


def _belief(answer, case_id: str = "I-01") -> BeliefState:
    from masbench.core.task_bridge import canonical_answer

    key = canonical_answer(answer) if answer is not None else "UNKNOWN"
    return BeliefState(
        status=BeliefStatus.CANDIDATE,
        proposal="test",
        consensus_key=key,
        support=[],
        uncertainty="",
        open_questions=[],
        private_notes="test",
        structured_state={"task_name": "silo", "case_id": case_id, "answer": answer},
    )


def _fake_result(schedule_edges: list[list[tuple[int, int]]], answers: list, case_id="I-01"):
    """Minimal protocol-result stand-in for the mode scorers."""
    states = [
        AgentState(local_observation={"agent_id": i}, belief_state=_belief(a, case_id))
        for i, a in enumerate(answers)
    ]
    schedule = [
        CommunicationStep(step_idx=i, transmissions=edges, description=f"s{i}")
        for i, edges in enumerate(schedule_edges)
    ]
    return SimpleNamespace(
        schedule=schedule,
        final_agent_states=states,
        total_messages=sum(len(e) for e in schedule_edges),
        total_steps=len(schedule_edges),
        total_model_calls=0,
        total_prompt_tokens=0,
        total_completion_tokens=0,
        config=SimpleNamespace(protocol_spec=None),
        final_result=SimpleNamespace(
            aggregation_method="vote", final_key="test", final_answer=None
        ),
    )


# --------------------------------------------------------------------------- #
# 1. Real task (II-12): answers and the optimal topology are invisible.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not THIRD_PARTY.is_dir(), reason="silo submodule not present")
def test_real_task_prompts_hide_answers_and_optimal_topology():
    adapter = SiloBenchAdapter(THIRD_PARTY)
    inst = next(iter(adapter.iter_instances(cases=["II-12"], agent_counts=[5])))
    # 泄漏字段在实例层就被剥掉。
    assert "optimal_topology" not in inst.meta
    assert "Communication Protocol" not in inst.task_prompt
    task_adapter = SiloProtocolAdapter(inst)
    gt = task_adapter.build_global_task()
    obs = task_adapter.split_into_local_observations(gt, 5)
    expected = inst.meta["expected_outputs"][0]
    expected_marker = json.dumps(expected)[:24]
    init_prompt = task_adapter.format_protocol_init_prompt(
        global_task=gt, local_observation=obs[0]
    )
    merge_prompt = task_adapter.format_protocol_merge_prompt(
        merge_mode="llm_full_merge",
        global_task=gt,
        local_observation=obs[0],
        old_belief_state=task_adapter.initial_protocol_belief(obs[0]),
        inbox=[],
    )
    for prompt in (init_prompt, merge_prompt):
        assert find_leakage_tokens(prompt) == []
        assert expected_marker not in prompt
        assert "II-12" not in prompt  # lookupable case id is masked
        assert "Chain (0" not in prompt  # the old protocol section's topology
    # 分片数据本身仍可见（这是 agent 的合法本地观测）。
    assert json.dumps(obs[0]["input_shard"][:3])[1:-1] in init_prompt


# --------------------------------------------------------------------------- #
# 2. Private scoring still produces exact/partial from the private payload.
# --------------------------------------------------------------------------- #
def test_private_scoring_still_exact_and_partial():
    inst = _instance("I-01")
    gt = SiloProtocolAdapter(inst).build_global_task()
    assert private_answer_key(gt) == "9"
    exact = score_protocol_answer(9, gt)
    assert exact["exact_match"] is True and exact["partial"] == 1.0
    near = score_protocol_answer(8, gt)
    assert near["exact_match"] is False and 0.0 < near["partial"] < 1.0
    none = score_protocol_answer(None, gt)
    assert none["partial"] == 0.0


# --------------------------------------------------------------------------- #
# 3+6. Gather-only star: sink passes on the sink's state; all_agents fails
#      even when the majority is correct (one wrong agent must sink the run).
# --------------------------------------------------------------------------- #
def test_gather_only_star_sink_passes_all_agents_fails():
    inst = _instance("I-01", 2)
    # 手工构造 5-agent 版本星形聚合不可行(fixture n=2)；用 2-agent 等价:
    # 0<-1 汇聚，agent0 正确、agent1 错误。
    gt = SiloProtocolAdapter(inst).build_global_task()
    result = _fake_result([[(1, 0)]], answers=[9, 3])
    sink_score = _score_protocol_result(
        result, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="sink",
    )
    assert sink_score.extra["sink_id"] == 0
    assert sink_score.extra["sink_information_coverage"] == 1.0
    assert sink_score.success is True  # sink 状态正确即可
    all_score = _score_protocol_result(
        result, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="all_agents",
    )
    assert all_score.extra["per_agent_correct"] == [True, False]
    assert all_score.extra["agent_success_rate"] == 0.5
    assert all_score.extra["all_agents_exact"] is False
    assert all_score.extra["all_agents_full_information"] is False
    assert all_score.success is False  # 多数票不能掩盖个体错误


# --------------------------------------------------------------------------- #
# 4+7. Gather then broadcast: both modes pass structural coverage; with every
#      agent correct, S=1 and all_agents_exact is True.
# --------------------------------------------------------------------------- #
def test_gather_broadcast_passes_both_modes_and_s_equals_one():
    inst = _instance("I-01", 2)
    gt = SiloProtocolAdapter(inst).build_global_task()
    result = _fake_result([[(1, 0)], [(0, 1)]], answers=[9, 9])
    sink_score = _score_protocol_result(
        result, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="sink",
    )
    assert sink_score.success is True
    all_score = _score_protocol_result(
        result, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="all_agents",
    )
    assert all_score.extra["per_agent_correct"] == [True, True]
    assert all_score.extra["agent_success_rate"] == 1.0
    assert all_score.extra["all_agents_exact"] is True
    assert all_score.extra["min_information_coverage"] == 1.0
    assert all_score.extra["all_agents_full_information"] is True
    assert 0.0 < all_score.extra["communication_density"] <= 1.0
    assert all_score.success is True


# --------------------------------------------------------------------------- #
# 5. One-way chain: the end sink passes; all_agents does not (structurally).
# --------------------------------------------------------------------------- #
def test_one_way_chain_end_sink_passes_all_agents_fails():
    inst = _instance("I-01", 2)
    gt = SiloProtocolAdapter(inst).build_global_task()
    # chain 0->1：末端 agent1 覆盖全体；agent0 只有自己。
    result = _fake_result([[(0, 1)]], answers=[9, 9])
    sink_score = _score_protocol_result(
        result, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="sink",
    )
    assert sink_score.extra["sink_id"] == 1  # argmax structural coverage
    assert sink_score.extra["sink_information_coverage"] == 1.0
    assert sink_score.success is True
    all_score = _score_protocol_result(
        result, inst, SiloProtocolAdapter(inst), gt,
        extra={}, information_goal="all_agents",
    )
    # 答案恰好都对（离线双方都持 9），但结构覆盖必须暴露单向链的信息不对称。
    assert all_score.extra["information_coverage_by_agent"][0] == 0.5
    assert all_score.extra["all_agents_full_information"] is False


# --------------------------------------------------------------------------- #
# 8. Segmented tasks grade EVERY agent against its OWN expected output.
# --------------------------------------------------------------------------- #
def test_segmented_all_agents_uses_per_agent_expected_outputs():
    seg = _instance("SEG-99")
    gt = SiloProtocolAdapter(seg).build_global_task()
    # agent0 的段 [1,3,6]、agent1 的段 [10,15]：各自持有自己的正确段。
    result = _fake_result(
        [[(0, 1)], [(1, 0)]], answers=[[1, 3, 6], [10, 15]], case_id="SEG-99"
    )
    ok = _score_protocol_result(
        result, seg, SiloProtocolAdapter(seg), gt,
        extra={}, information_goal="all_agents",
    )
    assert ok.extra["per_agent_correct"] == [True, True]
    assert ok.success is True
    # agent1 交出 agent0 的段：必须按"自己的段"判错，而不是按全局多数。
    swapped = _fake_result(
        [[(0, 1)], [(1, 0)]], answers=[[1, 3, 6], [1, 3, 6]], case_id="SEG-99"
    )
    bad = _score_protocol_result(
        swapped, seg, SiloProtocolAdapter(seg), gt,
        extra={}, information_goal="all_agents",
    )
    assert bad.extra["per_agent_correct"] == [True, False]
    assert bad.success is False


# --------------------------------------------------------------------------- #
# 9 (soldier half). The four soldier templates are genuinely different and
#    audit-clean; init prompts keep the offline fake-parseable markers.
# --------------------------------------------------------------------------- #
def test_soldier_prompt_templates_differ_and_pass_audit():
    import hashlib

    kwargs = dict(
        task_context={"task_ref": "abc123", "n_agents": 2},
        prompt_context="Task text.\n",
        local_observation={"agent_id": 0, "n_agents": 2, "input_shard": [1]},
        task_ref="abc123",
    )
    sink_init = format_sink_protocol_init_prompt(**kwargs)
    all_init = format_all_agents_protocol_init_prompt(**kwargs)
    merge_kwargs = dict(
        merge_mode="llm_full_merge",
        task_context={"task_ref": "abc123", "n_agents": 2},
        prompt_context="Task text.\n",
        own_answer=1,
        inbox_answers=[2],
        verified_answer=None,
        task_ref="abc123",
    )
    sink_merge = format_sink_protocol_merge_prompt(**merge_kwargs)
    all_merge = format_all_agents_protocol_merge_prompt(**merge_kwargs)
    prompts = [sink_init, all_init, sink_merge, all_merge]
    hashes = {hashlib.sha256(p.encode()).hexdigest() for p in prompts}
    assert len(hashes) == 4  # all four templates are distinct
    for p in prompts:
        assert find_leakage_tokens(p) == []
    # 语义分离：sink 明确单一汇点；all_agents 明确全员独立提交。
    assert "sink agent is responsible" in sink_init
    assert "EVERY agent, including you" in all_init
    assert "Non-sink agents are NOT required" in sink_merge
    assert "submit it independently" in all_merge
    # all_agents 模板绝不出现"所有 Agent 必须提交相同答案"式要求。
    assert "same final answer" not in all_init.lower()
    # 离线 fake 客户端解析的三段标记保持存在与次序。
    for init in (sink_init, all_init):
        a = init.index("LOCAL_OBSERVATION_JSON:")
        b = init.index("OLD_BELIEF_STATE_JSON:")
        c = init.index("INBOX_JSON:")
        assert a < b < c


# --------------------------------------------------------------------------- #
# 10+14. GraphGen parse failure: NO named fallback; the run fails with
#        graph_generation_failed, and the architect audit artifacts persist
#        (prompt + sha + scrubbed responses, no secrets).
# --------------------------------------------------------------------------- #
class _JunkLLM:
    """Deliberately unparseable architect responses (offline)."""

    def __init__(self, secret: str = "") -> None:
        self.secret = secret

    def complete(self, prompt, model_name, temperature=None):
        text = f"NOT-JSON {self.secret} garbage"
        return LLMResponse(
            text=text, usage=LLMUsage(prompt_tokens=1, completion_tokens=1)
        )


def test_graphgen_parse_failure_has_no_named_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("MASBENCH_TEST_API_KEY", "sk-test-secret-abcdef123456")
    inst = _instance("I-01")
    cfg = RunConfig(
        use_planner=True,
        planner_mode="graph_generate",
        llm_provider="openai",  # non-fake platform => the architect LLM path
        model_name="junk",
        n_agents=2,
        graph_artifacts_dir=str(tmp_path / "artifacts"),
    )
    score = run_instance(
        inst, cfg, llm_client=_JunkLLM(secret="sk-test-secret-abcdef123456")
    )
    assert score.success is False and score.partial == 0.0
    assert score.extra["graph_generation_failed"]
    assert score.extra["topology"] is None  # 绝无 one_peer/tree/mesh 具名兜底
    # 审计产物持久化（非 TemporaryDirectory）。
    calls = list((tmp_path / "artifacts").rglob("architect_call.json"))
    assert calls, "architect_call.json must persist"
    payload = json.loads(calls[0].read_text())
    assert payload["graph_generation_failed"]
    assert payload["rendered_prompt"] and payload["prompt_sha256"]
    blob = json.dumps(payload)
    assert "sk-test-secret-abcdef123456" not in blob  # 密钥被遮蔽
    assert "[REDACTED:MASBENCH_TEST_API_KEY]" in blob
    # 提示词本身过泄漏审计。
    assert find_leakage_tokens(payload["rendered_prompt"]) == []


# --------------------------------------------------------------------------- #
# 11. fallback/fixed/fake records cannot enter a clean GraphGen bank.
# --------------------------------------------------------------------------- #
def test_clean_bank_admission_blocks_contaminated_provenance():
    def card(skill_id: str, provenance: str | None, goal: str = "sink") -> SkillCard:
        return SkillCard(
            skill_id=skill_id,
            task_family="silo",
            objective="accuracy_first",
            trigger={"task_family": "silo", "information_goal": goal},
            information_goal=goal,  # type: ignore[arg-type]
            provenance=provenance,  # type: ignore[arg-type]
            organization_policy={"topology_name": f"generated:{skill_id}"},
            evidence=[{"status": "observed"}],
        )

    bank = SkillBank(
        skills=[
            card("clean_llm", "llm_generated"),
            card("clean_replay", "skill_replay"),
            card("dirty_fixed", "fixed_named"),
            card("dirty_fallback", "named_fallback"),
            card("dirty_fake", "fake"),
            card("legacy_none", None),
        ]
    )
    request = PlannerRequest(
        task_family="silo",
        n_agents=2,
        objective=ObjectiveSpec.from_name("accuracy_first"),
        planner_mode="graph_generate",
        information_goal="sink",
        provenance_allowlist=["llm_generated", "skill_replay"],
    )
    got = {s.skill_id for s in bank.retrieve(request)}
    assert got == {"clean_llm", "clean_replay"}
    # 无白名单（legacy 检索）不受影响。
    legacy = request.model_copy(update={"provenance_allowlist": None})
    assert len(bank.retrieve(legacy)) == 6


# --------------------------------------------------------------------------- #
# 12. sink cards and all_agents cards cannot cross-retrieve or merge.
# --------------------------------------------------------------------------- #
def test_cross_mode_skill_isolation():
    from exp_graph.mas.skill_bank import _skill_equivalence_key

    def card(goal: str) -> SkillCard:
        return SkillCard(
            skill_id=f"silo__x__{goal}",
            task_family="silo",
            objective="accuracy_first",
            trigger={"task_family": "silo", "information_goal": goal},
            information_goal=goal,  # type: ignore[arg-type]
            provenance="llm_generated",  # type: ignore[arg-type]
            organization_policy={"topology_name": "generated:x"},
            evidence=[{"status": "observed"}],
        )

    sink_card, all_card = card("sink"), card("all_agents")
    bank = SkillBank(skills=[sink_card, all_card])
    base = PlannerRequest(
        task_family="silo",
        n_agents=2,
        objective=ObjectiveSpec.from_name("accuracy_first"),
        planner_mode="graph_generate",
    )
    sink_hits = bank.retrieve(base.model_copy(update={"information_goal": "sink"}))
    all_hits = bank.retrieve(
        base.model_copy(update={"information_goal": "all_agents"})
    )
    assert {s.skill_id for s in sink_hits} == {"silo__x__sink"}
    assert {s.skill_id for s in all_hits} == {"silo__x__all_agents"}
    # 等价键按模式命名空间：结构相同也不允许合并/去重互吞。
    assert _skill_equivalence_key(sink_card) != _skill_equivalence_key(all_card)


# --------------------------------------------------------------------------- #
# 13+15. Cache key / bench report carry the mode; the fake offline pipeline
#        runs end-to-end in BOTH modes.
# --------------------------------------------------------------------------- #
def test_cache_key_and_report_carry_mode_and_offline_e2e(tmp_path):
    cfg_sink = RunConfig(llm_provider="fake", n_agents=2, silo_eval_mode="sink")
    cfg_all = RunConfig(llm_provider="fake", n_agents=2, silo_eval_mode="all_agents")
    k1 = EvidenceCache.key(
        case_id="I-01", n_agents=2, planner_mode="graph_generate",
        objective="accuracy_first", seed=0, cfg=cfg_sink,
    )
    k2 = EvidenceCache.key(
        case_id="I-01", n_agents=2, planner_mode="graph_generate",
        objective="accuracy_first", seed=0, cfg=cfg_all,
    )
    assert k1 != k2 and "mode=sink" in k1 and "mode=all_agents" in k2

    adapter = SiloBenchAdapter(DATA)
    for mode, out in (("sink", tmp_path / "sink"), ("all_agents", tmp_path / "all")):
        cfg = RunConfig(
            llm_provider="fake", silo_eval_mode=mode,
            graph_artifacts_dir=str(tmp_path / "ga"),
        )
        results = run_benchmark(
            adapter,
            cases=["I-01"],
            agent_counts=[2],
            seeds=[0],
            arms=["fixed", "graphgen"],
            cfg_base=cfg,
            fixed_topologies=["chain"],
            graphgen_candidates=1,
            out=str(out),
            progress=False,
        )
        assert results["silo_eval_mode"] == mode
        assert results["clean_run"] is True
        assert len(results["runs"]) == 2  # 1 fixed + 1 graphgen, end to end
        report = (out / "report.md").read_text()
        assert f"Silo eval mode: `{mode}`" in report
        for run in results["runs"]:
            assert run.get("error") is None or "error" not in run

    # run_fixed_protocol 双模式各自可跑（15 的 fixed 侧）。
    inst = _instance("I-01")
    for mode in ("sink", "all_agents"):
        cfg = RunConfig(llm_provider="fake", n_agents=2, silo_eval_mode=mode)
        score = run_fixed_protocol(inst, cfg, topology="chain")
        assert score.extra["silo_eval_mode"] == mode
        assert score.extra["provenance"] == "fixed_named"


# --------------------------------------------------------------------------- #
# Sanitizer unit: the Communication Protocol section is excised as a whole.
# --------------------------------------------------------------------------- #
def test_sanitize_task_description_removes_protocol_section():
    text = (
        "**Task: X**\n\nBody.\n\n**Algorithm:**\nDo it.\n\n"
        "**Communication Protocol:**\nTopology: Chain (0-1-2). Exchange.\n"
        "All agents must submit the same final answer.\n"
    )
    out = sanitize_task_description(text)
    assert "Communication Protocol" not in out
    assert "Topology: Chain" not in out
    assert "**Algorithm:**" in out and "Body." in out
