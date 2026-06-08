from exp_graph.mas.graph_generation import (
    GraphValidationOptions,
    build_free_graph_prompt,
)
from exp_graph.mas.schemas import PlannerRequest


def _opt(n: int = 2) -> GraphValidationOptions:
    return GraphValidationOptions(
        n_agents=n, max_steps=4, max_messages=32, max_receiver_fan_in=4, repair_attempts=1
    )


def test_cf_prompt_unchanged():
    p = build_free_graph_prompt(
        request=PlannerRequest(task_family="count_frequency", n_agents=2),
        skills=[], options=_opt(), num_candidates=1,
    )
    assert "count_frequency_design_notes" in p
    assert "For count_frequency" in p
    assert "task_design_notes" not in p


def test_non_cf_prompt_is_task_aware():
    brief = "Global Max: find the global maximum across all agents"
    p = build_free_graph_prompt(
        request=PlannerRequest(task_family="silo", n_agents=2),
        skills=[], options=_opt(), num_candidates=1, task_brief=brief,
    )
    assert "task_design_notes" in p
    assert brief in p
    # No false claim that a non-CF task is frequency counting.
    assert "sharded frequency counting" not in p
    assert "count_frequency_design_notes" not in p


def test_non_cf_without_brief_falls_back_to_family():
    p = build_free_graph_prompt(
        request=PlannerRequest(task_family="silo", n_agents=2),
        skills=[], options=_opt(), num_candidates=1,
    )
    assert "task_design_notes" in p
    assert "Task family: silo" in p
