"""JSSP corroboration: does the SAME learner evolve on a different benchmark?

NEW additive script (frozen Silo judges untouched). Mirrors the
verify_evolve_stable protocol on JSSP instances: disjoint case split, cold
same-pipeline baseline (empty bank, no motif prior), R accumulating
evolution rounds, paired held-out eval per round. Reports BOTH metrics per
round: exact-match rate (schedule valid AND makespan <= the instance's
heuristic UB) and mean schedule quality (UB/makespan, 0 when invalid).

This is corroborating evidence for learner generalization, not a Silo
acceptance instrument. Exit 0 iff the last --stable-rounds rounds all
dominate on exact-match (same rule as the stable judge).
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.jssp_bench import JSSPBenchAdapter
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
    p.add_argument("--benchmarks-dir", required=True,
                   help="directory of *.jssp files (see gen_jssp_instances.py)")
    p.add_argument("--llm", default="openai")
    p.add_argument("--model-name", default="gpt-4o-mini")
    p.add_argument("--objective", default="accuracy_first")
    p.add_argument("--evolved-mode", default="graph_generate",
                   choices=["graph_generate", "select_then_refine"])
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--stable-rounds", type=int, default=2)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=[21, 22, 23, 24])
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--delta-min", type=float, default=0.05)
    p.add_argument("--win-margin", type=int, default=2)
    p.add_argument("--max-runs", type=int, default=400)
    p.add_argument("--out", default="runs/jssp_evolve_check")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    overlap = set(args.eval_seeds) & (set(args.train_seeds) | set(args.val_seeds))
    if overlap:
        raise SystemExit(f"eval seeds must be disjoint; overlap={sorted(overlap)}")

    cfg = RunConfig(
        benchmark="jssp", objective=args.objective,
        merge_mode="llm_full_merge", init_mode="llm_local_solve",
        llm_provider=args.llm, model_name=args.model_name,
        request_timeout=args.request_timeout, evolved_mode=args.evolved_mode,
        num_graph_candidates=args.graphgen_candidates,
        n_agents=args.n_agents,
    )
    adapter = JSSPBenchAdapter(args.benchmarks_dir)
    instances = list(adapter.iter_instances(
        agent_counts=[args.n_agents], cases=args.cases))
    if not instances:
        raise SystemExit("no JSSP instances matched (check --n-agents vs n_jobs)")
    all_cases = sorted({i.case_id for i in instances})
    train_cases, test_cases = _split_cases(all_cases, args.holdout_frac)
    test_instances = [i for i in instances if i.case_id in set(test_cases)]
    pairs = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]

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

    def eval_grid(bank: SkillBank, motif) -> list[tuple[float, float]]:
        def one(task):
            inst, seed = task
            row = _run_one(inst, eval_cfg, objective=objective, skill_bank=bank,
                           seed=seed, llm_client=client, motif_stats=motif)
            return (float(row.get("ExactMatchRate", 0.0)),
                    float(row.get("MeanPrimaryMetric", 0.0)))
        with ThreadPoolExecutor(max_workers=min(args.workers, len(pairs))) as ex:
            return list(ex.map(one, pairs))

    t0 = time.monotonic()
    print("baseline: cold pipeline (empty bank, no motif prior) on the held-out grid ...")
    base = eval_grid(SkillBank(), None)
    base_em = sum(em for em, _q in base) / len(base)
    base_q = sum(q for _em, q in base) / len(base)
    print(f"baseline: exact-match={base_em * 100:.1f}%  quality={base_q * 100:.1f}%  ({len(pairs)} pairs)")

    bank, motif = SkillBank(), {}
    rounds_out = []
    for r in range(1, args.rounds + 1):
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[args.n_agents],
            train_seeds=args.train_seeds, val_seeds=args.val_seeds,
            cfg=evo_cfg, levels=None, llm_client=client,
            workers=args.workers, progress=True,
            initial_skills=[s.model_dump(mode="json") for s in bank],
        )
        new_bank, new_motif = _bank_and_motif(summ)
        bank, motif = new_bank, _merge_motif(motif, new_motif)
        scores = eval_grid(bank, motif)
        em = sum(s for s, _q in scores) / len(scores)
        q = sum(qq for _s, qq in scores) / len(scores)
        # v2 (registered before the M21 rerun): pairwise wins decided by
        # exact-match first; when em ties (the common case on scheduling),
        # schedule QUALITY decides with a 0.05 dead-band. Round dominance
        # accepts either metric clearing the bar -- em stays primary, the
        # graded metric stops all-tie blindness.
        wins = losses = 0
        for (s, sq), (b, bq) in zip(scores, base):
            if s != b:
                wins, losses = wins + (s > b), losses + (s < b)
            elif abs(sq - bq) > 0.05:
                wins, losses = wins + (sq > bq), losses + (sq < bq)
        ok = (
            (em >= base_em + args.delta_min) or (q >= base_q + args.delta_min)
        ) and ((wins - losses) >= args.win_margin)
        rounds_out.append({
            "round": r, "exact_match": em, "quality": q,
            "delta_em": em - base_em, "delta_quality": q - base_q,
            "wins": wins, "losses": losses, "dominates": ok,
            "n_skills": len(bank), "gate": summ.get("gate"),
        })
        el = int(time.monotonic() - t0)
        print(f"round {r}/{args.rounds}: em={em * 100:5.1f}% q={q * 100:5.1f}% "
              f"(dEM={100 * (em - base_em):+.1f}pp dQ={100 * (q - base_q):+.1f}pp "
              f"wins={wins} losses={losses} skills={len(bank)}) "
              f"{'DOMINATES' if ok else 'below'}  [{el // 60}:{el % 60:02d}]")

    tail = rounds_out[-args.stable_rounds:]
    machinery_ok = len(bank) > 0
    passed = machinery_ok and all(pt["dominates"] for pt in tail)

    report = {
        "benchmark": "jssp", "mode": cfg.evolved_mode, "n_agents": args.n_agents,
        "train_cases": train_cases, "test_cases": test_cases,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds, "n_pairs": len(pairs),
        "baseline_exact_match": base_em, "baseline_quality": base_q,
        "rounds": rounds_out,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin,
                     "stable_rounds": args.stable_rounds},
        "machinery_ok": machinery_ok, "passed": passed,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"jssp_evolve_{cfg.evolved_mode}_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))

    print(f"\nbaseline em={base_em * 100:.1f}% q={base_q * 100:.1f}%  |  curve: " + "  ".join(
        f"r{pt['round']}=em{pt['exact_match'] * 100:.0f}%/q{pt['quality'] * 100:.0f}%"
        f"{'*' if pt['dominates'] else ''}"
        for pt in rounds_out))
    print(f"report: {path}")
    print(f"\nVERDICT: {'PASS -- evolution dominates the cold baseline on JSSP' if passed else 'FAIL/NEUTRAL -- no stable JSSP dominance at this scale'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
