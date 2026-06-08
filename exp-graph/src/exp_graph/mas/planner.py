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
        # ``retrieve`` reads request.objective.min_seeds (default 1 = no gate)
        # and request.objective.uncertainty_weight flows into score_skill below.
        min_seeds = int(getattr(request.objective, "min_seeds", 1))
        skills = self.skill_bank.retrieve(request)
        if not skills:
            skills = [
                skill
                for skill in self.skill_bank
                if is_selectable_skill(skill, min_seeds=min_seeds)
            ]
        if not skills:
            return fallback_plan(request)

        # Plan 3 Part F knobs. All default to no-ops so the block below is
        # byte-identical to the prior relative-only selection: ``risk_weight``
        # 0.0 leaves ``selection_score`` == ``score``; ``enforce_avoid_veto``
        # False keeps every candidate; ``max_acceptable_loss`` None skips the
        # floor.
        risk_weight = float(getattr(request.objective, "risk_weight", 0.0))
        enforce_avoid_veto = bool(
            getattr(request.objective, "enforce_avoid_veto", False)
        )
        max_acceptable_loss = getattr(request.objective, "max_acceptable_loss", None)

        scored = []
        for skill in skills:
            score, breakdown = score_skill(
                skill,
                objective=request.objective,
                peers=skills,
            )
            selection_score = score - risk_weight * _skill_risk_penalty(skill)
            scored.append((selection_score, breakdown, skill))
        scored.sort(key=lambda item: item[0], reverse=True)

        veto_note = ""
        if enforce_avoid_veto:
            vetoed = _vetoed_topology_names(self.skill_bank, request)
            if vetoed:
                kept = [
                    item
                    for item in scored
                    if (item[2].topology_name or "") not in vetoed
                ]
                if not kept:
                    return _veto_fallback_plan(request, vetoed)
                if len(kept) != len(scored):
                    veto_note = (
                        " Excluded vetoed topologies "
                        f"{sorted(vetoed)} via counterexample skills."
                    )
                scored = kept

        best_score, best_breakdown, best_skill = scored[0]

        if max_acceptable_loss is not None:
            best_loss = _breakdown_loss(best_breakdown)
            if best_loss > float(max_acceptable_loss):
                return _floor_fallback_plan(
                    request,
                    best_skill=best_skill,
                    best_loss=best_loss,
                    max_acceptable_loss=float(max_acceptable_loss),
                )

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
                + veto_note
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


def _skill_risk_penalty(skill: SkillCard) -> float:
    """Read ``confidence.risk_penalty`` (lower is safer); default 0.0.

    Recorded by ``consolidation._recompute_confidence`` as
    ``min(0.4, 0.05 * len(distinct risk tags))``. Absent/non-numeric values
    contribute 0.0 so the risk term is a no-op for skills without it.
    """
    value = skill.confidence.get("risk_penalty")
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _breakdown_loss(breakdown: dict[str, float]) -> float:
    """Lower-is-better loss for the absolute floor.

    ``score_skill`` stores this as ``breakdown['rmse']``, which is the converted
    ``mean_primary_loss`` when present (generic benchmarks) and otherwise
    ``mean_rmse`` (count-frequency). See ``scoring.primary_loss_metric``.
    """
    value = breakdown.get("rmse")
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _vetoed_topology_names(skill_bank: SkillBank, request: PlannerRequest) -> set[str]:
    """Topology names flagged by matching avoid/counterexample skills."""
    return {
        skill.topology_name
        for skill in skill_bank.retrieve_avoid(request)
        if skill.topology_name
    }


def _veto_fallback_plan(request: PlannerRequest, vetoed: set[str]) -> MASPlan:
    """Safe-default plan used when every candidate topology is vetoed."""
    topology = default_topology_for_objective(request)
    operators = operators_for_objective(request)
    return MASPlan(
        planner_mode="topology_select",
        topology_name=topology,
        operators=operators,
        rationale=(
            "Counterexample veto excluded every candidate topology "
            f"{sorted(vetoed)}; fell back to safe default {topology} "
            f"for {request.objective.name}."
        ),
    )


def _floor_fallback_plan(
    request: PlannerRequest,
    *,
    best_skill: SkillCard,
    best_loss: float,
    max_acceptable_loss: float,
) -> MASPlan:
    """Safe-default plan used when the best candidate violates the loss floor."""
    topology = default_topology_for_objective(request)
    operators = operators_for_objective(request)
    return MASPlan(
        planner_mode="topology_select",
        topology_name=topology,
        operators=operators,
        rationale=(
            f"Best candidate {best_skill.skill_id} loss {best_loss:g} exceeds the "
            f"acceptable loss floor {max_acceptable_loss:g}; fell back to safe "
            f"default {topology} for {request.objective.name}."
        ),
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
