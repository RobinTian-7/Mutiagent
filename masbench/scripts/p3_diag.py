"""Digest a verify_evolve_stable report + its MASBENCH_EVOLVE_DUMP_DIR.

Usage: uv run python scripts/p3_diag.py runs/p3_dev1 [diag_refine]
Pure analysis -- no LLM calls; verify_evolve_stable.py stays the judge.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(root: str, diag_name: str = "diag_refine") -> None:
    base = Path(root)
    for rp in sorted(base.glob("stable_*.json")):
        r = json.loads(rp.read_text())
        print(f"== {rp.name} ==")
        print(f"  mode={r['mode']} n={r['n_agents']}")
        print(f"  train={r['train_cases']}")
        print(f"  test={r['test_cases']} eval_seeds={r['eval_seeds']}")
        print(f"  baseline={r['baseline_mean']*100:.1f}%  pass={r['passed']}")
        for pt in r["rounds"]:
            gate = pt.get("gate") or {}
            print(
                f"  round {pt['round']}: mean={pt['mean']*100:5.1f}% "
                f"delta={pt['delta']*100:+5.1f}pp wins={pt['wins']} losses={pt['losses']} "
                f"skills={pt['n_skills']} dominates={pt['dominates']} "
                f"gate={gate.get('mode')}/{'ACC' if gate.get('accepted') else 'REJ'} "
                f"j {gate.get('j_before')}->{gate.get('j_after')}"
            )

    diag = base / diag_name
    runs_file = diag / "eval_runs.jsonl"
    if runs_file.exists():
        rows = [json.loads(line) for line in runs_file.open()]
        evals = [x for x in rows if x.get("phase") == ""]
        print(f"\n-- deployment rows ({len(evals)}) by (case, bank_size>0) --")
        agg: dict = defaultdict(list)
        for x in evals:
            arm = "evolved" if x.get("bank_size", 0) > 0 else "cold"
            agg[(x["case_id"], arm)].append(x)
        for (case, arm), items in sorted(agg.items()):
            ems = [float(i.get("exact_match") or 0.0) for i in items]
            topos = Counter(str(i.get("topology")) for i in items)
            abst = sum(1 for i in items if i.get("transfer_abstained"))
            print(
                f"  {case:6s} {arm:7s} mean_em={sum(ems)/len(ems):.2f} n={len(ems)} "
                f"abstained={abst} topo={dict(topos)}"
            )
        print("\n-- abstention by bucket (evolved rows) --")
        byb: dict = defaultdict(lambda: [0, 0])
        for x in evals:
            if x.get("bank_size", 0) > 0:
                b = byb[x.get("transfer_bucket")]
                b[0] += 1
                b[1] += 1 if x.get("transfer_abstained") else 0
        for bucket, (n, a) in sorted(byb.items()):
            print(f"  {bucket}: {a}/{n} abstained")

    for ev in sorted(diag.glob("evolution_*.json")) if diag.exists() else []:
        d = json.loads(ev.read_text())
        gate = d.get("gate") or {}
        print(
            f"\n== {ev.name}: bank {d.get('skill_bank_size_before')}->"
            f"{d.get('skill_bank_size_after')} gate={gate.get('mode')}"
            f"/{'ACC' if gate.get('accepted') else 'REJ'} "
            f"j {gate.get('j_before')}->{gate.get('j_after')} "
            f"explore={d.get('n_explore_rows')} portfolio={d.get('n_portfolio_rows')}"
        )
        for s in d.get("evolved_skills", []):
            policy = s.get("organization_policy") or {}
            ledger = policy.get("transfer_evidence") or {}
            spec = "spec" if isinstance(policy.get("protocol_spec"), dict) else "----"
            led = {
                k: f"{v.get('em_sum',0)}/{v.get('n',0)}" for k, v in ledger.items()
            }
            loss = (s.get("expected_tradeoff") or {}).get("mean_primary_loss")
            print(f"   {spec} loss={loss} {s['skill_id'][:60]:60s} {led}")


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:] or []))
