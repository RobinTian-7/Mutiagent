"""D2: opt-in hard constraint that the generated DAG's sink (selected_primary)
is temporally reachable from ALL agents (full information coverage). Default OFF
so CF / existing behaviour is byte-identical; masbench (Silo) turns it on.
"""
from exp_graph.mas.graph_generation import (
    GeneratedGraphPlan,
    GeneratedGraphStep,
    GraphValidationOptions,
    repair_graph_plan,
    validate_graph_plan,
)


def _graph_missing_one(n=3, sink=2):
    # Only 0->2 ; agent 1 has NO temporal path to the sink (2).
    return GeneratedGraphPlan(
        n_agents=n, selected_primary=sink,
        steps=[GeneratedGraphStep(edges=[(0, 2)])],
    )


def test_coverage_off_by_default_is_only_a_warning():
    g = _graph_missing_one()
    res = validate_graph_plan(g, GraphValidationOptions(n_agents=3))
    assert res.valid  # structurally valid; coverage NOT enforced by default
    assert any("temporal path" in w for w in res.warnings)


def test_coverage_enforced_errors_when_agent_cannot_reach_sink():
    g = _graph_missing_one()
    res = validate_graph_plan(
        g, GraphValidationOptions(n_agents=3, require_full_sink_coverage=True)
    )
    assert not res.valid
    assert any("sink" in e.lower() for e in res.errors)


def test_coverage_enforced_requires_a_sink():
    g = GeneratedGraphPlan(n_agents=3, selected_primary=None,
                           steps=[GeneratedGraphStep(edges=[(0, 1), (1, 2)])])
    res = validate_graph_plan(
        g, GraphValidationOptions(n_agents=3, require_full_sink_coverage=True)
    )
    assert not res.valid


def test_coverage_repair_routes_uncovered_to_sink():
    g = _graph_missing_one()
    opts = GraphValidationOptions(n_agents=3, require_full_sink_coverage=True)
    repaired, notes = repair_graph_plan(g, opts)
    res = validate_graph_plan(repaired, opts)
    assert res.valid, res.errors  # after repair every agent reaches the sink
