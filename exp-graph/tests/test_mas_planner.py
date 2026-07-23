from pathlib import Path

from exp_graph.mas import EmperorPlanner, PlannerRequest, SkillBank
from exp_graph.protocols import build_protocol_schedule_from_spec


SKILL_DIR = Path(__file__).parents[1] / "configs" / "mas_skills"


def _bank() -> SkillBank:
    return SkillBank.load_dir(SKILL_DIR)


def test_topology_select_accuracy_first_uses_peer_star_skill() -> None:
    planner = EmperorPlanner(_bank())
    request = PlannerRequest.from_names(
        n_agents=8,
        objective="accuracy_first",
        planner_mode="topology_select",
    )

    plan = planner.plan(request)

    assert plan.skill_id == "cf_accuracy_peer_star"
    assert plan.topology_name == "one_peer_exponential_dag_star"
    assert plan.operators == ["local_solve", "peer_propagate", "star_sink"]


def test_topology_select_budget_first_uses_tree_skill() -> None:
    planner = EmperorPlanner(_bank())
    request = PlannerRequest.from_names(
        n_agents=8,
        objective="budget_first",
        planner_mode="topology_select",
    )

    plan = planner.plan(request)

    assert plan.skill_id == "cf_budget_tree"
    assert plan.topology_name == "tree"


def test_counterexample_skill_is_not_selected() -> None:
    planner = EmperorPlanner(_bank())
    request = PlannerRequest.from_names(
        n_agents=8,
        objective="balanced",
        planner_mode="topology_select",
        allowed_topologies=["random"],
    )

    plan = planner.plan(request)

    assert plan.skill_id != "cf_avoid_sparse_random"
    assert plan.topology_name != "random"


def test_operator_compose_generates_finite_protocol_spec() -> None:
    planner = EmperorPlanner(_bank())
    request = PlannerRequest.from_names(
        n_agents=4,
        objective="accuracy_first",
        planner_mode="operator_compose",
    )

    plan = planner.plan(request)

    assert plan.planner_mode == "operator_compose"
    assert plan.protocol_spec is not None
    assert plan.protocol_spec.metadata["compiled_from_topology"] == (
        "one_peer_exponential_dag_star"
    )
    assert len(build_protocol_schedule_from_spec(plan.protocol_spec)) == 3


def test_graph_generate_uses_tree_when_budget_is_tight() -> None:
    planner = EmperorPlanner(_bank())
    request = PlannerRequest.from_names(
        n_agents=8,
        objective="accuracy_first",
        budget="tight",
        planner_mode="graph_generate",
    )

    plan = planner.plan(request)

    assert plan.planner_mode == "graph_generate"
    assert plan.topology_name == "tree"
    assert plan.operators == ["local_solve", "tree_reduce"]
    assert plan.protocol_spec is not None
