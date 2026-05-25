from pathlib import Path
import json

import pytest

from exp_graph.llm.base import LLMResponse, LLMUsage
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphValidationOptions,
    build_free_graph_prompt,
    compile_generated_graph,
    plan_free_graph,
    parse_graph_candidates_response,
    repair_graph_plan,
    validate_graph_plan,
    _objective_score,
)
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest, SkillCard
from exp_graph.mas.skill_bank import SkillBank
from exp_graph.protocols import build_protocol_schedule_from_spec
from exp_graph.tasks import CountFrequencyTaskAdapter


def test_generated_graph_schema_accepts_valid_temporal_dag() -> None:
    graph = GeneratedGraphPlan(
        candidate_id="g1",
        name="pair_reduce",
        n_agents=4,
        selected_primary=3,
        steps=[
            GeneratedGraphStep(edges=[[0, 1], [2, 3]]),
            GeneratedGraphStep(edges=[[1, 3]]),
        ],
    )

    assert graph.graph_type == "temporal_dag"
    assert graph.steps[0].edges == [(0, 1), (2, 3)]


def test_generated_graph_schema_rejects_bad_edges() -> None:
    with pytest.raises(ValueError, match="pair"):
        GeneratedGraphStep(edges=[[0, 1, 2]])


def test_graph_validator_rejects_self_loop_invalid_agent_budget() -> None:
    graph = GeneratedGraphPlan(
        n_agents=3,
        selected_primary=2,
        steps=[
            GeneratedGraphStep(edges=[(0, 0), (1, 4)]),
            GeneratedGraphStep(edges=[(0, 1), (1, 2)]),
        ],
    )
    result = validate_graph_plan(
        graph,
        GraphValidationOptions(n_agents=3, max_steps=1, max_messages=1),
    )

    assert result.valid is False
    assert any("self-loop" in error for error in result.errors)
    assert any("invalid agent" in error for error in result.errors)
    assert any("max_steps" in error for error in result.errors)
    assert any("max_messages" in error for error in result.errors)


def test_graph_repair_dedupes_and_fixes_selected_primary() -> None:
    graph = GeneratedGraphPlan(
        n_agents=3,
        selected_primary=99,
        steps=[
            GeneratedGraphStep(edges=[(0, 1), (0, 1), (1, 1), (1, 2), (9, 2)])
        ],
    )

    repaired, notes = repair_graph_plan(
        graph,
        GraphValidationOptions(n_agents=3, max_messages=2),
    )

    assert repaired.steps[0].edges == [(0, 1), (1, 2)]
    assert repaired.selected_primary == 2
    assert notes


def test_generated_graph_compiles_to_protocol_spec() -> None:
    graph = GeneratedGraphPlan(
        candidate_id="g1",
        name="pair_reduce",
        n_agents=4,
        selected_primary=3,
        steps=[
            GeneratedGraphStep(edges=[(0, 1), (2, 3)]),
            GeneratedGraphStep(edges=[(1, 3)]),
        ],
    )

    spec = compile_generated_graph(graph, GraphValidationOptions(n_agents=4))
    schedule = build_protocol_schedule_from_spec(spec)

    assert spec.metadata["generated_graph"] is True
    assert spec.metadata["candidate_id"] == "g1"
    assert spec.metadata["topology_equivalence_hash"]
    assert spec.metadata["canonical_temporal_edges"]
    assert schedule[0].transmissions == [(0, 1), (2, 3)]


def test_graph_validator_allows_source_fanout_and_temporal_feedback() -> None:
    fanout = GeneratedGraphPlan(
        n_agents=4,
        selected_primary=3,
        steps=[
            GeneratedGraphStep(edges=[(0, 1), (0, 2), (0, 3), (1, 0)]),
            GeneratedGraphStep(edges=[(1, 0), (2, 0)]),
        ],
    )
    result = validate_graph_plan(
        fanout,
        GraphValidationOptions(n_agents=4, max_receiver_fan_in=2, max_messages=6),
    )

    assert result.valid is True


def test_graph_validator_still_limits_receiver_fan_in() -> None:
    graph = GeneratedGraphPlan(
        n_agents=4,
        selected_primary=3,
        steps=[GeneratedGraphStep(edges=[(0, 3), (1, 3), (2, 3)])],
    )
    result = validate_graph_plan(
        graph,
        GraphValidationOptions(n_agents=4, max_receiver_fan_in=2),
    )

    assert result.valid is False
    assert any("max_receiver_fan_in" in error for error in result.errors)


