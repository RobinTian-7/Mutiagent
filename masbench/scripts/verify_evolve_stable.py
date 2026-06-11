"""PASS/FAIL check: does self-evolution STABLY beat the cold baseline as it evolves?

Stronger than verify_evolve.py (one-shot paired delta): this runs R accumulating
evolution rounds and requires the held-out score to rise above and STAY above the
same-pipeline cold baseline.

Protocol (honest by construction):
  1. Disjoint case split: last ``holdout_frac`` of cases = TEST, never evolved on.
  2. Cold BASELINE: the same planner pipeline with an EMPTY bank and no motif
     prior, run once per (test case, eval seed) pair. Memory is the ONLY
     difference between arms.
  3. R rounds of ``run_evolution`` on TRAIN (bank + motif ACCUMULATE across
     rounds via ``initial_skills``); after each round, paired eval of the
     evolved bank on the same (case, seed) grid.
  4. PASS iff for EVERY one of the last ``--stable-rounds`` rounds:
       mean_em[round] >= mean_em[baseline] + ``--delta-min``  AND
       (evolved-only wins) - (baseline-only wins) >= ``--win-margin``.
     One lucky round cannot pass; a curve that rises then collapses cannot pass.

Exit codes: 0 verified stable improvement; 1 not verified; 2 aborted (budget).
Offline (``--llm fake``) Silo is topology-invariant -> MUST exit 1 ("machinery
OK"). This script is the frozen acceptance target: fixes go into the pipeline,
never into this file.
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
from masbench.curve import (
    _bank_and_motif,
    _bounded,
    _evolved_planner_mode,
    _merge_motif,
    _split_cases,
)
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
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--levels", nargs="+", default=["I"])
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--rounds", type=int, default=3,
                   help="accumulating self-evolution rounds (the curve's x-axis)")
    p.add_argument("--stable-rounds", type=int, default=2,
                   help="the LAST K rounds must ALL dominate the baseline")
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=list(range(11, 19)),
                   help="held-out eval seeds; MUST be disjoint from train/val seeds")
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--graph-validation-seeds", type=int, default=0)
    p.add_argument("--use-llm-insights", action="store_true")
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--delta-min", type=float, default=0.05)
    p.add_argument("--win-margin", type=int, default=2)
    p.add_argument("--max-runs", type=int, default=900,
                   help="abort before spending if the planned LLM run count exceeds this")
    p.add_argument("--out", default="runs/verify_evolve_stable")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.stable_rounds > args.rounds:
        raise SystemExit("--stable-rounds cannot exceed --rounds")
    overlap = set(args.eval_seeds) & (set(args.train_seeds) | set(args.val_seeds))
    if overlap:
        raise SystemExit(f"eval seeds must be disjoint from train/val; overlap={sorted(overlap)}")

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
    pairs = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]

    # ---- budget guard (before any spend) ----
    evo_per_round = len(train_cases) * 3 * (len(args.train_seeds) + len(args.val_seeds))
    planned = args.rounds * evo_per_round + (1 + args.rounds) * len(pairs)
    print(f"plan: TRAIN={train_cases} TEST={test_cases} rounds={args.rounds}")
    print(f"plan: ~{planned} protocol runs (n={args.n_agents}, workers={args.workers})")
    if planned > args.max_runs:
        print(f"ABORT: planned {planned} > --max-runs {args.max_runs}")
        return 2

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))
    generate = cfg.evolved_mode in ("graph_generate", "select_then_refine")
    eval_cfg = replace(cfg, planner_mode="graph_generate" if generate else "topology_select")

    def eval_grid(bank: SkillBank, motif) -> list[float]:
        def one(task):
            inst, seed = task
            row = _run_one(inst, eval_cfg, objective=objective, skill_bank=bank,
                           seed=seed, llm_client=client, motif_stats=motif)
            return float(row.get("ExactMatchRate", 0.0))
        with ThreadPoolExecutor(max_workers=min(args.workers, len(pairs))) as ex:
            return list(ex.map(one, pairs))

    t0 = time.monotonic()
    print("baseline: cold pipeline (empty bank, no motif prior) on the held-out grid ...")
    base = eval_grid(SkillBank(), None)
    base_mean = sum(base) / len(base)
    print(f"baseline mean exact-match = {base_mean * 100:.1f}%  ({len(pairs)} pairs)")

    bank, motif = SkillBank(), {}
    rounds_out = []
    for r in range(1, args.rounds + 1):
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[args.n_agents],
            train_seeds=args.train_seeds, val_seeds=args.val_seeds,
            cfg=evo_cfg, levels=args.levels, llm_client=client,
            workers=args.workers, progress=True,
            initial_skills=[s.model_dump(mode="json") for s in bank],
        )
        new_bank, new_motif = _bank_and_motif(summ)
        bank, motif = new_bank, _merge_motif(motif, new_motif)
        scores = eval_grid(bank, motif)
        mean = sum(scores) / len(scores)
        wins = sum(1 for s, b in zip(scores, base) if s > b)
        losses = sum(1 for s, b in zip(scores, base) if s < b)
        ok = (mean >= base_mean + args.delta_min) and ((wins - losses) >= args.win_margin)
        rounds_out.append({
            "round": r, "mean": mean, "delta": mean - base_mean,
            "wins": wins, "losses": losses, "dominates": ok,
            "n_skills": len(bank), "gate": summ.get("gate"),
        })
        el = int(time.monotonic() - t0)
        print(f"round {r}/{args.rounds}: evolved={mean * 100:5.1f}% "
              f"(delta={100 * (mean - base_mean):+.1f}pp, wins={wins}, losses={losses}, "
              f"skills={len(bank)}) {'DOMINATES' if ok else 'below'}  [{el // 60}:{el % 60:02d}]")

    tail = rounds_out[-args.stable_rounds:]
    machinery_ok = len(bank) > 0
    passed = machinery_ok and all(pt["dominates"] for pt in tail)

    report = {
        "mode": cfg.evolved_mode, "n_agents": args.n_agents,
        "train_cases": train_cases, "test_cases": test_cases,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds, "n_pairs": len(pairs),
        "baseline_mean": base_mean, "rounds": rounds_out,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin,
                     "stable_rounds": args.stable_rounds},
        "machinery_ok": machinery_ok, "passed": passed,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"stable_{cfg.evolved_mode}_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))

    print(f"\nbaseline={base_mean * 100:.1f}%  |  curve: " + "  ".join(
        f"r{pt['round']}={pt['mean'] * 100:.0f}%{'*' if pt['dominates'] else ''}"
        for pt in rounds_out))
    print(f"need: last {args.stable_rounds} rounds ALL >= baseline+{args.delta_min * 100:.0f}pp "
          f"with win margin >= {args.win_margin}   (* = dominates)")
    print(f"report: {path}")
    print(f"\nVERDICT: {'PASS -- evolution stably beats the cold baseline' if passed else 'FAIL -- no stable verified improvement'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
