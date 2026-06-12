"""M19c (dev-11): what you verify must be what you deploy.

dev-11 deployed a 4-step instruction-stripped mutilation of a 5-step
verified recipe: validate failed on max_messages, repair_graph_plan trimmed
the final answer step AND rebuilt steps without their instruction field.
Two invariants pinned here:

1. repair never strips instructions from steps it keeps.
2. skill-replay candidates (candidate_id ``skill_*``) are admitted under
   widened budgets that fit the stored artifact exactly -- budgets bind
   SYNTHESIS, not replay of an already-executed spec. Fresh candidates
   stay budget-bound.
"""

from __future__ import annotations

from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphValidationOptions,
    _validate_and_compile_candidates,
    repair_graph_plan,
)


def _bidirectional_chain_step(n: int, instruction: str) -> GeneratedGraphStep:
    edges = []
    for i in range(n - 1):
        edges.append((i, i + 1))
        edges.append((i + 1, i))
    return GeneratedGraphStep(
        description="exchange", edges=edges, instruction=instruction
    )


def _recipe_like_plan(candidate_id: str) -> GeneratedGraphPlan:
    # 5 steps x 8 edges = 40 messages at n=5: exceeds the default
    # max_messages=32 exactly like dev-11's recipe
    return GeneratedGraphPlan(
        candidate_id=candidate_id,
        name="recipe_like",
        n_agents=5,
        selected_primary=2,
        steps=[_bidirectional_chain_step(5, f"step {i} instruction") for i in range(5)],
    )


def test_repair_preserves_instructions():
    options = GraphValidationOptions(n_agents=5, max_steps=4, max_messages=32)
    repaired, _notes = repair_graph_plan(_recipe_like_plan("candidate_x"), options)
    assert repaired.steps, "repair must keep some steps"
    for step in repaired.steps:
        assert step.instruction, "repair dropped step instructions"


def test_skill_replay_admitted_verbatim():
    options = GraphValidationOptions(n_agents=5, max_steps=4, max_messages=32)
    states = _validate_and_compile_candidates(
        [_recipe_like_plan("skill_silo__recipe_r__a5")], options
    )
    state = states[0]
    assert state.record.status == "valid", state.record.validation_errors
    assert state.spec is not None
    assert len(state.spec.steps) == 5, "verified artifact must deploy whole"
    assert sum(len(s.transmissions) for s in state.spec.steps) == 40
    assert all((s.instruction or "").strip() for s in state.spec.steps)


def test_fresh_candidates_stay_budget_bound():
    options = GraphValidationOptions(n_agents=5, max_steps=4, max_messages=32)
    states = _validate_and_compile_candidates(
        [_recipe_like_plan("candidate_0")], options
    )
    state = states[0]
    assert state.record.status in {"repaired", "rejected"}
    if state.spec is not None:
        assert len(state.spec.steps) <= 4
        assert sum(len(s.transmissions) for s in state.spec.steps) <= 32
