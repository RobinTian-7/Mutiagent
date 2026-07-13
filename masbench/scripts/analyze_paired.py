"""Pre-registered paired analysis of a ``verify_beats_baselines`` report.

Consumes the verifier's JSON (``pairs`` = per-(case,seed) binary all-agents S,
plus ``pair_details`` for the paper P/C/D reporting table) and decides the
frozen PASS / FAIL / INCONCLUSIVE verdict for the hot-start PythonGenerate
all_agents study. It NEVER re-runs models and NEVER re-scores; it only reads
the recorded S values and applies the registered decision rule.

Primary metric S: binary "all N agents correct" per (case, seed) — exactly the
verifier's ``pairs[arm]`` value (score.success in all_agents mode). The
fractional per-agent ``paper_S`` is NOT the primary metric here (it is reported
separately by the verifier). P is the paper partial score (secondary).

Registered PASS rule (ALL must hold, else FAIL; guards below force INCONCLUSIVE):
  * against EACH hot-start baseline: mean S delta (evolved - baseline) >= delta_min;
  * bootstrap 95% CI lower bound > 0;
  * wins - losses >= win_margin;
  * Holm-corrected paired exact test still rejects (evolved-favored);
  * evolved Python also improves over cold Python (mean S delta > 0).
Guards: >= min_valid_pairs retained pairs, dropped-pair fraction <= max_dropped_frac.
Honesty rules: S tie but higher P -> "partial-correctness signal", not a win;
all methods S == 0 -> "does not support QueenBee being stronger".
"""
from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path
from random import Random
from typing import Any

# The five warm-start baselines the evolved arm must beat, as arm keys in the
# verifier report (the two fixed topologies are per-topology paired arms).
DEFAULT_HOT_START_BASELINES = (
    "p2p",
    "broadcast",
    "sfs",
    "fixed:one_peer_exponential_dag",
    "fixed:static_exponential",
)


