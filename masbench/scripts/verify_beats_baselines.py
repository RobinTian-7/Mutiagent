"""Phase-2 frozen judge: does R-round self-evolution beat EVERY baseline?

Protocol (honest by construction):
  1. Disjoint case split. Prefer explicit ``--train-cases``/``--test-cases``;
     otherwise the lexicographic tail of ``--cases`` is TEST, as in phase 1.
  2. Evolve for ``--rounds`` R (>=1) rounds on TRAIN only, ACCUMULATING the
     skill bank + motif stats across rounds (the "after several evolutions"
     state is what gets judged).
  3. ``fixed_best_on_train``: every topology in ``--fixed-topologies`` runs on
     the TRAIN cases x train seeds; the best mean exact-match (lexicographic
     tiebreak) is selected -- the strongest constant named-topology policy
     choosable WITHOUT test data. Oracle-on-test is deliberately NOT a baseline.
  4. Paired eval on TEST: for each (case, seed), evolved and every requested
     baseline run with identical conditions. A pair where ANY arm errors is
     DROPPED whole (symmetric), and counted. ``--baselines`` can additionally
     select the paper's dynamic P2P, Broadcast, and SFS transports.
  5. PASS iff, against EACH requested baseline: paired mean delta
     (evolved - baseline) >= --delta-min AND (evolved-only wins - baseline-only
     wins) >= --win-margin.
  6. Rounds STABILITY is a separate reported verdict (not the exit code): with
     --curves-json (a ``masbench curve`` output), the last 3 rounds' scores
     must all exceed every baseline recorded in that file.

Exit code: 0 = verified win over all baselines, 1 = not verified, 2 = aborted
(budget guard). Offline (--llm fake) Silo is topology-invariant, so this MUST
exit 1 with "machinery OK"; that is the harness smoke test.
The report retains per-agent submissions and paper S/P/C/D for every arm.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from exp_graph.mas.schemas import SkillCard
from exp_graph.mas.skill_bank import SkillBank

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.adapters.silo_paper_protocols import (
    PAPER_PROTOCOL_ARMS,
    run_silo_paper_protocol,
)
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.diagnostics import run_full_information_single_agent
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
AVAILABLE_BASELINES = (*BASELINES, "programgen", "pycodegen", *PAPER_PROTOCOL_ARMS)


def _resolve_case_split(
    all_cases: list[str],
    *,
    holdout_frac: float,
    train_cases: list[str] | None = None,
    test_cases: list[str] | None = None,
) -> tuple[list[str], list[str], str]:
    """Resolve an auditable explicit split or fall back to tail holdout."""
    if (train_cases is None) != (test_cases is None):
        raise ValueError("--train-cases and --test-cases must be provided together")
    if train_cases is None:
        train, test = _split_cases(all_cases, holdout_frac)
        return train, test, "lexicographic_holdout"

    train = list(dict.fromkeys(train_cases))
    test = list(dict.fromkeys(test_cases or []))
    if not train or not test:
        raise ValueError("explicit TRAIN and TEST case lists must both be non-empty")
    overlap = set(train) & set(test)
    if overlap:
        raise ValueError(f"TRAIN and TEST cases overlap: {sorted(overlap)}")
    missing = (set(train) | set(test)) - set(all_cases)
    if missing:
        raise ValueError(
            "requested cases are unavailable for the selected levels/agent count: "
            f"{sorted(missing)}"
        )
    return train, test, "explicit"


def _save_skill_bank_snapshot(
    root: Path,
    *,
    relative_name: str,
    skills: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Persist one auditable bank as JSON plus one YAML file per skill."""
    snapshot_dir = root / relative_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    bank = SkillBank(skills=[SkillCard.model_validate(item) for item in skills])
    canonical = [
        skill.model_dump(mode="json")
        for skill in sorted(bank, key=lambda item: item.skill_id)
    ]
    bank.save_dir(snapshot_dir / "skills")
    payload = {
        "n_skills": len(canonical),
        "skill_ids": [item["skill_id"] for item in canonical],
        "skills": canonical,
    }
    (snapshot_dir / "bank.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=str)
    )
    return {
        "name": relative_name,
        "n_skills": len(canonical),
        "skill_ids": payload["skill_ids"],
        "bank_json": str(Path(relative_name) / "bank.json"),
        "skills_dir": str(Path(relative_name) / "skills"),
        "metadata_json": str(Path(relative_name) / "metadata.json"),
    }


