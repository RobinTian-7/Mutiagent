"""Operator ultimate-goal check: gen-mode supremacy over the full bar stack.

ADDITIVE instrument (frozen judges untouched). Operator goal (2026-06-12):
gen, after multi-round evolution, must STABLY dominate (1) the cold
baseline, (2) the best fixed topology where "best" is PER-CASE customized,
(3) select; and ideally (4) refine -- with refine at full strength (its own
independent evolution, never weakened).

Arms on the held-out grid (paired per case x seed):
  gen          R-round gen-mode evolution -> final bank, graph_generate eval
  coldgen      empty bank, graph_generate (zero-experience control)
  select       empty bank, topology_select (same semantics as the frozen
               4-arm judge's select arm)
  oracle_fixed EVERY topology in --fixed-topologies runs the FULL eval
               grid; per CASE the best mean-over-seeds topology is chosen
               ON THESE EVAL RUNS. This is a deliberate UPPER-ENVELOPE
               ORACLE (uses eval outcomes for the per-case pick): no
               realizable fixed policy scores above it.
  refine       independent select_then_refine evolution (its own rounds,
               full method) -> deployed exactly like the frozen judge's
               refine evolved arm.

PASS (exit 0) = gen beats EACH of {coldgen, oracle_fixed, select} by
>= --delta-min with win-margin >= --win-margin. The gen-vs-refine
comparison is reported with the same statistics but does NOT gate the exit
code (operator: "最好" -- aspirational, and refine must not be nerfed to
make it pass).
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

CORE_BASELINES = ("coldgen", "select", "oracle_fixed")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmarks-dir", default="third_party/acl26-silo-bench/benchmarks")
    p.add_argument("--llm", default="openai")
    p.add_argument("--model-name", default="gpt-4o-mini")
    p.add_argument("--merge-mode", default="llm_full_merge")
    p.add_argument("--init-mode", default="llm_local_solve")
    p.add_argument("--objective", default="accuracy_first")
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--levels", nargs="+", default=["I"])
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--gen-rounds", type=int, default=5)
    p.add_argument("--refine-rounds", type=int, default=3)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, required=True)
    p.add_argument("--fixed-topologies", nargs="+",
                   default=["tree", "mesh_star", "one_peer_exponential_dag_star", "chain"])
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--delta-min", type=float, default=0.05)
    p.add_argument("--win-margin", type=int, default=2)
    p.add_argument("--max-runs", type=int, default=1200)
    p.add_argument("--out", default="runs/verify_gen_supremacy")
    return p.parse_args()


def _pairwise(pairs: list[dict[str, Any]], a: str, b: str,
              delta_min: float, win_margin: int) -> dict[str, Any]:
    da = sum(p[a] for p in pairs) / max(1, len(pairs))
    db = sum(p[b] for p in pairs) / max(1, len(pairs))
    wins = sum(1 for p in pairs if p[a] > p[b])
    losses = sum(1 for p in pairs if p[a] < p[b])
    return {
        "delta": da - db, "a_mean": da, "b_mean": db,
        "a_only_wins": wins, "b_only_wins": losses,
        "passed": (da - db) >= delta_min and (wins - losses) >= win_margin,
    }


def main() -> int:
    args = parse_args()
    overlap = set(args.eval_seeds) & (set(args.train_seeds) | set(args.val_seeds))
    if overlap:
        raise SystemExit(f"eval seeds must be disjoint; overlap={sorted(overlap)}")

    cfg = RunConfig(
        benchmark="silo_bench", objective=args.objective,
        merge_mode=args.merge_mode, init_mode=args.init_mode,
        llm_provider=args.llm, model_name=args.model_name,
        request_timeout=args.request_timeout,
        num_graph_candidates=args.graphgen_candidates,
        n_agents=args.n_agents,
    )
    adapter = SiloBenchAdapter(args.benchmarks_dir)
    instances = list(adapter.iter_instances(
        levels=args.levels, agent_counts=[args.n_agents], cases=args.cases))
    all_cases = sorted({i.case_id for i in instances})
    train_cases, test_cases = _split_cases(all_cases, args.holdout_frac)
    test_instances = [i for i in instances if i.case_id in set(test_cases)]
    pair_keys = [(inst, seed) for inst in test_instances for seed in args.eval_seeds]
    n_pairs = len(pair_keys)

    evo_per_round = len(train_cases) * 3 * (len(args.train_seeds) + len(args.val_seeds))
    planned = (
        (args.gen_rounds + args.refine_rounds) * evo_per_round
        + (3 + len(args.fixed_topologies) + 1) * n_pairs
    )
    print(f"plan: TRAIN={train_cases} TEST={test_cases} "
          f"gen_rounds={args.gen_rounds} refine_rounds={args.refine_rounds}")
    print(f"plan: ~{planned} protocol runs (n={args.n_agents}, workers={args.workers})")
    if planned > args.max_runs:
        print(f"ABORT: planned {planned} > --max-runs {args.max_runs}")
        return 2

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    t0 = time.monotonic()

    def _evolve(mode: str, rounds: int) -> tuple[SkillBank, dict, list[dict]]:
        evo_cfg = replace(
            cfg, evolved_mode=mode, planner_mode=_evolved_planner_mode(mode)
        )
        bank, motif = SkillBank(), {}
        log = []
        # v3 (operator: deploy the evolved BEST point, legitimately): the
        # gate measures held-out-VAL generation loss (j_after) every
        # accepted round. Deploy the accepted checkpoint with the lowest
        # VAL loss (ties -> later round, more accumulated trust) instead of
        # blindly the last round -- evolution curves wobble and the final
        # round is an endpoint lottery. Selection uses train/val signal
        # ONLY (eval-based checkpoint selection is red-lined).
        best: tuple[float, int, SkillBank, dict] | None = None
        for r in range(1, rounds + 1):
            summ = run_evolution(
                adapter, cases=train_cases, agent_counts=[args.n_agents],
                train_seeds=args.train_seeds, val_seeds=args.val_seeds,
                cfg=evo_cfg, levels=args.levels, llm_client=client,
                workers=args.workers, progress=True,
                initial_skills=[s.model_dump(mode="json") for s in bank],
            )
            gate = summ.get("gate") or {}
            accepted = bool(gate.get("accepted"))
            new_bank, new_motif = _bank_and_motif(summ)
            # v2 (dev-15): INCUMBENT-PRESERVING chain. A rejected UPDATE
            # never deploys, but the previously-accepted incumbent persists.
            if accepted or len(new_bank) > 0:
                bank, motif = new_bank, _merge_motif(motif, new_motif)
            if accepted and len(bank) > 0:
                j_after = gate.get("j_after")
                j_val = float(j_after) if j_after is not None else 1.0
                if best is None or j_val <= best[0]:
                    best = (j_val, r,
                            SkillBank(skills=[s.model_copy(deep=True) for s in bank]),
                            dict(motif))
            log.append({"round": r, "n_skills": len(bank), "accepted": accepted,
                        "gate": summ.get("gate")})
            el = int(time.monotonic() - t0)
            print(f"[{mode}] round {r}/{rounds}: skills={len(bank)} "
                  f"gate_acc={accepted} "
                  f"[{el // 60}:{el % 60:02d}]", flush=True)
        if best is not None:
            j_val, sel_round, sel_bank, sel_motif = best
            log.append({"checkpoint_selected": sel_round, "val_j": j_val,
                        "n_skills": len(sel_bank)})
            print(f"[{mode}] deploying VAL-selected checkpoint: round "
                  f"{sel_round} (val j={j_val:.3f}, skills={len(sel_bank)})",
                  flush=True)
            return sel_bank, sel_motif, log
        return bank, motif, log

    print("== evolving GEN bank ==")
    gen_bank, gen_motif, gen_log = _evolve("graph_generate", args.gen_rounds)
    print("== evolving REFINE bank (independent, full strength) ==")
    ref_bank, ref_motif, ref_log = _evolve("select_then_refine", args.refine_rounds)

    gen_eval_cfg = replace(cfg, evolved_mode="graph_generate", planner_mode="graph_generate")
    ref_eval_cfg = replace(cfg, evolved_mode="select_then_refine", planner_mode="graph_generate")

    def _arm(task) -> float | None:
        inst, seed, arm = task
        try:
            if arm == "gen":
                row = _run_one(inst, gen_eval_cfg, objective=objective,
                               skill_bank=gen_bank, seed=seed, llm_client=client,
                               motif_stats=gen_motif or None)
            elif arm == "refine":
                row = _run_one(inst, ref_eval_cfg, objective=objective,
                               skill_bank=ref_bank, seed=seed, llm_client=client,
                               motif_stats=ref_motif or None)
            elif arm == "coldgen":
                row = _run_one(inst, replace(cfg, planner_mode="graph_generate"),
                               objective=objective, skill_bank=SkillBank(),
                               seed=seed, llm_client=client)
            elif arm == "select":
                row = _run_one(inst, replace(cfg, planner_mode="topology_select"),
                               objective=objective, skill_bank=SkillBank(),
                               seed=seed, llm_client=client)
            else:  # fixed:<topology>
                topo = arm.split(":", 1)[1]
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=topo, llm_client=client)
                return 1.0 if score.success else 0.0
            return float(row.get("ExactMatchRate", 0.0))
        except Exception as exc:  # noqa: BLE001 - drop the pair symmetrically
            print(f"  [eval] {arm} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            return None

    arm_names = ["gen", "refine", "coldgen", "select",
                 *[f"fixed:{t}" for t in args.fixed_topologies]]
    tasks = [(inst, seed, arm) for (inst, seed) in pair_keys for arm in arm_names]
    print(f"== paired eval: {len(tasks)} runs over {n_pairs} pairs x {len(arm_names)} arms ==")
    with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
        flat = list(ex.map(_arm, tasks))

    k_arms = len(arm_names)
    pairs: list[dict[str, Any]] = []
    dropped = 0
    for k, (inst, seed) in enumerate(pair_keys):
        vals = flat[k_arms * k: k_arms * (k + 1)]
        if any(v is None for v in vals):
            dropped += 1
            continue
        pairs.append({"case_id": inst.case_id, "seed": seed,
                      **{arm: vals[i] for i, arm in enumerate(arm_names)}})

    # per-case oracle fixed: best mean-over-seeds topology PER CASE, chosen on
    # these eval runs (upper envelope of the fixed family)
    oracle_pick: dict[str, str] = {}
    for case in sorted({p["case_id"] for p in pairs}):
        case_pairs = [p for p in pairs if p["case_id"] == case]
        means = {
            t: sum(p[f"fixed:{t}"] for p in case_pairs) / len(case_pairs)
            for t in args.fixed_topologies
        }
        oracle_pick[case] = max(sorted(means), key=lambda t: means[t])
    for p in pairs:
        p["oracle_fixed"] = p[f"fixed:{oracle_pick[p['case_id']]}"]

    per_baseline = {
        b: _pairwise(pairs, "gen", b, args.delta_min, args.win_margin)
        for b in CORE_BASELINES
    }
    vs_refine = _pairwise(pairs, "gen", "refine", args.delta_min, args.win_margin)
    machinery_ok = len(gen_bank) > 0 and len(ref_bank) > 0
    passed = machinery_ok and all(v["passed"] for v in per_baseline.values())

    arm_means = {
        a: sum(p[a] for p in pairs) / max(1, len(pairs))
        for a in ["gen", "refine", "coldgen", "select", "oracle_fixed"]
    }
    report = {
        "instrument": "gen_supremacy_v1 (additive; oracle_fixed = per-case "
                      "upper envelope chosen on eval outcomes)",
        "n_agents": args.n_agents,
        "gen_rounds": args.gen_rounds, "refine_rounds": args.refine_rounds,
        "train_cases": train_cases, "test_cases": test_cases,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds,
        "fixed_topologies": args.fixed_topologies,
        "oracle_pick_per_case": oracle_pick,
        "n_pairs": len(pairs), "dropped_pairs": dropped,
        "arm_means": arm_means,
        "per_baseline": per_baseline,
        "gen_vs_refine": vs_refine,
        "gen_rounds_log": gen_log, "refine_rounds_log": ref_log,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin,
                     "gating_arms": list(CORE_BASELINES),
                     "refine_comparison": "reported, non-gating (operator: aspirational)"},
        "machinery_ok": machinery_ok, "passed": passed,
        "pairs": pairs,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"gen_supremacy_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))

    print("\narm means: " + "  ".join(f"{a}={v * 100:.1f}%" for a, v in arm_means.items()))
    print(f"oracle picks per case: {oracle_pick}")
    for b, v in per_baseline.items():
        print(f"gen vs {b}: delta={v['delta'] * 100:+.1f}pp "
              f"wins={v['a_only_wins']}:{v['b_only_wins']} "
              f"{'PASS' if v['passed'] else 'FAIL'}")
    print(f"gen vs refine (non-gating): delta={vs_refine['delta'] * 100:+.1f}pp "
          f"wins={vs_refine['a_only_wins']}:{vs_refine['b_only_wins']} "
          f"{'ahead' if vs_refine['passed'] else 'not ahead'}")
    print(f"report: {path}")
    print(f"\nVERDICT: {'PASS -- gen dominates cold + per-case-best-fixed + select' if passed else 'FAIL -- gen supremacy not verified'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
