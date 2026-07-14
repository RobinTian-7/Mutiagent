from __future__ import annotations

from masbench.gates import evaluate_strict_dense_gate


def _row(seed: int, **updates):
    row = {
        "case_id": "II-01",
        "seed": seed,
        "program_validity": 1.0,
        "structural_coverage": 1.0,
        "submission_rate": 1.0,
        "evolution_partial": 0.4,
        "evolution_success": 0.0,
        "evolution_stage_score": 0.6,
        "paper_C": 10.0,
        "paper_D": 0.5,
    }
    row.update(updates)
    return row


def test_strict_gate_accepts_dense_quality_improvement() -> None:
    before = [_row(1), _row(2)]
    after = [
        _row(1, evolution_partial=0.6, evolution_stage_score=0.7),
        _row(2, evolution_partial=0.6, evolution_stage_score=0.7),
    ]
    result = evaluate_strict_dense_gate(before, after, bootstrap_samples=100)
    assert result["accepted"] is True
    assert result["reason"] == "quality_improvement"
    assert result["n_samples"] == 2


def test_strict_gate_rejects_equal_quality_and_equal_cost_as_no_change() -> None:
    before = [_row(1), _row(2)]
    result = evaluate_strict_dense_gate(before, list(before), bootstrap_samples=100)
    assert result["accepted"] is False
    assert result["accepted_no_change"] is False
    assert result["reason"] == "no_change"


def test_strict_gate_allows_cost_tiebreak_only_at_equal_quality() -> None:
    before = [_row(1), _row(2)]
    cheaper = [_row(1, paper_C=8.0), _row(2, paper_C=8.0)]
    accepted = evaluate_strict_dense_gate(before, cheaper, bootstrap_samples=100)
    assert accepted["accepted"] is True
    assert accepted["reason"] == "equal_quality_lower_cost"

    regressed = [
        _row(1, structural_coverage=0.8, evolution_stage_score=0.8, paper_C=1.0),
        _row(2, structural_coverage=0.8, evolution_stage_score=0.8, paper_C=1.0),
    ]
    rejected = evaluate_strict_dense_gate(before, regressed, bootstrap_samples=100)
    assert rejected["accepted"] is False
    assert rejected["checks"]["min_K_non_regression"] is False


def test_strict_gate_rejects_higher_algorithm_failure_rate() -> None:
    before = [_row(1), _row(2)]
    after = [
        _row(
            1,
            failure_class="algorithm_failure",
            program_validity=0.0,
            structural_coverage=0.0,
            submission_rate=0.0,
            evolution_partial=0.0,
            evolution_stage_score=0.0,
        ),
        _row(2, evolution_stage_score=0.8),
    ]
    result = evaluate_strict_dense_gate(before, after, bootstrap_samples=100)
    assert result["accepted"] is False
    assert result["checks"]["algorithm_failure_rate_non_increasing"] is False
