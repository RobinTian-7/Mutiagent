"""Paired dense ratchet for evolution candidate deployment."""

from __future__ import annotations

import math
import random
from statistics import fmean
from typing import Any


_QUALITY_FIELDS = ("V", "K", "U", "P", "S", "stage_score")


def dense_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(row.get("case_id") or "unknown"),
        "seed": int(row.get("seed", 0) or 0),
        "algorithm_failure": (
            str(row.get("failure_class") or "") == "algorithm_failure"
            or float(row.get("program_validity", 1.0) or 0.0) <= 0.0
        ),
        "V": _number(row.get("program_validity", 1.0)),
        "K": _number(row.get("structural_coverage", 0.0)),
        "U": _number(row.get("submission_rate", 0.0)),
        "P": _number(
            row.get("evolution_partial", row.get("PartialCorrectness", 0.0))
        ),
        "S": _number(row.get("evolution_success", row.get("ExactMatchRate", 0.0))),
        "stage_score": _number(row.get("evolution_stage_score", 0.0)),
        "C": _number(row.get("paper_C", row.get("MeanTokenCost", 0.0))),
        "D": _number(row.get("paper_D", row.get("MeanTotalMessages", 0.0))),
    }


def _number(value: Any) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _mean(samples: list[dict[str, Any]], key: str) -> float:
    return fmean(float(sample[key]) for sample in samples) if samples else 0.0


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def paired_bootstrap_ci(
    deltas: list[float],
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    if not deltas:
        return (0.0, 0.0)
    if len(deltas) == 1 or samples <= 1:
        return (deltas[0], deltas[0])
    rng = random.Random(seed)
    estimates = [
        fmean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(samples)
    ]
    return (_percentile(estimates, 0.025), _percentile(estimates, 0.975))


def evaluate_strict_dense_gate(
    incumbent_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    min_dense_delta: float = 0.01,
    partial_tolerance: float = 0.0,
    bootstrap_samples: int = 2000,
    bootstrap_seed: int = 20260713,
) -> dict[str, Any]:
    """Evaluate strict_dense_v2 on exactly paired case/seed samples."""
    incumbents = {
        (sample["case_id"], sample["seed"]): sample
        for sample in map(dense_sample, incumbent_rows)
    }
    candidates = {
        (sample["case_id"], sample["seed"]): sample
        for sample in map(dense_sample, candidate_rows)
    }
    if set(incumbents) != set(candidates):
        raise ValueError("strict_dense_v2 requires identical incumbent/candidate keys")
    keys = sorted(incumbents)
    if not keys:
        return {
            "accepted": False,
            "accepted_no_change": False,
            "reason": "no_paired_validation_samples",
            "policy": "strict_dense_v2",
            "n_samples": 0,
            "paired_samples": [],
        }
    before = [incumbents[key] for key in keys]
    after = [candidates[key] for key in keys]
    means_before = {field: _mean(before, field) for field in (*_QUALITY_FIELDS, "C", "D")}
    means_after = {field: _mean(after, field) for field in (*_QUALITY_FIELDS, "C", "D")}
    algorithm_before = fmean(float(item["algorithm_failure"]) for item in before)
    algorithm_after = fmean(float(item["algorithm_failure"]) for item in after)
    min_k_before = min(float(item["K"]) for item in before)
    min_k_after = min(float(item["K"]) for item in after)
    stage_deltas = [
        float(candidates[key]["stage_score"] - incumbents[key]["stage_score"])
        for key in keys
    ]
    ci_low, ci_high = paired_bootstrap_ci(
        stage_deltas,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    tolerance = 1e-12
    checks = {
        "algorithm_failure_rate_non_increasing": algorithm_after <= algorithm_before + tolerance,
        "mean_V_non_regression": means_after["V"] + tolerance >= means_before["V"],
        "min_K_non_regression": min_k_after + tolerance >= min_k_before,
        "mean_U_non_regression": means_after["U"] + tolerance >= means_before["U"],
        "mean_P_within_tolerance": (
            means_after["P"] + partial_tolerance + tolerance >= means_before["P"]
        ),
        # P has its own explicit tolerance.  The paired dense-score interval is
        # a separate ratchet and may not hide regression behind that tolerance.
        "bootstrap_no_regression": ci_low >= -tolerance,
    }
    mean_stage_delta = means_after["stage_score"] - means_before["stage_score"]
    quality_improved = bool(
        means_after["S"] > means_before["S"] + tolerance
        or mean_stage_delta >= min_dense_delta - tolerance
    )
    quality_equal = all(
        abs(means_after[field] - means_before[field]) <= tolerance
        for field in _QUALITY_FIELDS
    ) and abs(algorithm_after - algorithm_before) <= tolerance
    c_improved = means_after["C"] < means_before["C"] - tolerance
    d_improved = means_after["D"] < means_before["D"] - tolerance
    cost_not_worse = (
        means_after["C"] <= means_before["C"] + tolerance
        and means_after["D"] <= means_before["D"] + tolerance
    )
    cost_tiebreak = quality_equal and cost_not_worse and (c_improved or d_improved)
    hard_checks_pass = all(checks.values())
    accepted = bool(hard_checks_pass and (quality_improved or cost_tiebreak))
    if not hard_checks_pass:
        reason = "quality_regression"
    elif quality_improved:
        reason = "quality_improvement"
    elif cost_tiebreak:
        reason = "equal_quality_lower_cost"
    else:
        reason = "no_change"
    return {
        "accepted": accepted,
        "accepted_no_change": False,
        "reason": reason,
        "policy": "strict_dense_v2",
        "n_samples": len(keys),
        "min_dense_delta": min_dense_delta,
        "partial_tolerance": partial_tolerance,
        "algorithm_failure_rate_before": algorithm_before,
        "algorithm_failure_rate_after": algorithm_after,
        "mean_before": means_before,
        "mean_after": means_after,
        "min_K_before": min_k_before,
        "min_K_after": min_k_after,
        "mean_stage_delta": mean_stage_delta,
        "paired_stage_bootstrap_95_ci": [ci_low, ci_high],
        "checks": checks,
        "quality_improved": quality_improved,
        "quality_equal": quality_equal,
        "cost_tiebreak": cost_tiebreak,
        "paired_samples": [
            {
                "case_id": key[0],
                "seed": key[1],
                "incumbent": incumbents[key],
                "candidate": candidates[key],
                "delta_stage_score": (
                    candidates[key]["stage_score"]
                    - incumbents[key]["stage_score"]
                ),
            }
            for key in keys
        ],
    }