def _paired_bootstrap_ci(
    diffs: list[float],
    *,
    n_resamples: int,
    seed: int,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of paired differences.

    Deterministic given ``seed``. Every comparison is bootstrapped with the same
    seed, so the same resampled (case, seed) units are used across baselines
    (jointly consistent paired resampling).
    """
    n = len(diffs)
    if n == 0:
        return (float("nan"), float("nan"))
    rng = Random(seed)
    means: list[float] = []
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo_idx = int((alpha / 2.0) * n_resamples)
    hi_idx = int((1.0 - alpha / 2.0) * n_resamples) - 1
    lo_idx = max(0, min(n_resamples - 1, lo_idx))
    hi_idx = max(0, min(n_resamples - 1, hi_idx))
    return (means[lo_idx], means[hi_idx])


def _exact_mcnemar_p(wins: int, losses: int) -> float:
    """Two-sided exact binomial (McNemar / sign) p-value on discordant pairs.

    Under H0 the ``wins + losses`` discordant pairs split 50/50, so wins ~
    Binomial(b, 0.5). Returns 1.0 when there are no discordant pairs.
    """
    b = wins + losses
    if b == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(comb(b, i) for i in range(0, k + 1)) * (0.5 ** b)
    return min(1.0, 2.0 * tail)


def _holm_reject(pvalues: list[float], alpha: float) -> list[bool]:
    """Holm step-down rejections aligned to the input order.

    Sort p-values ascending; the rank-``r`` (0-based) smallest is compared to
    ``alpha / (m - r)``; stop at the first non-rejection (step-down).
    """
    m = len(pvalues)
    reject = [False] * m
    order = sorted(range(m), key=lambda i: pvalues[i])
    for rank, idx in enumerate(order):
        threshold = alpha / (m - rank)
        if pvalues[idx] <= threshold:
            reject[idx] = True
        else:
            break
    return reject


def _paired_vectors(
    pairs: list[dict[str, Any]], evolved: str, baseline: str
) -> tuple[list[float], list[float]]:
    """Return aligned (evolved, baseline) S vectors over the retained pairs."""
    e: list[float] = []
    x: list[float] = []
    for row in pairs:
        if evolved in row and baseline in row:
            e.append(float(row[evolved]))
            x.append(float(row[baseline]))
    return e, x


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _arm_p_mean(pair_details: list[dict[str, Any]], arm: str) -> float:
    """Mean paper P for an arm over pair_details (secondary metric)."""
    vals = [
        float(detail["arms"][arm]["P"])
        for detail in pair_details
        if arm in detail.get("arms", {})
    ]
    return _mean(vals)


def analyze(
    report: dict[str, Any],
    *,
    evolved_arm: str,
    hot_start_baselines: tuple[str, ...],
    cold_arm: str,
    delta_min: float,
    win_margin: int,
    bootstrap_n: int,
    bootstrap_seed: int,
    alpha: float,
    min_valid_pairs: int,
    max_dropped_frac: float,
) -> dict[str, Any]:
    pairs = report.get("pairs", [])
    pair_details = report.get("pair_details", [])
    n_valid = len(pairs)
    dropped = int(report.get("dropped_pairs", 0))
    denom = n_valid + dropped
    dropped_frac = (dropped / denom) if denom > 0 else 0.0

    evolved_s_mean = _mean([float(p[evolved_arm]) for p in pairs if evolved_arm in p])

    # ---- per-baseline paired comparisons on S ----
    per_baseline: dict[str, Any] = {}
    pvalues: list[float] = []
    ordered_baselines: list[str] = []
    for b in hot_start_baselines:
        e, x = _paired_vectors(pairs, evolved_arm, b)
        n = len(e)
        diffs = [e[i] - x[i] for i in range(n)]
        wins = sum(1 for d in diffs if d > 0)
        losses = sum(1 for d in diffs if d < 0)
        ties = sum(1 for d in diffs if d == 0)
        mean_delta = _mean(diffs)
        ci_lo, ci_hi = _paired_bootstrap_ci(
            diffs, n_resamples=bootstrap_n, seed=bootstrap_seed, alpha=alpha
        )
        p_exact = _exact_mcnemar_p(wins, losses)
        p_delta = _arm_p_mean(pair_details, evolved_arm) - _arm_p_mean(pair_details, b)
        per_baseline[b] = {
            "n": n,
            "evolved_S_mean": _mean(e),
            "baseline_S_mean": _mean(x),
            "mean_delta_S": mean_delta,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_minus_loss": wins - losses,
            "bootstrap_ci_95": [ci_lo, ci_hi],
            "exact_p": p_exact,
            "mean_delta_P": p_delta,
            "s_tie_p_higher": bool(mean_delta == 0.0 and p_delta > 0.0),
            # per-comparison gate components (Holm added after all p-values known)
            "passes_delta": bool(mean_delta >= delta_min),
            "passes_ci": bool(ci_lo > 0.0),
            "passes_margin": bool((wins - losses) >= win_margin),
        }
        pvalues.append(p_exact)
        ordered_baselines.append(b)

    holm = _holm_reject(pvalues, alpha)
    for b, rej, p in zip(ordered_baselines, holm, pvalues):
        entry = per_baseline[b]
        entry["holm_reject"] = bool(rej)
        # evolved-favored direction required in addition to Holm rejection
        entry["passes_holm"] = bool(rej and entry["win_minus_loss"] > 0)
        entry["passed"] = bool(
            entry["passes_delta"]
            and entry["passes_ci"]
            and entry["passes_margin"]
            and entry["passes_holm"]
        )

    # ---- evolved vs cold python ----
    ce, cx = _paired_vectors(pairs, evolved_arm, cold_arm)
    cold_diffs = [ce[i] - cx[i] for i in range(len(ce))]
    cold_wins = sum(1 for d in cold_diffs if d > 0)
    cold_losses = sum(1 for d in cold_diffs if d < 0)
    cold_ci_lo, cold_ci_hi = _paired_bootstrap_ci(
        cold_diffs, n_resamples=bootstrap_n, seed=bootstrap_seed, alpha=alpha
    )
    cold_mean_delta = _mean(cold_diffs)
    evolved_vs_cold = {
        "cold_arm": cold_arm,
        "n": len(ce),
        "evolved_S_mean": _mean(ce),
        "cold_S_mean": _mean(cx),
        "mean_delta_S": cold_mean_delta,
        "wins": cold_wins,
        "losses": cold_losses,
        "ties": len(ce) - cold_wins - cold_losses,
        "bootstrap_ci_95": [cold_ci_lo, cold_ci_hi],
        "exact_p": _exact_mcnemar_p(cold_wins, cold_losses),
        "improves": bool(cold_mean_delta > 0.0),
    }

    # ---- global guards + all-zero honesty check ----
    all_baseline_means_zero = all(
        per_baseline[b]["baseline_S_mean"] == 0.0 for b in ordered_baselines
    )
    all_methods_s_zero = bool(evolved_s_mean == 0.0 and all_baseline_means_zero)

    dropped_ok = dropped_frac <= max_dropped_frac
    samples_ok = n_valid >= min_valid_pairs
    all_baselines_beaten = bool(
        ordered_baselines and all(per_baseline[b]["passed"] for b in ordered_baselines)
    )
    beats_cold = evolved_vs_cold["improves"]

    if not dropped_ok:
        verdict = "INCONCLUSIVE"
        reason = (
            f"dropped-pair fraction {dropped_frac:.1%} exceeds the "
            f"{max_dropped_frac:.0%} ceiling; real per-arm failures were not hidden "
            "but too many pairs were symmetrically dropped to judge."
        )
    elif not samples_ok:
        verdict = "INCONCLUSIVE"
        reason = (
            f"only {n_valid} valid paired samples (< {min_valid_pairs} required)."
        )
    elif all_methods_s_zero:
        verdict = "FAIL"
        reason = (
            "every method (evolved and all baselines) scored S = 0 (no run had all "
            "agents correct); the data do not support QueenBee being stronger. Any "
            "token savings cannot substitute for correctness."
        )
    elif all_baselines_beaten and beats_cold:
        verdict = "PASS"
        reason = (
            "evolved beat every hot-start baseline on all registered criteria "
            "(delta S >= {dm}, bootstrap CI lower bound > 0, wins-losses >= {wm}, "
            "Holm-corrected exact test), and also improved over cold Python."
        ).format(dm=delta_min, wm=win_margin)
    else:
        verdict = "FAIL"
        failing = [b for b in ordered_baselines if not per_baseline[b]["passed"]]
        parts = []
        if failing:
            parts.append("did not clear all criteria vs " + ", ".join(failing))
        if not beats_cold:
            parts.append(
                f"did not improve over cold Python "
                f"(delta S = {cold_mean_delta:+.3f})"
            )
        reason = "evolved " + "; ".join(parts) + "."

    partial_signal_baselines = [
        b for b in ordered_baselines if per_baseline[b]["s_tie_p_higher"]
    ]

    return {
        "primary_metric": "S = all-agents-correct (binary, per case,seed)",
        "criteria": {
            "delta_min": delta_min,
            "win_margin": win_margin,
            "bootstrap_n": bootstrap_n,
            "bootstrap_seed": bootstrap_seed,
            "alpha": alpha,
            "min_valid_pairs": min_valid_pairs,
            "max_dropped_frac": max_dropped_frac,
            "holm_family_size": len(ordered_baselines),
        },
        "evolved_arm": evolved_arm,
        "hot_start_baselines": list(ordered_baselines),
        "n_valid_pairs": n_valid,
        "dropped_pairs": dropped,
        "dropped_frac": dropped_frac,
        "evolved_S_mean": evolved_s_mean,
        "per_baseline": per_baseline,
        "evolved_vs_cold": evolved_vs_cold,
        "all_methods_s_zero": all_methods_s_zero,
        "partial_signal_baselines": partial_signal_baselines,
        "guards": {
            "dropped_ok": dropped_ok,
            "samples_ok": samples_ok,
            "all_baselines_beaten": all_baselines_beaten,
            "beats_cold": beats_cold,
        },
        "verdict": verdict,
        "reason": reason,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", required=True, help="verify_beats_baselines_n*.json")
    p.add_argument("--evolved-arm", default="evolved")
    p.add_argument(
        "--hot-start-baselines",
        nargs="+",
        default=list(DEFAULT_HOT_START_BASELINES),
    )
    p.add_argument("--cold-arm", default="pycodegen")
    p.add_argument("--delta-min", type=float, default=0.05)
    p.add_argument("--win-margin", type=int, default=2)
    p.add_argument("--bootstrap-n", type=int, default=20000)
    p.add_argument("--bootstrap-seed", type=int, default=20260713)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--min-valid-pairs", type=int, default=10)
    p.add_argument("--max-dropped-frac", type=float, default=0.10)
    p.add_argument("--out", default=None, help="write the analysis JSON here")
    return p.parse_args()


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def main() -> int:
    args = parse_args()
    report = json.loads(Path(args.report).read_text())
    result = analyze(
        report,
        evolved_arm=args.evolved_arm,
        hot_start_baselines=tuple(args.hot_start_baselines),
        cold_arm=args.cold_arm,
        delta_min=args.delta_min,
        win_margin=args.win_margin,
        bootstrap_n=args.bootstrap_n,
        bootstrap_seed=args.bootstrap_seed,
        alpha=args.alpha,
        min_valid_pairs=args.min_valid_pairs,
        max_dropped_frac=args.max_dropped_frac,
    )
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True))

    print(f"=== paired analysis on S (all-agents-correct) ===")
    print(
        f"valid pairs={result['n_valid_pairs']} dropped={result['dropped_pairs']} "
        f"({result['dropped_frac']:.1%}) | evolved S={_fmt_pct(result['evolved_S_mean'])}"
    )
    print(
        f"{'baseline':<34} {'bS':>6} {'dS':>7} {'CI95':>16} "
        f"{'W/L/T':>9} {'exactP':>7} {'holm':>5} {'pass':>5}"
    )
    for b in result["hot_start_baselines"]:
        e = result["per_baseline"][b]
        ci = e["bootstrap_ci_95"]
        print(
            f"{b:<34} {_fmt_pct(e['baseline_S_mean']):>6} "
            f"{e['mean_delta_S'] * 100:+6.1f}pp "
            f"[{ci[0] * 100:+5.1f},{ci[1] * 100:+5.1f}] "
            f"{e['wins']}/{e['losses']}/{e['ties']:>1} "
            f"{e['exact_p']:.3f} {str(e['holm_reject']):>5} "
            f"{'YES' if e['passed'] else 'no':>5}"
        )
    c = result["evolved_vs_cold"]
    print(
        f"evolved vs cold ({c['cold_arm']}): dS={c['mean_delta_S'] * 100:+.1f}pp "
        f"W/L/T={c['wins']}/{c['losses']}/{c['ties']} improves={c['improves']}"
    )
    if result["partial_signal_baselines"]:
        print(
            "partial-correctness signal (S tie, higher P) vs: "
            + ", ".join(result["partial_signal_baselines"])
        )
    print(f"\nVERDICT: {result['verdict']} -- {result['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