def test_parse_graph_candidates_response_rejects_schema_echo() -> None:
    with pytest.raises(ValueError, match="schema"):
        parse_graph_candidates_response(
            '{"required_json_shape": {"candidates": []}}',
            n_agents=4,
        )


def test_parse_graph_candidates_response_accepts_candidates_array() -> None:
    graphs = parse_graph_candidates_response(
        """
        {
          "candidates": [
            {
              "candidate_id": "g1",
              "name": "simple",
              "n_agents": 2,
              "selected_primary": 1,
              "steps": [{"edges": [[0, 1]]}]
            }
          ]
        }
        """,
        n_agents=2,
    )

    assert graphs[0].candidate_id == "g1"
    assert graphs[0].steps[0].edges == [(0, 1)]


def test_accuracy_max_candidate_score_uses_only_rmse() -> None:
    high_cost_low_rmse = {
        "objective": "budget_first",
        "mean_rmse": 1.0,
        "exact_match_rate": 0.0,
        "mean_messages": 1000.0,
        "mean_token_cost": 1_000_000.0,
    }
    low_cost_high_rmse = {
        "objective": "budget_first",
        "mean_rmse": 2.0,
        "exact_match_rate": 1.0,
        "mean_messages": 1.0,
        "mean_token_cost": 1.0,
    }

    assert _objective_score(
        high_cost_low_rmse,
        score_mode="accuracy_max",
    ) > _objective_score(
        low_cost_high_rmse,
        score_mode="accuracy_max",
    )


def test_free_graph_prompt_includes_avoid_skills_as_constraints() -> None:
    prompt = build_free_graph_prompt(
        request=PlannerRequest.from_names(
            n_agents=4,
            array_size=128,
            planner_mode="graph_generate",
        ),
        skills=[],
        avoid_skills=[
            SkillCard(
                skill_id="cf_avoid_generated:bad",
                objective="balanced",
                organization_policy={"topology_name": "generated:bad"},
            )
        ],
        options=GraphValidationOptions(n_agents=4),
        num_candidates=1,
    )

    assert "avoid_or_counterexample_skills" in prompt
    assert "cf_avoid_generated:bad" in prompt
    assert "negative constraints" in prompt


def test_free_graph_prompt_uses_structural_hints_not_named_templates() -> None:
    prompt = build_free_graph_prompt(
        request=PlannerRequest.from_names(
            n_agents=4,
            array_size=128,
            planner_mode="graph_generate",
        ),
        skills=[],
        avoid_skills=[],
        options=GraphValidationOptions(n_agents=4),
        num_candidates=1,
    )

    assert "tree-like" not in prompt
    assert "tree reduce" not in prompt
    assert "star sink" not in prompt
    assert '"operator_hint": "tree_reduce"' not in prompt
    assert '"fallback_topology": "tree"' not in prompt
    assert "bounded fan-in aggregation" in prompt
    assert "explicit sink placement" in prompt
    assert "audit edge for provenance check" in prompt
    assert "temporal reachability" in prompt


def test_free_graph_prompt_includes_skill_design_insights() -> None:
    prompt = build_free_graph_prompt(
        request=PlannerRequest.from_names(
            n_agents=4,
            array_size=128,
            planner_mode="graph_generate",
        ),
        skills=[
            SkillCard(
                skill_id="cf_generated_design",
                objective="balanced",
                organization_policy={"topology_name": "generated:design"},
                design_insights=[
                    {
                        "insight_id": "insight_keep_sink",
                        "summary": "Preserve the validated sink when fan-in stays bounded.",
                        "operation_recommendations": [
                            {
                                "action_type": "preserve",
                                "target": "sink_selection",
                                "instruction": "Keep selected_primary=3.",
                            }
                        ],
                    }
                ],
            )
        ],
        avoid_skills=[],
        options=GraphValidationOptions(n_agents=4),
        num_candidates=1,
    )

    assert "design_insights" in prompt
    assert "insight_keep_sink" in prompt
    assert "Prioritize design_insights.operation_recommendations" in prompt
    assert "Keep selected_primary=3" in prompt


