from pathlib import Path

from exp_graph.mas.evolution import build_cost_patches_from_evidence
from exp_graph.mas.insights import build_insight_prompt
from exp_graph.mas.llm_planner import build_emperor_prompt, parse_llm_plan_response
from exp_graph.mas.consolidation import consolidate_skill_updates
from exp_graph.mas.schemas import EvidenceRecord, PlannerRequest, SkillCard, SkillPatch
from exp_graph.mas.skill_bank import SkillBank


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def test_consolidator_merges_evidence_and_bumps_version():
    bank = SkillBank.load_dir(SKILL_DIR)
    records = [
        EvidenceRecord(
            evidence_id="run:tree:1",
            source_type="run",
            topology_name="tree",
            n_agents=4,
            seed=1,
            metrics={
                "final_rmse": 0.1,
                "total_messages": 3,
                "token_cost": 20,
                "final_exact_match": True,
            },
        )
    ]
    patch = SkillPatch(
        patch_id="merge_tree_run_1",
        action="merge",
        target_skill_id="cf_budget_tree",
        evidence_refs=["run:tree:1"],
        update={
            "risk_notes": [
                {
                    "source": "test",
                    "summary": "single run evidence should merge, not replace",
                }
            ]
        },
        lesson="merge one new run evidence record",
        confidence=0.8,
        source="test",
    )
    before = bank.get("cf_budget_tree").version

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[patch],
        evidence_records=records,
        batch_id="test_batch",
    )

    skill = updated.get("cf_budget_tree")
    assert skill.version != before
    assert "run:tree:1" in skill.evidence_refs
    assert skill.expected_tradeoff["active_evidence_count"] == 1
    assert result.counts["merged"] == 1
    assert result.revisions[0].skill_id == "cf_budget_tree"


def test_consolidator_recomputes_exact_match_rate_from_run_evidence():
    bank = SkillBank.load_dir(SKILL_DIR)
    records = [
        EvidenceRecord(
            evidence_id="run:tree:exact",
            source_type="run",
            topology_name="tree",
            n_agents=4,
            seed=1,
            metrics={
                "final_rmse": 0.0,
                "total_messages": 3,
                "token_cost": 20,
                "final_exact_match": True,
            },
        )
    ]

    updated, _result = consolidate_skill_updates(
        bank=bank,
        patches=[
            SkillPatch(
                patch_id="merge_tree_exact",
                action="merge",
                target_skill_id="cf_budget_tree",
                evidence_refs=["run:tree:exact"],
                lesson="exact tree run",
            )
        ],
        evidence_records=records,
        batch_id="exact_batch",
    )

    assert updated.get("cf_budget_tree").expected_tradeoff["exact_match_rate"] == 1.0


def test_consolidator_discards_patch_with_mismatched_evidence_topology():
    bank = SkillBank.load_dir(SKILL_DIR)
    before = bank.get("cf_budget_tree").model_dump()
    records = [
        EvidenceRecord(
            evidence_id="run:peer:1",
            source_type="run",
            topology_name="one_peer_exponential_dag_star",
            n_agents=8,
            seed=1,
            metrics={"final_rmse": 1.0, "token_cost": 100},
        )
    ]

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[
            SkillPatch(
                patch_id="bad_cost_patch",
                action="merge",
                target_skill_id="cf_budget_tree",
                evidence_refs=["run:peer:1"],
                lesson="wrongly route peer evidence into tree",
            )
        ],
        evidence_records=records,
        batch_id="mismatch_batch",
    )

    assert updated.get("cf_budget_tree").model_dump() == before
    assert result.counts["discarded"] == 1
    assert result.warnings


def test_consolidator_discard_does_not_change_skill():
    bank = SkillBank.load_dir(SKILL_DIR)
    before = bank.get("cf_budget_tree").model_dump()

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[
            SkillPatch(
                patch_id="noise",
                action="discard",
                target_skill_id="cf_budget_tree",
                lesson="noise",
            )
        ],
        evidence_records=[],
        batch_id="discard_batch",
    )

    assert updated.get("cf_budget_tree").model_dump() == before
    assert result.counts["discarded"] == 1


def test_cost_analyst_does_not_emit_cost_patch_for_single_topology_run():
    records = [
        EvidenceRecord(
            evidence_id="run:peer:single",
            source_type="run",
            topology_name="one_peer_exponential_dag_star",
            n_agents=8,
            seed=1,
            metrics={
                "final_rmse": 9.0,
                "total_messages": 31,
                "token_cost": 39000,
            },
        )
    ]

    assert build_cost_patches_from_evidence(records) == []


def test_openai_json_prompts_contain_lowercase_json_keyword():
    request = PlannerRequest.from_names(
        n_agents=8,
        objective="accuracy_first",
        planner_mode="operator_compose",
    )
    bank = SkillBank.load_dir(SKILL_DIR)
    emperor_prompt = build_emperor_prompt(
        request=request,
        positive_skills=bank.retrieve(request),
        avoid_skills=[],
    )
    insight_prompt = build_insight_prompt(
        evidence_pack={"experiment_id": "demo", "topologies": {}}
    )

    assert "json" in emperor_prompt
    assert "json" in insight_prompt


def test_parse_llm_plan_response_unwraps_plan_but_rejects_schema_echo():
    request = PlannerRequest.from_names(n_agents=4)

    parsed = parse_llm_plan_response(
        '{"plan": {"planner_mode": "topology_select", "topology_name": "tree"}}',
        request,
    )

    assert parsed["topology_name"] == "tree"
    try:
        parse_llm_plan_response('{"output_schema": {"topology_name": "tree"}}', request)
    except ValueError as exc:
        assert "schema" in str(exc)
    else:
        raise AssertionError("schema echo should be rejected")


def test_evolve_skills_accepts_generated_topology_policy():
    bank = SkillBank.load_dir(SKILL_DIR)
    candidate = SkillCard(
        skill_id="cf_generated_pair_reduce",
        skill_type="generated_topology_policy",
        objective="accuracy_first",
        organization_policy={
            "planner_mode": "graph_generate",
            "planner_policy": "free_graph",
            "topology_name": "generated:pair_reduce",
            "graph_type": "temporal_dag",
            "protocol_spec": {
                "name": "pair_reduce",
                "n_agents": 4,
                "steps": [
                    {"transmissions": [[0, 1], [2, 3]], "description": "pair"},
                    {"transmissions": [[1, 3]], "description": "sink"},
                ],
            },
            "selected_primary": 3,
        },
    )
    record = EvidenceRecord(
        evidence_id="run:generated:pair_reduce:1",
        source_type="run",
        topology_name="generated:pair_reduce",
        n_agents=4,
        seed=1,
        metrics={"final_rmse": 0.0, "token_cost": 100, "final_exact_match": True},
    )
    patch = SkillPatch(
        patch_id="add_generated_pair_reduce",
        action="add",
        candidate_skill=candidate,
        evidence_refs=[record.evidence_id],
        lesson="add stable generated DAG skill",
    )

    updated, result = consolidate_skill_updates(
        bank=bank,
        patches=[patch],
        evidence_records=[record],
        batch_id="generated_batch",
    )

    skill = updated.get("cf_generated_pair_reduce")
    assert skill is not None
    assert skill.skill_type == "generated_topology_policy"
    assert result.counts["added"] == 1
