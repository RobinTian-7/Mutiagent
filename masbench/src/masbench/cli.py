"""masbench command-line interface."""
# ============================================================
# 【模块导读】masbench 命令行入口。
# 定义 argparse 解析器与六个子命令：run(单实例)/run-suite(网格批量)/
# report(汇总运行目录)/evolve(带留出集验证门的自进化)/bench(四臂对比→表1)/
# curve(进化学习曲线)。每个子命令对应一个 _cmd_* 处理函数。
# ============================================================

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from masbench.adapters.silo_bench import SiloBenchAdapter
from masbench.bench import DEFAULT_ARMS, DEFAULT_FIXED_TOPOLOGIES, run_benchmark
from masbench.core.config import RunConfig
from masbench.core.instance import BenchmarkInstance
from masbench.core.scoring import ScoreResult
from masbench.engine import run_instance
from masbench.evolve import (
    INCUMBENT_BASELINE_TOPOLOGY,
    accepting_held_out_rows,
    run_evolution,
)


# 【职责】按 benchmark 名选择并构造对应的 BenchmarkAdapter。
# - jssp 走 JSSPBenchAdapter；silo_bench 走 SiloBenchAdapter；其它名报错退出。
def _adapter(benchmark: str, benchmarks_dir: str) -> SiloBenchAdapter:
    if benchmark == "jssp":
        from masbench.adapters.jssp_bench import JSSPBenchAdapter

        return JSSPBenchAdapter(benchmarks_dir)
    if benchmark != "silo_bench":
        raise SystemExit(f"unknown benchmark '{benchmark}' (Plan 1 supports silo_bench)")
    return SiloBenchAdapter(benchmarks_dir)


# 【职责】从 argparse 命名空间组装一个 RunConfig(用 getattr 兜底缺省的可选项)。
def _cfg_from_args(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        benchmark=args.benchmark,
        use_planner=getattr(args, "planner", False),
        sft_profile=getattr(args, "sft_profile", "off"),
        sft_state_dir=getattr(args, "sft_state_dir", None),
        sft_protocol_path=getattr(args, "sft_protocol", None),
        planner_mode=getattr(args, "planner_mode", "topology_select"),
        topology=args.topology,
        objective=getattr(args, "objective", "balanced"),
        merge_mode=getattr(args, "merge_mode", "deterministic"),
        init_mode=getattr(args, "init_mode", "deterministic"),
        max_rounds=args.max_rounds,
        max_parallel_agents=getattr(args, "max_parallel_agents", 5),
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        seed=args.seed,
        request_timeout=getattr(args, "request_timeout", 90.0),
        llm_timeout_attempts=getattr(args, "llm_timeout_attempts", 2),
        require_complete_runs=getattr(args, "require_complete_runs", False),
        silo_eval_mode=getattr(args, "silo_eval_mode", "sink"),
        python_repair_attempts=getattr(args, "python_repair_attempts", 3),
        python_gen_temperature=getattr(args, "python_gen_temperature", None),
        python_execution_timeout=getattr(args, "python_execution_timeout", None),
        python_cpu_seconds=getattr(args, "python_cpu_seconds", 10),
        python_memory_mb=getattr(args, "python_memory_mb", 512),
        python_max_output_bytes=getattr(args, "python_max_output_bytes", 1_000_000),
        python_artifacts_dir=getattr(args, "python_artifacts_dir", None),
        python_dry_run=getattr(args, "python_dry_run", True),
        python_worker_contract=getattr(
            args, "python_worker_contract", "action_json_v1"
        ),
        python_max_model_calls=getattr(args, "python_max_model_calls", 20),
        python_max_completion_tokens=getattr(
            args, "python_max_completion_tokens", 4000
        ),
        python_max_messages=getattr(args, "python_max_messages", 30),
        hot_start_enabled=getattr(args, "hot_start_enabled", False),
        hot_start_protocols=getattr(args, "hot_start_protocols", "auto"),
        hot_start_topologies=getattr(args, "hot_start_topologies", "auto"),
        hot_start_seed_count=getattr(args, "hot_start_seed_count", 1),
        hot_start_dual_branch=getattr(args, "hot_start_dual_branch", True),
        hot_start_innovation_mode=getattr(
            args, "hot_start_innovation_mode", "auto"
        ),
        python_innovation_strategy=getattr(
            args, "python_innovation_strategy", "mutate_and_fresh"
        ),
        failure_policy=getattr(args, "failure_policy", "legacy_drop"),
        evolution_gate_policy=getattr(
            args, "evolution_gate_policy", "legacy_non_regression"
        ),
        strict_gate_min_dense_delta=getattr(
            args, "strict_gate_min_dense_delta", 0.01
        ),
        strict_gate_partial_tolerance=getattr(
            args, "strict_gate_partial_tolerance", 0.0
        ),
        strict_gate_bootstrap_samples=getattr(
            args, "strict_gate_bootstrap_samples", 2000
        ),
        strict_gate_bootstrap_seed=getattr(
            args, "strict_gate_bootstrap_seed", 20260713
        ),
    )


