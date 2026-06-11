"""Cheap 2-arm directional screener for the dev loop (NOT a judge).

Runs R evolution rounds (evidence-cache-aware) and a paired eval of evolved vs
ONE baseline arm on the held-out tail with few seeds. Prints delta +
discordants and always exits 0: the frozen ``verify_beats_baselines.py`` stays
the sole verdict authority -- this exists so a method iteration costs ~$0.2
to direction-check instead of ~$0.9 for the full 4-arm judge.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.curve import _bank_and_motif, _bounded, _evolved_planner_mode, _merge_motif, _split_cases
from masbench.engine import _build_llm_client, run_fixed_protocol
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
    p.add_argument("--baseline", default="select",
                   choices=["select", "graphgen", "fixed"],
                   help="single comparison arm (fixed needs --fixed-topology)")
    p.add_argument("--fixed-topology", default="one_peer_exponential_dag_star")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--levels", nargs="+", default=["I"])
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=[11, 12, 13, 14, 15])
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--graph-validation-seeds", type=int, default=0)
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default="runs/dev_screen")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = RunConfig(
        benchmark="silo_bench", objective=args.objective,
        merge_mode=args.merge_mode, init_mode=args.init_mode,
        llm_provider=args.llm, model_name=args.model_name,
        request_timeout=args.request_timeout, evolved_mode=args.evolved_mode,
        num_graph_candidates=args.graphgen_candidates, n_agents=args.n_agents,
        graph_validation_seeds=args.graph_validation_seeds,
    )
    adapter = SiloBenchAdapter(args.benchmarks_dir)
    instances = list(adapter.iter_instances(
        levels=args.levels, agent_counts=[args.n_agents], cases=args.cases))
    all_cases = sorted({i.case_id for i in instances})
    train_cases, test_cases = _split_cases(all_cases, args.holdout_frac)
    test_instances = [i for i in instances if i.case_id in set(test_cases)]

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))
    generate = cfg.evolved_mode in ("graph_generate", "select_then_refine")
    eval_cfg = replace(cfg, planner_mode="graph_generate" if generate else "topology_select")

    bank, motif = SkillBank(), {}
    for r in range(1, args.rounds + 1):
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[args.n_agents],
            train_seeds=args.train_seeds, val_seeds=args.val_seeds,
            cfg=evo_cfg, levels=args.levels, llm_client=client,
            workers=args.workers, progress=True,
            initial_skills=[s.model_dump(mode="json") for s in bank] or None,
        )
        bank, new_motif = _bank_and_motif(summ)
        motif = _merge_motif(motif, new_motif)
        print(f"screen round {r}/{args.rounds}: skills={len(bank)} gate={summ.get('gate')}")

    pair_keys = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]

    def _arm(task) -> float | None:
        inst, seed, arm = task
        try:
            if arm == "fixed":
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=args.fixed_topology,
                    llm_client=client)
                return 1.0 if score.success else 0.0
            if arm == "evolved":
                row = _run_one(inst, eval_cfg, objective=objective, skill_bank=bank,
                               seed=seed, llm_client=client, motif_stats=motif or None)
            elif arm == "select":
                row = _run_one(inst, replace(cfg, planner_mode="topology_select"),
                               objective=objective, skill_bank=SkillBank(), seed=seed,
                               llm_client=client)
            else:
                row = _run_one(inst, replace(cfg, planner_mode="graph_generate"),
                               objective=objective, skill_bank=SkillBank(), seed=seed,
                               llm_client=client)
            return float(row.get("ExactMatchRate", 0.0))
        except Exception as exc:  # noqa: BLE001
            print(f"  [screen] {arm} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            return None

    tasks = [(inst, seed, arm) for (inst, seed) in pair_keys for arm in ("evolved", args.baseline)]
    with ThreadPoolExecutor(max_workers=min(args.workers, max(1, len(tasks)))) as ex:
        flat = list(ex.map(_arm, tasks))
    pairs = []
    for k, (inst, seed) in enumerate(pair_keys):
        e, b = flat[2 * k], flat[2 * k + 1]
        if e is None or b is None:
            continue
        pairs.append({"case_id": inst.case_id, "seed": seed, "evolved": e, "baseline": b})

    n = len(pairs)
    mean_e = sum(p["evolved"] for p in pairs) / n if n else 0.0
    mean_b = sum(p["baseline"] for p in pairs) / n if n else 0.0
    wins = sum(1 for p in pairs if p["evolved"] > p["baseline"])
    losses = sum(1 for p in pairs if p["evolved"] < p["baseline"])
    report = {
        "screening_only": True, "baseline": args.baseline, "mode": cfg.evolved_mode,
        "n_agents": args.n_agents, "rounds": args.rounds,
        "train_cases": train_cases, "test_cases": test_cases,
        "eval_seeds": args.eval_seeds, "n_pairs": n,
        "mean_evolved": mean_e, "mean_baseline": mean_b, "delta": mean_e - mean_b,
        "evolved_only_wins": wins, "baseline_only_wins": losses,
        "n_skills": len(bank), "pairs": pairs,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"screen_{args.baseline}_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\nSCREEN (not a verdict): evolved {mean_e * 100:.1f}% vs {args.baseline} "
          f"{mean_b * 100:.1f}%  delta={100 * (mean_e - mean_b):+.1f}pp "
          f"wins={wins}/{losses} over {n} pairs -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
