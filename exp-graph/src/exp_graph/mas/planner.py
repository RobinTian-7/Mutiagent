"""Emperor planners that select or construct MAS protocol plans."""

from __future__ import annotations

from exp_graph.mas.operators import compose_protocol_from_operators
from exp_graph.mas.schemas import MASPlan, PlannerRequest, SkillCard
from exp_graph.mas.scoring import score_skill
from exp_graph.mas.skill_bank import SkillBank, is_selectable_skill


class EmperorPlanner:
    """Dispatch planner requests to the selected construction mode."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank
        self.topology_select = TopologySelectPlanner(skill_bank)
        self.operator_compose = OperatorComposePlanner(skill_bank)
        self.graph_generate = GraphGeneratePlanner(skill_bank)

    def plan(self, request: PlannerRequest) -> MASPlan:
        if request.planner_mode == "topology_select":
            return self.topology_select.plan(request)
        if request.planner_mode == "operator_compose":
            return self.operator_compose.plan(request)
        if request.planner_mode == "graph_generate":
            return self.graph_generate.plan(request)
        raise ValueError(f"unsupported planner_mode: {request.planner_mode}")


class TopologySelectPlanner:
    """Select from existing topology names using versioned skills."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        skills = self.skill_bank.retrieve(request)
        if not skills:
            skills = [skill for skill in self.skill_bank if is_selectable_skill(skill)]
        if not skills:
            return fallback_plan(request)

        scored = []
        for skill in skills:
            score, breakdown = score_skill(
                skill,
                objective=request.objective,
                peers=skills,
            )
            scored.append((score, breakdown, skill))
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_breakdown, best_skill = scored[0]
        topology_name = best_skill.topology_name or default_topology_for_objective(request)
        return MASPlan(
            planner_mode="topology_select",
            topology_name=topology_name,
            skill_id=best_skill.skill_id,
            operators=best_skill.operators,
            config_overrides=config_overrides_for_skill(best_skill),
            score=best_score,
            score_breakdown=best_breakdown,
            fallback_skill_id=fallback_skill_id(best_skill),
            alternatives=[
                {
                    "skill_id": skill.skill_id,
                    "topology_name": skill.topology_name,
                    "score": score,
                    "score_breakdown": breakdown,
                }
                for score, breakdown, skill in scored[1:4]
            ],
            rationale=(
                f"Selected {topology_name} from skill {best_skill.skill_id} "
                f"for {request.objective.name}."
            ),
        )


class OperatorComposePlanner:
    """Compose a protocol graph spec from organization operators."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        base_plan = TopologySelectPlanner(self.skill_bank).plan(
            request.model_copy(update={"planner_mode": "topology_select"})
        )
        operators = base_plan.operators or operators_for_objective(request)
        spec = compose_protocol_from_operators(
            name=f"mas_{request.objective.name}_{request.n_agents}",
            n_agents=request.n_agents,
            operators=operators,
            max_messages=request.budget.max_messages,
        )
        topology_name = str(spec.metadata.get("compiled_from_topology", base_plan.topology_name))
        return base_plan.model_copy(
            update={
                "planner_mode": "operator_compose",
                "topology_name": topology_name,
                "operators": operators,
                "protocol_spec": spec,
                "config_overrides": {
                    **base_plan.config_overrides,
                    "protocol_spec": spec,
                },
                "rationale": (
                    "Composed finite ProtocolGraphSpec from organization operators: "
                    + " -> ".join(operators)
                ),
            }
        )


class GraphGeneratePlanner:
    """Generate a valid finite graph spec under request constraints."""

    def __init__(self, skill_bank: SkillBank) -> None:
        self.skill_bank = skill_bank

    def plan(self, request: PlannerRequest) -> MASPlan:
        operators = operators_for_objective(request)
        if request.budget.level == "tight":
            operators = ["local_solve", "tree_reduce"]
        spec = compose_protocol_from_operators(
            name=f"generated_{request.objective.name}_{request.n_agents}",
            n_agents=request.n_agents,
            operators=operators,
            max_messages=request.budget.max_messages,
        )
        topology_name = str(spec.metadata.get("compiled_from_topology", "custom"))
        return MASPlan(
            planner_mode="graph_generate",
            topology_name=topology_name,
            operators=operators,
            protocol_spec=spec,
            config_overrides={"protocol_spec": spec},
            score=0.0,
            score_breakdown={},
            rationale=(
                "Generated a finite ProtocolGraphSpec from objective defaults "
                "and budget constraints."
            ),
        )


def fallback_plan(request: PlannerRequest) -> MASPlan:
    topology = default_topology_for_objective(request)
    operators = operators_for_objective(request)
    return MASPlan(
        planner_mode=request.planner_mode,
        topology_name=topology,
        operators=operators,
        rationale="Fallback plan because no matching skills were available.",
    )


def default_topology_for_objective(request: PlannerRequest) -> str:
    if request.objective.name == "accuracy_first" and request.budget.level != "tight":
        return "one_peer_exponential_dag_star"
    if request.objective.name == "budget_first" or request.budget.level == "tight":
        return "tree"
    return "mesh_star"


def operators_for_objective(request: PlannerRequest) -> list[str]:
    if request.objective.name == "accuracy_first" and request.budget.level != "tight":
        return ["local_solve", "peer_propagate", "star_sink"]
    if request.objective.name == "budget_first" or request.budget.level == "tight":
        return ["local_solve", "tree_reduce"]
    return ["local_solve", "mesh_broadcast", "star_sink"]


def config_overrides_for_skill(skill: SkillCard) -> dict[str, object]:
    overrides: dict[str, object] = {}
    selected_primary = skill.organization_policy.get("selected_primary")
    if selected_primary is not None:
        overrides["selected_primary"] = selected_primary
    average_min = skill.organization_policy.get("average_include_min_coverage")
    if average_min is not None:
        overrides["average_include_min_coverage"] = average_min
    return overrides


def fallback_skill_id(skill: SkillCard) -> str | None:
    fallback = skill.fallback
    for value in fallback.values():
        if value:
            return str(value)
    return None
