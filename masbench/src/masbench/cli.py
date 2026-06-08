"""masbench command-line interface."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance
from masbench.evolve import (
    INCUMBENT_BASELINE_TOPOLOGY,
    accepting_held_out_rows,
    run_evolution,
)


def _adapter(benchmark: str, benchmarks_dir: str) -> SiloBenchAdapter:
    if benchmark != "silo_bench":
        raise SystemExit(f"unknown benchmark '{benchmark}' (Plan 1 supports silo_bench)")
    return SiloBenchAdapter(benchmarks_dir)


def _cfg_from_args(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        benchmark=args.benchmark,
        use_planner=getattr(args, "planner", False),
        planner_mode=getattr(args, "planner_mode", "topology_select"),
        topology=args.topology,
        objective=getattr(args, "objective", "balanced"),
        merge_mode=getattr(args, "merge_mode", "deterministic"),
        init_mode=getattr(args, "init_mode", "deterministic"),
        max_rounds=args.max_rounds,
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        seed=args.seed,
    )


def _filters(args: argparse.Namespace) -> dict:
    filters: dict = {}
    if getattr(args, "levels", None):
        filters["levels"] = args.levels
    if getattr(args, "agent_counts", None):
        filters["agent_counts"] = [int(a) for a in args.agent_counts]
    if getattr(args, "cases", None):
        filters["cases"] = args.cases
    return filters


def _record(instance: BenchmarkInstance, cfg: RunConfig, score: ScoreResult) -> dict:
    return {
        "benchmark": instance.benchmark,
        "case_id": instance.case_id,
        "case_name": instance.case_name,
        "n_agents": instance.n_agents,
        "config": asdict(cfg),
        "score": asdict(score),
    }


def _cmd_run(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    base_cfg = _cfg_from_args(args)
    instance = next(adapter.iter_instances(cases=[args.case], agent_counts=[args.n_agents]))
    cfg = RunConfig(**{**asdict(base_cfg), "n_agents": instance.n_agents})
    score = run_instance(instance, cfg)
    print(json.dumps(_record(instance, cfg, score), indent=2, sort_keys=True))
    return 0


def _cmd_run_suite(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    cfg = _cfg_from_args(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for instance in adapter.iter_instances(**_filters(args)):
        run_cfg = RunConfig(**{**asdict(cfg), "n_agents": instance.n_agents})
        score = run_instance(instance, run_cfg)
        record = _record(instance, run_cfg, score)
        records.append(record)
        fname = f"{instance.case_id}_n{instance.n_agents}_seed{run_cfg.seed}.json"
        (out / fname).write_text(json.dumps(record, indent=2, sort_keys=True))
        print(f"{instance.case_id} n{instance.n_agents}: success={score.success} "
              f"answer={score.final_answer} tokens={score.tokens}")
    summary = _summarize(records)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nsuccess_rate={summary['success_rate']:.3f} over {summary['n_instances']} instances")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    records = [
        json.loads(p.read_text())
        for p in sorted(run_dir.glob("*.json"))
        if p.name != "summary.json"
    ]
    summary = _summarize(records)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _cmd_evolve(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    cfg = RunConfig(
        benchmark=args.benchmark,
        use_planner=True,
        use_skill_evolution=True,
        objective=args.objective,
        merge_mode=args.merge_mode,
        init_mode=args.init_mode,
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        seed=args.seed,
    )
    # Offline (fake LLM) Silo runs are topology-invariant on success, so by
    # default we inject a synthetic multi-topology held-out set plus a baseline
    # incumbent to make the gate decision real (see masbench.evolve). With a real
    # LLM, pass --no-synthetic-held-out to score the gate purely on the real
    # held-out Silo runs; in that mode we do NOT seed the synthetic baseline
    # incumbent (it has no real held-out measurement), so the gate compares the
    # planner's real-evidence fallback against the evolved skills.
    use_synth = getattr(args, "synthetic_held_out", True)
    incumbent = getattr(args, "seed_incumbent_topology", None) or None
    summary = run_evolution(
        adapter,
        cases=getattr(args, "cases", None),
        agent_counts=[int(a) for a in args.agent_counts] if args.agent_counts else None,
        levels=getattr(args, "levels", None),
        train_seeds=[int(s) for s in args.train_seeds],
        val_seeds=[int(s) for s in args.val_seeds],
        cfg=cfg,
        held_out_rows=accepting_held_out_rows() if use_synth else None,
        seed_incumbent_topology=incumbent if use_synth else None,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    gate = summary["gate"]
    print(
        f"gate accepted={gate['accepted']} "
        f"J_before={gate['j_before']:.6f} J_after={gate['j_after']:.6f} "
        f"epsilon={gate['epsilon']:.6f}"
    )
    print(
        f"train={summary['train_cases']} (rows={summary['n_train_rows']}, "
        f"success={summary['train_success_rate']:.3f}) | "
        f"val={summary['val_cases']} (rows={summary['n_val_rows_real']}, "
        f"success={summary['val_success_rate']:.3f})"
    )
    print(
        f"knobs={summary['objective_knobs']} | "
        f"skill_bank {summary['skill_bank_size_before']}->"
        f"{summary['skill_bank_size_after']} mutated={summary['skill_bank_mutated']}"
    )
    return 0


def _summarize(records: list[dict]) -> dict:
    n = len(records)
    successes = sum(1 for r in records if r["score"]["success"])
    tokens = sum(int(r["score"]["tokens"]) for r in records)
    messages = sum(int(r["score"]["n_messages"]) for r in records)
    return {
        "n_instances": n,
        "success_rate": (successes / n) if n else 0.0,
        "successes": successes,
        "total_tokens": tokens,
        "total_messages": messages,
        "by_case": {
            r["case_id"]: {"success": r["score"]["success"], "answer": r["score"]["final_answer"]}
            for r in records
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="masbench", description="Clean MAS benchmark pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--benchmark", default="silo_bench")
        p.add_argument("--benchmarks-dir", default="third_party/acl26-silo-bench/benchmarks")
        p.add_argument("--topology", default="mesh")
        p.add_argument("--objective", default="balanced",
                       help="planner objective: balanced | accuracy_first | budget_first")
        p.add_argument("--merge-mode", default="deterministic",
                       help="(planner) deterministic | llm_belief_merge | llm_full_merge")
        p.add_argument("--init-mode", default="deterministic",
                       help="(planner) deterministic | llm_local_solve")
        p.add_argument("--max-rounds", type=int, default=4)
        p.add_argument("--llm", dest="llm", default="fake",
                       help="fake | openai | deepseek | bailian | dashscope | qwen | alibaba | xiaomi")
        p.add_argument("--model-name", default="fake")
        p.add_argument("--base-url", default=None)
        p.add_argument("--api-key-env", default=None)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--planner", action="store_true",
                       help="enable the QueenBee planner + generalized ProtocolRunner")
        p.add_argument("--planner-mode", dest="planner_mode",
                       choices=["topology_select", "graph_generate"],
                       default="topology_select",
                       help="(planner) topology_select picks a named topology; "
                            "graph_generate has the emperor LLM invent a temporal DAG")

    p_run = sub.add_parser("run", help="run a single instance")
    add_common(p_run)
    p_run.add_argument("--case", required=True)
    p_run.add_argument("--n-agents", type=int, required=True)
    p_run.set_defaults(func=_cmd_run)

    p_suite = sub.add_parser("run-suite", help="run a grid of instances")
    add_common(p_suite)
    p_suite.add_argument("--levels", nargs="+", default=None)
    p_suite.add_argument("--agent-counts", nargs="+", default=None)
    p_suite.add_argument("--cases", nargs="+", default=None)
    p_suite.add_argument("--out", required=True)
    p_suite.set_defaults(func=_cmd_run_suite)

    p_report = sub.add_parser("report", help="aggregate a run directory")
    p_report.add_argument("--run-dir", required=True)
    p_report.set_defaults(func=_cmd_report)

    p_evolve = sub.add_parser(
        "evolve",
        help="run the gated QueenBee self-evolution loop on Silo-Bench",
    )
    add_common(p_evolve)
    p_evolve.add_argument("--levels", nargs="+", default=None)
    p_evolve.add_argument("--agent-counts", nargs="+", default=None)
    p_evolve.add_argument("--cases", nargs="+", default=None)
    p_evolve.add_argument("--train-seeds", nargs="+", default=["0"])
    p_evolve.add_argument("--val-seeds", nargs="+", default=["0"])
    p_evolve.add_argument(
        "--seed-incumbent-topology",
        default=INCUMBENT_BASELINE_TOPOLOGY,
        help="incumbent topology the planner starts from (for a real J_before)",
    )
    p_evolve.add_argument(
        "--no-synthetic-held-out",
        dest="synthetic_held_out",
        action="store_false",
        help="score the gate purely on real held-out Silo runs (real-LLM use)",
    )
    p_evolve.add_argument("--out", required=True)
    p_evolve.set_defaults(func=_cmd_evolve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
