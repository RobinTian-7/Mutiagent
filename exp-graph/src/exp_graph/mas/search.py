"""AFlow-lite candidate search over supported MAS policies."""

from __future__ import annotations

from dataclasses import dataclass, field

from exp_graph.mas.planner import default_topology_for_objective
from exp_graph.mas.schemas import MASPlan, PlannerRequest
from exp_graph.mas.scoring import score_skill
from exp_graph.mas.skill_bank import SkillBank, is_selectable_skill


@dataclass
class SearchResult:
    """One scored AFlow-lite candidate."""

    topology_name: str
    score: float
    score_breakdown: dict[str, float] = field(default_factory=dict)
    mutation: str = "seed"


SUPPORTED_SEARCH_TOPOLOGIES = [
    "tree",
    "mesh_star",
    "one_peer_exponential_dag_star",
    "dag_mesh",
    "random",
    "static_exponential_star",
]


def search_candidates(
    *,
    request: PlannerRequest,
    skill_bank: SkillBank,
    top_k: int = 5,
) -> list[SearchResult]:
    """Score supported topology candidates against skill-bank evidence."""
    skills = [skill for skill in skill_bank if is_selectable_skill(skill)]
    results: list[SearchResult] = []
    for topology in SUPPORTED_SEARCH_TOPOLOGIES:
        matching = [skill for skill in skills if skill.topology_name == topology]
        if matching:
            score, breakdown = score_skill(
                matching[0],
                objective=request.objective,
                peers=skills,
            )
        else:
            score = 0.01 if topology == default_topology_for_objective(request) else 0.0
            breakdown = {}
        results.append(
            SearchResult(
                topology_name=topology,
                score=score,
                score_breakdown=breakdown,
                mutation="existing_supported_topology",
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]


def plan_from_search_result(
    *,
    request: PlannerRequest,
    result: SearchResult,
) -> MASPlan:
    return MASPlan(
        planner_mode="topology_select",
        topology_name=result.topology_name,
        score=result.score,
        score_breakdown=result.score_breakdown,
        rationale=f"AFlow-lite selected {result.topology_name} from scored candidates.",
    )
