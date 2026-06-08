"""Scoring helpers for emperor topology-skill selection."""

from __future__ import annotations

import math
from collections.abc import Iterable

from exp_graph.mas.schemas import ObjectiveSpec, SkillCard

# Module-level default for the lower-confidence-bound (LCB) penalty weight
# (kappa). ``0.0`` keeps ``score_skill`` byte-identical to the plain-mean
# behavior; callers opt in by passing a positive ``uncertainty_weight`` or by
# setting ``ObjectiveSpec.uncertainty_weight``.
DEFAULT_UNCERTAINTY_WEIGHT = 0.0


def min_max_normalize(value: float, values: Iterable[float], *, invert: bool) -> float:
    """Return a [0, 1] normalized score, optionally treating lower as better."""
    series = [float(item) for item in values]
    if not series:
        return 0.0
    low = min(series)
    high = max(series)
    if high == low:
        return 1.0
    normalized = (float(value) - low) / (high - low)
    return 1.0 - normalized if invert else normalized


def skill_metric(skill: SkillCard, key: str, default: float = 0.0) -> float:
    """Read a numeric metric from the newest evidence entry that contains it."""
    if key in skill.expected_tradeoff and skill.expected_tradeoff[key] is not None:
        return float(skill.expected_tradeoff[key])
    for evidence in reversed(skill.evidence):
        if key in evidence and evidence[key] is not None:
            return float(evidence[key])
    return default


def primary_loss_metric(skill: SkillCard, default: float = 1e9) -> float:
    """Read the lower-is-better accuracy signal for a skill.

    Generic benchmarks store a converted ``mean_primary_loss`` (e.g. Silo-Bench
    success-rate -> ``1 - success``); count-frequency skills only carry
    ``mean_rmse``. Both are lower-is-better, so downstream normalization is
    identical regardless of which one supplied the value.
    """
    if _has_metric(skill, "mean_primary_loss"):
        return skill_metric(skill, "mean_primary_loss", default=default)
    return skill_metric(skill, "mean_rmse", default=default)


def _has_metric(skill: SkillCard, key: str) -> bool:
    if key in skill.expected_tradeoff and skill.expected_tradeoff[key] is not None:
        return True
    return any(
        key in evidence and evidence[key] is not None for evidence in skill.evidence
    )


def primary_loss_std(skill: SkillCard, default: float = 0.0) -> float:
    """Read the spread of the lower-is-better accuracy signal for a skill.

    Mirrors :func:`primary_loss_metric`: prefer ``std_primary_loss`` (the spread
    of the converted generic loss) when present, otherwise fall back to
    ``std_rmse`` (the only spread the CF/consolidation pipeline records today).
    Both describe the same lower-is-better loss, so the LCB penalty is computed
    on a consistent scale regardless of which one supplied the value.
    """
    if _has_metric(skill, "std_primary_loss"):
        return skill_metric(skill, "std_primary_loss", default=default)
    return skill_metric(skill, "std_rmse", default=default)


def evidence_sample_count(skill: SkillCard, default: int = 1) -> int:
    """Read the number of independent observations behind a skill's metrics.

    Prefers ``confidence.seed_count`` (distinct seeds), then
    ``confidence.active_evidence_count`` / ``expected_tradeoff
    .active_evidence_count`` (aggregate rows), then the raw evidence list.
    Used as ``n`` in the LCB standard-error term. Never returns below ``1`` so
    ``sqrt(n)`` is well defined.
    """
    for source, key in (
        (skill.confidence, "seed_count"),
        (skill.confidence, "active_evidence_count"),
        (skill.expected_tradeoff, "active_evidence_count"),
    ):
        value = source.get(key)
        if value is not None:
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count > 0:
                return count
    if skill.evidence:
        return len(skill.evidence)
    return max(1, default)


def lcb_primary_loss(
    skill: SkillCard,
    *,
    uncertainty_weight: float,
    default: float = 1e9,
) -> float:
    """Return a pessimistic (upper-confidence-bound) accuracy *loss*.

    ``loss_lcb = mean_loss + kappa * std / sqrt(max(1, n))``. With
    ``uncertainty_weight`` (kappa) ``== 0`` this is exactly ``mean_loss`` so
    downstream normalization is unchanged. A high ``std`` and/or tiny ``n``
    inflate the loss, demoting "lucky" high-variance skills.
    """
    mean_loss = primary_loss_metric(skill, default=default)
    if uncertainty_weight <= 0.0:
        return mean_loss
    std = primary_loss_std(skill, default=0.0)
    n = evidence_sample_count(skill, default=1)
    return mean_loss + uncertainty_weight * std / math.sqrt(max(1, n))


def score_skill(
    skill: SkillCard,
    *,
    objective: ObjectiveSpec,
    peers: list[SkillCard],
    uncertainty_weight: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Score one skill against peer skills for the requested objective.

    ``uncertainty_weight`` (kappa) controls a lower-confidence-bound (LCB)
    penalty on the accuracy term: the accuracy signal becomes a pessimistic
    loss ``mean_loss + kappa * std / sqrt(max(1, n))`` before normalization, so
    a high-variance / tiny-sample "lucky" skill is demoted relative to a stable
    one. When ``None`` (the default) the weight is read from
    ``ObjectiveSpec.uncertainty_weight`` if present, else the module default
    ``0.0``. With kappa == 0 the LCB loss equals ``mean_loss`` and this function
    is byte-identical to the plain-mean behavior.
    """
    if uncertainty_weight is None:
        uncertainty_weight = float(
            getattr(objective, "uncertainty_weight", DEFAULT_UNCERTAINTY_WEIGHT)
        )

    rmse = primary_loss_metric(skill, default=1e9)
    token_cost = skill_metric(skill, "mean_token_cost", default=1e9)
    messages = skill_metric(skill, "mean_messages", default=1e9)
    std_rmse = skill_metric(skill, "std_rmse", default=0.0)
    loss_lcb = lcb_primary_loss(
        skill, uncertainty_weight=uncertainty_weight, default=1e9
    )
    loss_lcb_values = [
        lcb_primary_loss(item, uncertainty_weight=uncertainty_weight, default=1e9)
        for item in peers
    ]
    token_values = [skill_metric(item, "mean_token_cost", default=1e9) for item in peers]
    message_values = [skill_metric(item, "mean_messages", default=1e9) for item in peers]
    std_values = [skill_metric(item, "std_rmse", default=0.0) for item in peers]

    accuracy_score = min_max_normalize(loss_lcb, loss_lcb_values, invert=True)
    token_score = min_max_normalize(token_cost, token_values, invert=True)
    message_score = min_max_normalize(messages, message_values, invert=True)
    cost_score = (token_score + message_score) / 2.0
    stability_score = min_max_normalize(std_rmse, std_values, invert=True)

    score = (
        objective.accuracy_weight * accuracy_score
        + objective.cost_weight * cost_score
        + objective.stability_weight * stability_score
    )
    return score, {
        "accuracy": accuracy_score,
        "cost": cost_score,
        "stability": stability_score,
        "rmse": rmse,
        "token_cost": token_cost,
        "messages": messages,
        "std_rmse": std_rmse,
        # Additive uncertainty diagnostics; existing keys above are unchanged.
        "uncertainty_weight": uncertainty_weight,
        "uncertainty_std": primary_loss_std(skill, default=0.0),
        "uncertainty_n": float(evidence_sample_count(skill, default=1)),
        "loss_lcb": loss_lcb,
    }
