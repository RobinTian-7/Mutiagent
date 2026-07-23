"""Scoring helpers for emperor topology-skill selection."""

from __future__ import annotations

from collections.abc import Iterable

from exp_graph.mas.schemas import ObjectiveSpec, SkillCard


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


def score_skill(
    skill: SkillCard,
    *,
    objective: ObjectiveSpec,
    peers: list[SkillCard],
) -> tuple[float, dict[str, float]]:
    """Score one skill against peer skills for the requested objective."""
    rmse = skill_metric(skill, "mean_rmse", default=1e9)
    token_cost = skill_metric(skill, "mean_token_cost", default=1e9)
    messages = skill_metric(skill, "mean_messages", default=1e9)
    std_rmse = skill_metric(skill, "std_rmse", default=0.0)
    rmse_values = [skill_metric(item, "mean_rmse", default=1e9) for item in peers]
    token_values = [skill_metric(item, "mean_token_cost", default=1e9) for item in peers]
    message_values = [skill_metric(item, "mean_messages", default=1e9) for item in peers]
    std_values = [skill_metric(item, "std_rmse", default=0.0) for item in peers]

    accuracy_score = min_max_normalize(rmse, rmse_values, invert=True)
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
    }
