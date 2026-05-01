"""Run CF topology sweeps and report consensus rounds plus RMSE.

This script follows the API style of ``run_llm_experiments.py`` while keeping
secrets configurable through environment variables or CLI flags.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent / "exp-graph"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from exp_graph.configs import ExperimentConfig
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import CountFrequencyTaskAdapter
from exp_graph.tasks.count_frequency import FREQ_KEY_PREFIX, canonicalize_counts
from exp_graph.tasks.count_frequency import (
    count_frequency_consensus_key,
    counts_from_partials,
    parse_cf_state_payload,
)


DEFAULT_TOPOLOGIES = ["chain", "mesh", "one_peer_exponential"]
DEFAULT_AGENT_COUNTS = [8, 16, 32]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "cf_topology_sweep_results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare chain, mesh, and one-peer exponential topology on the "
            "count-frequency task."
        )
    )
    parser.add_argument(
        "--topologies",
        nargs="+",
        default=DEFAULT_TOPOLOGIES,
        help="Topology names to compare.",
    )
    parser.add_argument(
        "--agent-counts",
        nargs="+",
        type=int,
        default=DEFAULT_AGENT_COUNTS,
        help="Agent counts to sweep.",
    )
    parser.add_argument("--array-size", type=int, default=1000)
    parser.add_argument("--value-min", type=int, default=0)
    parser.add_argument("--value-max", type=int, default=9)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=40,
        help="High enough for chain propagation at 32 agents.",
    )
    parser.add_argument(
        "--consensus-threshold",
        type=float,
        default=0.8,
    )
    parser.add_argument(
        "--final-accept-threshold",
        type=float,
        default=0.7,
    )
    parser.add_argument(
        "--adjudication-margin",
        type=float,
        default=0.1,
    )
    parser.add_argument(
        "--llm-provider",
        choices=["fake", "openai", "auto"],
        default="openai",
        help="Use fake for dry runs; openai/auto for real LLM runs.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY", ""),
        help="API key. Defaults to OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.siliconflow.com/v1"),
        help="OpenAI-compatible base URL.",
    )
    parser.add_argument(
        "--model-name",
        default=os.environ.get("OPENAI_MODEL_NAME", "moonshotai/Kimi-K2.5"),
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--json-retry-attempts", type=int, default=2)
    parser.add_argument(
        "--config-retries",
        type=int,
        default=1,
        help="Retry a whole topology/agent-count configuration after API failures.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing raw result JSON files instead of rerunning them.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Write per-agent prompt/response traces to output_dir/traces.",
    )
    parser.add_argument(
        "--retain-traces",
        action="store_true",
        help="Also retain full traces in memory. Usually avoid this in sweeps.",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip PNG visualization generation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_api_environment(args)
    ensure_dir(args.output_dir)
    ensure_dir(args.output_dir / "raw_data")
    if args.trace:
        ensure_dir(args.output_dir / "traces")

    results = run_grid(args)
    write_outputs(results, args)
    print_results_table(results)
    print(f"\nReport written to: {args.output_dir / 'experiment_report.md'}")


def configure_api_environment(args: argparse.Namespace) -> None:
    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key
    if args.base_url:
        os.environ["OPENAI_BASE_URL"] = args.base_url

    if args.llm_provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is required for --llm-provider openai. "
            "Pass --api-key, export OPENAI_API_KEY, or use --llm-provider fake."
        )


def run_grid(args: argparse.Namespace) -> list[dict[str, Any]]:
    task_adapter = CountFrequencyTaskAdapter()
    global_task = task_adapter.build_global_task(
        array_size=args.array_size,
        seed=args.seed,
        value_min=args.value_min,
        value_max=args.value_max,
    )

    rows = []
    for topology in args.topologies:
        for n_agents in args.agent_counts:
            result_path = raw_result_path(args.output_dir, topology, n_agents, args.seed)
            if args.resume and result_path.exists():
                print(f"\n[{topology} / {n_agents}] loading cached {result_path.name}")
                rows.append(load_row(result_path))
                continue

            print(f"\n[{topology} / {n_agents}] running CF sweep item...")
            config = ExperimentConfig(
                topology_name=topology,
                n_agents=n_agents,
                max_rounds=args.max_rounds,
                seed=args.seed,
                model_name=args.model_name,
                llm_provider=args.llm_provider,
                temperature=args.temperature,
                json_retry_attempts=args.json_retry_attempts,
                consensus_threshold=args.consensus_threshold,
                final_accept_threshold=args.final_accept_threshold,
                adjudication_margin=args.adjudication_margin,
                trace_enabled=args.trace,
                save_prompts=args.trace,
                retain_traces=args.retain_traces,
                trace_dir=str(args.output_dir / "traces") if args.trace else None,
                run_id=f"cf_{topology}_n{n_agents}_seed{args.seed}",
            )
            row = run_one_config_with_retries(
                config=config,
                task_adapter=task_adapter,
                global_task=global_task,
                topology=topology,
                n_agents=n_agents,
                args=args,
            )

            write_json(result_path, row)
            rows.append(row)
            rmse_text = "NA" if row["RMSE"] is None else f"{row['RMSE']:.4f}"
            print(
                "  -> "
                f"rounds={row['RoundsToConsensus']}, "
                f"rmse={rmse_text}, "
                f"exact={row['ExactMatch']}, "
                f"status={row['Status']}"
            )

    return rows


def run_one_config_with_retries(
    *,
    config: ExperimentConfig,
    task_adapter: CountFrequencyTaskAdapter,
    global_task: dict[str, Any],
    topology: str,
    n_agents: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt_idx in range(args.config_retries + 1):
        try:
            if attempt_idx:
                print(f"  -> retrying config, attempt {attempt_idx + 1}")
            result = SynchronousRunner(
                config=config,
                task_adapter=task_adapter,
                global_task=global_task,
            ).run()
            return build_row(
                result=result,
                global_task=global_task,
                topology=topology,
                n_agents=n_agents,
                args=args,
                error=None,
            )
        except Exception as exc:
            last_error = exc
            print(f"  -> attempt {attempt_idx + 1} failed: {exc}")

    assert last_error is not None
    return build_failed_row(
        global_task=global_task,
        topology=topology,
        n_agents=n_agents,
        args=args,
        error=last_error,
    )


def build_row(
    *,
    result,
    global_task: dict[str, Any],
    topology: str,
    n_agents: int,
    args: argparse.Namespace,
    error: Exception | None,
) -> dict[str, Any]:
    final_key = result.final_result.final_key
    fallback_used = False
    pred_counts = parse_freq_key(final_key)
    if pred_counts is None:
        fallback_counts = merge_cf_state_from_agent_states(result.final_agent_states)
        if fallback_counts:
            fallback_used = True
            pred_counts = fallback_counts
            final_key = count_frequency_consensus_key(fallback_counts)
    final_key_valid = pred_counts is not None
    if pred_counts is None:
        pred_counts = {}
    rmse = compute_rmse(pred_counts, global_task["answer_counts"])
    normalized_rmse = rmse / max(1, int(global_task["array_length"]))

    return {
        "Task": "count_frequency",
        "Topology": topology,
        "Agents": n_agents,
        "ArraySize": args.array_size,
        "ValueMin": args.value_min,
        "ValueMax": args.value_max,
        "Seed": args.seed,
        "MaxRounds": args.max_rounds,
        "Model": args.model_name,
        "Provider": args.llm_provider,
        "Temperature": args.temperature,
        "StopReason": result.stop_reason,
        "AggregationMethod": result.final_result.aggregation_method,
        "FallbackUsed": fallback_used,
        "RunCompleted": True,
        "ConsensusReached": result.final_result.consensus_reached,
        "RoundsToConsensus": result.metrics.rounds_to_consensus
        if result.metrics.rounds_to_consensus is not None
        else -1,
        "StopRoundIdx": result.metrics.stop_round_idx
        if result.metrics.stop_round_idx is not None
        else -1,
        "ExactMatch": result.metrics.final_accuracy,
        "FinalKeyValid": final_key_valid,
        "RMSE": rmse,
        "NormalizedRMSE": normalized_rmse,
        "TotalModelCalls": result.metrics.total_model_calls,
        "TotalTokenCost": result.metrics.total_token_cost,
        "FinalKey": final_key,
        "ExpectedKey": global_task["answer_key"],
        "ExpectedCounts": global_task["answer_counts"],
        "PredictedCounts": canonicalize_counts(pred_counts),
        "Status": "ok" if error is None else "failed",
        "Error": "" if error is None else str(error),
    }


def build_failed_row(
    *,
    global_task: dict[str, Any],
    topology: str,
    n_agents: int,
    args: argparse.Namespace,
    error: Exception,
) -> dict[str, Any]:
    return {
        "Task": "count_frequency",
        "Topology": topology,
        "Agents": n_agents,
        "ArraySize": args.array_size,
        "ValueMin": args.value_min,
        "ValueMax": args.value_max,
        "Seed": args.seed,
        "MaxRounds": args.max_rounds,
        "Model": args.model_name,
        "Provider": args.llm_provider,
        "Temperature": args.temperature,
        "StopReason": "error",
        "AggregationMethod": "error",
        "FallbackUsed": False,
        "RunCompleted": False,
        "ConsensusReached": False,
        "RoundsToConsensus": -1,
        "StopRoundIdx": -1,
        "ExactMatch": False,
        "FinalKeyValid": False,
        "RMSE": None,
        "NormalizedRMSE": None,
        "TotalModelCalls": 0,
        "TotalTokenCost": 0,
        "FinalKey": "RUN_FAILED",
        "ExpectedKey": global_task["answer_key"],
        "ExpectedCounts": global_task["answer_counts"],
        "PredictedCounts": None,
        "Status": "failed",
        "Error": str(error),
    }


def parse_freq_key(final_key: str | None) -> dict[str, int] | None:
    if not final_key:
        return None
    text = str(final_key).strip()
    if not text.startswith(FREQ_KEY_PREFIX):
        return None
    try:
        parsed = json.loads(text[len(FREQ_KEY_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return canonicalize_counts(parsed)


def compute_rmse(pred_counts: dict[str, int], true_counts: dict[str, int]) -> float:
    pred = canonicalize_counts(pred_counts)
    truth = canonicalize_counts(true_counts)
    keys = sorted(set(pred) | set(truth), key=count_key_sorter)
    if not keys:
        return 0.0
    mse = sum((pred.get(key, 0) - truth.get(key, 0)) ** 2 for key in keys) / len(keys)
    return math.sqrt(mse)


def merge_cf_state_from_agent_states(agent_states: list[Any]) -> dict[str, int] | None:
    """Merge CF_STATE_JSON payloads from final belief states after a completed run."""
    partials: dict[str, dict[str, int]] = {}
    for state in agent_states:
        belief = getattr(state, "belief_state", None)
        if belief is None:
            continue
        payload = parse_cf_state_payload(getattr(belief, "proposal", ""))
        if not payload:
            continue
        for agent_id, counts in payload["partials"].items():
            partials[str(agent_id)] = counts
    if not partials:
        return None
    return counts_from_partials(partials)


def write_outputs(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    write_json(args.output_dir / "summary.json", rows)
    write_csv(args.output_dir / "summary.csv", rows)
    if not args.no_plots:
        generate_visualizations(rows, args.output_dir)
    generate_report(rows, args.output_dir, plots_enabled=not args.no_plots)


def generate_visualizations(rows: list[dict[str, Any]], output_dir: Path) -> None:
    mpl_cache_dir = output_dir / ".mpl-cache"
    xdg_cache_dir = output_dir / ".cache"
    ensure_dir(mpl_cache_dir)
    ensure_dir(xdg_cache_dir)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache_dir))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required for plots. Install with "
            'pip install -e "exp-graph[analysis]" or rerun with --no-plots.'
        ) from exc

    colors = {
        "chain": "#2563eb",
        "mesh": "#dc2626",
        "one_peer_exponential": "#16a34a",
    }

    plot_metric(
        rows,
        output_dir / "rounds_to_consensus.png",
        "Rounds to Consensus vs Agent Count",
        "Rounds to consensus (-1 means no consensus)",
        "RoundsToConsensus",
        colors,
        plt,
    )
    plot_metric(
        rows,
        output_dir / "rmse.png",
        "Final Answer RMSE vs Agent Count",
        "RMSE over frequency counts",
        "RMSE",
        colors,
        plt,
    )
    plot_metric(
        rows,
        output_dir / "token_cost.png",
        "Token Cost vs Agent Count",
        "Total estimated tokens",
        "TotalTokenCost",
        colors,
        plt,
    )


def plot_metric(
    rows: list[dict[str, Any]],
    output_path: Path,
    title: str,
    ylabel: str,
    metric: str,
    colors: dict[str, str],
    plt,
) -> None:
    plt.figure(figsize=(8, 5))
    for topology in unique_values(rows, "Topology"):
        sub_rows = sorted(
            [row for row in rows if row["Topology"] == topology],
            key=lambda row: row["Agents"],
        )
        plt.plot(
            [row["Agents"] for row in sub_rows],
            [safe_plot_value(row.get(metric)) for row in sub_rows],
            marker="o",
            label=topology,
            color=colors.get(topology),
            linewidth=2,
        )
    plt.title(title)
    plt.xlabel("Number of Agents")
    plt.ylabel(ylabel)
    plt.xticks(sorted(unique_values(rows, "Agents")))
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def generate_report(
    rows: list[dict[str, Any]],
    output_dir: Path,
    *,
    plots_enabled: bool,
) -> None:
    report_path = output_dir / "experiment_report.md"
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# CF Topology Sweep Report\n\n")
        handle.write("## Configuration\n\n")
        if rows:
            first = rows[0]
            handle.write(f"- Model: `{first['Model']}`\n")
            handle.write(f"- Provider: `{first['Provider']}`\n")
            handle.write(f"- Array size: `{first['ArraySize']}`\n")
            handle.write(f"- Value range: `[{first['ValueMin']}, {first['ValueMax']}]`\n")
            handle.write(f"- Max rounds: `{first['MaxRounds']}`\n")
            handle.write(f"- Seed: `{first['Seed']}`\n")
        handle.write("\n## Results\n\n")
        handle.write(markdown_table(rows) + "\n\n")
        handle.write(
            "Rows with `RunCompleted=False` are API/runtime failures. They did "
            "not reach final reducer, so they are not valid model answers.\n\n"
        )
        if plots_enabled:
            handle.write("## Visualizations\n\n")
            handle.write("![Rounds to consensus](rounds_to_consensus.png)\n\n")
            handle.write("![RMSE](rmse.png)\n\n")
            handle.write("![Token cost](token_cost.png)\n\n")
        failed = [row for row in rows if row["Status"] != "ok"]
        if failed:
            handle.write("## Failures\n\n")
            for row in failed:
                handle.write(
                    f"- `{row['Topology']}` / `{row['Agents']}` agents: "
                    f"{row['Error']}\n"
                )


def print_results_table(rows: list[dict[str, Any]]) -> None:
    print("\nCF topology sweep results:")
    print(markdown_table(rows))


def markdown_table(rows: list[dict[str, Any]]) -> str:
    columns = [
        "Topology",
        "Agents",
        "RoundsToConsensus",
        "RMSE",
        "NormalizedRMSE",
        "ExactMatch",
        "ConsensusReached",
        "RunCompleted",
        "FallbackUsed",
        "TotalModelCalls",
        "TotalTokenCost",
        "Status",
    ]
    if not rows:
        return "(no rows)"
    table = ["| " + " | ".join(columns) + " |"]
    table.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in sorted(rows, key=lambda item: (item["Topology"], item["Agents"])):
        values = []
        for column in columns:
            value = row[column]
            if isinstance(value, float):
                value = f"{value:.6f}"
            values.append(str(value))
        table.append("| " + " | ".join(values) + " |")
    return "\n".join(table)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def load_row(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        row = json.load(handle)
    return normalize_cached_row(row)


def normalize_cached_row(row: dict[str, Any]) -> dict[str, Any]:
    """Migrate older cached rows that used null final keys for run failures."""
    row.setdefault("RunCompleted", row.get("Status") == "ok")
    row.setdefault("FallbackUsed", False)
    if row.get("Status") != "ok":
        row["RunCompleted"] = False
        if row.get("FinalKey") is None:
            row["FinalKey"] = "RUN_FAILED"
        if row.get("RMSE") is not None and row.get("FinalKeyValid") is False:
            row["RMSE"] = None
            row["NormalizedRMSE"] = None
        if row.get("PredictedCounts") == {}:
            row["PredictedCounts"] = None
    return row


def raw_result_path(output_dir: Path, topology: str, n_agents: int, seed: int) -> Path:
    return output_dir / "raw_data" / f"cf_{topology}_n{n_agents}_seed{seed}.json"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def unique_values(rows: list[dict[str, Any]], key: str) -> list[Any]:
    return sorted({row[key] for row in rows})


def count_key_sorter(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def safe_plot_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return math.nan


if __name__ == "__main__":
    main()