def _pick_fixed_best(rows: list[dict[str, Any]]) -> str:
    """Argmax mean exact over per-run rows {topology, exact}; ties -> lexicographic."""
    by_topology: dict[str, list[float]] = {}
    for row in rows:
        by_topology.setdefault(str(row["topology"]), []).append(float(row["exact"]))
    means = {t: sum(v) / len(v) for t, v in by_topology.items() if v}
    best = max(means.values())
    return min(t for t, m in means.items() if m == best)


FIXED_ARM_PREFIX = "fixed:"


def _expand_fixed_baselines(
    baselines: tuple[str, ...],
    fixed_topologies: list[str],
    *,
    per_topology: bool,
) -> tuple[tuple[str, ...], frozenset[str]]:
    """Expand the aggregate ``fixed`` baseline into per-topology paired arms.

    When ``per_topology`` is set AND ``fixed`` is a requested baseline, every
    entry of ``fixed_topologies`` becomes its OWN independent paired arm, keyed
    ``fixed:<topology>`` (evaluated on each held-out (case, seed) exactly like
    any other arm and judged with the untouched ``_verdict`` logic). The
    aggregate ``fixed`` arm (``fixed_best_on_train``) is retained as a
    SUPPLEMENTARY paired arm rather than the sole fixed baseline, so the paper's
    two named transports are compared directly instead of being collapsed to
    their train-selected maximum. Order is preserved and the aggregate ``fixed``
    moves to the end.

    Returns ``(eval_baselines, supplementary_arms)``: the ordered baselines to
    evaluate, and the subset that is reported but excluded from the verifier's
    own pass/fail gate. When ``per_topology`` is false (the default) the input
    is returned unchanged, so existing behavior and the frozen offline test are
    fully preserved.
    """
    if not per_topology or "fixed" not in baselines:
        return baselines, frozenset()
    topologies = list(dict.fromkeys(str(t) for t in fixed_topologies))
    if not topologies:
        return baselines, frozenset()
    expanded = [name for name in baselines if name != "fixed"]
    expanded.extend(f"{FIXED_ARM_PREFIX}{topology}" for topology in topologies)
    expanded.append("fixed")  # aggregate fixed_best_on_train, supplementary
    return tuple(dict.fromkeys(expanded)), frozenset({"fixed"})


def _verdict(
    pairs: list[dict[str, Any]], *, delta_min: float, win_margin: int,
    baselines: tuple[str, ...] = BASELINES,
) -> dict[str, Any]:
    """Paired verdict vs every requested baseline."""
    n = len(pairs)
    means = {
        arm: (sum(float(p[arm]) for p in pairs) / n if n else 0.0)
        for arm in ("evolved", *baselines)
    }
    per_baseline: dict[str, Any] = {}
    for b in baselines:
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


def _metrics_from_score(score: Any) -> dict[str, Any]:
    """Paper metrics plus every submitted answer from a ScoreResult."""
    extra = score.extra or {}
    exact = 1.0 if score.success else 0.0
    return {
        "success": exact,
        "S": float(extra.get("paper_S", exact) or 0.0),
        "P": float(extra.get("paper_P", score.partial or 0.0) or 0.0),
        "C": float(extra.get("paper_C", 0.0) or 0.0),
        "D": float(extra.get("paper_D", 0.0) or 0.0),
        "messages": int(score.n_messages),
        "model_calls": int(score.n_model_calls),
        "tokens": int(score.tokens),
        "per_agent_submissions": extra.get("per_agent_submissions", []),
    }


def _metrics_from_evolution_row(row: dict[str, Any]) -> dict[str, Any]:
    """Paper metrics carried by the unified scorer into an evolution row."""
    exact = float(row.get("ExactMatchRate", 0.0))
    return {
        "success": exact,
        "S": float(row.get("paper_S", exact) or 0.0),
        "P": float(
            row.get("paper_P", row.get("PartialCorrectness", exact)) or 0.0
        ),
        "C": float(row.get("paper_C", 0.0) or 0.0),
        "D": float(row.get("paper_D", 0.0) or 0.0),
        "messages": int(row.get("MeanTotalMessages", 0) or 0),
        "model_calls": int(row.get("MeanTotalModelCalls", 0) or 0),
        "tokens": int(row.get("MeanTokenCost", 0) or 0),
        "per_agent_submissions": row.get("per_agent_submissions", []),
    }


