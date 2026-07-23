from pathlib import Path

import pytest

from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphValidationOptions,
    compile_generated_graph,
    parse_graph_candidates_response,
    repair_graph_plan,
    validate_graph_plan,
    _objective_score,
)
from exp_graph.protocols import build_protocol_schedule_from_spec


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
    assert schedule[0].transmissions == [(0, 1), (2, 3)]


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