def test_plan_free_graph_replays_skill_protocol_as_candidate(tmp_path: Path) -> None:
    protocol_spec = {
        "name": "stored_tree",
        "n_agents": 4,
        "steps": [
            {
                "transmissions": [[0, 1], [2, 3]],
                "description": "pair reduce",
                "operator": "tree_reduce",
            },
            {
                "transmissions": [[1, 3]],
                "description": "final sink",
                "operator": "tree_reduce",
            },
        ],
        "operators": ["llm_generate_dag"],
        "metadata": {
            "generated_graph": True,
            "candidate_id": "old_best",
            "selected_primary": 3,
        },
    }
    bank = SkillBank(
        [
            SkillCard(
                skill_id="cf_topology_generated:stored_tree__a4__arr128",
                objective="balanced",
                trigger={
                    "min_agents": 4,
                    "max_agents": 4,
                    "min_array_size": 128,
                    "max_array_size": 128,
                    "condition_key": "agents_4__arrays_128",
                },
                organization_policy={
                    "topology_name": "generated:stored_tree",
                    "protocol_spec": protocol_spec,
                },
                expected_tradeoff={"mean_rmse": 1.0},
            )
        ]
    )

    result = plan_free_graph(
        request=PlannerRequest.from_names(
            n_agents=4,
            array_size=128,
            planner_mode="graph_generate",
        ),
        runtime=MASRuntimeConfig(llm_provider="fake", graph_search_mode="single"),
        skill_bank=bank,
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
    )

    assert result.selected_candidate_id.startswith("skill_")
    assert result.plan.protocol_spec.name == "stored_tree"
    assert result.plan.protocol_spec.steps[0].transmissions == [(0, 1), (2, 3)]


class _StaticGraphClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def complete(
        self,
        prompt: str,
        model_name: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            text=json.dumps(self.payload),
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        )


def test_plan_free_graph_dedupes_equivalent_candidates_before_probe(
    tmp_path: Path,
) -> None:
    client = _StaticGraphClient(
        {
            "candidates": [
                {
                    "candidate_id": "tree_a",
                    "name": "tree_a",
                    "n_agents": 4,
                    "selected_primary": 3,
                    "steps": [
                        {"edges": [[0, 1], [2, 3]]},
                        {"edges": [[1, 3]]},
                    ],
                },
                {
                    "candidate_id": "tree_b",
                    "name": "tree_b",
                    "n_agents": 4,
                    "selected_primary": 0,
                    "steps": [
                        {"edges": [[1, 0], [3, 2]]},
                        {"edges": [[2, 0]]},
                    ],
                },
                {
                    "candidate_id": "tree_audit",
                    "name": "tree_audit",
                    "n_agents": 4,
                    "selected_primary": 3,
                    "steps": [
                        {"edges": [[0, 1], [2, 3]]},
                        {"edges": [[1, 3], [1, 0]]},
                    ],
                },
            ]
        }
    )

    result = plan_free_graph(
        request=PlannerRequest.from_names(
            n_agents=4,
            array_size=8,
            planner_mode="graph_generate",
            merge_mode="deterministic",
            init_mode="deterministic",
        ),
        runtime=MASRuntimeConfig(
            llm_provider="openai",
            model_name="fake",
            graph_search_mode="topk",
            num_graph_candidates=3,
            graph_validation_seeds=[1],
        ),
        skill_bank=SkillBank([]),
        seed=1,
        task_adapter=CountFrequencyTaskAdapter(),
        output_dir=tmp_path,
        llm_client=client,
    )

    records = json.loads((tmp_path / "generated_graph_candidates.json").read_text())
    statuses = {record["candidate_id"]: record["status"] for record in records}

    assert result.selected_candidate_id in {"tree_a", "tree_audit"}
    assert statuses["tree_b"] == "duplicate_equivalent_topology"
    assert statuses["tree_a"] != "duplicate_equivalent_topology"
    assert statuses["tree_audit"] != "duplicate_equivalent_topology"
    assert (tmp_path / "graph_candidate_eval" / "tree_a" / "seed_1.json").exists()
    assert not (tmp_path / "graph_candidate_eval" / "tree_b").exists()
    summary = json.loads((tmp_path / "graph_validation_summary.json").read_text())
    assert summary["duplicate_equivalent_candidate_count"] == 1
