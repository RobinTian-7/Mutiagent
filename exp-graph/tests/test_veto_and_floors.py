"""Plan 3 Part F: counterexample hard veto, absolute performance floor, and
risk-penalty-aware scoring in ``TopologySelectPlanner.plan``.

The invariant under test is that the *default* knobs
(``enforce_avoid_veto=False``, ``max_acceptable_loss=None``, ``risk_weight=0.0``)
reproduce today's relative-only selection byte-for-byte, while turning each knob
on stops a known-bad topology from being chosen just because it is the best of a
bad lot:

* the hard veto excludes any candidate whose ``topology_name`` matches a
  retrieved avoid/counterexample skill before the max is taken;
* the absolute floor refuses to trust the best candidate when its loss is worse
  than ``max_acceptable_loss`` and falls back to the safe default topology;
* the risk weight subtracts ``risk_weight * confidence.risk_penalty`` from the
  selection score so a riskier skill loses to a safer near-tie.
"""

from __future__ import annotations

from exp_graph.mas import EmperorPlanner, PlannerRequest, SkillBank
from exp_graph.mas.planner import default_topology_for_objective
from exp_graph.mas.schemas import ObjectiveSpec, SkillCard


def _skill(
    skill_id: str,
    *,
    topology: str,
    mean_loss: float = 0.10,
    std: float = 0.0,
    risk_penalty: float | None = None,
    tags: list[str] | None = None,
    objective: str = "balanced",
) -> SkillCard:
    """Build a SkillCard the way the consolidation pipeline records it.

    ``mean_rmse``/``std_rmse`` live in ``expected_tradeoff`` (see
    ``consolidation._recompute_tradeoff``); ``risk_penalty``/``seed_count`` live
    in ``confidence`` (see ``consolidation._recompute_confidence``). An avoid
    skill is signalled by the ``counterexample`` tag or a ``cf_avoid_`` id (see
    ``skill_bank.is_avoid_skill``).
    """
    confidence: dict[str, object] = {"seed_count": 1, "active_evidence_count": 1}
    if risk_penalty is not None:
        confidence["risk_penalty"] = risk_penalty
    return SkillCard(
        skill_id=skill_id,
        objective=objective,  # type: ignore[arg-type]
        organization_policy={"topology_name": topology},
        expected_tradeoff={
            "mean_rmse": mean_loss,
            "std_rmse": std,
            "mean_token_cost": 100.0,
            "mean_messages": 10.0,
            "active_evidence_count": 1,
        },
        confidence=confidence,
        tags=tags or [],
    )


def _request(objective: str = "balanced", **kwargs) -> PlannerRequest:
    return PlannerRequest.from_names(
        n_agents=8,
        objective=objective,  # type: ignore[arg-type]
        planner_mode="topology_select",
        **kwargs,
    )


def test_defaults_unchanged() -> None:
    """A bank whose top (lowest-loss) selectable skill shares a topology with an
    avoid skill: with default knobs the veto is OFF, so plan() still selects that
    top skill exactly as today."""
    good = _skill("cf_good_random", topology="random", mean_loss=0.05)
    other = _skill("cf_other_mesh", topology="mesh_star", mean_loss=0.30)
    avoid = _skill(
        "cf_avoid_random",
        topology="random",
        mean_loss=0.42,
        tags=["counterexample"],
    )
    bank = SkillBank([good, other, avoid])

    plan = EmperorPlanner(bank).plan(_request())

    assert plan.skill_id == "cf_good_random"
    assert plan.topology_name == "random"
    assert "veto" not in plan.rationale.lower()


