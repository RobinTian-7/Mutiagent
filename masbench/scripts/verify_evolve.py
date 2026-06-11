"""Minimal PASS/FAIL verification: does self-evolution help on held-out Silo cases?

Protocol (honest by construction):
  1. Disjoint case split: the last ``holdout_frac`` of level-I cases are TEST and
     are never seen by evolution.
  2. ``run_evolution()`` on the TRAIN cases only -- the full gated pipeline
     (analyst -> held-out acceptance gate -> bank/motif prior).
  3. Paired eval on TEST: for each (case, seed) pair the SAME planner runs twice,
     once with an EMPTY skill bank and once with the EVOLVED bank (+motif prior),
     on eval seeds disjoint from the training/val seeds.
  4. PASS iff BOTH hold on the paired exact-match outcomes:
       - mean delta (evolved - empty) >= ``--delta-min``
       - discordant pairs favor evolved by >= ``--win-margin``
         (evolved-only-correct minus empty-only-correct; McNemar-style)

Exit code: 0 = verified improvement, 1 = not verified (the report says why),
2 = aborted (budget guard).

Offline (``--llm fake``) Silo runs are topology-invariant, so this MUST exit 1
with "machinery OK"; that is the harness smoke test, not a failure of the method.
This file is the agreed verification target -- once frozen, fixes go into the
pipeline, never into this script.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.curve import _bank_and_motif, _bounded, _evolved_planner_mode, _split_cases
from masbench.engine import _build_llm_client
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmarks-dir", default="third_party/acl26-silo-bench/benchmarks")
    p.add_argument("--llm", default="openai")
    p.add_argument("--model-name", default="gpt-4o-mini")
    p.add_argument("--merge-mode", default="llm_full_merge")
    p.add_argument("--init-mode", default="llm_local_solve")
    p.add_argument("--objective", default="accuracy_first")
    p.add_argument("--evolved-mode", default="select_then_refine",
                   choices=["topology_select", "graph_generate", "select_then_refine"])
    p.add_argument("--n-agents", type=int, default=5,
                   help="5 by default: n=2 sits on the exact-match floor (no headroom)")
    p.add_argument("--levels", nargs="+", default=["I"])
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=list(range(11, 19)),
                   help="held-out eval seeds; MUST be disjoint from train/val seeds")
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--graph-validation-seeds", type=int, default=0)
    p.add_argument("--use-llm-insights", action="store_true")
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--delta-min", type=float, default=0.05,
                   help="required mean exact-match improvement (evolved - empty)")
    p.add_argument("--win-margin", type=int, default=2,
                   help="required (evolved-only wins) - (empty-only wins)")
    p.add_argument("--max-runs", type=int, default=400,
                   help="abort before spending if the planned LLM run count exceeds this")
    p.add_argument("--out", default="runs/verify_evolve")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    overlap = set(args.eval_seeds) & (set(args.train_seeds) | set(args.val_seeds))
    if overlap:
        raise SystemExit(f"eval seeds must be disjoint from train/val seeds; overlap={sorted(overlap)}")

    cfg = RunConfig(
        benchmark="silo_bench", objective=args.objective,
        merge_mode=args.merge_mode, init_mode=args.init_mode,
        llm_provider=args.llm, model_name=args.model_name,
        request_timeout=args.request_timeout, evolved_mode=args.evolved_mode,
        num_graph_candidates=args.graphgen_candidates,
        graph_validation_seeds=args.graph_validation_seeds,
        use_llm_insights=args.use_llm_insights, n_agents=args.n_agents,
    )
    adapter = SiloBenchAdapter(args.benchmarks_dir)
    instances = list(adapter.iter_instances(
        levels=args.levels, agent_counts=[args.n_agents], cases=args.cases))
    all_cases = sorted({i.case_id for i in instances})
    train_cases, test_cases = _split_cases(all_cases, args.holdout_frac)
    test_instances = [i for i in instances if i.case_id in set(test_cases)]

    # ---- budget guard (before any spend) ----
    n_pairs = len(test_instances) * len(args.eval_seeds)
    evo_runs = len(train_cases) * 3 * len(args.train_seeds) + len(test_cases) * 3 * len(args.val_seeds)
    planned = evo_runs + 2 * n_pairs
    print(f"plan: TRAIN={train_cases} TEST={test_cases}")
    print(f"plan: ~{evo_runs} evolution runs + {2 * n_pairs} paired eval runs "
          f"= ~{planned} protocol runs (n={args.n_agents}, workers={args.workers})")
    if planned > args.max_runs:
        print(f"ABORT: planned {planned} > --max-runs {args.max_runs}")
        return 2

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))
    generate = cfg.evolved_mode in ("graph_generate", "select_then_refine")
    eval_cfg = replace(cfg, planner_mode="graph_generate" if generate else "topology_select")

    # ---- 1. evolve on TRAIN only ----
    t0 = time.monotonic()
    summ = run_evolution(
        adapter, cases=train_cases, agent_counts=[args.n_agents],
        train_seeds=args.train_seeds, val_seeds=args.val_seeds,
        cfg=evo_cfg, levels=args.levels, llm_client=client,
        workers=args.workers, progress=True,
    )
    bank, motif = _bank_and_motif(summ)
    gate = summ.get("gate") or {}
    print(f"evolved: skills={len(bank)} gate={gate} ({time.monotonic() - t0:.0f}s)")

    # ---- 2. paired held-out eval (same case+seed for both arms) ----
    pairs = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]

    def run_arm(task):
        inst, seed, evolved = task
        row = _run_one(
            inst, eval_cfg, objective=objective,
            skill_bank=bank if evolved else SkillBank(), seed=seed,
            llm_client=client, motif_stats=(motif if evolved else None),
        )
        return float(row.get("ExactMatchRate", 0.0))

    tasks = [(i, s, e) for (i, s) in pairs for e in (False, True)]
    with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
        flat = list(ex.map(run_arm, tasks))
    results = [
        {"case_id": pairs[k][0].case_id, "seed": pairs[k][1],
         "empty": flat[2 * k], "evolved": flat[2 * k + 1]}
        for k in range(len(pairs))
    ]

    # ---- 3. verdict ----
    mean_empty = sum(r["empty"] for r in results) / len(results)
    mean_evolved = sum(r["evolved"] for r in results) / len(results)
    delta = mean_evolved - mean_empty
    wins = sum(1 for r in results if r["evolved"] > r["empty"])
    losses = sum(1 for r in results if r["evolved"] < r["empty"])
    machinery_ok = len(bank) > 0 and ("j_before" in gate or gate.get("mode"))
    passed = bool(delta >= args.delta_min and (wins - losses) >= args.win_margin)

    report = {
        "mode": cfg.evolved_mode, "n_agents": args.n_agents,
        "train_cases": train_cases, "test_cases": test_cases,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds, "n_pairs": len(results),
        "mean_empty": mean_empty, "mean_evolved": mean_evolved, "delta": delta,
        "evolved_only_wins": wins, "empty_only_wins": losses,
        "n_skills": len(bank), "gate": gate, "machinery_ok": machinery_ok,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin},
        "passed": passed, "pairs": results,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"verify_{cfg.evolved_mode}_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))

    print(f"\npaired held-out exact-match over {len(results)} (case,seed) pairs:")
    print(f"  empty bank   : {mean_empty * 100:5.1f}%")
    print(f"  evolved bank : {mean_evolved * 100:5.1f}%   delta={delta * 100:+.1f}pp "
          f"(need >= {args.delta_min * 100:.0f}pp)")
    print(f"  discordant   : evolved-only={wins}  empty-only={losses} "
          f"(need margin >= {args.win_margin})")
    print(f"  machinery    : {'OK' if machinery_ok else 'BROKEN'} "
          f"(skills={len(bank)}, gate present={bool(gate)})")
    print(f"  report       : {path}")
    print(f"\nVERDICT: {'PASS -- self-evolve verified on held-out Silo' if passed else 'FAIL -- no verified improvement'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
