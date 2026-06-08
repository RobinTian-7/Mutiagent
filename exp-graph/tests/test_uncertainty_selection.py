"""Plan 3 Part E: uncertainty-aware skill selection + min-sample gating.

These cover the opt-in lower-confidence-bound (LCB) accuracy term in
``score_skill`` and the ``min_seeds`` gate in ``SkillBank.retrieve``. The
invariant under test is that the *default* parameters (kappa=0, min_seeds=1)
reproduce today's behavior byte-for-byte, while turning the knobs up makes a
high-variance / tiny-sample "lucky" skill lose to a stable one.
"""

from __future__ import annotations

from exp_graph.mas.schemas import ObjectiveSpec, PlannerRequest, SkillCard
from exp_graph.mas.scoring import min_max_normalize, score_skill
from exp_graph.mas.skill_bank import SkillBank


def _skill(
    skill_id: str,
    *,
    mean_loss: float,
    std: float = 0.0,
    n: int = 1,
    topology: str | None = None,
    objective: str = "balanced",
) -> SkillCard:
    """Build a valid SkillCard carrying loss/std/seed-count the way the
    real consolidation pipeline records them.

    ``std_rmse`` lives in ``expected_tradeoff`` (see
    ``consolidation._recompute_tradeoff``) and ``seed_count`` lives in
    ``confidence`` (see ``consolidation._recompute_confidence``).
    """
    return SkillCard(
        skill_id=skill_id,
        objective=objective,  # type: ignore[arg-type]
        organization_policy={"topology_name": topology or f"topo_{skill_id}"},
        expected_tradeoff={
            "mean_rmse": mean_loss,
            "std_rmse": std,
            "mean_token_cost": 100.0,
            "mean_messages": 10.0,
            "active_evidence_count": n,
        },
        confidence={"seed_count": n},
    )


def test_lcb_default_is_noop() -> None:
    """With the default kappa=0, the accuracy term equals the plain
    min_max_normalize of the mean loss, and the overall ranking matches
    today's behavior."""
    skill_a = _skill("a", mean_loss=0.10, std=0.30, n=2)
    skill_b = _skill("b", mean_loss=0.15, std=0.02, n=8)
    peers = [skill_a, skill_b]

    spec = ObjectiveSpec.from_name("balanced")

    _score_a, breakdown_a = score_skill(skill_a, objective=spec, peers=peers)
    _score_b, breakdown_b = score_skill(skill_b, objective=spec, peers=peers)

    # Accuracy term must be the plain (kappa=0) min_max_normalize of mean loss.
    expected_acc_a = min_max_normalize(0.10, [0.10, 0.15], invert=True)
    expected_acc_b = min_max_normalize(0.15, [0.10, 0.15], invert=True)
    assert breakdown_a["accuracy"] == expected_acc_a
    assert breakdown_b["accuracy"] == expected_acc_b

    # A has the lower mean loss, so with kappa=0 A must win on accuracy.
    assert breakdown_a["accuracy"] > breakdown_b["accuracy"]
    # Existing breakdown keys are preserved.
    for key in ("accuracy", "cost", "stability", "rmse", "token_cost", "messages", "std_rmse"):
        assert key in breakdown_a


def test_lcb_penalizes_high_variance() -> None:
    """skill A is a lucky-but-noisy winner (low mean, high std, tiny n);
    skill B is stable (slightly higher mean, low std, many seeds). With
    kappa>0 the pessimistic loss flips the accuracy ranking to B; with
    kappa=0 the mean wins and A stays ahead."""
    spec = ObjectiveSpec.from_name("accuracy_first")

    skill_a = _skill("a", mean_loss=0.10, std=0.30, n=2)
    skill_b = _skill("b", mean_loss=0.15, std=0.02, n=8)
    peers = [skill_a, skill_b]

    # kappa = 0 -> mean wins -> A ahead on accuracy.
    _, base_a = score_skill(skill_a, objective=spec, peers=peers, uncertainty_weight=0.0)
    _, base_b = score_skill(skill_b, objective=spec, peers=peers, uncertainty_weight=0.0)
    assert base_a["accuracy"] > base_b["accuracy"]

    # kappa = 1.0 -> pessimistic loss: A = 0.10 + 1.0*0.30/sqrt(2) ~= 0.312;
    # B = 0.15 + 1.0*0.02/sqrt(8) ~= 0.157. B's LCB loss is lower -> B wins.
    score_a, lcb_a = score_skill(
        skill_a, objective=spec, peers=peers, uncertainty_weight=1.0
    )
    score_b, lcb_b = score_skill(
        skill_b, objective=spec, peers=peers, uncertainty_weight=1.0
    )
    assert lcb_b["accuracy"] > lcb_a["accuracy"]
    # With accuracy_first weighting, the flipped accuracy term flips the
    # overall score too (cost/stability are otherwise comparable here).
    assert score_b > score_a

    # Breakdown additively exposes the std/n that drove the penalty.
    assert lcb_a["uncertainty_std"] == 0.30
    assert lcb_a["uncertainty_n"] == 2
    assert lcb_b["uncertainty_std"] == 0.02
    assert lcb_b["uncertainty_n"] == 8


def test_min_seeds_excludes_low_n() -> None:
    """retrieve(min_seeds=2) drops a 1-seed skill but keeps a 5-seed one;
    the default retrieve() keeps both."""
    low = _skill("cf_low_seed", mean_loss=0.10, std=0.01, n=1, topology="topo_low")
    high = _skill("cf_high_seed", mean_loss=0.20, std=0.01, n=5, topology="topo_high")
    bank = SkillBank([low, high])
    request = PlannerRequest.from_names(n_agents=8, objective="balanced")

    default_ids = {skill.skill_id for skill in bank.retrieve(request)}
    assert default_ids == {"cf_low_seed", "cf_high_seed"}

    gated_ids = {skill.skill_id for skill in bank.retrieve(request, min_seeds=2)}
    assert gated_ids == {"cf_high_seed"}