def test_hard_veto_excludes_topology() -> None:
    """Same bank, but ``enforce_avoid_veto=True``: the vetoed ``random``
    topology is excluded before the max, so the non-vetoed ``mesh_star`` skill is
    selected and the rationale names the veto."""
    good = _skill("cf_good_random", topology="random", mean_loss=0.05)
    other = _skill("cf_other_mesh", topology="mesh_star", mean_loss=0.30)
    avoid = _skill(
        "cf_avoid_random",
        topology="random",
        mean_loss=0.42,
        tags=["counterexample"],
    )
    bank = SkillBank([good, other, avoid])

    request = _request()
    request.objective.enforce_avoid_veto = True
    plan = EmperorPlanner(bank).plan(request)

    assert plan.topology_name == "mesh_star"
    assert plan.skill_id == "cf_other_mesh"
    assert "veto" in plan.rationale.lower()
    assert "random" in plan.rationale.lower()


def test_hard_veto_all_vetoed_falls_back_to_safe_default() -> None:
    """When every candidate's topology is vetoed, plan() falls back to the safe
    default topology instead of selecting a known-bad one."""
    only = _skill("cf_only_random", topology="random", mean_loss=0.05)
    avoid = _skill(
        "cf_avoid_random",
        topology="random",
        mean_loss=0.42,
        tags=["counterexample"],
    )
    bank = SkillBank([only, avoid])

    request = _request()
    request.objective.enforce_avoid_veto = True
    plan = EmperorPlanner(bank).plan(request)

    assert plan.topology_name == default_topology_for_objective(request)
    assert plan.topology_name != "random"
    assert plan.skill_id is None
    assert "veto" in plan.rationale.lower()


def test_absolute_floor_falls_back() -> None:
    """The only candidate has a loss worse than ``max_acceptable_loss``; plan()
    refuses to trust it and falls back to the safe default topology."""
    bad = _skill("cf_bad_mesh", topology="mesh_star", mean_loss=0.50)
    bank = SkillBank([bad])

    request = _request()
    request.objective.max_acceptable_loss = 0.20
    plan = EmperorPlanner(bank).plan(request)

    assert plan.topology_name == default_topology_for_objective(request)
    assert plan.skill_id is None
    assert "floor" in plan.rationale.lower()


def test_absolute_floor_keeps_good_skill() -> None:
    """A candidate at or below the floor is still trusted and selected."""
    good = _skill("cf_good_mesh", topology="mesh_star", mean_loss=0.10)
    bank = SkillBank([good])

    request = _request()
    request.objective.max_acceptable_loss = 0.20
    plan = EmperorPlanner(bank).plan(request)

    assert plan.skill_id == "cf_good_mesh"
    assert plan.topology_name == "mesh_star"


def test_risk_weight_demotes_risky_skill() -> None:
    """Two near-tied-accuracy candidates with different
    ``confidence.risk_penalty``: with ``risk_weight=0`` the marginally more
    accurate (riskier) one wins (current behavior); with ``risk_weight>0`` the
    risk penalty flips the selection to the safer one.

    A far-worse ``anchor`` peer widens the min-max normalization range so the
    0.10 vs 0.12 loss gap maps to a genuinely small accuracy difference (as it
    would in a real multi-topology bank) rather than being stretched to the full
    [0, 1] scale by a 2-skill normalization.
    """
    risky = _skill(
        "cf_risky_random",
        topology="random",
        mean_loss=0.10,
        risk_penalty=0.40,
    )
    safe = _skill(
        "cf_safe_mesh",
        topology="mesh_star",
        mean_loss=0.12,
        risk_penalty=0.0,
    )
    anchor = _skill(
        "cf_anchor_tree",
        topology="tree",
        mean_loss=1.00,
        risk_penalty=0.0,
    )
    bank = SkillBank([risky, safe, anchor])

    # risk_weight = 0 (default) -> lowest loss wins -> risky skill selected.
    base_plan = EmperorPlanner(bank).plan(_request())
    assert base_plan.skill_id == "cf_risky_random"

    # risk_weight > 0 -> the 0.40 risk penalty outweighs the tiny accuracy edge
    # -> the safe skill is selected instead.
    request = _request()
    request.objective.risk_weight = 1.0
    risk_plan = EmperorPlanner(bank).plan(request)
    assert risk_plan.skill_id == "cf_safe_mesh"
    assert risk_plan.topology_name == "mesh_star"