# 【职责】从命令行参数收集实例过滤条件(levels/agent_counts/cases)成字典。
def _filters(args: argparse.Namespace) -> dict:
    filters: dict = {}
    if getattr(args, "levels", None):
        filters["levels"] = args.levels
    if getattr(args, "agent_counts", None):
        filters["agent_counts"] = [int(a) for a in args.agent_counts]
    if getattr(args, "cases", None):
        filters["cases"] = args.cases
    return filters


# 【职责】把一次运行的实例信息+配置+评分打包成一条可序列化记录字典。
def _record(instance: BenchmarkInstance, cfg: RunConfig, score: ScoreResult) -> dict:
    return {
        "benchmark": instance.benchmark,
        "case_id": instance.case_id,
        "case_name": instance.case_name,
        "n_agents": instance.n_agents,
        "config": asdict(cfg),
        "score": asdict(score),
    }


# 【职责】run 子命令：跑单个实例并把记录 JSON 打印到标准输出。
def _cmd_run(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    base_cfg = _cfg_from_args(args)
    instance = next(adapter.iter_instances(cases=[args.case], agent_counts=[args.n_agents]))
    cfg = RunConfig(**{**asdict(base_cfg), "n_agents": instance.n_agents})
    score = run_instance(instance, cfg)
    print(json.dumps(_record(instance, cfg, score), indent=2, sort_keys=True))
    return 0


# 【职责】run-suite 子命令：按过滤条件跑一批实例，逐个落盘并写 summary.json。
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


# 【职责】report 子命令：读取一个运行目录下的所有记录 JSON，汇总后打印。
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


# 【职责】evolve 子命令：在 Silo-Bench 上跑带留出集验证门的自进化循环。
# - 打开 planner 与技能进化；默认注入合成留出集使门控判定生效(见函数体注释)。
# - 打印门控接受与否、J_before/J_after、训练/验证成功率与技能库变化。
def _cmd_evolve(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    sft_profile = getattr(args, "sft_profile", "off")
    sft_state_dir = getattr(args, "sft_state_dir", None)
    sft_protocol_path = getattr(args, "sft_protocol", None)
    if sft_profile != "off" and sft_state_dir is None:
        sft_state_dir = str((Path(args.out).resolve() / "sft").resolve())
    elif sft_profile != "off":
        sft_state_dir = str(Path(sft_state_dir).resolve())
    if sft_protocol_path is not None:
        sft_protocol_path = str(Path(sft_protocol_path).resolve())
    sft_experiment_manifest = getattr(args, "sft_experiment_manifest", None)
    if sft_experiment_manifest is not None:
        sft_experiment_manifest = str(Path(sft_experiment_manifest).resolve())
    sft_runtime_authority = getattr(args, "sft_runtime_authority", None)
    if sft_runtime_authority is not None:
        sft_runtime_authority = str(Path(sft_runtime_authority).resolve())
    sft_bootstrap_authority = getattr(args, "sft_bootstrap_authority", None)
    if sft_bootstrap_authority is not None:
        sft_bootstrap_authority = str(Path(sft_bootstrap_authority).resolve())
    sft_result_dir = getattr(args, "sft_result_dir", None)
    if sft_result_dir is None and sft_profile == "phase_v5_executable_sft":
        sft_result_dir = str((Path(args.out).resolve() / "sft-results").resolve())
    elif sft_result_dir is not None:
        sft_result_dir = str(Path(sft_result_dir).resolve())
    cfg = RunConfig(
        benchmark=args.benchmark,
        use_planner=True,
        use_skill_evolution=True,
        sft_profile=sft_profile,
        sft_state_dir=sft_state_dir,
        sft_protocol_path=sft_protocol_path,
        sft_experiment_manifest_path=sft_experiment_manifest,
        sft_runtime_authority_path=sft_runtime_authority,
        sft_bootstrap_authority_path=sft_bootstrap_authority,
        sft_result_dir=sft_result_dir,
        planner_mode=getattr(args, "planner_mode", "topology_select"),
        evolved_mode=getattr(args, "planner_mode", "topology_select"),
        objective=args.objective,
        merge_mode=args.merge_mode,
        init_mode=args.init_mode,
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        seed=args.seed,
        request_timeout=getattr(args, "request_timeout", 90.0),
        silo_eval_mode=getattr(args, "silo_eval_mode", "sink"),
        max_rounds=args.max_rounds,
        max_parallel_agents=args.max_parallel_agents,
        python_repair_attempts=args.python_repair_attempts,
        python_gen_temperature=args.python_gen_temperature,
        python_execution_timeout=args.python_execution_timeout,
        python_cpu_seconds=args.python_cpu_seconds,
        python_memory_mb=args.python_memory_mb,
        python_max_output_bytes=args.python_max_output_bytes,
        python_artifacts_dir=args.python_artifacts_dir,
        python_dry_run=args.python_dry_run,
        python_worker_contract=args.python_worker_contract,
        python_max_model_calls=args.python_max_model_calls,
        python_max_completion_tokens=args.python_max_completion_tokens,
        python_max_messages=args.python_max_messages,
        hot_start_enabled=args.hot_start_enabled,
        hot_start_protocols=args.hot_start_protocols,
        hot_start_topologies=args.hot_start_topologies,
        hot_start_seed_count=args.hot_start_seed_count,
        hot_start_dual_branch=args.hot_start_dual_branch,
        hot_start_innovation_mode=args.hot_start_innovation_mode,
        failure_policy=(
            "honest_v2"
            if sft_profile != "off"
            else getattr(args, "failure_policy", "legacy_drop")
        ),
        evolution_gate_policy=(
            "strict_dense_v2"
            if sft_profile != "off"
            else getattr(
                args,
                "evolution_gate_policy",
                "legacy_non_regression",
            )
        ),
        evolve_explore=0 if sft_profile != "off" else 1,
        evidence_portfolio="" if sft_profile != "off" else "chain",
        recipe_search_budget=0 if sft_profile != "off" else 18,
        exemplar_search_budget=0 if sft_profile != "off" else 6,
    )
    # 中文：离线(fake LLM)的 Silo 运行在成功时与拓扑无关，故默认注入一个合成的
    #   多拓扑留出集加一个基线 incumbent，让门控判定变真实(见 masbench.evolve)。
    #   用真实 LLM 时，传 --no-synthetic-held-out 让门控只按真实留出 Silo 运行打分；
    #   该模式下不再播种合成基线 incumbent(它没有真实留出测量)，于是门控比较的是
    #   planner 基于真实证据的兜底 vs 进化后的技能。
    # Offline (fake LLM) Silo runs are topology-invariant on success, so by
    # default we inject a synthetic multi-topology held-out set plus a baseline
    # incumbent to make the gate decision real (see masbench.evolve). With a real
    # LLM, pass --no-synthetic-held-out to score the gate purely on the real
    # held-out Silo runs; in that mode we do NOT seed the synthetic baseline
    # incumbent (it has no real held-out measurement), so the gate compares the
    # planner's real-evidence fallback against the evolved skills.
    use_synth = (
        False
        if sft_profile != "off"
        else getattr(args, "synthetic_held_out", True)
    )
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


# 【职责】bench 子命令：论文级多臂对比，产出表1。
# - base 配置只带共享旋钮；每臂的 planner 开关由 benchmark 框架自设。
# - 支持断点续跑、并行 worker，写 results.json/csv 与 report.md。
def _cmd_bench(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    # 中文：benchmark 框架会自行设置每个实验臂的 planner 开关，故 base 配置只携带
    #   共享的运行旋钮(provider/model/objective/merge/init)。
    # The benchmark harness sets per-arm planner flags itself, so the base config
    # only carries the shared run knobs (provider/model/objective/merge/init).
    cfg_base = RunConfig(
        benchmark=args.benchmark,
        objective=args.objective,
        merge_mode=args.merge_mode,
        init_mode=args.init_mode,
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        request_timeout=getattr(args, "request_timeout", 90.0),
        evolved_mode=getattr(args, "evolved_mode", "topology_select"),
        graph_validation_seeds=getattr(args, "graph_validation_seeds", 0),
        use_llm_insights=getattr(args, "use_llm_insights", False),
        evolved_test_seeds=getattr(args, "evolved_test_seeds", 1),
        max_rounds=args.max_rounds,
        max_parallel_agents=args.max_parallel_agents,
        silo_eval_mode=getattr(args, "silo_eval_mode", "sink"),
        python_repair_attempts=args.python_repair_attempts,
        python_gen_temperature=args.python_gen_temperature,
        python_execution_timeout=args.python_execution_timeout,
        python_cpu_seconds=args.python_cpu_seconds,
        python_memory_mb=args.python_memory_mb,
        python_max_output_bytes=args.python_max_output_bytes,
        python_artifacts_dir=args.python_artifacts_dir,
        python_dry_run=args.python_dry_run,
        python_worker_contract=args.python_worker_contract,
        python_max_model_calls=args.python_max_model_calls,
        python_max_completion_tokens=args.python_max_completion_tokens,
        python_max_messages=args.python_max_messages,
        hot_start_enabled=args.hot_start_enabled,
        hot_start_protocols=args.hot_start_protocols,
        hot_start_topologies=args.hot_start_topologies,
        hot_start_seed_count=args.hot_start_seed_count,
        hot_start_dual_branch=args.hot_start_dual_branch,
        hot_start_innovation_mode=args.hot_start_innovation_mode,
    )
    results = run_benchmark(
        adapter,
        cases=getattr(args, "cases", None),
        levels=getattr(args, "levels", None),
        agent_counts=[int(a) for a in args.agent_counts] if args.agent_counts else None,
        seeds=[int(s) for s in args.seeds],
        arms=args.arms,
        cfg_base=cfg_base,
        fixed_topologies=args.fixed_topologies,
        graphgen_candidates=args.graphgen_candidates,
        out=args.out,
        resume=getattr(args, "resume", False),
        workers=getattr(args, "workers", 1),
        progress=not getattr(args, "quiet", False),
    )
    overall = results["overall"]
    bits = " ".join(
        f"{arm}={overall[arm]['success']['mean'] * 100:.1f}%"
        for arm in results["arms"]
        if arm in overall
    )
    print(f"overall success: {bits}")
    print(f"wrote results.json + results.csv + report.md to {args.out}")
    return 0


# 【职责】curve 子命令：在互斥的留出案例划分上画进化学习曲线。
# - 同时给出「训练案例数」的数据曲线与「自进化轮数」的轮数曲线，写 curves.json。
def _cmd_curve(args: argparse.Namespace) -> int:
    adapter = _adapter(args.benchmark, args.benchmarks_dir)
    cfg = RunConfig(
        benchmark=args.benchmark,
        objective=args.objective,
        merge_mode=args.merge_mode,
        init_mode=args.init_mode,
        llm_provider=args.llm,
        model_name=args.model_name,
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None),
        request_timeout=getattr(args, "request_timeout", 90.0),
        evolved_mode=args.evolved_mode,
        num_graph_candidates=args.graphgen_candidates,
        graph_validation_seeds=getattr(args, "graph_validation_seeds", 0),
        use_llm_insights=getattr(args, "use_llm_insights", False),
        max_parallel_agents=args.max_parallel_agents,
        silo_eval_mode=getattr(args, "silo_eval_mode", "sink"),
        python_repair_attempts=args.python_repair_attempts,
        python_gen_temperature=args.python_gen_temperature,
        python_execution_timeout=args.python_execution_timeout,
        python_cpu_seconds=args.python_cpu_seconds,
        python_memory_mb=args.python_memory_mb,
        python_max_output_bytes=args.python_max_output_bytes,
        python_artifacts_dir=args.python_artifacts_dir,
        python_dry_run=args.python_dry_run,
        python_worker_contract=args.python_worker_contract,
        python_max_model_calls=args.python_max_model_calls,
        python_max_completion_tokens=args.python_max_completion_tokens,
        python_max_messages=args.python_max_messages,
        hot_start_enabled=args.hot_start_enabled,
        hot_start_protocols=args.hot_start_protocols,
        hot_start_topologies=args.hot_start_topologies,
        hot_start_seed_count=args.hot_start_seed_count,
        hot_start_dual_branch=args.hot_start_dual_branch,
        hot_start_innovation_mode=args.hot_start_innovation_mode,
    )
    from masbench.curve import run_curves

    res = run_curves(
        adapter, cfg, n_agents=args.agent_count,
        seeds=[int(s) for s in args.seeds], levels=args.levels, cases=args.cases,
        holdout_frac=args.holdout_frac, data_points=args.data_points, rounds=args.rounds,
        workers=getattr(args, "workers", 1),
        progress=not getattr(args, "quiet", False),
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "curves.json").write_text(json.dumps(res, indent=2, default=str))

    def _g(pt: dict) -> str:
        g = pt.get("gate") or {}
        jb, ja = g.get("j_before"), g.get("j_after")
        return f"J={jb}/{ja}" if jb is not None else ""

    print(f"held-out TEST cases: {res['test_cases']}  |  train: {res['train_cases']}")
    print("baselines (held-out success): " + "  ".join(
        f"{k}={v * 100:.1f}%" for k, v in res["baselines"].items()))
    print(f"\nDATA curve (evolved_mode={res['evolved_mode']}) -- held-out success vs #train cases:")
    for pt in res["data_curve"]:
        print(f"  k_cases={pt['k_cases']:>2}  score={pt['score'] * 100:5.1f}%  "
              f"skills={pt['n_skills']:>2}  {_g(pt)}")
    print("\nROUNDS curve -- held-out success vs #self-evolution rounds:")
    for pt in res["rounds_curve"]:
        print(f"  round={pt['round']:>2}  score={pt['score'] * 100:5.1f}%  "
              f"skills={pt['n_skills']:>2}  {_g(pt)}")
    print(f"\nwrote curves.json to {args.out}")
    return 0


# 【职责】把一批运行记录聚合为汇总(实例数/成功率/token/消息数/按案例细分)。
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


# 【职责】构建 argparse 顶层解析器与全部子命令(run/run-suite/report/evolve/bench/curve)。
# - add_common 挂载各子命令共享的参数；每个子命令用 set_defaults(func=...) 绑定处理函数。
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="masbench", description="Clean MAS benchmark pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    # 【职责】给一个子解析器挂载所有子命令共享的参数(benchmark/拓扑/LLM/planner 等)。
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
        p.add_argument("--request-timeout", dest="request_timeout", type=float,
                       default=90.0,
                       help="per-request hard wall-clock timeout (s) for non-fake "
                            "LLM calls; a hung request fails fast (<=0 disables)")
        p.add_argument(
            "--llm-timeout-attempts",
            type=int,
            default=2,
            help="bounded attempts for a request that hits the wall-clock timeout",
        )
        p.add_argument(
            "--require-complete-runs",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="abort instead of dropping an infrastructure-failed train/eval run",
        )
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--planner", action="store_true",
                       help="enable the QueenBee planner + generalized ProtocolRunner")
        p.add_argument("--planner-mode", dest="planner_mode",
                       choices=[
                           "topology_select",
                           "graph_generate",
                           "program_generate",
                           "python_generate",
                       ],
                       default="topology_select",
                       help="(planner) topology_select picks a named topology; "
                            "graph_generate invents a free temporal DAG; "
                            "program_generate independently emits restricted "
                            "phase_program_v1 stages; python_generate emits and "
                            "sandboxes a complete constrained program.py")
        p.add_argument("--python-repair-attempts", type=int, default=3,
                       help="maximum bounded replace-code repairs for python_generate")
        p.add_argument("--python-gen-temperature", type=float, default=None,
                       help="architect temperature for python_generate (default: worker temperature)")
        p.add_argument(
            "--python-execution-timeout",
            type=float,
            default=None,
            help=(
                "whole generated-program wall-clock timeout in seconds; default "
                "derives a safe budget from per-request timeout, rounds, agent "
                "count, and --max-parallel-agents"
            ),
        )
        p.add_argument("--python-cpu-seconds", type=int, default=10)
        p.add_argument("--python-memory-mb", type=int, default=512)
        p.add_argument("--python-max-output-bytes", type=int, default=1_000_000)
        p.add_argument("--python-artifacts-dir", default=None)
        p.add_argument("--no-python-dry-run", dest="python_dry_run",
                       action="store_false",
                       help="disable the fake canary preflight (not recommended)")
        p.set_defaults(python_dry_run=True)
        p.add_argument("--python-max-model-calls", type=int, default=20)
        p.add_argument("--python-max-completion-tokens", type=int, default=4000)
        p.add_argument("--python-max-messages", type=int, default=30)
        p.add_argument(
            "--max-parallel-agents",
            type=int,
            default=5,
            help=(
                "maximum Agent LLM calls that may overlap inside one logical "
                "round; rounds themselves remain synchronized"
            ),
        )
        p.add_argument("--python-worker-contract", dest="python_worker_contract",
                       choices=["action_json_v1", "message_only_v1",
                                "message_only_v2"],
                       default="action_json_v1",
                       help="PythonGen worker output contract: action_json_v1 "
                            "(legacy worker action JSON), message_only_v1 "
                            "(planner-source routing and plain-text workers), "
                            "or message_only_v2 (synchronized final submit)")
        p.add_argument("--silo-eval-mode", dest="silo_eval_mode",
                       choices=["sink", "all_agents"], default="sink",
                       help="information goal: sink grades ONLY the designated "
                            "sink agent; all_agents requires EVERY agent to "
                            "independently hold the correct answer (prompts, "
                            "graph validation, scoring, skill banks, caches and "
                            "reports are all namespaced by this mode)")
        p.add_argument(
            "--hot-start",
            dest="hot_start_enabled",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="pretrain evolution from measured paper protocols/fixed "
                 "topologies before normal gated learning",
        )
        p.add_argument(
            "--hot-start-protocols",
            default="auto",
            help="comma-separated p2p,broadcast,sfs; auto enables all three "
                 "only in all_agents mode",
        )
        p.add_argument(
            "--hot-start-topologies",
            default="auto",
            help="comma-separated executable fixed topologies; auto picks "
                 "goal-appropriate defaults",
        )
        p.add_argument("--hot-start-seed-count", type=int, default=1)
        p.add_argument(
            "--hot-start-dual-branch",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="for each train pair run both existing-skill reuse and fresh "
                 "parent-conditioned generation",
        )
        p.add_argument(
            "--hot-start-innovation-mode",
            choices=[
                "auto",
                "graph_generate",
                "program_generate",
                "python_generate",
            ],
            default="auto",
            help="planner used by the fresh branch (auto follows the evolved "
                 "generator, or graph_generate for topology_select)",
        )
        p.add_argument(
            "--python-innovation-strategy",
            choices=["fresh", "mutate", "mutate_and_fresh"],
            default="mutate_and_fresh",
            help="Python hot-start branch policy; only active when Python "
                 "innovation is enabled",
        )
        p.add_argument(
            "--failure-policy",
            choices=["legacy_drop", "honest_v2"],
            default="legacy_drop",
            help="legacy exception dropping or typed honest failure semantics",
        )
        p.add_argument(
            "--evolution-gate-policy",
            choices=["legacy_non_regression", "strict_dense_v2"],
            default="legacy_non_regression",
        )
        p.add_argument("--strict-gate-min-dense-delta", type=float, default=0.01)
        p.add_argument("--strict-gate-partial-tolerance", type=float, default=0.0)
        p.add_argument("--strict-gate-bootstrap-samples", type=int, default=2000)
        p.add_argument("--strict-gate-bootstrap-seed", type=int, default=20260713)

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
        "--sft-profile",
        choices=[
            "off",
            "phase_v3_shadow_register",
            "phase_v4_single_writer_preliminary",
            "phase_v5_executable_sft",
        ],
        default="off",
        help=(
            "opt into the isolated Phase SFT control plane; v3 creates/loads "
            "empty authenticated state, v4 restores a pre-provisioned "
            "SQLite component bundle (both mechanics-only, no probes or "
            "efficacy claim), and v5 is the executable profile that "
            "additionally requires a sealed experiment manifest plus both "
            "frozen authority manifests"
        ),
    )
    p_evolve.add_argument(
        "--sft-state-dir",
        default=None,
        help="authoritative SFT state directory (active default: OUT/sft)",
    )
    p_evolve.add_argument(
        "--sft-protocol",
        default=None,
        help=(
            "absolute path to a frozen PilotProtocolV1 JSON file; required "
            "by phase_v4_single_writer_preliminary and phase_v5_executable_sft"
        ),
    )
    p_evolve.add_argument(
        "--sft-experiment-manifest",
        default=None,
        help=(
            "absolute path to the sealed PilotExperimentManifestV1 JSON "
            "file; required only by phase_v5_executable_sft"
        ),
    )
    p_evolve.add_argument(
        "--sft-runtime-authority",
        default=None,
        help=(
            "absolute path to the frozen runtime authority manifest; "
            "required only by phase_v5_executable_sft"
        ),
    )
    p_evolve.add_argument(
        "--sft-bootstrap-authority",
        default=None,
        help=(
            "absolute path to the frozen bootstrap authority manifest; "
            "required only by phase_v5_executable_sft"
        ),
    )
    p_evolve.add_argument(
        "--sft-result-dir",
        default=None,
        help=(
            "external result-ledger directory for phase_v5_executable_sft "
            "(active default: OUT/sft-results); never a Bank writer"
        ),
    )
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

    p_bench = sub.add_parser(
        "bench",
        help="paper-grade arm comparison (graphgen/programgen/pycodegen) -> Table 1",
    )
    add_common(p_bench)
    p_bench.add_argument("--levels", nargs="+", default=None)
    p_bench.add_argument("--agent-counts", nargs="+", default=None)
    p_bench.add_argument("--cases", nargs="+", default=None)
    p_bench.add_argument("--seeds", nargs="+", default=["0"])
    p_bench.add_argument(
        "--arms",
        nargs="+",
        default=list(DEFAULT_ARMS),
        choices=[
            "fixed",
            "select",
            "graphgen",
            "programgen",
            "pycodegen",
            "evolved",
            "p2p",
            "broadcast",
            "sfs",
        ],
        help=(
            "which arms to compare; graphgen, programgen, and pycodegen are independent; "
            "p2p/broadcast/sfs reproduce the three "
            "SILO-BENCH paper transports and require --silo-eval-mode all_agents"
        ),
    )
    p_bench.add_argument(
        "--fixed-topologies",
        dest="fixed_topologies",
        nargs="+",
        default=list(DEFAULT_FIXED_TOPOLOGIES),
        help="protocol topologies for the planner-OFF fixed baselines",
    )
    p_bench.add_argument(
        "--graphgen-candidates",
        dest="graphgen_candidates",
        type=int,
        default=4,
        help="num_graph_candidates for the graphgen arm (>1 activates motif prior)",
    )
    p_bench.add_argument("--out", required=True)
    p_bench.add_argument(
        "--resume",
        action="store_true",
        help="resume from out/runs.jsonl: skip runs already checkpointed there "
             "(a fresh run truncates it). Crashed/timed-out grids continue without "
             "re-executing finished runs.",
    )
    p_bench.add_argument(
        "--workers",
        type=int,
        default=1,
        help="number of parallel worker threads for the run grid (default 1 = "
             "sequential). The grid is I/O-bound (LLM calls release the GIL), so "
             ">1 dispatches independent run-units to a thread pool for near-linear "
             "speedup; checkpoint/resume semantics are unchanged.",
    )
    p_bench.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the live per-run progress stream (default: ON, prints a "
             "startup line then one line per finished run-unit to stdout). The "
             "final 'overall success' + 'wrote ...' summary still prints.",
    )
    p_bench.add_argument(
        "--evolved-mode",
        dest="evolved_mode",
        choices=[
            "topology_select",
            "graph_generate",
            "program_generate",
            "python_generate",
            "select_then_refine",
        ],
        default="topology_select",
        help="the evolved arm's mode. topology_select (default): evolution tunes "
             "the skill bank, then PICKS a named topology. graph_generate: the "
             "emperor DESIGNS a bespoke DAG from scratch. program_generate: "
             "evolve and deploy the independent restricted phase DSL. "
             "python_generate: evolve and deploy validated full Python programs. "
             "select_then_refine: "
             "evidence via select (bank gets the WORKING topologies' reference "
             "specs), then the emperor REFINES a DAG from those references "
             "(anchor-on-what-works).",
    )
    p_bench.add_argument(
        "--graph-validation-seeds",
        dest="graph_validation_seeds",
        type=int,
        default=0,
        help="D1: >0 turns on top-k candidate PROBE-evaluation for generated "
             "topologies (graphgen + evolved generate/refine) -- each candidate is "
             "run on this many seeds and the best is selected. 0 = off (blind pick). "
             "Real-LLM cost scales with candidates x seeds.",
    )
    p_bench.add_argument(
        "--use-llm-insights",
        dest="use_llm_insights",
        action="store_true",
        help="B2: run the LLM design-insight minister over the evolution evidence, "
             "falsify insights against held-out, and fold VERIFIED ones into the "
             "skill bank (richer design rules for generation). Extra LLM calls.",
    )
    p_bench.add_argument(
        "--evolved-test-seeds",
        dest="evolved_test_seeds",
        type=int,
        default=1,
        help="how many trailing seeds the evolved arm holds out for eval + gate "
             "(train=seeds[:-K], test=seeds[-K:]). K>1 gives the evolved arm more "
             "eval points per condition -> much lower variance.",
    )
    p_bench.set_defaults(func=_cmd_bench)

    p_curve = sub.add_parser(
        "curve", help="evolution learning curves on a disjoint held-out case split"
    )
    add_common(p_curve)
    p_curve.add_argument("--levels", nargs="+", default=None)
    p_curve.add_argument("--cases", nargs="+", default=None)
    p_curve.add_argument("--agent-count", dest="agent_count", type=int, default=5)
    p_curve.add_argument("--seeds", nargs="+", default=["1", "2", "3"])
    p_curve.add_argument("--graphgen-candidates", dest="graphgen_candidates", type=int, default=3)
    p_curve.add_argument("--graph-validation-seeds", dest="graph_validation_seeds", type=int, default=0)
    p_curve.add_argument("--use-llm-insights", dest="use_llm_insights", action="store_true")
    p_curve.add_argument(
        "--evolved-mode", dest="evolved_mode",
        choices=[
            "topology_select",
            "graph_generate",
            "program_generate",
            "python_generate",
            "select_then_refine",
        ],
        default="graph_generate",
    )
    p_curve.add_argument(
        "--holdout-frac", dest="holdout_frac", type=float, default=0.3,
        help="fraction of cases held out (disjoint) as the curve's TEST set",
    )
    p_curve.add_argument(
        "--data-points", dest="data_points", type=int, default=4,
        help="number of points on the #train-cases (data-scaling) curve",
    )
    p_curve.add_argument(
        "--rounds", dest="rounds", type=int, default=4,
        help="number of self-evolution rounds on the rounds curve",
    )
    p_curve.add_argument(
        "--workers", type=int, default=1,
        help="parallel worker threads for evidence collection + held-out evals "
             "(default 1 = sequential). LLM calls are I/O-bound, so >1 gives "
             "near-linear speedup; match it to your provider's concurrency. This "
             "is a GLOBAL cap on concurrent LLM calls, not a per-stage pool width.",
    )
    p_curve.add_argument(
        "--quiet", action="store_true",
        help="suppress the live per-phase progress lines (printed by default)",
    )
    p_curve.add_argument("--out", required=True)
    p_curve.set_defaults(func=_cmd_curve)

    return parser


# 【职责】CLI 入口：解析 argv，分发到所选子命令的 func 并返回其退出码。
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