def _paper_metric_means(
    pair_details: list[dict[str, Any]], arms: tuple[str, ...]
) -> dict[str, dict[str, float]]:
    """Aggregate S/P/C/D over retained paired evaluation units."""
    means: dict[str, dict[str, float]] = {}
    for arm in arms:
        rows = [detail["arms"][arm] for detail in pair_details]
        means[arm] = {
            metric: (
                sum(float(row[metric]) for row in rows) / len(rows)
                if rows
                else 0.0
            )
            for metric in ("S", "P", "C", "D")
        }
    return means


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmarks-dir", default="third_party/acl26-silo-bench/benchmarks")
    p.add_argument("--llm", default="openai")
    p.add_argument("--model-name", default="gpt-4o-mini")
    p.add_argument("--merge-mode", default="llm_full_merge")
    p.add_argument("--init-mode", default="llm_local_solve")
    p.add_argument("--objective", default="accuracy_first")
    p.add_argument("--evolved-mode", default="select_then_refine",
                   choices=[
                       "topology_select",
                       "graph_generate",
                       "program_generate",
                       "python_generate",
                       "select_then_refine",
                   ])
    p.add_argument("--rounds", type=int, default=3,
                   help="evolution rounds R (bank+motif accumulate across rounds)")
    p.add_argument(
        "--curriculum",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="grow the train subset within every requested level across rounds",
    )
    p.add_argument(
        "--skill-ablation-strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="reject individually measured skills with more paired losses than wins",
    )
    p.add_argument(
        "--capability-diagnostic",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also run the full-information single-agent capability floor",
    )
    p.add_argument(
        "--hot-start",
        dest="hot_start_enabled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="pretrain from fixed organizations/paper transports and run paired "
             "reuse plus fresh-creation branches on every TRAIN pair",
    )
    p.add_argument("--hot-start-protocols", default="auto")
    p.add_argument("--hot-start-topologies", default="auto")
    p.add_argument("--hot-start-seed-count", type=int, default=1)
    p.add_argument(
        "--hot-start-dual-branch",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p.add_argument(
        "--hot-start-innovation-mode",
        choices=["auto", "graph_generate", "program_generate", "python_generate"],
        default="auto",
    )
    p.add_argument("--n-agents", type=int, default=5)
    p.add_argument("--levels", nargs="+", default=["II", "III"])
    p.add_argument(
        "--cases", nargs="+", default=None,
        help="cases to split by --holdout-frac; incompatible with explicit case lists",
    )
    p.add_argument(
        "--train-cases", nargs="+", default=None,
        help="explicit TRAIN cases; requires --test-cases",
    )
    p.add_argument(
        "--test-cases", nargs="+", default=None,
        help="explicit held-out TEST cases; requires --train-cases",
    )
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--train-seeds", nargs="+", type=int, default=[1, 2])
    p.add_argument("--val-seeds", nargs="+", type=int, default=[3])
    p.add_argument("--eval-seeds", nargs="+", type=int, default=list(range(11, 19)))
    p.add_argument("--fixed-topologies", nargs="+",
                   default=["tree", "mesh_star", "one_peer_exponential_dag_star", "chain"])
    p.add_argument(
        "--fixed-per-topology-arms",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="expand the 'fixed' baseline into one INDEPENDENT paired arm per "
             "--fixed-topologies entry (arm key 'fixed:<topology>') while keeping "
             "the aggregate fixed_best_on_train as a supplementary paired arm; "
             "off by default so existing behavior is unchanged",
    )
    p.add_argument(
        "--baselines", nargs="+", choices=list(AVAILABLE_BASELINES),
        default=list(BASELINES),
        help="paired baselines to judge (default: select graphgen fixed); use "
             "'p2p broadcast sfs' for all original SILO-BENCH transports",
    )
    p.add_argument("--graphgen-candidates", type=int, default=3)
    p.add_argument("--python-repair-attempts", type=int, default=3)
    p.add_argument("--python-execution-timeout", type=float, default=30.0)
    p.add_argument("--python-cpu-seconds", type=int, default=10)
    p.add_argument("--python-memory-mb", type=int, default=512)
    p.add_argument("--python-max-output-bytes", type=int, default=1_000_000)
    p.add_argument("--python-max-model-calls", type=int, default=20)
    p.add_argument("--python-max-completion-tokens", type=int, default=4000)
    p.add_argument("--python-max-messages", type=int, default=30)
    p.add_argument(
        "--silo-eval-mode", dest="silo_eval_mode",
        choices=["sink", "all_agents"], default="sink",
        help="information goal for EVERY run in this verification (prompts, "
             "graph validation, scoring, skill bank, caches and the report are "
             "namespaced by it); science runs should pass it explicitly",
    )
    p.add_argument("--graph-validation-seeds", type=int, default=0)
    p.add_argument("--use-llm-insights", action="store_true")
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--max-rounds", type=int, default=4,
                   help="maximum rounds for each paper P2P/Broadcast/SFS run")
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
    baselines = tuple(dict.fromkeys(args.baselines))
    # Optionally promote each fixed topology to its own paired baseline while
    # keeping fixed_best_on_train as a supplementary arm (see
    # _expand_fixed_baselines). eval_baselines drives every arm dispatch, the
    # budget guard, the verdict table and the report; supplementary_baselines
    # are reported but do NOT gate the exit code.
    eval_baselines, supplementary_baselines = _expand_fixed_baselines(
        baselines, args.fixed_topologies, per_topology=args.fixed_per_topology_arms
    )
    primary_baselines = tuple(
        b for b in eval_baselines if b not in supplementary_baselines
    )
    if set(baselines) & set(PAPER_PROTOCOL_ARMS) and args.silo_eval_mode != "all_agents":
        raise SystemExit(
            "p2p/broadcast/sfs baselines require --silo-eval-mode all_agents"
        )
    if (
        args.hot_start_enabled
        and args.silo_eval_mode != "all_agents"
        and args.hot_start_protocols.strip().lower() not in {"", "auto"}
    ):
        raise SystemExit(
            "hot-start p2p/broadcast/sfs require --silo-eval-mode all_agents"
        )
    explicit_split = args.train_cases is not None or args.test_cases is not None
    if explicit_split and args.cases is not None:
        raise SystemExit(
            "--cases cannot be combined with --train-cases/--test-cases"
        )
    if (args.train_cases is None) != (args.test_cases is None):
        raise SystemExit("--train-cases and --test-cases must be provided together")
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
        max_rounds=args.max_rounds,
        silo_eval_mode=args.silo_eval_mode,
        curriculum_enabled=args.curriculum,
        curriculum_total_rounds=args.rounds,
        skill_ablation_strict=args.skill_ablation_strict,
        python_repair_attempts=args.python_repair_attempts,
        python_execution_timeout=args.python_execution_timeout,
        python_cpu_seconds=args.python_cpu_seconds,
        python_memory_mb=args.python_memory_mb,
        python_max_output_bytes=args.python_max_output_bytes,
        python_max_model_calls=args.python_max_model_calls,
        python_max_completion_tokens=args.python_max_completion_tokens,
        python_max_messages=args.python_max_messages,
        python_artifacts_dir=str(Path(args.out) / "pycodegen_artifacts"),
        hot_start_enabled=args.hot_start_enabled,
        hot_start_protocols=args.hot_start_protocols,
        hot_start_topologies=args.hot_start_topologies,
        hot_start_seed_count=args.hot_start_seed_count,
        hot_start_dual_branch=args.hot_start_dual_branch,
        hot_start_innovation_mode=args.hot_start_innovation_mode,
    )
    adapter = SiloBenchAdapter(args.benchmarks_dir)
    requested_cases = args.cases
    if explicit_split:
        requested_cases = list(dict.fromkeys([*args.train_cases, *args.test_cases]))
    instances = list(adapter.iter_instances(
        levels=args.levels, agent_counts=[args.n_agents], cases=requested_cases))
    all_cases = sorted({i.case_id for i in instances})
    try:
        train_cases, test_cases, split_mode = _resolve_case_split(
            all_cases,
            holdout_frac=args.holdout_frac,
            train_cases=args.train_cases,
            test_cases=args.test_cases,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
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
    hot_pretrain_runs = 0
    if args.hot_start_enabled:
        topology_count = (
            (2 if args.silo_eval_mode == "all_agents" else 7)
            if args.hot_start_topologies.strip().lower() == "auto"
            else len([x for x in args.hot_start_topologies.split(",") if x.strip()])
        )
        protocol_count = (
            (3 if args.silo_eval_mode == "all_agents" else 0)
            if args.hot_start_protocols.strip().lower() == "auto"
            else len([x for x in args.hot_start_protocols.split(",") if x.strip()])
        )
        hot_pretrain_runs = (
            half
            * max(1, args.hot_start_seed_count)
            * (topology_count + protocol_count)
        )
        if args.hot_start_dual_branch:
            evo_per_round += 2 * half * len(args.train_seeds)
    fixed_sel_runs = (
        len(args.fixed_topologies) * len(train_instances) * len(args.train_seeds)
        if "fixed" in eval_baselines
        else 0
    )
    paired_arm_count = 1 + len(eval_baselines)
    planned = (
        args.rounds * evo_per_round
        + hot_pretrain_runs
        + fixed_sel_runs
        + paired_arm_count * n_pairs
    )
    cleanliness = "hot-start/non-clean" if args.hot_start_enabled else "clean_run"
    print(f"=== SILO EVAL MODE: {args.silo_eval_mode} ({cleanliness} pipeline) ===")
    print(
        f"plan: split={split_mode} TRAIN={train_cases} TEST={test_cases} "
        f"rounds={args.rounds}"
    )
    print(f"plan: ~{args.rounds}x{evo_per_round} evolution + {hot_pretrain_runs} hot-pretrain "
          f"+ {fixed_sel_runs} fixed-selection "
          f"+ {paired_arm_count * n_pairs} paired eval "
          f"({paired_arm_count} arms) = ~{planned} protocol runs "
          f"(n={args.n_agents})")
    if planned > args.max_runs:
        print(f"ABORT: planned {planned} > --max-runs {args.max_runs}")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    skill_banks_root = out / "skill_banks"
    manifest_path = skill_banks_root / "manifest.json"
    skill_bank_manifest: dict[str, Any] = {
        "schema_version": "skill_bank_audit_v2",
        "silo_eval_mode": args.silo_eval_mode,
        "clean_run": not args.hot_start_enabled,
        "hot_start_enabled": args.hot_start_enabled,
        "clean_pythongen": bool(cfg.clean_pythongen),
        "description": (
            "Every distinct bank used by this verifier. Evolution rounds retain "
            "before, candidate, and gate-approved deployed snapshots."
        ),
        "fixed_uses_skill_bank": False,
        "snapshots": [],
        "rounds": [],
    }

    # Cold controls always use an empty bank. Save each semantic role once
    # rather than writing the same empty payload for every paired run.
    for arm in (
        name
        for name in baselines
        if name in {"graphgen", "programgen", "pycodegen", "select"}
    ):
        entry = _save_skill_bank_snapshot(
            skill_banks_root,
            relative_name=f"controls/{arm}_empty",
            skills=[],
            metadata={
                "arm": arm,
                "scope": "shared empty control bank",
                "used_for_every_control_run": True,
            },
        )
        skill_bank_manifest["snapshots"].append(entry)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(skill_bank_manifest, indent=2, sort_keys=True)
    )

    client = _bounded(_build_llm_client(cfg), args.workers)
    objective = evolution_objective_spec(cfg)
    evo_cfg = replace(cfg, planner_mode=_evolved_planner_mode(cfg.evolved_mode))
    generate = cfg.evolved_mode in (
        "graph_generate",
        "program_generate",
        "python_generate",
        "select_then_refine",
    )
    eval_cfg = replace(
        cfg,
        planner_mode=(
            cfg.evolved_mode
            if cfg.evolved_mode
            in {"graph_generate", "program_generate", "python_generate"}
            else ("graph_generate" if generate else "topology_select")
        ),
    )

    # ---- 1. R rounds of evolution on TRAIN only (accumulating) ----
    t0 = time.monotonic()
    bank, motif = SkillBank(), {}
    rounds_log: list[dict[str, Any]] = []
    for r in range(1, args.rounds + 1):
        round_cfg = replace(evo_cfg, curriculum_round=r)
        summ = run_evolution(
            adapter, cases=train_cases, agent_counts=[args.n_agents],
            train_seeds=args.train_seeds, val_seeds=args.val_seeds,
            cfg=round_cfg, levels=args.levels, llm_client=client,
            workers=args.workers, progress=True,
            initial_skills=[s.model_dump(mode="json") for s in bank] or None,
        )
        bank, new_motif = _bank_and_motif(summ)
        motif = _merge_motif(motif, new_motif)
        round_dir = skill_banks_root / f"round_{r:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "evolution_summary.json").write_text(
            json.dumps(summ, indent=2, sort_keys=True, default=str)
        )
        (round_dir / "deployed_motif_stats.json").write_text(
            json.dumps(motif, indent=2, sort_keys=True, default=str)
        )
        snapshots = summ.get("skill_bank_snapshots") or {
            "before": [],
            "candidate": summ.get("evolved_skills", []),
            "deployed": summ.get("evolved_skills", []),
        }
        round_snapshots = []
        for stage in ("before", "candidate", "deployed"):
            entry = _save_skill_bank_snapshot(
                skill_banks_root,
                relative_name=f"round_{r:02d}/{stage}",
                skills=list(snapshots.get(stage) or []),
                metadata={
                    "round": r,
                    "stage": stage,
                    "gate": summ.get("gate"),
                    "meaning": {
                        "before": "bank entering this evolution round",
                        "candidate": "post-update bank before the held-out gate",
                        "deployed": "bank allowed to reach evaluation after the gate",
                    }[stage],
                },
            )
            round_snapshots.append(entry)
            skill_bank_manifest["snapshots"].append(entry)
        skill_bank_manifest["rounds"].append(
            {
                "round": r,
                "gate": summ.get("gate"),
                "hot_start": summ.get("hot_start"),
                "snapshots": [entry["name"] for entry in round_snapshots],
                "evolution_summary": f"round_{r:02d}/evolution_summary.json",
                "deployed_motif_stats": (
                    f"round_{r:02d}/deployed_motif_stats.json"
                ),
            }
        )
        manifest_path.write_text(
            json.dumps(skill_bank_manifest, indent=2, sort_keys=True, default=str)
        )
        rounds_log.append({
            "round": r, "n_skills": len(bank), "gate": summ.get("gate"),
            "skill_ids": summ.get("skill_ids_after"),
            "rejected_skill_ids": summ.get("rejected_skill_ids"),
            "hot_start": summ.get("hot_start"),
        })
        print(f"round {r}/{args.rounds}: skills={len(bank)} gate={summ.get('gate')}")

    final_entry = _save_skill_bank_snapshot(
        skill_banks_root,
        relative_name="final/deployed",
        skills=[skill.model_dump(mode="json") for skill in bank],
        metadata={
            "stage": "final",
            "rounds": args.rounds,
            "meaning": "exact evolved bank used by the paired evaluation",
        },
    )
    (skill_banks_root / "final" / "motif_stats.json").write_text(
        json.dumps(motif, indent=2, sort_keys=True, default=str)
    )
    skill_bank_manifest["snapshots"].append(final_entry)
    skill_bank_manifest["final"] = {
        **final_entry,
        "motif_stats": "final/motif_stats.json",
    }
    manifest_path.write_text(
        json.dumps(skill_bank_manifest, indent=2, sort_keys=True, default=str)
    )

    # ---- 2. fixed_best_on_train (train data only) ----
    fixed_tasks = (
        [
            (inst, topo, seed)
            for topo in args.fixed_topologies
            for inst in train_instances
            for seed in args.train_seeds
        ]
        if "fixed" in eval_baselines
        else []
    )

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

    fixed_rows: list[dict[str, Any]] = []
    fixed_best: str | None = None
    fixed_train_means: dict[str, float] = {}
    if fixed_tasks:
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

    def _arm(task) -> dict[str, Any] | None:
        inst, seed, arm = task
        try:
            if arm in PAPER_PROTOCOL_ARMS:
                score = run_silo_paper_protocol(
                    inst,
                    replace(cfg, seed=seed),
                    protocol=arm,
                    llm_client=client,
                )
                return _metrics_from_score(score)
            if arm.startswith(FIXED_ARM_PREFIX):
                topology = arm[len(FIXED_ARM_PREFIX):]
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=topology, llm_client=client)
                return _metrics_from_score(score)
            if arm == "fixed":
                assert fixed_best is not None
                score = run_fixed_protocol(
                    inst, replace(cfg, seed=seed), topology=fixed_best, llm_client=client)
                return _metrics_from_score(score)
            if arm == "evolved":
                row = _run_one(
                    inst, eval_cfg, objective=objective, skill_bank=bank, seed=seed,
                    llm_client=client, motif_stats=motif or None, diag_phase="")
            elif arm == "select":
                row = _run_one(
                    inst, replace(cfg, planner_mode="topology_select"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            elif arm == "graphgen":
                row = _run_one(
                    inst, replace(cfg, planner_mode="graph_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            elif arm == "programgen":
                row = _run_one(
                    inst, replace(cfg, planner_mode="program_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            else:  # pycodegen
                row = _run_one(
                    inst, replace(cfg, planner_mode="python_generate"),
                    objective=objective, skill_bank=SkillBank(), seed=seed,
                    llm_client=client, diag_phase="")
            return _metrics_from_evolution_row(row)
        except Exception as exc:  # noqa: BLE001 - drop the whole pair, symmetric
            print(f"  [eval] {arm} {inst.case_id} seed={seed} FAILED: {exc}", flush=True)
            return None

    arms = ("evolved", *eval_baselines)
    tasks = [(inst, seed, arm) for (inst, seed) in pair_keys for arm in arms]
    with ThreadPoolExecutor(max_workers=min(args.workers, len(tasks))) as ex:
        flat = list(ex.map(_arm, tasks))
    pairs: list[dict[str, Any]] = []
    pair_details: list[dict[str, Any]] = []
    dropped = 0
    for k, (inst, seed) in enumerate(pair_keys):
        start = len(arms) * k
        vals = flat[start:start + len(arms)]
        if any(v is None for v in vals):
            dropped += 1
            continue
        assert all(isinstance(value, dict) for value in vals)
        metrics_by_arm = {
            arm: vals[i]
            for i, arm in enumerate(arms)
        }
        pairs.append({
            "case_id": inst.case_id, "seed": seed,
            **{arm: float(metrics_by_arm[arm]["success"]) for arm in arms},
        })
        pair_details.append(
            {
                "case_id": inst.case_id,
                "seed": seed,
                "arms": metrics_by_arm,
            }
        )

    # ---- 4. verdict ----
    verdict = _verdict(
        pairs,
        delta_min=args.delta_min,
        win_margin=args.win_margin,
        baselines=eval_baselines,
    )
    # The verifier's own pass/fail gate is computed over the PRIMARY baselines
    # only; supplementary arms (e.g. the aggregate fixed_best_on_train when
    # per-topology fixed arms are enabled) are reported but never gate the exit
    # code. With per-topology fixed arms off this reduces exactly to
    # verdict["passed"] (supplementary is empty). The pre-registered scientific
    # PASS/FAIL/INCONCLUSIVE is decided by the separate paired-analysis script.
    verifier_passed = bool(
        len(pairs) > 0
        and all(verdict["per_baseline"][b]["passed"] for b in primary_baselines)
    )
    paper_metric_means = _paper_metric_means(pair_details, arms)
    capability_diagnostic: dict[str, Any] = {
        "enabled": bool(args.capability_diagnostic),
        "full_information_single_agent": None,
        "cold_generated": (
            paper_metric_means.get("pycodegen")
            if cfg.evolved_mode == "python_generate"
            else
            paper_metric_means.get("programgen")
            if cfg.evolved_mode == "program_generate"
            else paper_metric_means.get("graphgen")
        ),
        "evolved_generated": paper_metric_means.get("evolved"),
    }
    if args.capability_diagnostic:
        def _full_info(task: tuple[BenchmarkInstance, int]) -> dict[str, Any] | None:
            inst, seed = task
            try:
                return _metrics_from_score(
                    run_full_information_single_agent(
                        inst,
                        replace(cfg, seed=seed),
                        llm_client=client,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - diagnostic is noncompetitive
                print(
                    f"  [diagnostic] {inst.case_id} seed={seed} FAILED: {exc}",
                    flush=True,
                )
                return None

        with ThreadPoolExecutor(
            max_workers=min(args.workers, max(1, len(pair_keys)))
        ) as ex:
            diagnostic_rows = [
                row for row in ex.map(_full_info, pair_keys) if row is not None
            ]
        capability_diagnostic["full_information_single_agent"] = {
            metric: (
                sum(float(row[metric]) for row in diagnostic_rows)
                / len(diagnostic_rows)
                if diagnostic_rows
                else 0.0
            )
            for metric in ("S", "P", "C", "D")
        }
        capability_diagnostic["n_runs"] = len(diagnostic_rows)
    machinery_ok = bool(
        len(bank) > 0
        and len(rounds_log) == args.rounds
        and all(r.get("gate") for r in rounds_log)
    )
    stable_rounds_ok = None
    if args.curves_json:
        stable_rounds_ok = _stable_rounds(json.loads(Path(args.curves_json).read_text()))

    report = {
        "silo_eval_mode": args.silo_eval_mode,
        "clean_run": not args.hot_start_enabled,
        "hot_start_enabled": args.hot_start_enabled,
        "hot_start_protocols": args.hot_start_protocols,
        "hot_start_topologies": args.hot_start_topologies,
        "hot_start_seed_count": args.hot_start_seed_count,
        "hot_start_dual_branch": args.hot_start_dual_branch,
        "hot_start_innovation_mode": args.hot_start_innovation_mode,
        "clean_pythongen": bool(cfg.clean_pythongen),
        "mode": cfg.evolved_mode, "n_agents": args.n_agents, "rounds": args.rounds,
        "train_cases": train_cases, "test_cases": test_cases,
        "split_mode": split_mode,
        "train_seeds": args.train_seeds, "val_seeds": args.val_seeds,
        "eval_seeds": args.eval_seeds,
        "fixed_topologies": args.fixed_topologies,
        "baselines": list(baselines),
        "fixed_per_topology_arms": bool(args.fixed_per_topology_arms),
        "eval_baselines": list(eval_baselines),
        "primary_baselines": list(primary_baselines),
        "supplementary_baselines": sorted(supplementary_baselines),
        "fixed_best_topology": fixed_best, "fixed_train_means": fixed_train_means,
        "n_pairs": len(pairs), "dropped_pairs": dropped,
        "arm_means": verdict["arm_means"], "per_baseline": verdict["per_baseline"],
        "paper_metric_means": paper_metric_means,
        "capability_diagnostic": capability_diagnostic,
        "pair_details": pair_details,
        "rounds_log": rounds_log, "n_skills": len(bank),
        "skill_bank_manifest": str(manifest_path),
        "n_skill_bank_snapshots": len(skill_bank_manifest["snapshots"]),
        "machinery_ok": machinery_ok, "stable_rounds_ok": stable_rounds_ok,
        "criteria": {"delta_min": args.delta_min, "win_margin": args.win_margin},
        "passed": verifier_passed,
        "verdict_passed_all_arms": verdict["passed"],
        "pairs": pairs,
    }
    path = out / f"verify_beats_baselines_n{args.n_agents}.json"
    path.write_text(json.dumps(report, indent=2))

    means = verdict["arm_means"]
    print(f"\n=== SILO EVAL MODE: {args.silo_eval_mode} ===")
    print(f"\npaired held-out exact-match over {len(pairs)} (case,seed) pairs "
          f"({dropped} dropped):")
    print(f"  evolved (R={args.rounds}) : {means['evolved'] * 100:5.1f}%")
    for b in eval_baselines:
        v = verdict["per_baseline"][b]
        label = f"{b}={fixed_best}" if b == "fixed" else b
        tag = " [supplementary]" if b in supplementary_baselines else ""
        print(f"  vs {label:<35}: {means[b] * 100:5.1f}%  delta={v['delta'] * 100:+.1f}pp "
              f"wins={v['evolved_only_wins']}/{v['baseline_only_wins']} "
              f"{'PASS' if v['passed'] else 'fail'}{tag}")
    print("\npaper metrics (mean over retained pairs):")
    print("  arm                    S       P       C       D")
    for arm in arms:
        metric = paper_metric_means[arm]
        print(
            f"  {arm:<20} "
            f"{metric['S'] * 100:6.1f}% "
            f"{metric['P'] * 100:6.1f}% "
            f"{metric['C']:7.1f} "
            f"{metric['D']:7.3f}"
        )
    if args.capability_diagnostic:
        diag_metric = capability_diagnostic["full_information_single_agent"]
        print(
            "  capability floor (one agent, full information): "
            f"S={diag_metric['S'] * 100:.1f}% P={diag_metric['P'] * 100:.1f}%"
        )
    print(f"  machinery : {'OK' if machinery_ok else 'BROKEN'} "
          f"(skills={len(bank)}, rounds={len(rounds_log)})")
    print(f"  banks     : {manifest_path} "
          f"({len(skill_bank_manifest['snapshots'])} snapshots)")
    if stable_rounds_ok is not None:
        print(f"  rounds stability (last 3 > all curve baselines): "
              f"{'OK' if stable_rounds_ok else 'NOT MET'}")
    print(f"  report    : {path}")
    print(
        "\nVERDICT: "
        + (
            "PASS -- evolved beats all primary baselines on held-out Silo"
            if verifier_passed
            else "FAIL -- not verified against all primary baselines"
        )
    )
    return 0 if verifier_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
