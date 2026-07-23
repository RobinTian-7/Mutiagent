"""Command-line tools for MAS skill bootstrap, selection, and search."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exp_graph.mas.benchmark import build_benchmark_report
from exp_graph.mas.evolution import (
    build_evolution_batch_from_experiment_dir,
    consolidate_batch,
)
from exp_graph.mas.consolidation import evolve_skill_dir
from exp_graph.mas.evidence import (
    default_evidence_output_path,
    ingest_experiment_evidence,
    write_evidence_jsonl,
)
from exp_graph.mas.formatting import format_evolution_result
from exp_graph.mas.matrix import (
    analyze_matrix_insights,
    collect_matrix,
    run_matrix,
)
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.pipeline import run_mas_pipeline
from exp_graph.mas.schemas import MASRuntimeConfig, PlannerRequest
from exp_graph.mas.search import search_candidates
from exp_graph.mas.skill_bank import (
    SkillBank,
    compact_skill_dir,
    render_skill_bank_markdown,
)
from exp_graph.mas.workflow import (
    WORKFLOW_NODES,
    WorkflowRunOptions,
    load_workflow_config,
    run_workflow,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="MAS emperor skill tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--experiment-dir", type=Path, required=True)
    bootstrap.add_argument("--skill-dir", type=Path, required=True)
    bootstrap.add_argument("--markdown-dir", type=Path, default=None)

    select = subparsers.add_parser("select")
    select.add_argument("--skill-dir", type=Path, required=True)
    select.add_argument("--n-agents", type=int, required=True)
    select.add_argument(
        "--objective",
        choices=["accuracy_first", "budget_first", "balanced"],
        default="balanced",
    )
    select.add_argument(
        "--budget",
        choices=["loose", "normal", "tight"],
        default="normal",
    )
    select.add_argument(
        "--planner-mode",
        choices=["topology_select", "operator_compose", "graph_generate"],
        default="topology_select",
    )

    search = subparsers.add_parser("search")
    search.add_argument("--skill-dir", type=Path, required=True)
    search.add_argument("--n-agents", type=int, required=True)
    search.add_argument(
        "--objective",
        choices=["accuracy_first", "budget_first", "balanced"],
        default="balanced",
    )
    search.add_argument("--top-k", type=int, default=5)

    ingest = subparsers.add_parser("ingest-evidence")
    ingest.add_argument("--experiment-dir", type=Path, required=True)
    ingest.add_argument("--evidence-dir", type=Path, required=True)
    ingest.add_argument("--output-file", type=Path, default=None)

    evolve = subparsers.add_parser("evolve-skills")
    evolve.add_argument("--skill-dir", type=Path, required=True)
    evolve.add_argument("--evidence-file", type=Path, default=None)
    evolve.add_argument("--patch-dir", type=Path, required=True)
    evolve.add_argument("--include-insights", action="store_true")
    evolve.add_argument("--backup", action="store_true")
    evolve.add_argument("--markdown-dir", type=Path, default=None)
    evolve.add_argument("--revision-dir", type=Path, default=None)

    compact = subparsers.add_parser("compact-skills")
    compact.add_argument("--skill-dir", type=Path, required=True)
    compact.add_argument("--output-dir", type=Path, required=True)
    compact.add_argument("--archive-dir", type=Path, required=True)
    compact.add_argument("--max-per-condition", type=int, default=3)

    run = subparsers.add_parser("run")
    run.add_argument("--skill-dir", type=Path, required=True)
    run.add_argument(
        "--objective",
        choices=["accuracy_first", "budget_first", "balanced"],
        default="balanced",
    )
    run.add_argument(
        "--budget",
        choices=["loose", "normal", "tight"],
        default="normal",
    )
    run.add_argument(
        "--planner-mode",
        choices=["topology_select", "operator_compose", "graph_generate"],
        default="topology_select",
    )
    run.add_argument(
        "--planner-policy",
        choices=[
            "skill_grounded",
            "llm_free",
            "fixed_topology",
            "topology_sweep",
            "free_graph",
        ],
        default="skill_grounded",
    )
    run.add_argument("--fixed-topology", default=None)
    run.add_argument("--n-agents", type=int, required=True)
    run.add_argument("--array-size", type=int, default=64)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument(
        "--merge-mode",
        choices=["deterministic", "llm_belief_merge", "llm_full_merge"],
        default="deterministic",
    )
    run.add_argument(
        "--init-mode",
        choices=["deterministic", "llm_local_solve"],
        default="deterministic",
    )
    run.add_argument(
        "--llm-provider",
        choices=["auto", "fake", "openai"],
        default="fake",
    )
    run.add_argument("--model-name", default="fake")
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--json-retry-attempts", type=int, default=2)
    run.add_argument("--max-parallel-agents", type=int, default=1)
    run.add_argument("--max-parallel-ministers", type=int, default=1)
    run.add_argument("--trace", action="store_true")
    run.add_argument("--retain-traces", action="store_true")
    run.add_argument("--verbose-events", action="store_true")
    run.add_argument("--llm-insights", action="store_true")
    _add_graph_generation_args(run)
    run.add_argument("--output-dir", type=Path, required=True)

    run_matrix_parser = subparsers.add_parser("run-matrix")
    _add_matrix_run_args(run_matrix_parser)

    eval_matrix_parser = subparsers.add_parser("eval-matrix")
    _add_matrix_run_args(eval_matrix_parser)
    eval_matrix_parser.add_argument(
        "--phase",
        choices=["eval", "test"],
        default="eval",
    )
    eval_matrix_parser.add_argument("--disable-evolution", action="store_true")

    collect = subparsers.add_parser("collect-matrix")
    collect.add_argument("--matrix-dir", type=Path, required=True)
    collect.add_argument("--output-dir", type=Path, required=True)

    insights = subparsers.add_parser("analyze-insights")
    insights.add_argument("--skill-dir", type=Path, required=True)
    insights.add_argument("--evidence-file", type=Path, required=True)
    insights.add_argument("--summary-file", type=Path, required=True)
    insights.add_argument("--trace-summary-file", type=Path, required=True)
    insights.add_argument(
        "--llm-provider",
        choices=["auto", "fake", "openai"],
        default="fake",
    )
    insights.add_argument("--model-name", default="fake")
    insights.add_argument("--max-parallel-insight-shards", type=int, default=1)
    insights.add_argument("--output-dir", type=Path, required=True)

    benchmark = subparsers.add_parser("benchmark-report")
    benchmark.add_argument("--fixed-collected-dir", type=Path, required=True)
    benchmark.add_argument("--v0-collected-dir", type=Path, required=True)
    benchmark.add_argument("--v1-collected-dir", type=Path, required=True)
    benchmark.add_argument("--output-dir", type=Path, required=True)

    workflow = subparsers.add_parser("run-workflow")
    _add_workflow_args(workflow)

    args = parser.parse_args()
    if args.command == "bootstrap":
        batch = build_evolution_batch_from_experiment_dir(args.experiment_dir)
        bank = consolidate_batch(batch)
        bank.save_dir(args.skill_dir)
        if args.markdown_dir is not None:
            render_skill_bank_markdown(bank, args.markdown_dir)
        print(
            json.dumps(
                {
                    "skills": len(bank),
                    "patches": len(batch.patches),
                    "skill_dir": str(args.skill_dir),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command == "select":
        bank = SkillBank.load_dir(args.skill_dir)
        request = PlannerRequest.from_names(
            n_agents=args.n_agents,
            objective=args.objective,
            budget=args.budget,
            planner_mode=args.planner_mode,
        )
        plan = EmperorPlanner(bank).plan(request)
        print(json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True))
        return

    if args.command == "search":
        bank = SkillBank.load_dir(args.skill_dir)
        request = PlannerRequest.from_names(
            n_agents=args.n_agents,
            objective=args.objective,
        )
        results = search_candidates(
            request=request,
            skill_bank=bank,
            top_k=args.top_k,
        )
        print(
            json.dumps(
                [result.__dict__ for result in results],
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command == "ingest-evidence":
        records = ingest_experiment_evidence(args.experiment_dir)
        output_file = args.output_file or default_evidence_output_path(
            experiment_dir=args.experiment_dir,
            evidence_dir=args.evidence_dir,
        )
        write_evidence_jsonl(records, output_file)
        print(
            json.dumps(
                {
                    "records": len(records),
                    "evidence_file": str(output_file),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command == "evolve-skills":
        result = evolve_skill_dir(
            skill_dir=args.skill_dir,
            evidence_file=args.evidence_file,
            patch_dir=args.patch_dir,
            backup=args.backup,
            markdown_dir=args.markdown_dir,
            revision_dir=args.revision_dir,
        )
        print("[evolve-skills]")
        print(format_evolution_result(result))
        return

    if args.command == "compact-skills":
        result = compact_skill_dir(
            skill_dir=args.skill_dir,
            output_dir=args.output_dir,
            archive_dir=args.archive_dir,
            max_per_condition=args.max_per_condition,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "run":
        bank = SkillBank.load_dir(args.skill_dir)
        request = PlannerRequest.from_names(
            n_agents=args.n_agents,
            objective=args.objective,
            budget=args.budget,
            planner_mode=args.planner_mode,
            array_size=args.array_size,
            merge_mode=args.merge_mode,
            init_mode=args.init_mode,
        )
        runtime = MASRuntimeConfig(
            llm_provider=args.llm_provider,
            model_name=args.model_name,
            temperature=args.temperature,
            json_retry_attempts=args.json_retry_attempts,
            max_parallel_agents=args.max_parallel_agents,
            max_parallel_ministers=args.max_parallel_ministers,
            trace_enabled=args.trace,
            retain_traces=args.retain_traces,
            verbose_events=args.verbose_events,
            output_dir=str(args.output_dir),
            graph_search_mode=args.graph_search_mode,
            num_graph_candidates=args.num_graph_candidates,
            graph_top_k=args.graph_top_k,
            graph_candidate_score_mode=args.graph_candidate_score_mode,
            graph_max_steps=args.graph_max_steps,
            graph_max_messages=args.graph_max_messages,
            graph_max_receiver_fan_in=args.graph_max_receiver_fan_in,
            graph_repair_attempts=args.graph_repair_attempts,
            graph_validation_seeds=_parse_int_list(args.graph_validation_seeds),
        )
        result = run_mas_pipeline(
            request=request,
            runtime=runtime,
            skill_bank=bank,
            seed=args.seed,
            llm_insights=args.llm_insights,
            print_sections=True,
            planner_policy=args.planner_policy,
            fixed_topology=args.fixed_topology,
        )
        print(
            json.dumps(
                {
                    "output_dir": result.output_dir,
                    "patches": len(result.patches),
                    "final_rmse": result.protocol_result.final_result.rmse,
                    "exact_match": result.protocol_result.final_result.exact_match,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command in {"run-matrix", "eval-matrix"}:
        result = run_matrix(
            skill_dir=args.skill_dir,
            output_dir=args.output_dir,
            objectives=_parse_str_list(args.objectives),
            planner_modes=_parse_str_list(args.planner_modes),
            planner_policies=_parse_str_list(args.planner_policies),
            topologies=_parse_str_list(args.topologies),
            n_agents_values=_parse_int_list(args.n_agents),
            array_sizes=_parse_int_list(args.array_sizes),
            seeds=_parse_int_list(args.seeds),
            llm_provider=args.llm_provider,
            model_name=args.model_name,
            merge_mode=args.merge_mode,
            init_mode=args.init_mode,
            trace_enabled=args.trace,
            retain_traces=args.retain_traces,
            verbose_events=args.verbose_events,
            max_parallel_runs=args.max_parallel_runs,
            max_parallel_agents=args.max_parallel_agents,
            max_parallel_ministers=args.max_parallel_ministers,
            graph_search_mode=args.graph_search_mode,
            num_graph_candidates=args.num_graph_candidates,
            graph_top_k=args.graph_top_k,
            graph_candidate_score_mode=args.graph_candidate_score_mode,
            graph_max_steps=args.graph_max_steps,
            graph_max_messages=args.graph_max_messages,
            graph_max_receiver_fan_in=args.graph_max_receiver_fan_in,
            graph_repair_attempts=args.graph_repair_attempts,
            graph_validation_seeds=_parse_int_list(args.graph_validation_seeds),
            phase=getattr(args, "phase", "train"),
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return

    if args.command == "collect-matrix":
        result = collect_matrix(
            matrix_dir=args.matrix_dir,
            output_dir=args.output_dir,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return

    if args.command == "analyze-insights":
        report = analyze_matrix_insights(
            skill_dir=args.skill_dir,
            evidence_file=args.evidence_file,
            summary_file=args.summary_file,
            trace_summary_file=args.trace_summary_file,
            llm_provider=args.llm_provider,
            model_name=args.model_name,
            max_parallel_insight_shards=args.max_parallel_insight_shards,
            output_dir=args.output_dir,
        )
        print(
            json.dumps(
                {
                    "report_id": report.report_id,
                    "insights": len(report.key_insights),
                    "patches": len(report.skill_update_recommendations),
                    "rejected": len(report.rejected_insights),
                    "output_dir": str(args.output_dir),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command == "benchmark-report":
        result = build_benchmark_report(
            fixed_collected_dir=args.fixed_collected_dir,
            v0_collected_dir=args.v0_collected_dir,
            v1_collected_dir=args.v1_collected_dir,
            output_dir=args.output_dir,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return

    if args.command == "run-workflow":
        config = load_workflow_config(
            args.workflow_config,
            overrides=_workflow_overrides(args),
        )
        try:
            state = run_workflow(
                config,
                WorkflowRunOptions(
                    workflow_backend=args.workflow_backend,
                    dry_run=args.dry_run,
                    debug=args.debug,
                    resume=args.resume,
                    stop_after=args.stop_after,
                    only_node=args.only_node,
                    resume_from=args.resume_from,
                    pause_before_evolve=args.pause_before_evolve,
                    inspect_artifacts=args.inspect_artifacts,
                    save_node_logs=not args.no_save_node_logs,
                ),
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            json.dumps(
                {
                    "workflow_id": state.workflow_id,
                    "output_dir": state.output_dir,
                    "current_node": state.current_node,
                    "failed_node": state.failed_node,
                    "report": state.artifact_paths.get("workflow_report", ""),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return


def _add_matrix_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--objectives", default="accuracy_first")
    parser.add_argument("--planner-modes", default="operator_compose")
    parser.add_argument("--planner-policies", default="skill_grounded")
    parser.add_argument("--topologies", default="")
    parser.add_argument("--n-agents", required=True)
    parser.add_argument("--array-sizes", required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "fake", "openai"],
        default="fake",
    )
    parser.add_argument("--model-name", default="fake")
    parser.add_argument(
        "--merge-mode",
        choices=["deterministic", "llm_belief_merge", "llm_full_merge"],
        default="deterministic",
    )
    parser.add_argument(
        "--init-mode",
        choices=["deterministic", "llm_local_solve"],
        default="deterministic",
    )
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--retain-traces", action="store_true")
    parser.add_argument("--verbose-events", action="store_true")
    _add_graph_generation_args(parser)
    parser.add_argument("--max-parallel-runs", type=int, default=1)
    parser.add_argument("--max-parallel-agents", type=int, default=1)
    parser.add_argument("--max-parallel-ministers", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)


def _add_workflow_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workflow-backend",
        choices=["shell", "langgraph"],
        default="shell",
    )
    parser.add_argument("--workflow-config", type=Path, default=None)
    parser.add_argument("--repo-dir", type=Path, default=None)
    parser.add_argument("--python-bin", default=None)
    parser.add_argument("--skill-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--objectives", default=None)
    parser.add_argument("--topologies", default=None)
    parser.add_argument("--n-agents", default=None)
    parser.add_argument("--array-sizes", default=None)
    parser.add_argument("--train-seeds", default=None)
    parser.add_argument("--test-seeds", default=None)
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "fake", "openai"],
        default=None,
    )
    parser.add_argument("--model-name", default=None)
    parser.add_argument(
        "--merge-mode",
        choices=["deterministic", "llm_belief_merge", "llm_full_merge"],
        default=None,
    )
    parser.add_argument(
        "--init-mode",
        choices=["deterministic", "llm_local_solve"],
        default=None,
    )
    parser.add_argument("--max-parallel-runs", type=int, default=None)
    parser.add_argument("--max-parallel-agents", type=int, default=None)
    parser.add_argument("--max-parallel-ministers", type=int, default=None)
    parser.add_argument("--max-parallel-insight-shards", type=int, default=None)
    parser.add_argument("--verbose-events", action="store_true")
    parser.add_argument("--confirm-real-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", choices=WORKFLOW_NODES, default=None)
    parser.add_argument("--only-node", choices=WORKFLOW_NODES, default=None)
    parser.add_argument("--resume-from", choices=WORKFLOW_NODES, default=None)
    parser.add_argument("--pause-before-evolve", action="store_true")
    parser.add_argument("--inspect-artifacts", action="store_true")
    parser.add_argument("--no-save-node-logs", action="store_true")
    parser.add_argument(
        "--graph-search-mode",
        choices=["single", "topk"],
        default=None,
    )
    parser.add_argument("--num-graph-candidates", type=int, default=None)
    parser.add_argument("--graph-top-k", type=int, default=None)
    parser.add_argument(
        "--graph-candidate-score-mode",
        choices=["objective", "accuracy_max"],
        default=None,
    )
    parser.add_argument("--graph-max-steps", type=int, default=None)
    parser.add_argument("--graph-max-messages", type=int, default=None)
    parser.add_argument("--graph-max-receiver-fan-in", type=int, default=None)
    parser.add_argument("--graph-repair-attempts", type=int, default=None)
    parser.add_argument("--graph-validation-seeds", default=None)


def _workflow_overrides(args: argparse.Namespace) -> dict:
    override_keys = [
        "python_bin",
        "objectives",
        "topologies",
        "n_agents",
        "array_sizes",
        "train_seeds",
        "test_seeds",
        "llm_provider",
        "model_name",
        "merge_mode",
        "init_mode",
        "max_parallel_runs",
        "max_parallel_agents",
        "max_parallel_ministers",
        "max_parallel_insight_shards",
        "graph_search_mode",
        "num_graph_candidates",
        "graph_top_k",
        "graph_candidate_score_mode",
        "graph_max_steps",
        "graph_max_messages",
        "graph_max_receiver_fan_in",
        "graph_repair_attempts",
        "graph_validation_seeds",
    ]
    overrides = {key: getattr(args, key) for key in override_keys if getattr(args, key) is not None}
    if args.repo_dir is not None:
        overrides["repo_dir"] = str(args.repo_dir)
    if args.skill_dir is not None:
        overrides["skill_dir"] = str(args.skill_dir)
    if args.output_dir is not None:
        overrides["output_dir"] = str(args.output_dir)
    if args.verbose_events:
        overrides["verbose_events"] = True
    if args.confirm_real_llm:
        overrides["confirm_real_llm"] = True
    return overrides


def _add_graph_generation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--graph-search-mode",
        choices=["single", "topk"],
        default="single",
    )
    parser.add_argument("--num-graph-candidates", type=int, default=1)
    parser.add_argument("--graph-top-k", type=int, default=1)
    parser.add_argument(
        "--graph-candidate-score-mode",
        choices=["objective", "accuracy_max"],
        default="objective",
    )
    parser.add_argument("--graph-max-steps", type=int, default=4)
    parser.add_argument("--graph-max-messages", type=int, default=32)
    parser.add_argument("--graph-max-receiver-fan-in", type=int, default=4)
    parser.add_argument("--graph-repair-attempts", type=int, default=1)
    parser.add_argument("--graph-validation-seeds", default="")


def _parse_str_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    main()
