"""Assemble the auditable Markdown report from a verify_beats_baselines run.

Reads the verifier report JSON, the per-round evolution summaries, and the
paired-analysis JSON, and emits the deliverable tables: 5-round training table,
per-arm S/P/C/D/(U) table, paired delta/CI/Holm table, per-level/case/arm error
+ per-agent submission summary, capability floor, and the dropped/failed list.
Deterministic post-processing only; no models, no re-scoring.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def _submission_rate(arm_metrics: dict[str, Any]) -> float:
    subs = arm_metrics.get("per_agent_submissions") or []
    if not subs:
        return 0.0
    real = sum(1 for s in subs if s.get("answer") not in (None, "", []))
    return real / len(subs)


def _arm_eval_means(report: dict[str, Any], arm: str) -> dict[str, float]:
    rows = [d["arms"][arm] for d in report["pair_details"] if arm in d.get("arms", {})]
    n = len(rows)
    if not n:
        return {}
    return {
        "S": sum(float(r["success"]) for r in rows) / n,   # binary all-agents S
        "paper_S_frac": sum(float(r.get("S", 0.0)) for r in rows) / n,
        "P": sum(float(r["P"]) for r in rows) / n,
        "C": sum(float(r["C"]) for r in rows) / n,
        "D": sum(float(r["D"]) for r in rows) / n,
        "U": sum(_submission_rate(r) for r in rows) / n,
        "model_calls": sum(float(r["model_calls"]) for r in rows) / n,
        "tokens": sum(float(r["tokens"]) for r in rows) / n,
    }


def training_table(report: dict[str, Any], run_dir: Path) -> str:
    lines = [
        "| Round | Bank | Gate | reuse n/succ | innov n/succ | V | K | U | P | S | tokens |",
        "|--:|--:|:--|:--|:--|--:|--:|--:|--:|--:|--:|",
    ]
    for r in report["rounds_log"]:
        rd = r["round"]
        summ_path = run_dir / "skill_banks" / f"round_{rd:02d}" / "evolution_summary.json"
        ts = {}
        reuse = innov = {}
        tokens = 0
        if summ_path.exists():
            summ = _load(summ_path)
            ts = summ.get("training_signal", {})
            db = summ.get("hot_start", {}).get("dual_branch", {}).get("branches", {})
            reuse = db.get("reuse", {})
            innov = db.get("innovation", {})
            tot = summ.get("hot_start", {}).get("total_extra_cost", {})
            tokens = int(tot.get("tokens", 0) or 0)
        gate = r.get("gate") or {}
        gate_s = "accept" if gate.get("accepted") else "reject"

        def _ns(b):
            n = b.get("n_rows", 0)
            sr = b.get("success_rate", 0.0)
            return f"{n}/{sr * n:.0f}"

        lines.append(
            f"| {rd} | {r['n_skills']} | {gate_s} "
            f"| {_ns(reuse)} | {_ns(innov)} "
            f"| {ts.get('mean_V', 0):.2f} | {ts.get('mean_K', 0):.2f} "
            f"| {ts.get('mean_U', 0):.2f} | {ts.get('mean_P', 0):.2f} "
            f"| {ts.get('mean_S', 0):.2f} | {tokens} |"
        )
    return "\n".join(lines)


def arm_table(report: dict[str, Any]) -> str:
    arms = ["evolved", *report["eval_baselines"]]
    lines = [
        "| Arm | S (all-correct) | paper_S frac | P | C (tok/round) | D | U | calls | tokens |",
        "|:--|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for a in arms:
        m = _arm_eval_means(report, a)
        if not m:
            continue
        tag = " *(supp)*" if a in report.get("supplementary_baselines", []) else ""
        lines.append(
            f"| {a}{tag} | {m['S'] * 100:.1f}% | {m['paper_S_frac'] * 100:.1f}% "
            f"| {m['P'] * 100:.1f}% | {m['C']:.1f} | {m['D']:.3f} | {m['U'] * 100:.0f}% "
            f"| {m['model_calls']:.0f} | {m['tokens']:.0f} |"
        )
    cap = report.get("capability_diagnostic", {}).get("full_information_single_agent")
    if cap:
        lines.append(
            f"| full_information_single_agent *(floor)* | {cap['S'] * 100:.1f}% | - "
            f"| {cap['P'] * 100:.1f}% | {cap['C']:.1f} | {cap['D']:.3f} | - | - | - |"
        )
    return "\n".join(lines)


def paired_table(analysis: dict[str, Any]) -> str:
    lines = [
        "| Baseline | evolved S | base S | delta S | 95% CI | W/L/T | exact p | Holm rej | pass |",
        "|:--|--:|--:|--:|:--|:--|--:|:--:|:--:|",
    ]
    for b in analysis["hot_start_baselines"]:
        e = analysis["per_baseline"][b]
        ci = e["bootstrap_ci_95"]
        lines.append(
            f"| {b} | {e['evolved_S_mean'] * 100:.1f}% | {e['baseline_S_mean'] * 100:.1f}% "
            f"| {e['mean_delta_S'] * 100:+.1f}pp | [{ci[0] * 100:+.1f}, {ci[1] * 100:+.1f}] "
            f"| {e['wins']}/{e['losses']}/{e['ties']} | {e['exact_p']:.4f} "
            f"| {'yes' if e['holm_reject'] else 'no'} | {'YES' if e['passed'] else 'no'} |"
        )
    c = analysis["evolved_vs_cold"]
    lines.append(
        f"| _{c['cold_arm']} (cold ref)_ | {c['evolved_S_mean'] * 100:.1f}% "
        f"| {c['cold_S_mean'] * 100:.1f}% | {c['mean_delta_S'] * 100:+.1f}pp "
        f"| [{c['bootstrap_ci_95'][0] * 100:+.1f}, {c['bootstrap_ci_95'][1] * 100:+.1f}] "
        f"| {c['wins']}/{c['losses']}/{c['ties']} | {c['exact_p']:.4f} | - "
        f"| {'YES' if c['improves'] else 'no'} |"
    )
    return "\n".join(lines)


def per_case_submissions(report: dict[str, Any]) -> str:
    lines = [
        "| case | seed | arm | S | P | per-agent correct |",
        "|:--|--:|:--|--:|--:|:--|",
    ]
    arms = ["evolved", *report["eval_baselines"]]
    for d in report["pair_details"]:
        for a in arms:
            m = d["arms"].get(a)
            if not m:
                continue
            subs = m.get("per_agent_submissions") or []
            correct = "".join("1" if s.get("correct") else "0" for s in subs) or "-"
            lines.append(
                f"| {d['case_id']} | {d['seed']} | {a} "
                f"| {int(float(m['success']))} | {float(m['P']) * 100:.0f}% | {correct} |"
            )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", required=True)
    p.add_argument("--analysis", default=None)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    report = _load(args.report)
    run_dir = Path(args.run_dir)
    analysis = _load(args.analysis) if args.analysis else None

    parts = ["## 5-round training table\n", training_table(report, run_dir), "",
             "## Per-arm S/P/C/D/U (held-out TEST)\n", arm_table(report), ""]
    if analysis:
        parts += ["## Paired comparison vs hot-start baselines\n",
                  paired_table(analysis), "",
                  f"**Verdict:** {analysis['verdict']} — {analysis['reason']}", ""]
    parts += ["## Per-(case,seed,arm) submissions\n", per_case_submissions(report), ""]
    text = "\n".join(parts)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
