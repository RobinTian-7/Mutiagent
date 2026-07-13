"""SILO-BENCH Section 3.3 metrics over final per-agent submissions.

This module intentionally mirrors the paper formulas instead of routing through
masbench's older structure-based partial scorer.  In particular, Level II uses
position-wise element accuracy and Level III uses the longest correctly ordered
subsequence.  Keeping the implementation first-party lets GraphGen and the three
paper transports share one scorer without importing the vendored ``src`` package.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from typing import Any

from masbench.core.task_bridge import canonical_answer


def _normalize(value: Any) -> Any:
    """Normalize common string encodings used in benchmark submissions."""
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except (TypeError, ValueError):
            pass
        try:
            return float(text)
        except (TypeError, ValueError):
            pass
        if text.startswith(("[", "{")):
            try:
                return _normalize(json.loads(text))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return text
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _lis_length(values: list[int]) -> int:
    tails: list[int] = []
    for value in values:
        index = bisect_left(tails, value)
        if index == len(tails):
            tails.append(value)
        else:
            tails[index] = value
    return len(tails)


def paper_agent_quality(
    answer: Any,
    expected: Any,
    *,
    level: str,
    tolerance: float = 0.01,
) -> float:
    """Return the paper's per-agent quality score ``q_i`` in ``[0, 1]``."""
    actual = _normalize(answer)
    target = _normalize(expected)

    if level == "I":
        if (
            isinstance(target, (int, float))
            and not isinstance(target, bool)
            and isinstance(actual, (int, float))
            and not isinstance(actual, bool)
        ):
            if target == 0:
                return 1.0 if actual == 0 else 0.0
            return 1.0 if abs(actual - target) <= tolerance * abs(target) else 0.0
        return 1.0 if actual == target else 0.0

    if level == "II":
        if isinstance(target, list) and isinstance(actual, list):
            if not target:
                return 1.0 if not actual else 0.0
            matches = sum(1 for exp, got in zip(target, actual) if exp == got)
            return matches / len(target)
        return 1.0 if actual == target else 0.0

    if level == "III":
        if isinstance(target, list) and isinstance(actual, list):
            if not target:
                return 1.0 if not actual else 0.0
            try:
                expected_positions = {value: idx for idx, value in enumerate(target)}
                positions = [
                    expected_positions[value]
                    for value in actual
                    if value in expected_positions
                ]
            except TypeError:
                return 1.0 if actual == target else 0.0
            return _lis_length(positions) / len(target)
        return 1.0 if actual == target else 0.0

    # Synthetic fixtures outside the paper's I/II/III namespace remain useful
    # for plumbing tests; exact-only quality is the least surprising fallback.
    return 1.0 if actual == target else 0.0


def evaluate_paper_submissions(
    *,
    case_id: str,
    answers: list[Any],
    expected_outputs: list[Any],
    submitted_rounds: list[int | None] | None = None,
) -> dict[str, Any]:
    """Compute paper ``S``/``P`` and an auditable record for every agent."""
    n_agents = len(expected_outputs)
    level = str(case_id).split("-", 1)[0]
    rounds = list(submitted_rounds or [])
    records: list[dict[str, Any]] = []
    correct_count = 0
    quality_sum = 0.0

    for agent_id in range(n_agents):
        answer = answers[agent_id] if agent_id < len(answers) else None
        expected = expected_outputs[agent_id]
        correct = (
            answer is not None
            and canonical_answer(answer) == canonical_answer(expected)
        )
        quality = paper_agent_quality(answer, expected, level=level)
        correct_count += int(correct)
        quality_sum += quality
        records.append(
            {
                "agent_id": agent_id,
                "answer": answer,
                "correct": bool(correct),
                "partial": float(quality),
                "submitted_round": rounds[agent_id] if agent_id < len(rounds) else None,
            }
        )

    success_rate = correct_count / n_agents if n_agents else 0.0
    partial = quality_sum / n_agents if n_agents else 0.0
    return {
        "paper_S": success_rate,
        "paper_P": partial,
        "per_agent_submissions": records,
        "per_agent_answers": [record["answer"] for record in records],
        "per_agent_correct": [record["correct"] for record in records],
        "per_agent_partial": [record["partial"] for record in records],
    }


def paper_token_consumption(output_tokens: int, rounds_executed: int) -> float:
    """Paper Eq. 4: generated output tokens divided by executed rounds."""
    if rounds_executed <= 0:
        return 0.0
    return float(output_tokens) / rounds_executed


def paper_communication_density(communication_events: int, n_agents: int) -> float:
    """Paper Eq. 5: outward information transfers over directed agent pairs."""
    denominator = n_agents * (n_agents - 1)
    if denominator <= 0:
        return 0.0
    return float(communication_events) / denominator
