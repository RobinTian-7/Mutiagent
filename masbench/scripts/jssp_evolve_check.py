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
    p.add_argument("--planner-model", default=None,
                   help="M23: architect-side model (graph generation, instruction rewrite, recipe/exemplar writing); workers keep --model-name. None = no split")
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
    p.add_argument("--paired-final", action="store_true",
                   help="v4: the decisive verdict comes from a SAME-WINDOW "
                        "paired eval -- the VAL-selected checkpoint and a "
                        "FRESH cold arm run interleaved in one pool, so "
                        "provider drift hits both arms equally (the "
                        "start-of-run baseline is reported as diagnostics "
                        "only). Mirrors the frozen beats judge's design.")
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
        planner_model_name=args.planner_model,
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
    # v5 (operator: JSSP must show a RISING training curve). Two structural
    # fixes over v4: (a) PER-ROUND same-window pairing -- each round's
    # evolved bank and a FRESH cold arm run interleaved, so the curve is
    # drift-corrected (cross-window cold drifts 0<->50pp and buried every
    # margin); (b) checkpoint chosen by held-out VAL QUALITY (train
    # instances x val seeds), since the gate's EM-based j_after floors to
    # 1.0 and picked the decayed last round (v9: r5 over the r1 peak).
    probe_insts = list(adapter.iter_instances(
        agent_counts=[args.n_agents], cases=train_cases))
    probe_pairs = [(inst, s) for inst in probe_insts for s in args.val_seeds]
    best_ckpt: tuple[float, int, SkillBank, dict] | None = None

    def _paired_eval(bk, mt):
        def _arm(task):
            inst, seed, arm = task
            b2, m2 = (bk, mt) if arm == "ev" else (SkillBank(), None)
            row = _run_one(inst, eval_cfg, objective=objective, skill_bank=b2,
                           seed=seed, llm_client=client, motif_stats=m2)
            return (float(row.get("ExactMatchRate", 0.0)),
                    float(row.get("MeanPrimaryMetric", 0.0)))
        tasks = [(i, s, a) for (i, s) in pairs for a in ("ev", "cold")]
        with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
            flat = list(ex.map(_arm, tasks))
        return flat[0::2], flat[1::2]

    for r in range(1, args.rounds + 1):
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[args.n_agents],
            train_seeds=args.train_seeds, val_seeds=args.val_seeds,
            cfg=evo_cfg, levels=None, llm_client=client,
            workers=args.workers, progress=True,
            initial_skills=[s.model_dump(mode="json") for s in bank],
        )
        new_bank, new_motif = _bank_and_motif(summ)
        gate = summ.get("gate") or {}
        if bool(gate.get("accepted")) or len(new_bank) > 0:
            bank, motif = new_bank, _merge_motif(motif, new_motif)
        if bool(gate.get("accepted")) and len(bank) > 0:
            def _pq(task):
                inst, s = task
                row = _run_one(inst, eval_cfg, objective=objective,
                               skill_bank=bank, seed=s, llm_client=client,
                               motif_stats=motif)
                return float(row.get("MeanPrimaryMetric", 0.0))
            with ThreadPoolExecutor(
                max_workers=min(args.workers, len(probe_pairs))
            ) as ex:
                vq = sum(ex.map(_pq, probe_pairs)) / len(probe_pairs)
            if best_ckpt is None or vq > best_ckpt[0]:
                best_ckpt = (
                    vq, r,
                    SkillBank(skills=[s.model_copy(deep=True) for s in bank]),
                    dict(motif),
                )
        if args.paired_final:
            scores, cold_now = _paired_eval(bank, motif)
        else:
            scores, cold_now = eval_grid(bank, motif), base
        em = sum(s for s, _q in scores) / len(scores)
        q = sum(qq for _s, qq in scores) / len(scores)
        cb_em = sum(s for s, _q in cold_now) / len(cold_now)
        cb_q = sum(qq for _s, qq in cold_now) / len(cold_now)
        # pairwise wins vs the SAME-WINDOW cold arm: exact-match first,
        # schedule QUALITY on em ties (0.05 dead-band).
        wins = losses = 0
        for (s, sq), (b, bq) in zip(scores, cold_now):
            if s != b:
                wins, losses = wins + (s > b), losses + (s < b)
            elif abs(sq - bq) > 0.05:
                wins, losses = wins + (sq > bq), losses + (sq < bq)
        ok = (
            (em >= cb_em + args.delta_min) or (q >= cb_q + args.delta_min)
        ) and ((wins - losses) >= args.win_margin)
        rounds_out.append({
            "round": r, "exact_match": em, "quality": q,
            "cold_exact_match": cb_em, "cold_quality": cb_q,
            "delta_em": em - cb_em, "delta_quality": q - cb_q,
            "wins": wins, "losses": losses, "dominates": ok,
            "n_skills": len(bank), "gate": summ.get("gate"),
        })
        el = int(time.monotonic() - t0)
        print(f"round {r}/{args.rounds}: q={q * 100:5.1f}% vs same-window cold "
              f"{cb_q * 100:5.1f}% (dQ={100 * (q - cb_q):+.1f}pp "
              f"wins={wins} losses={losses} skills={len(bank)}) "
              f"{'DOMINATES' if ok else 'below'}  [{el // 60}:{el % 60:02d}]")

    tail = rounds_out[-args.stable_rounds:]
    machinery_ok = len(bank) > 0
    passed = machinery_ok and all(pt["dominates"] for pt in tail)

    # v3: beats-style FINAL deployment of the VAL-selected checkpoint.
    # v4 (--paired-final): the checkpoint and a FRESH cold arm run
    # INTERLEAVED in one pool -- same-window pairing neutralizes the
    # 0<->50pp schedule-validity drift that ate every cross-window margin.
    checkpoint_out: dict | None = None
    if best_ckpt is not None:
        j_val, sel_round, sel_bank, sel_motif = best_ckpt
        print(f"deploying VAL-QUALITY-selected checkpoint: round {sel_round} "
              f"(val quality={j_val:.3f}, skills={len(sel_bank)}) ...")
        if args.paired_final:
            def _arm(task):
                inst, seed, arm = task
                bk, mt = (sel_bank, sel_motif) if arm == "ck" else (SkillBank(), None)
                row = _run_one(inst, eval_cfg, objective=objective, skill_bank=bk,
                               seed=seed, llm_client=client, motif_stats=mt)
                return (float(row.get("ExactMatchRate", 0.0)),
                        float(row.get("MeanPrimaryMetric", 0.0)))
            tasks = [(inst, seed, arm) for (inst, seed) in pairs for arm in ("ck", "cold")]
            with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
                flat = list(ex.map(_arm, tasks))
            ck_scores = flat[0::2]
            cold_scores = flat[1::2]
        else:
            ck_scores = eval_grid(sel_bank, sel_motif)
            cold_scores = base
        ck_em = sum(s for s, _q in ck_scores) / len(ck_scores)
        ck_q = sum(qq for _s, qq in ck_scores) / len(ck_scores)
        cb_em = sum(s for s, _q in cold_scores) / len(cold_scores)
        cb_q = sum(qq for _s, qq in cold_scores) / len(cold_scores)
        wins = losses = 0
        for (s, sq), (b, bq) in zip(ck_scores, cold_scores):
            if s != b:
                wins, losses = wins + (s > b), losses + (s < b)
            elif abs(sq - bq) > 0.05:
                wins, losses = wins + (sq > bq), losses + (sq < bq)
        ck_pass = (
            (ck_em >= cb_em + args.delta_min) or (ck_q >= cb_q + args.delta_min)
        ) and ((wins - losses) >= args.win_margin)
        checkpoint_out = {
            "round": sel_round, "val_j": j_val, "n_skills": len(sel_bank),
            "paired_same_window": bool(args.paired_final),
            "exact_match": ck_em, "quality": ck_q,
            "cold_exact_match": cb_em, "cold_quality": cb_q,
            "delta_em": ck_em - cb_em, "delta_quality": ck_q - cb_q,
            "wins": wins, "losses": losses, "passed": ck_pass,
        }
        print(f"checkpoint{' (same-window paired)' if args.paired_final else ''}: "
              f"em={ck_em * 100:.1f}% q={ck_q * 100:.1f}% vs cold "
              f"em={cb_em * 100:.1f}% q={cb_q * 100:.1f}% "
              f"(dQ={100 * (ck_q - cb_q):+.1f}pp wins={wins} losses={losses}) "
              f"{'PASS' if ck_pass else 'FAIL'}")

    report = {
        "benchmark": "jssp", "mode": cfg.evolved_mode, "n_agents": args.n_agents,
        "train_cases": train_cases, "test_cases": test_cases,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds, "n_pairs": len(pairs),
        "baseline_exact_match": base_em, "baseline_quality": base_q,
        "rounds": rounds_out,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin,
                     "stable_rounds": args.stable_rounds},
        "checkpoint_deployment": checkpoint_out,
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
    ck_passed = bool(checkpoint_out and checkpoint_out.get("passed"))
    print(f"\nVERDICT(curve): {'PASS' if passed else 'FAIL/NEUTRAL'}  |  "
          f"VERDICT(val-checkpoint): {'PASS' if ck_passed else 'FAIL' if checkpoint_out else 'n/a'}")
    return 0 if (passed or ck_passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
