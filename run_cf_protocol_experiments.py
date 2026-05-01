"""Run Count Frequency protocol experiments over topology schedules."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent / "exp-graph"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from exp_graph.runner import ProtocolRunner, ProtocolRunnerConfig  # noqa: E402
from exp_graph.tasks import CountFrequencyTaskAdapter  # noqa: E402


DEFAULT_TOPOLOGIES = [
    "chain",
    "star",
    "mesh",
    "static_exponential",
    "one_peer_exponential",
]
DEFAULT_AGENT_COUNTS = [2, 4, 8, 16]
DEFAULT_SEEDS = [42]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "cf_protocol_results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CF protocol topology experiments."
    )
    parser.add_argument("--array-size", type=int, default=5000)
    parser.add_argument("--value-min", type=int, default=1)
    parser.add_argument("--value-max", type=int, default=1000)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--agent-counts", nargs="+", type=int, default=DEFAULT_AGENT_COUNTS)
    parser.add_argument("--topologies", nargs="+", default=DEFAULT_TOPOLOGIES)
    parser.add_argument("--star-center", type=int, default=0)
    parser.add_argument(
        "--star-broadcast",
        action="store_true",
        help=(
            "After leaves send to the star center, let the center broadcast back "
            "to leaves. Default star protocol stops after center merge."
        ),
    )
    parser.add_argument(
        "--merge-mode",
        choices=["deterministic", "llm_belief_merge", "llm_full_merge"],
        default="deterministic",
        help=(
            "deterministic is the perfect structured merge baseline; "
            "llm_belief_merge lets the LLM update belief wording while verified "
            "CF structure is preserved; llm_full_merge evaluates the LLM's own "
            "structured CF merge."
        ),
    )
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "fake", "openai"],
        default="auto",
        help="LLM backend for LLM merge modes.",
    )
    parser.add_argument("--model-name", default="gpt-4o-mini")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--json-retry-attempts", type=int, default=2)
    parser.add_argument("--max-parallel-agents", type=int, default=1)
    parser.add_argument(
        "--max-parallel-runs",
        type=int,
        default=1,
        help=(
            "Run independent seed/topology/n_agents experiments concurrently. "
            "This multiplies API concurrency with --max-parallel-agents, so keep "
            "it small for real LLM runs."
        ),
    )
    parser.add_argument(
        "--init-mode",
        choices=["auto", "deterministic", "llm_local_solve"],
        default="auto",
        help=(
            "Initial belief construction. auto uses deterministic init for "
            "deterministic merge mode and llm_local_solve for LLM merge modes."
        ),
    )
    parser.add_argument(
        "--no-deterministic-repair",
        action="store_true",
        help=(
            "For LLM merge modes, fail instead of falling back to deterministic "
            "merge after invalid JSON or invalid CF structured_state."
        ),
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--retain-traces", action="store_true")
    parser.add_argument("--trace-dir", type=Path, default=None)
    parser.add_argument(
        "--verbose-events",
        action="store_true",
        help=(
            "Print live communication edges, LLM attempts, retry events, and "
            "retry failures while each run executes."
        ),
    )
    parser.add_argument("--average-include-min-coverage", type=float, default=1.0)
    parser.add_argument(
        "--selected-primary",
        choices=["topology_default", "vote", "average"],
        default="topology_default",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.resolved_init_mode = resolve_init_mode(args)
    configure_api_environment(args)
    ensure_dir(args.output_dir)
    ensure_dir(args.output_dir / "raw_data")
    trace_dir = args.trace_dir or (args.output_dir / "traces")
    if args.trace:
        ensure_dir(trace_dir)

    run_rows: list[dict[str, Any]] = []
    agent_rows: list[dict[str, Any]] = []
    global_rows: list[dict[str, Any]] = []

    jobs = []
    for order, (seed, topology, n_agents) in enumerate(
        (
            (seed, topology, n_agents)
            for seed in args.seeds
            for topology in args.topologies
            for n_agents in args.agent_counts
        )
    ):
        jobs.append(
            {
                "order": order,
                "seed": seed,
                "topology": topology,
                "n_agents": n_agents,
            }
        )

    max_parallel_runs = min(max(1, int(args.max_parallel_runs)), max(1, len(jobs)))
    if max_parallel_runs > 1:
        print(
            "[parallel-runs] "
            f"running up to {max_parallel_runs} experiments concurrently; "
            f"per-run max_parallel_agents={args.max_parallel_agents}"
        )

    job_results = []
    if max_parallel_runs <= 1:
        for job in jobs:
            job_results.append(run_protocol_job(args, trace_dir=trace_dir, job=job))
    else:
        with ThreadPoolExecutor(max_workers=max_parallel_runs) as executor:
            futures = {
                executor.submit(
                    run_protocol_job,
                    args,
                    trace_dir=trace_dir,
                    job=job,
                ): job
                for job in jobs
            }
            for future in as_completed(futures):
                job_results.append(future.result())

    for job_result in sorted(job_results, key=lambda item: item["order"]):
        topology = job_result["topology"]
        n_agents = job_result["n_agents"]
        seed = job_result["seed"]
        payload = job_result["payload"]
        run_row = dict(payload_to_summary(payload))
        run_rows.append(run_row)
        agent_rows.extend(
            add_run_keys(
                row,
                topology,
                n_agents,
                seed,
                args.merge_mode,
                args.resolved_init_mode,
            )
            for row in payload["agent_step_metrics"]
        )
        global_rows.extend(
            add_run_keys(
                row,
                topology,
                n_agents,
                seed,
                args.merge_mode,
                args.resolved_init_mode,
            )
            for row in payload["global_step_metrics"]
        )
        print(
            "  -> "
            f"topology={topology}, agents={n_agents}, seed={seed}, "
            f"steps={run_row['TotalSteps']}, "
            f"messages={run_row['TotalMessages']}, "
            f"calls={run_row['TotalModelCalls']}, "
            f"final_rmse={run_row['FinalRMSE']:.6f}, "
            f"vote_rmse={run_row['VoteRMSE']:.6f}, "
            f"avg_rmse={format_optional_float(run_row['AverageRMSE'])}, "
            f"exact={run_row['FinalExactMatch']}"
        )

    if not run_rows:
        raise RuntimeError("No protocol experiment runs were scheduled.")

    aggregate_rows = aggregate_run_rows(run_rows)
    write_csv(args.output_dir / "run_summary.csv", run_rows)
    write_csv(args.output_dir / "aggregate_summary.csv", aggregate_rows)
    write_csv(args.output_dir / "agent_step_metrics.csv", agent_rows)
    write_csv(args.output_dir / "global_step_metrics.csv", global_rows)
    write_json(args.output_dir / "run_summary.json", run_rows)
    write_json(args.output_dir / "aggregate_summary.json", aggregate_rows)
    generate_agent_local_error_table(agent_rows, args.output_dir)
    if not args.no_plots:
        generate_plots(run_rows, global_rows, args.output_dir)
    generate_report(run_rows, aggregate_rows, args.output_dir, plots_enabled=not args.no_plots)
    print("\nAggregate summary:")
    print(markdown_table(aggregate_rows))
    print(f"\nReport written to: {args.output_dir / 'experiment_report.md'}")
    print(f"Agent local error table written to: {args.output_dir / 'agent_local_error_table.md'}")


def run_protocol_job(
    args: argparse.Namespace,
    *,
    trace_dir: Path,
    job: dict[str, Any],
) -> dict[str, Any]:
    """Run or load one independent protocol experiment."""
    seed = int(job["seed"])
    topology = str(job["topology"])
    n_agents = int(job["n_agents"])
    raw_path = raw_result_path(
        args.output_dir,
        topology,
        n_agents,
        seed,
        args.merge_mode,
        args.resolved_init_mode,
    )
    payload = None
    if args.resume and raw_path.exists():
        cached_payload = read_json(raw_path)
        if payload_has_current_metric_schema(cached_payload):
            payload = cached_payload
            print(
                f"[cached] topology={topology} agents={n_agents} seed={seed}",
                flush=True,
            )
        else:
            print(
                "[stale-cache] "
                f"topology={topology} agents={n_agents} seed={seed} "
                "reason=old_metric_schema; rerunning",
                flush=True,
            )
    if payload is None:
        print(
            "[run] "
            f"topology={topology} agents={n_agents} seed={seed} "
            f"merge_mode={args.merge_mode}",
            flush=True,
        )
        task_adapter = CountFrequencyTaskAdapter()
        global_task = task_adapter.build_global_task(
            array_size=args.array_size,
            value_min=args.value_min,
            value_max=args.value_max,
            seed=seed,
        )
        config = ProtocolRunnerConfig(
            topology_name=topology,
            n_agents=n_agents,
            seed=seed,
            model_name=(
                "deterministic"
                if (
                    args.merge_mode == "deterministic"
                    and args.resolved_init_mode == "deterministic"
                )
                else args.model_name
            ),
            merge_mode=args.merge_mode,
            init_mode=args.resolved_init_mode,
            llm_provider=args.llm_provider,
            temperature=args.temperature,
            json_retry_attempts=args.json_retry_attempts,
            allow_deterministic_repair=not args.no_deterministic_repair,
            max_parallel_agents=args.max_parallel_agents,
            trace_enabled=args.trace,
            save_prompts=args.trace,
            retain_traces=args.retain_traces,
            trace_dir=str(trace_dir) if args.trace else None,
            star_center=args.star_center,
            include_star_broadcast=args.star_broadcast,
            average_include_min_coverage=args.average_include_min_coverage,
            selected_primary=args.selected_primary,
            verbose_events=args.verbose_events,
            run_id=(
                f"cf_protocol_{args.resolved_init_mode}_{args.merge_mode}_"
                f"{topology}_n{n_agents}_seed{seed}"
            ),
        )
        result = ProtocolRunner(
            config=config,
            task_adapter=task_adapter,
            global_task=global_task,
        ).run()
        payload = result.model_dump(mode="json")
        write_json(raw_path, payload)

    return {
        "order": int(job["order"]),
        "seed": seed,
        "topology": topology,
        "n_agents": n_agents,
        "payload": payload,
    }


def configure_api_environment(args: argparse.Namespace) -> None:
    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key
    if args.base_url:
        os.environ["OPENAI_BASE_URL"] = args.base_url
    needs_llm = (
        args.merge_mode != "deterministic"
        or getattr(args, "resolved_init_mode", resolve_init_mode(args)) == "llm_local_solve"
    )
    if needs_llm and args.llm_provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is required for --llm-provider openai. "
                "Pass --api-key, export OPENAI_API_KEY, or use --llm-provider fake."
            )


def resolve_init_mode(args: argparse.Namespace) -> str:
    if args.init_mode != "auto":
        return args.init_mode
    return "deterministic" if args.merge_mode == "deterministic" else "llm_local_solve"


def payload_to_summary(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload["config"]
    global_task = payload["global_task"]
    final = payload["final_result"]
    vote = final["vote"]
    average = final.get("average")
    return {
        "Task": "count_frequency_protocol",
        "Topology": config["topology_name"],
        "Agents": int(config["n_agents"]),
        "ArraySize": int(global_task["array_length"]),
        "ValueMin": int(global_task["value_min"]),
        "ValueMax": int(global_task["value_max"]),
        "Seed": int(config["seed"]),
        "MergeMode": config["merge_mode"],
        "InitMode": config.get("init_mode", "deterministic"),
        "Provider": config.get("llm_provider"),
        "Model": config.get("model_name"),
        "Temperature": config.get("temperature"),
        "TotalSteps": int(payload["total_steps"]),
        "TotalMessages": int(payload["total_messages"]),
        "TotalModelCalls": int(payload.get("total_model_calls", 0)),
        "TotalPromptTokens": int(payload.get("total_prompt_tokens", 0)),
        "TotalCompletionTokens": int(payload.get("total_completion_tokens", 0)),
        "TotalRetryAttempts": int(payload.get("total_retry_attempts", 0)),
        "TotalDeterministicFallbacks": int(
            payload.get("total_deterministic_fallbacks", 0)
        ),
        "AggregationMethod": final["aggregation_method"],
        "SelectedPrimary": final["selected_primary"],
        "FinalRMSE": float(final["rmse"]),
        "FinalNormalizedL1Error": float(final["normalized_l1_error"]),
        "FinalExactMatch": bool(final["exact_match"]),
        "VoteRMSE": float(vote["rmse"]),
        "VoteNormalizedL1Error": float(vote["normalized_l1_error"]),
        "VoteTopRatio": vote["top_ratio"],
        "AverageRMSE": float(average["rmse"]) if average else None,
        "AverageNormalizedL1Error": (
            float(average["normalized_l1_error"]) if average else None
        ),
        "AverageIncludedAgents": len(average["included_agents"]) if average else 0,
        "VoteAverageDisagreementRMSE": final["vote_average_disagreement_rmse"],
        "FinalKey": final["final_key"],
    }


def aggregate_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row["Topology"],
                int(row["Agents"]),
                row["MergeMode"],
                row.get("InitMode", "deterministic"),
            )
        ].append(row)

    aggregate_rows = []
    for (topology, agents, merge_mode, init_mode), group in sorted(grouped.items()):
        aggregate_rows.append(
            {
                "Topology": topology,
                "Agents": agents,
                "MergeMode": merge_mode,
                "InitMode": init_mode,
                "Runs": len(group),
                "MeanFinalRMSE": mean(row["FinalRMSE"] for row in group),
                "StdFinalRMSE": stddev(row["FinalRMSE"] for row in group),
                "MeanVoteRMSE": mean(row["VoteRMSE"] for row in group),
                "MeanAverageRMSE": mean_optional(row["AverageRMSE"] for row in group),
                "MeanFinalNormalizedL1Error": mean(
                    row["FinalNormalizedL1Error"] for row in group
                ),
                "ExactMatchRate": mean(
                    1.0 if row["FinalExactMatch"] else 0.0 for row in group
                ),
                "MeanTotalSteps": mean(row["TotalSteps"] for row in group),
                "MeanTotalMessages": mean(row["TotalMessages"] for row in group),
                "MeanTotalModelCalls": mean(row["TotalModelCalls"] for row in group),
                "MeanTotalPromptTokens": mean(row["TotalPromptTokens"] for row in group),
                "MeanTotalCompletionTokens": mean(
                    row["TotalCompletionTokens"] for row in group
                ),
                "MeanDeterministicFallbacks": mean(
                    row["TotalDeterministicFallbacks"] for row in group
                ),
                "MeanVoteTopRatio": mean(row["VoteTopRatio"] for row in group),
                "MeanVoteAverageDisagreementRMSE": mean_optional(
                    row["VoteAverageDisagreementRMSE"] for row in group
                ),
            }
        )
    return aggregate_rows


def generate_plots(
    run_rows: list[dict[str, Any]],
    global_rows: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    try:
        import os

        os.environ.setdefault("MPLCONFIGDIR", str(output_dir / ".mpl-cache"))
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required for plots. Install exp-graph[analysis] "
            "or rerun with --no-plots."
        ) from exc

    plot_run_metric(run_rows, output_dir / "final_rmse.png", "Final RMSE", "FinalRMSE", plt)
    plot_run_metric(
        run_rows,
        output_dir / "vote_rmse.png",
        "Vote RMSE",
        "VoteRMSE",
        plt,
    )
    plot_run_metric(
        run_rows,
        output_dir / "average_rmse.png",
        "Average RMSE",
        "AverageRMSE",
        plt,
    )
    plot_step_metric(
        global_rows,
        output_dir / "mean_agent_rmse_by_step.png",
        "Mean Agent Local RMSE by Step",
        "mean_agent_rmse",
        plt,
    )
    plot_step_metric(
        global_rows,
        output_dir / "mean_agent_global_rmse_by_step.png",
        "Mean Agent Global RMSE by Step",
        "mean_agent_global_rmse",
        plt,
    )
    plot_step_metric(
        global_rows,
        output_dir / "mean_coverage_by_step.png",
        "Mean Coverage by Step",
        "mean_coverage",
        plt,
    )


def plot_run_metric(rows, output_path: Path, title: str, metric: str, plt) -> None:
    plt.figure(figsize=(8, 5))
    for topology in unique_values(rows, "Topology"):
        sub_rows = sorted(
            [row for row in rows if row["Topology"] == topology],
            key=lambda row: (row["Agents"], row["Seed"]),
        )
        plt.plot(
            [row["Agents"] for row in sub_rows],
            [safe_plot_value(row.get(metric)) for row in sub_rows],
            marker="o",
            linewidth=2,
            label=topology,
        )
    plt.title(title)
    plt.xlabel("Agents")
    plt.ylabel(metric)
    plt.xticks(sorted(unique_values(rows, "Agents")))
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def plot_step_metric(rows, output_path: Path, title: str, metric: str, plt) -> None:
    plt.figure(figsize=(10, 5))
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["Topology"], int(row["Agents"]))].append(row)
    for (topology, agents), group in sorted(grouped.items()):
        points: dict[int, list[float]] = defaultdict(list)
        for row in group:
            if metric not in row or row.get(metric) is None:
                continue
            points[int(row["step_idx"])].append(float(row[metric]))
        if not points:
            continue
        xs = sorted(points)
        ys = [statistics.fmean(points[x]) for x in xs]
        plt.plot(xs, ys, marker="o", linewidth=1.8, label=f"{topology} n={agents}")
    plt.title(title)
    plt.xlabel("Step index (-1 is initial)")
    plt.ylabel(metric)
    plt.legend(fontsize=7)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def generate_report(
    run_rows: list[dict[str, Any]],
    aggregate_rows: list[dict[str, Any]],
    output_dir: Path,
    *,
    plots_enabled: bool,
) -> None:
    with (output_dir / "experiment_report.md").open("w", encoding="utf-8") as handle:
        handle.write("# CF Protocol Topology Experiment\n\n")
        if run_rows:
            first = run_rows[0]
            handle.write("## Configuration\n\n")
            handle.write(f"- Array size: `{first['ArraySize']}`\n")
            handle.write(f"- Value range: `[{first['ValueMin']}, {first['ValueMax']}]`\n")
            handle.write(f"- Seeds: `{sorted(unique_values(run_rows, 'Seed'))}`\n")
            handle.write(f"- Agent counts: `{sorted(unique_values(run_rows, 'Agents'))}`\n")
            handle.write(f"- Topologies: `{sorted(unique_values(run_rows, 'Topology'))}`\n")
            handle.write(f"- Merge modes: `{sorted(unique_values(run_rows, 'MergeMode'))}`\n")
            handle.write(f"- Init modes: `{sorted(unique_values(run_rows, 'InitMode'))}`\n")
            handle.write(f"- Provider: `{first['Provider']}`\n")
            handle.write(f"- Model: `{first['Model']}`\n")
        handle.write("\n## Aggregate Results\n\n")
        handle.write(markdown_table(aggregate_rows) + "\n\n")
        handle.write("## Run Results\n\n")
        handle.write(markdown_table(run_rows) + "\n\n")
        handle.write(
            "This experiment uses the existing AgentState, BeliefState, and "
            "OutboxMessage data path. The protocol runner changes only which "
            "agents send and receive on each communication step.\n\n"
        )
        handle.write(
            "Agent-step RMSE is local by default: each agent answer is compared "
            "with the scoring-only truth for the source shards currently carried "
            "by that agent. `global_rmse` is recorded in parallel against the full "
            "global answer. RMSE is computed as root-sum-squared count error over "
            "the value domain, without dividing by domain size.\n\n"
        )
        handle.write(
            "Per-agent, per-frame local error is written to "
            "`agent_local_error_table.md`.\n\n"
        )
        if plots_enabled:
            handle.write("## Visualizations\n\n")
            handle.write("![Final RMSE](final_rmse.png)\n\n")
            handle.write("![Vote RMSE](vote_rmse.png)\n\n")
            handle.write("![Average RMSE](average_rmse.png)\n\n")
            handle.write("![Mean Agent RMSE](mean_agent_rmse_by_step.png)\n\n")
            handle.write(
                "![Mean Agent Global RMSE](mean_agent_global_rmse_by_step.png)\n\n"
            )
            handle.write("![Mean Coverage](mean_coverage_by_step.png)\n\n")


def generate_agent_local_error_table(
    agent_rows: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    """Write a compact Markdown table for per-agent per-frame local error."""
    path = output_dir / "agent_local_error_table.md"
    columns = [
        "Topology",
        "Agents",
        "Seed",
        "MergeMode",
        "InitMode",
        "Frame",
        "Phase",
        "Agent",
        "ActiveReceiver",
        "Received",
        "KnownSources",
        "KnownSourceCount",
        "KnownItemCount",
        "Coverage",
        "LocalRMSE",
        "GlobalRMSE",
        "LocalL1",
        "GlobalL1",
        "LocalExact",
        "GlobalExact",
    ]
    table_rows = [
        {
            "Topology": row.get("Topology"),
            "Agents": row.get("Agents"),
            "Seed": row.get("Seed"),
            "MergeMode": row.get("MergeMode"),
            "InitMode": row.get("InitMode"),
            "Frame": row.get("step_idx"),
            "Phase": row.get("phase"),
            "Agent": row.get("agent_id"),
            "ActiveReceiver": row.get("active_receiver"),
            "Received": row.get("received_count"),
            "KnownSources": row.get("known_sources"),
            "KnownSourceCount": row.get("known_source_count"),
            "KnownItemCount": row.get("known_item_count"),
            "Coverage": row.get("coverage_ratio"),
            "LocalRMSE": row.get("local_rmse", row.get("rmse")),
            "GlobalRMSE": row.get("global_rmse"),
            "LocalL1": row.get(
                "local_normalized_l1_error",
                row.get("normalized_l1_error"),
            ),
            "GlobalL1": row.get("global_normalized_l1_error"),
            "LocalExact": row.get("local_exact_match", row.get("exact_match")),
            "GlobalExact": row.get("global_exact_match"),
        }
        for row in sorted(
            agent_rows,
            key=lambda item: (
                str(item.get("Topology", "")),
                int(item.get("Agents", 0)),
                int(item.get("Seed", 0)),
                str(item.get("MergeMode", "")),
                str(item.get("InitMode", "")),
                int(item.get("step_idx", 0)),
                int(item.get("agent_id", 0)),
            ),
        )
    ]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Agent Local Error Table\n\n")
        handle.write(
            "`Frame = -1` is the post-initialization state. `LocalRMSE` compares "
            "the agent's `merged_counts` with the scoring-only truth for its "
            "`KnownSources`; `GlobalRMSE` compares the same answer with the full "
            "global answer.\n\n"
        )
        handle.write(markdown_table_for_columns(table_rows, columns) + "\n")


def markdown_table_for_columns(
    rows: list[dict[str, Any]],
    columns: list[str],
) -> str:
    if not rows:
        return "(no rows)"
    table = ["| " + " | ".join(columns) + " |"]
    table.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        table.append(
            "| "
            + " | ".join(format_table_value(row.get(column)) for column in columns)
            + " |"
        )
    return "\n".join(table)


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(no rows)"
    preferred = [
        "Topology",
        "Agents",
        "MergeMode",
        "InitMode",
        "Runs",
        "Seed",
        "TotalSteps",
        "TotalMessages",
        "TotalModelCalls",
        "TotalRetryAttempts",
        "TotalDeterministicFallbacks",
        "MeanFinalRMSE",
        "StdFinalRMSE",
        "FinalRMSE",
        "VoteRMSE",
        "AverageRMSE",
        "MeanAverageRMSE",
        "FinalNormalizedL1Error",
        "ExactMatchRate",
        "FinalExactMatch",
        "VoteTopRatio",
    ]
    columns = [column for column in preferred if column in rows[0]]
    columns.extend(column for column in rows[0] if column not in columns and column != "FinalKey")
    table = ["| " + " | ".join(columns) + " |"]
    table.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        table.append(
            "| "
            + " | ".join(format_table_value(row.get(column)) for column in columns)
            + " |"
        )
    return "\n".join(table)


def add_run_keys(
    row: dict[str, Any],
    topology: str,
    n_agents: int,
    seed: int,
    merge_mode: str,
    init_mode: str = "deterministic",
) -> dict[str, Any]:
    enriched = dict(row)
    enriched["Topology"] = topology
    enriched["Agents"] = n_agents
    enriched["Seed"] = seed
    enriched["MergeMode"] = merge_mode
    enriched["InitMode"] = init_mode
    return enriched


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({key: csv_value(row.get(key)) for key in rows[0]} for row in rows)


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def payload_has_current_metric_schema(payload: dict[str, Any]) -> bool:
    agent_metrics = payload.get("agent_step_metrics") or []
    if not agent_metrics:
        return False
    first_row = agent_metrics[0]
    return (
        "local_rmse" in first_row
        and "global_rmse" in first_row
        and "known_item_count" in first_row
    )


def raw_result_path(
    output_dir: Path,
    topology: str,
    n_agents: int,
    seed: int,
    merge_mode: str,
    init_mode: str = "deterministic",
) -> Path:
    init_prefix = "" if init_mode == "deterministic" else f"{init_mode}_"
    return (
        output_dir
        / "raw_data"
        / f"cf_protocol_{init_prefix}{merge_mode}_{topology}_n{n_agents}_seed{seed}.json"
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def mean(values) -> float:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return math.nan
    return statistics.fmean(numeric)


def mean_optional(values) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return statistics.fmean(numeric)


def stddev(values) -> float:
    numeric = [float(value) for value in values if value is not None]
    if len(numeric) < 2:
        return 0.0
    return statistics.stdev(numeric)


def unique_values(rows: list[dict[str, Any]], key: str) -> list[Any]:
    return sorted({row[key] for row in rows})


def safe_plot_value(value: Any) -> float:
    if value is None:
        return math.nan
    return float(value)


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return value


def format_table_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if value is None:
        return "None"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def format_optional_float(value: Any) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.6f}"


if __name__ == "__main__":
    main()
