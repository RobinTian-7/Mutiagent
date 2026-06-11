"""Round diagnostics: digest a verify_evolve report + its MASBENCH_EVOLVE_DUMP_DIR.

Usage: uv run python scripts/diag_report.py runs/dev_round1
Reads <dir>/verify_*.json and <dir>/diag/{evolution_*.json,eval_runs.jsonl}.
Pure analysis -- no LLM calls, no judgment changes; verify_evolve.py stays the
sole PASS/FAIL authority.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BLENDED_USD_PER_MTOK = 0.2625  # gpt-4o-mini, 75/25 in/out blend
GEN_CALL_TOKENS = 2500         # planner-side generation call not counted in rows


def main(root: str) -> None:
    base = Path(root)
    reports = sorted(base.glob("verify_*.json"))
    for rp in reports:
        r = json.loads(rp.read_text())
        print(f"== {rp.name} ==")
        print(f"  mode={r['mode']} n={r['n_agents']} train={r['train_cases']} test={r['test_cases']}")
        print(f"  eval_seeds={r['eval_seeds']}")
        print(f"  empty={r['mean_empty']*100:.1f}% evolved={r['mean_evolved']*100:.1f}% "
              f"delta={r['delta']*100:+.1f}pp wins(e/o)={r['evolved_only_wins']}/{r['empty_only_wins']} "
              f"passed={r['passed']}")
        print(f"  gate={r['gate']}")
        per_case: dict[str, list] = defaultdict(list)
        for p in r["pairs"]:
            per_case[p["case_id"]].append((p["empty"], p["evolved"]))
        for case, vals in sorted(per_case.items()):
            e = sum(v[0] for v in vals) / len(vals)
            v = sum(v[1] for v in vals) / len(vals)
            print(f"    {case}: empty={e*100:.0f}% evolved={v*100:.0f}% over {len(vals)} seeds")

    diag = base / "diag"
    evo_files = sorted(diag.glob("evolution_*.json"))
    for ef in evo_files:
        s = json.loads(ef.read_text())
        print(f"== {ef.name} ==")
        print(f"  gate_mode={s.get('gate_mode')} gate={s.get('gate')}")
        print(f"  selection_gate={s.get('selection_gate', {}).get('counts')}")
        print(f"  train_success={s.get('train_success_rate'):.2f} val_success={s.get('val_success_rate'):.2f} "
              f"patches={s.get('n_patches')} rejected={s.get('rejected_skill_ids')}")
        for sk in s.get("evolved_skills", []):
            pol = sk.get("organization_policy") or {}
            spec = pol.get("protocol_spec")
            tr = sk.get("expected_tradeoff") or {}
            print(f"    skill {sk['skill_id']}: topo={pol.get('topology_name')} "
                  f"loss={tr.get('mean_primary_loss', tr.get('mean_rmse'))} "
                  f"msgs={tr.get('mean_messages')} spec={'YES(' + str(len(spec.get('steps', []))) + ' steps)' if isinstance(spec, dict) else 'none'} "
                  f"counterex={len(sk.get('counterexamples') or [])}")

    runs_file = diag / "eval_runs.jsonl"
    if runs_file.exists():
        lines = [json.loads(l) for l in runs_file.read_text().splitlines()]
        print(f"== eval_runs.jsonl: {len(lines)} runs ==")
        print(f"  phases: {dict(Counter(l['phase'] for l in lines))}")
        ev = [l for l in lines if l["phase"] == ""]
        for arm, sel in (("empty", lambda l: l["bank_size"] == 0), ("evolved", lambda l: l["bank_size"] > 0)):
            rows = [l for l in ev if sel(l)]
            if not rows:
                continue
            em = sum(l["exact_match"] or 0 for l in rows) / len(rows)
            msgs = sum(l["messages"] or 0 for l in rows) / len(rows)
            toks = sum(l["tokens"] or 0 for l in rows) / len(rows)
            calls = sum(l["model_calls"] or 0 for l in rows) / len(rows)
            topos = Counter(str(l["topology"]) for l in rows)
            print(f"  {arm}: n={len(rows)} exact={em*100:.1f}% msgs={msgs:.1f} calls={calls:.1f} tokens={toks:.0f}")
            for t, c in topos.most_common(6):
                print(f"      {c:3d}x {t}")
        total_tokens = sum(l["tokens"] or 0 for l in lines)
        n_gen = sum(1 for l in lines if l["planner_mode"] == "graph_generate")
        est = (total_tokens + n_gen * GEN_CALL_TOKENS) / 1e6 * BLENDED_USD_PER_MTOK
        print(f"  cost: rows={total_tokens/1e6:.2f}M tok + ~{n_gen} gen calls -> est ${est:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs/dev_round1")
