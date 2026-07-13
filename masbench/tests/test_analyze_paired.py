"""Offline, deterministic tests for the pre-registered paired analysis.

Pure statistics (exact McNemar, Holm step-down, percentile bootstrap) plus the
PASS / FAIL / INCONCLUSIVE decision rule on synthetic verifier reports. No LLM,
no benchmark data, fixed bootstrap seed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from analyze_paired import (  # noqa: E402
    _exact_mcnemar_p,
    _holm_reject,
    _paired_bootstrap_ci,
    analyze,
)

BASELINES = ("p2p", "broadcast", "sfs", "fixed:a", "fixed:b")


def _report(evolved, per_baseline_s, cold, *, dropped=0, p_by_arm=None):
    """Build a minimal verifier-shaped report from per-arm S vectors."""
    n = len(evolved)
    pairs = []
    details = []
    for i in range(n):
        row = {"case_id": f"C{i % 4}", "seed": 300 + i, "evolved": float(evolved[i])}
        for b in BASELINES:
            row[b] = float(per_baseline_s[b][i])
        row["pycodegen"] = float(cold[i])
        pairs.append(row)
        arms = {}
        for arm in ("evolved", *BASELINES, "pycodegen"):
            s = row[arm]
            p = (p_by_arm or {}).get(arm, [s] * n)[i]
            arms[arm] = {"S": s, "P": float(p), "C": 0.0, "D": 0.0, "success": s}
        details.append({"case_id": row["case_id"], "seed": row["seed"], "arms": arms})
    return {"pairs": pairs, "pair_details": details, "dropped_pairs": dropped,
            "n_pairs": n}


def _analyze(report):
    return analyze(
        report,
        evolved_arm="evolved",
        hot_start_baselines=BASELINES,
        cold_arm="pycodegen",
        delta_min=0.05,
        win_margin=2,
        bootstrap_n=2000,
        bootstrap_seed=20260713,
        alpha=0.05,
        min_valid_pairs=10,
        max_dropped_frac=0.10,
    )


def test_exact_mcnemar_p_values():
    assert _exact_mcnemar_p(0, 0) == 1.0
    assert _exact_mcnemar_p(5, 0) == pytest.approx(2 * 0.5 ** 5)  # 0.0625
    assert _exact_mcnemar_p(0, 5) == pytest.approx(2 * 0.5 ** 5)  # symmetric
    assert _exact_mcnemar_p(4, 1) == pytest.approx(2 * (1 + 5) / 32)  # 0.375
    # 12/0 discordant -> very small two-sided p
    assert _exact_mcnemar_p(12, 0) == pytest.approx(2 * 0.5 ** 12)


def test_holm_reject_step_down():
    # Only the smallest clears 0.05/5=0.01; step-down stops at the first miss.
    rej = _holm_reject([0.01, 0.02, 0.5, 0.04, 0.03], 0.05)
    assert rej == [True, False, False, False, False]
    # All tiny -> all reject.
    assert _holm_reject([1e-4] * 5, 0.05) == [True] * 5
    # All large -> none.
    assert _holm_reject([0.2] * 5, 0.05) == [False] * 5


def test_bootstrap_ci_deterministic_and_degenerate():
    assert _paired_bootstrap_ci([1.0] * 8, n_resamples=500, seed=1) == (1.0, 1.0)
    assert _paired_bootstrap_ci([0.0] * 8, n_resamples=500, seed=1) == (0.0, 0.0)
    a = _paired_bootstrap_ci([1, 1, 1, 0, 1, 1], n_resamples=1000, seed=7)
    b = _paired_bootstrap_ci([1, 1, 1, 0, 1, 1], n_resamples=1000, seed=7)
    assert a == b  # same seed -> identical
    assert a[0] >= 0.0 and a[1] <= 1.0


def test_analyze_pass_clear_domination():
    n = 12
    evolved = [1.0] * 10 + [0.0] * 2
    per_b = {b: [0.0] * n for b in BASELINES}
    cold = [0.0] * n
    result = _analyze(_report(evolved, per_b, cold))
    assert result["verdict"] == "PASS"
    for b in BASELINES:
        e = result["per_baseline"][b]
        assert e["passes_delta"] and e["passes_ci"] and e["passes_margin"]
        assert e["passes_holm"] and e["passed"]
        assert e["bootstrap_ci_95"][0] > 0.0
    assert result["evolved_vs_cold"]["improves"] is True


def test_analyze_all_zero_is_fail_not_cost_win():
    n = 12
    evolved = [0.0] * n
    per_b = {b: [0.0] * n for b in BASELINES}
    result = _analyze(_report(evolved, per_b, [0.0] * n))
    assert result["all_methods_s_zero"] is True
    assert result["verdict"] == "FAIL"
    assert "do not support" in result["reason"].lower()


def test_analyze_inconclusive_when_too_many_dropped():
    n = 6
    evolved = [1.0] * n
    per_b = {b: [0.0] * n for b in BASELINES}
    # 6 valid + 6 dropped -> 50% dropped fraction > 10% ceiling.
    result = _analyze(_report(evolved, per_b, [0.0] * n, dropped=6))
    assert result["verdict"] == "INCONCLUSIVE"
    assert "dropped" in result["reason"].lower()


def test_analyze_fail_when_not_beating_cold():
    n = 12
    evolved = [1.0] * 10 + [0.0] * 2
    per_b = {b: [0.0] * n for b in BASELINES}
    cold = [1.0] * 10 + [0.0] * 2  # cold ties evolved -> no improvement
    result = _analyze(_report(evolved, per_b, cold))
    assert result["evolved_vs_cold"]["improves"] is False
    assert result["verdict"] == "FAIL"


def test_analyze_partial_signal_on_s_tie_higher_p():
    n = 12
    # evolved and every baseline tie on S but evolved has higher P.
    evolved = [1.0] * 6 + [0.0] * 6
    per_b = {b: list(evolved) for b in BASELINES}
    p_by_arm = {"evolved": [0.9] * n}
    p_by_arm.update({b: [0.3] * n for b in BASELINES})
    result = _analyze(_report(evolved, per_b, list(evolved), p_by_arm=p_by_arm))
    for b in BASELINES:
        assert result["per_baseline"][b]["mean_delta_S"] == 0.0
        assert result["per_baseline"][b]["s_tie_p_higher"] is True
    assert set(result["partial_signal_baselines"]) == set(BASELINES)
    assert result["verdict"] == "FAIL"  # tie on S is never a win
