"""Phase-2 frozen judge: does R-round self-evolution beat EVERY baseline?

Protocol (honest by construction):
  1. Disjoint case split (lexicographic tail of --cases = TEST, as in phase 1).
  2. Evolve for ``--rounds`` R (>=1) rounds on TRAIN only, ACCUMULATING the
     skill bank + motif stats across rounds (the "after several evolutions"
     state is what gets judged).
  3. ``fixed_best_on_train``: every topology in ``--fixed-topologies`` runs on
     the TRAIN cases x train seeds; the best mean exact-match (lexicographic
     tiebreak) is selected -- the strongest constant named-topology policy
     choosable WITHOUT test data. Oracle-on-test is deliberately NOT a baseline.
  4. Paired eval on TEST: for each (case, seed), FOUR arms run with identical
     conditions: evolved (R-round bank, deployed mode), select (empty bank),
     graphgen (empty bank, cold generation), fixed (the train-picked topology).
     A pair where ANY arm errors is DROPPED whole (symmetric), and counted.
  5. PASS iff, against EACH of the three baselines: paired mean delta
     (evolved - baseline) >= --delta-min AND (evolved-only wins - baseline-only
     wins) >= --win-margin.
  6. Rounds STABILITY is a separate reported verdict (not the exit code): with
     --curves-json (a ``masbench curve`` output), the last 3 rounds' scores
     must all exceed every baseline recorded in that file.

Exit code: 0 = verified win over all baselines, 1 = not verified, 2 = aborted
(budget guard). Offline (--llm fake) Silo is topology-invariant, so this MUST
exit 1 with "machinery OK"; that is the harness smoke test.
This file is the agreed phase-2 verification target -- once frozen, fixes go
into the pipeline, never into this script.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

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
from masbench.engine import _build_llm_client, run_fixed_protocol
from masbench.evolve import _run_one, evolution_objective_spec, run_evolution

BASELINES = ("select", "graphgen", "fixed")


def _pick_fixed_best(rows: list[dict[str, Any]]) -> str:
    """Argmax mean exact over per-run rows {topology, exact}; ties -> lexicographic."""
    by_topology: dict[str, list[float]] = {}
    for row in rows:
        by_topology.setdefault(str(row["topology"]), []).append(float(row["exact"]))
    means = {t: sum(v) / len(v) for t, v in by_topology.items() if v}
    best = max(means.values())
    return min(t for t, m in means.items() if m == best)


def _verdict(
    pairs: list[dict[str, Any]], *, delta_min: float, win_margin: int
) -> dict[str, Any]:
    """Paired verdict vs EVERY baseline; overall pass requires all three."""
    n = len(pairs)
    means = {
        arm: (sum(float(p[arm]) for p in pairs) / n if n else 0.0)
        for arm in ("evolved", *BASELINES)
    }
    per_baseline: dict[str, Any] = {}
    for b in BASELINES:
        wins = sum(1 for p in pairs if p["evolved"] > p[b])
        losses = sum(1 for p in pairs if p["evolved"] < p[b])
        delta = means["evolved"] - means[b]
        per_baseline[b] = {
            "delta": delta,
            "evolved_only_wins": wins,
            "baseline_only_wins": losses,
            "passed": bool(delta >= delta_min and (wins - losses) >= win_margin),
        }
    return {
        "arm_means": means,
        "per_baseline": per_baseline,
        "passed": bool(n > 0 and all(v["passed"] for v in per_baseline.values())),
    }


def _stable_rounds(curves: dict[str, Any], k: int = 3) -> bool:
    """Last k rounds of a ``masbench curve`` rounds_curve all strictly above
    every baseline recorded in the file."""
    rounds = curves.get("rounds_curve") or []
    baselines = curves.get("baselines") or {}
    if len(rounds) < k or not baselines:
        return False
    bar = max(float(v) for v in baselines.values())
    return all(float(r["score"]) > bar for r in rounds[-k:])


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
    p.add_argument("--rounds", type=int, default=3,
                   help="evolution rounds R (bank+motif accumulate across rounds)")
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--levels", nargs="+", default=["I"])
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=list(range(11, 19)))
    p.add_argument("--fixed-topologies", nargs="+",
                   default=["tree", "mesh_star", "one_peer_exponential_dag_star", "chain"])
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--graph-validation-seeds", type=int, default=0)
    p.add_argument("--use-llm-insights", action="store_true")
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--delta-min", type=float, default=0.05)
    p.add_argument("--win-margin", type=int, default=2)
    p.add_argument("--max-runs", type=int, default=600,
                   help="abort before spending if the planned LLM run count exceeds this")
    p.add_argument("--curves-json", default=None,
                   help="optional masbench-curve JSON for the rounds-stability verdict")
    p.add_argument("--out", default="runs/verify_beats_baselines")
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
    train_instances = [i for i in instances if i.case_id in set(train_cases)]

    # ---- budget guard (before any spend) ----
    n_pairs = len(test_instances) * len(args.eval_seeds)
    half = max(1, len(train_cases) // 2)
    evo_per_round = (
        half * 3 * len(args.train_seeds)
        + half * 3 * len(args.val_seeds)
        + 2 * half * len(args.val_seeds)  # generation gate, both arms
    )
    fixed_sel_runs = len(args.fixed_topologies) * len(train_instances) * len(args.train_seeds)
    planned = args.rounds * evo_per_round + fixed_sel_runs + 4 * n_pairs
    print(f"plan: TRAIN={train_cases} TEST={test_cases} rounds={args.rounds}")
    print(f"plan: ~{args.rounds}x{evo_per_round} evolution + {fixed_sel_runs} fixed-selection "
          f"+ {4 * n_pairs} paired eval = ~{planned} protocol runs (n={args.n_agents})")
    if planned > args.max_runs:
        print(f"ABORT: planned {planned} > --max-runs {args.max_runs}")
        return 2

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))
    generate = cfg.evolved_mode in ("graph_generate", "select_then_refine")
    eval_cfg = replace(cfg, planner_mode="graph_generate" if generate else "topology_select")

    # ---- 1. R rounds of evolution on TRAIN only (accumulating) ----
    t0 = time.monotonic()
    bank, motif = SkillBank(), {}
    rounds_log: list[dict[str, Any]] = []
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
        rounds_log.append({
            "round": r, "n_skills": len(bank), "gate": summ.get("gate"),
            "skill_ids": summ.get("skill_ids_after"),
            "rejected_skill_ids": summ.get("rejected_skill_ids"),
        })
        print(f"round {r}/{args.rounds}: skills={len(bank)} gate={summ.get('gate')}")

    # ---- 2. fixed_best_on_train (train data only) ----
    fixed_tasks = [
        (inst, topo, seed)
        for topo in args.fixed_topologies
        for inst in train_instances
        for seed in args.train_seeds
    ]

    def _fixed_train(task) -> dict[str, Any]:
        inst, topo, seed = task
        try:
            score = run_fixed_protocol(
                inst, replace(cfg, seed=seed), topology=topo, llm_client=client)
            exact = 1.0 if score.success else 0.0
        except Exception as exc:  # noqa: BLE001 - a failed selection run scores 0
            print(f"  [fixed-select] {topo} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            exact = 0.0
        return {"topology": topo, "exact": exact}

    with ThreadPoolExecutor(max_workers=min(args.workers, len(fixed_tasks))) as ex:
        fixed_rows = list(ex.map(_fixed_train, fixed_tasks))
    fixed_best = _pick_fixed_best(fixed_rows)
    fixed_train_means = {
        t: sum(r["exact"] for r in fixed_rows if r["topology"] == t)
        / max(1, sum(1 for r in fixed_rows if r["topology"] == t))
        for t in args.fixed_topologies
    }
    print(f"fixed_best_on_train: {fixed_best} (train means: {fixed_train_means}) "
          f"({time.monotonic() - t0:.0f}s)")

    # ---- 3. paired 4-arm eval on TEST ----
    pair_keys = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]

    def _arm(task) -> float | None:
        inst, seed, arm = task
        try:
            if arm == "fixed":
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=fixed_best, llm_client=client)
                return 1.0 if score.success else 0.0
            if arm == "evolved":
                row = _run_one(
                    inst, eval_cfg, objective=objective, skill_bank=bank, seed=seed,
                    llm_client=client, motif_stats=motif or None, diag_phase="")
            elif arm == "select":
                row = _run_one(
                    inst, replace(cfg, planner_mode="topology_select"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            else:  # graphgen
                row = _run_one(
                    inst, replace(cfg, planner_mode="graph_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            return float(row.get("ExactMatchRate", 0.0))
        except Exception as exc:  # noqa: BLE001 - drop the whole pair, symmetric
            print(f"  [eval] {arm} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            return None

    arms = ("evolved", *BASELINES)
    tasks = [(inst, seed, arm) for (inst, seed) in pair_keys for arm in arms]
    with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
        flat = list(ex.map(_arm, tasks))
    pairs: list[dict[str, Any]] = []
    dropped = 0
    for k, (inst, seed) in enumerate(pair_keys):
        vals = flat[4 * k: 4 * k + 4]
        if any(v is None for v in vals):
            dropped += 1
            continue
        pairs.append({
            "case_id": inst.case_id, "seed": seed,
            **{arm: vals[i] for i, arm in enumerate(arms)},
        })

    # ---- 4. verdict ----
    verdict = _verdict(pairs, delta_min=args.delta_min, win_margin=args.win_margin)
    machinery_ok = bool(
        len(bank) > 0
        and len(rounds_log) == args.rounds
        and all(r.get("gate") for r in rounds_log)
    )
    stable_rounds_ok = None
    if args.curves_json:
        stable_rounds_ok = _stable_rounds(json.loads(Path(args.curves_json).read_text()))

    report = {
        "mode": cfg.evolved_mode, "n_agents": args.n_agents, "rounds": args.rounds,
        "train_cases": train_cases, "test_cases": test_cases,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds,
        "fixed_topologies": args.fixed_topologies,
        "fixed_best_topology": fixed_best, "fixed_train_means": fixed_train_means,
        "n_pairs": len(pairs), "dropped_pairs": dropped,
        "arm_means": verdict["arm_means"], "per_baseline": verdict["per_baseline"],
        "rounds_log": rounds_log, "n_skills": len(bank),
        "machinery_ok": machinery_ok, "stable_rounds_ok": stable_rounds_ok,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin},
        "passed": verdict["passed"], "pairs": pairs,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"verify_beats_baselines_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))

    means = verdict["arm_means"]
    print(f"\npaired held-out exact-match over {len(pairs)} (case,seed) pairs "
          f"({dropped} dropped):")
    print(f"  evolved (R={args.rounds}) : {means['evolved'] * 100:5.1f}%")
    for b in BASELINES:
        v = verdict["per_baseline"][b]
        label = f"{b}={fixed_best}" if b == "fixed" else b
        print(f"  vs {label:<35}: {means[b] * 100:5.1f}%  delta={v['delta'] * 100:+.1f}pp "
              f"wins={v['evolved_only_wins']}/{v['baseline_only_wins']} "
              f"{'PASS' if v['passed'] else 'fail'}")
    print(f"  machinery : {'OK' if machinery_ok else 'BROKEN'} "
          f"(skills={len(bank)}, rounds={len(rounds_log)})")
    if stable_rounds_ok is not None:
        print(f"  rounds stability (last 3 > all curve baselines): "
              f"{'OK' if stable_rounds_ok else 'NOT MET'}")
    print(f"  report    : {path}")
    print(f"\nVERDICT: {'PASS -- evolved beats ALL baselines on held-out Silo' if verdict['passed'] else 'FAIL -- not verified against all baselines'}")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
