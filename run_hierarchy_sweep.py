"""Run a static hierarchy sweep on the count-frequency task.

This is the M2 driver for the "Emperor-Soldier" topology described in the
meeting notes. It is a deliberate sibling of ``run_cf_topology_sweep.py``:

- Each row is one fan-out shape (e.g., ``8``, ``2x4``, ``4x4``, ``4x2x4``).
- Plans are produced statically by ``build_static_hierarchy_plan`` from the
  fan-out schedule parsed out of the shape label; no LLM planner runs here.
- Shapes ``[N]`` give the M1 emperor-soldier star; ``[F1, F2]`` adds one
  minister layer; ``[F1, F2, F3]`` adds a sub-manager layer.
- Output mirrors ``run_cf_topology_sweep.py`` so a future comparison script
  can join hierarchy rows next to chain/star/mesh/tree baseline rows in one
  table.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = REPO_ROOT / "exp-graph"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from exp_graph.configs import ExperimentConfig
from exp_graph.hierarchy import (
    HierarchyTopology,
    LLMHierarchyPlanner,
    M3PlannerConfig,
    build_static_dispatch_tree,
    build_static_hierarchy_plan,
    expected_total_agents,
    shape_label_for_fanout,
    shape_label_to_fanout,
)
from exp_graph.llm.factory import create_llm_client
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import CountFrequencyTaskAdapter
from exp_graph.tasks.count_frequency import (
    FREQ_KEY_PREFIX,
    canonicalize_counts,
    count_frequency_consensus_key,
    counts_from_partials,
    parse_cf_state_payload,
)


DEFAULT_SHAPES = ["8", "2x4", "4x4"]
DEFAULT_ARRAY_SIZES = [1000, 5000]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "hierarchy_sweep_results"


def merge_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ if the key is not already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the static or LLM hierarchy planner on count-frequency and "
            "record the same metrics as the topology baseline sweep."
        )
    )
    parser.add_argument(
        "--planner",
        choices=["static", "llm"],
        default="static",
        help=(
            "static: fan-out from --shapes is honoured. "
            "llm: emperor LLM picks fan-out within --max-* bounds; --shapes "
            "is ignored except as a fallback."
        ),
    )
    parser.add_argument(
        "--shapes",
        nargs="+",
        type=str,
        default=DEFAULT_SHAPES,
        help=(
            "Fan-out shapes for --planner static, e.g. 8 (1 emperor + 8 "
            "soldiers), 2x4 (1 emperor + 2 ministers + 8 soldiers)."
        ),
    )
    parser.add_argument(
        "--n-soldiers",
        nargs="+",
        type=int,
        default=None,
        help=(
            "Deprecated alias: equivalent to --shapes <N> for each value. "
            "If both are passed, --shapes wins."
        ),
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="LLM planner: max layers including emperor (depth = len(fanout)+1).",
    )
    parser.add_argument(
        "--max-n-agents",
        type=int,
        default=64,
        help="LLM planner: cap on total agents (1 + sum of cumulative products).",
    )
    parser.add_argument(
        "--max-fanout-per-layer",
        type=int,
        default=32,
        help="LLM planner: cap on any single node's number of children.",
    )
    parser.add_argument(
        "--planner-fallback-shape",
        type=str,
        default="8",
        help="Shape used when LLM planner output is invalid or out of bounds.",
    )
    parser.add_argument(
        "--planner-retry-attempts",
        type=int,
        default=2,
        help=(
            "How many follow-up LLM calls the planner gets after a rejected "
            "proposal. Each retry sees the previous proposal and the "
            "validator's rejection reason. Set to 0 to disable retries."
        ),
    )
    parser.add_argument(
        "--no-constraint-examples",
        action="store_true",
        help=(
            "Disable the WORKED EXAMPLES block in the emperor planning prompt. "
            "Useful for ablation; cuts ~150 prompt tokens but lowers first-"
            "attempt success rate."
        ),
    )
    parser.add_argument(
        "--recursive-dispatch",
        action="store_true",
        help=(
            "M3-full: have each minister / sub-manager run its own LLM call "
            "to subdivide its assigned slice. Only takes effect with "
            "--planner llm."
        ),
    )
    parser.add_argument(
        "--max-parallel-agents",
        type=int,
        default=None,
        help=(
            "Cap on agents that step in parallel inside one round. Set this "
            "for real LLM runs to respect provider rate limits (e.g. 4). "
            "Default (None) lets the runner step all agents in parallel."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print an LLM-call / token / cost estimate for every config in "
            "the sweep and exit before doing any LLM call. Use this before "
            "burning real provider budget."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Stream a [event_type] message line for every emperor/minister "
            "planning call and every per-round per-agent step. Useful for "
            "watching real LLM runs live; also expensive to scroll through."
        ),
    )
    parser.add_argument(
        "--cost-input-per-million",
        type=float,
        default=0.15,
        help=(
            "Estimated input price per 1M tokens for the dry-run cost line. "
            "Default ~ gpt-4o-mini ($0.15/M)."
        ),
    )
    parser.add_argument(
        "--cost-output-per-million",
        type=float,
        default=0.60,
        help=(
            "Estimated output price per 1M tokens for the dry-run cost line. "
            "Default ~ gpt-4o-mini ($0.60/M)."
        ),
    )
    parser.add_argument(
        "--array-sizes",
        nargs="+",
        type=int,
        default=DEFAULT_ARRAY_SIZES,
    )
    parser.add_argument("--value-min", type=int, default=0)
    parser.add_argument("--value-max", type=int, default=9)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=12,
        help=(
            "Diameter doubles roughly per added layer; 12 leaves slack for "
            "up to 4-layer broadcasts."
        ),
    )
    parser.add_argument("--consensus-threshold", type=float, default=0.8)
    parser.add_argument("--final-accept-threshold", type=float, default=0.5)
    parser.add_argument("--adjudication-margin", type=float, default=0.1)
    parser.add_argument(
        "--llm-provider",
        choices=["fake", "openai", "auto"],
        default="fake",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY", ""),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.siliconflow.com/v1"),
    )
    parser.add_argument(
        "--model-name",
        default=os.environ.get("OPENAI_MODEL_NAME", "moonshotai/Kimi-K2.5"),
    )
    parser.add_argument(
        "--planner-model-name",
        default=os.environ.get("OPENAI_PLANNER_MODEL_NAME"),
        help=(
            "Model used only for emperor / recursive planning calls. "
            "Defaults to --model-name when unset, so workers can stay cheap "
            "while the planner uses a stronger model."
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--planner-temperature",
        type=float,
        default=None,
        help="Temperature used only for planning calls. Defaults to --temperature.",
    )
    parser.add_argument("--json-retry-attempts", type=int, default=2)
    parser.add_argument(
        "--config-retries",
        type=int,
        default=1,
        help="Retry a whole config after API/runtime failures.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse cached raw row JSON files when present.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
    )
    parser.add_argument(
        "--retain-traces",
        action="store_true",
    )
    return parser.parse_args()


def main() -> None:
    merge_dotenv(REPO_ROOT / ".env")
    args = parse_args()
    if args.dry_run:
        print_dry_run_preview(args)
        return
    configure_api_environment(args)
    ensure_dir(args.output_dir)
    ensure_dir(args.output_dir / "raw_data")
    if args.trace:
        ensure_dir(args.output_dir / "traces")

    rows = run_grid(args)
    write_outputs(rows, args)
    print_results_table(rows)
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


def resolve_shapes(args: argparse.Namespace) -> list[list[int]]:
    """Resolve the requested shapes into validated fan-out schedules."""
    raw_labels: list[str]
    if args.shapes != DEFAULT_SHAPES or args.n_soldiers is None:
        raw_labels = list(args.shapes)
    else:
        raw_labels = [str(int(value)) for value in args.n_soldiers]
    shapes: list[list[int]] = []
    seen: set[str] = set()
    for label in raw_labels:
        fanout = shape_label_to_fanout(label)
        canonical = shape_label_for_fanout(fanout)
        if canonical in seen:
            continue
        seen.add(canonical)
        shapes.append(fanout)
    if not shapes:
        raise ValueError("at least one shape is required")
    return shapes


def run_grid(args: argparse.Namespace) -> list[dict[str, Any]]:
    task_adapter = CountFrequencyTaskAdapter()
    rows: list[dict[str, Any]] = []
    for array_size in args.array_sizes:
        global_task = task_adapter.build_global_task(
            array_size=array_size,
            seed=args.seed,
            value_min=args.value_min,
            value_max=args.value_max,
        )
        if args.planner == "static":
            for fanout in resolve_shapes(args):
                rows.append(
                    _run_single_config(
                        task_adapter=task_adapter,
                        global_task=global_task,
                        fanout=fanout,
                        plan_label=shape_label_for_fanout(fanout),
                        args=args,
                    )
                )
        else:
            rows.append(
                _run_single_llm_config(
                    task_adapter=task_adapter,
                    global_task=global_task,
                    args=args,
                )
            )
    return rows


def _run_single_config(
    *,
    task_adapter: CountFrequencyTaskAdapter,
    global_task: dict[str, Any],
    fanout: list[int],
    plan_label: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    array_size = int(global_task["array_length"])
    n_total = expected_total_agents(fanout)
    cache_path = raw_result_path(args.output_dir, plan_label, array_size, args.seed)
    if args.resume and cache_path.exists():
        print(
            f"\n[hier_{plan_label} (n={n_total}) / size {array_size}] "
            "using cached row"
        )
        return load_row(cache_path)

    print(
        f"\n[hier_{plan_label} (n={n_total}) / size {array_size}] "
        "running hierarchy config..."
    )
    row = run_one_config_with_retries(
        task_adapter=task_adapter,
        global_task=global_task,
        fanout=fanout,
        args=args,
    )
    write_json(cache_path, row)
    rmse_text = "NA" if row["RMSE"] is None else f"{row['RMSE']:.4f}"
    print(
        "  -> "
        f"rounds={row['RoundsToConsensus']}, "
        f"rmse={rmse_text}, "
        f"exact={row['ExactMatch']}, "
        f"status={row['Status']}"
    )
    return row


def _run_single_llm_config(
    *,
    task_adapter: CountFrequencyTaskAdapter,
    global_task: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    array_size = int(global_task["array_length"])
    planner_model_name = args.planner_model_name or args.model_name
    planner_temperature = (
        args.temperature
        if args.planner_temperature is None
        else args.planner_temperature
    )
    cache_label = f"llm_seed{args.seed}"
    cache_path = raw_result_path(args.output_dir, cache_label, array_size, args.seed)
    if args.resume and cache_path.exists():
        print(f"\n[hier_llm / size {array_size}] using cached row")
        return load_row(cache_path)

    print(
        f"\n[hier_llm / size {array_size}] emperor LLM picking fan-out "
        f"(planner_model={planner_model_name}, worker_model={args.model_name})..."
    )
    planner_config = M3PlannerConfig(
        max_depth=args.max_depth,
        max_n_agents=args.max_n_agents,
        max_fanout_per_layer=args.max_fanout_per_layer,
        fallback_fanout_schedule=shape_label_to_fanout(args.planner_fallback_shape),
        model_name=planner_model_name,
        temperature=planner_temperature,
        recursive_dispatch=bool(args.recursive_dispatch),
        verbose=bool(args.verbose),
        plan_retry_attempts=int(args.planner_retry_attempts),
        include_constraint_examples=not bool(args.no_constraint_examples),
    )
    planner = LLMHierarchyPlanner(
        config=planner_config,
        llm_client=create_llm_client(args.llm_provider),
    )
    plan_result = planner.plan(
        task_description={
            "task": "count_frequency",
            "array_length": array_size,
            "value_min": int(global_task["value_min"]),
            "value_max": int(global_task["value_max"]),
        }
    )
    actual_label = shape_label_for_fanout(plan_result.plan.fanout_schedule)
    n_total = plan_result.plan.n_total
    rejected_records = [
        record for record in plan_result.planner_retry_records
        if not record.accepted
    ]
    for record in rejected_records:
        proposed_label = (
            shape_label_for_fanout(record.proposed_fanout_schedule)
            if record.proposed_fanout_schedule
            else "<unparsed>"
        )
        print(
            f"  attempt {record.attempt_idx + 1}: emperor proposed "
            f"shape={proposed_label} -> REJECTED ({record.reason})"
        )
    if plan_result.fallback_used:
        print(
            f"  all {1 + plan_result.planner_retry_attempts} planner "
            f"attempt(s) failed; using fallback shape={actual_label} "
            f"(n={n_total})"
        )
    else:
        retry_note = (
            ""
            if plan_result.planner_retry_attempts == 0
            else f" (after {plan_result.planner_retry_attempts} retry/retries)"
        )
        print(
            f"  emperor chose shape={actual_label} (n={n_total}){retry_note}; "
            f"rationale={plan_result.rationale!r}"
        )
    if plan_result.recursive_dispatch_used:
        n_calls = len(plan_result.subordinate_calls)
        n_failed = sum(
            1 for call in plan_result.subordinate_calls if call.fallback_used
        )
        print(
            f"  recursive dispatch: {n_calls} subordinate LLM call(s), "
            f"{n_failed} fell back to equal split"
        )

    row = run_one_config_with_retries(
        task_adapter=task_adapter,
        global_task=global_task,
        fanout=plan_result.plan.fanout_schedule,
        args=args,
        plan_result=plan_result,
    )
    write_json(cache_path, row)
    rmse_text = "NA" if row["RMSE"] is None else f"{row['RMSE']:.4f}"
    print(
        "  -> "
        f"rounds={row['RoundsToConsensus']}, "
        f"rmse={rmse_text}, "
        f"exact={row['ExactMatch']}, "
        f"status={row['Status']}"
    )
    return row


def run_one_config_with_retries(
    *,
    task_adapter: CountFrequencyTaskAdapter,
    global_task: dict[str, Any],
    fanout: list[int],
    args: argparse.Namespace,
    plan_result: Any = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt_idx in range(args.config_retries + 1):
        try:
            if attempt_idx:
                print(f"  -> retrying config, attempt {attempt_idx + 1}")
            return execute_one(
                task_adapter=task_adapter,
                global_task=global_task,
                fanout=fanout,
                args=args,
                plan_result=plan_result,
            )
        except Exception as exc:  # noqa: BLE001 — surface any runner failure
            last_error = exc
            print(f"  -> attempt {attempt_idx + 1} failed: {exc}")
    assert last_error is not None
    return build_failed_row(
        global_task=global_task,
        fanout=fanout,
        args=args,
        error=last_error,
    )


def execute_one(
    *,
    task_adapter: CountFrequencyTaskAdapter,
    global_task: dict[str, Any],
    fanout: list[int],
    args: argparse.Namespace,
    plan_result: Any = None,
) -> dict[str, Any]:
    if plan_result is not None:
        plan = plan_result.plan
        dispatch = plan_result.dispatch
        plan_origin = "llm" if plan_result.used_llm else "static_fallback"
    else:
        plan = build_static_hierarchy_plan(
            fanout,
            array_length=int(global_task["array_length"]),
        )
        dispatch = build_static_dispatch_tree(
            plan,
            array_length=int(global_task["array_length"]),
        )
        plan_origin = "static"
    topology = HierarchyTopology(plan)
    shape_label = shape_label_for_fanout(plan.fanout_schedule)
    config = ExperimentConfig(
        topology_name=f"hierarchy_{shape_label}",
        n_agents=plan.n_total,
        max_rounds=args.max_rounds,
        seed=args.seed,
        model_name=args.model_name,
        llm_provider=args.llm_provider,
        temperature=args.temperature,
        json_retry_attempts=args.json_retry_attempts,
        consensus_threshold=args.consensus_threshold,
        final_accept_threshold=args.final_accept_threshold,
        adjudication_margin=args.adjudication_margin,
        max_parallel_agents=args.max_parallel_agents,
        trace_enabled=args.trace,
        save_prompts=args.trace,
        retain_traces=args.retain_traces,
        verbose_events=bool(args.verbose),
        trace_dir=str(args.output_dir / "traces") if args.trace else None,
        run_id=(
            f"hier_{plan_origin}_{shape_label}_"
            f"size{global_task['array_length']}_seed{args.seed}"
        ),
    )
    result = SynchronousRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
        topology=topology,
        hierarchy_plan=plan,
        hierarchy_dispatch=dispatch,
    ).run()
    return build_row(
        result=result,
        plan=plan,
        global_task=global_task,
        fanout=plan.fanout_schedule,
        args=args,
        plan_result=plan_result,
    )


def build_row(
    *,
    result,
    plan,
    global_task: dict[str, Any],
    fanout: list[int],
    args: argparse.Namespace,
    plan_result: Any = None,
) -> dict[str, Any]:
    final_key = result.final_result.final_key
    pred_counts = parse_freq_key(final_key)
    fallback_used = False
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
    shape_label = shape_label_for_fanout(fanout)
    role_counts = _role_counts(plan)
    if plan_result is not None and plan_result.used_llm:
        if plan_result.recursive_dispatch_used:
            planner_label = "llm_recursive"
        elif plan_result.planner_retry_attempts > 0:
            planner_label = "llm_after_retry"
        else:
            planner_label = "llm"
    elif plan_result is not None and plan_result.fallback_used:
        planner_label = "llm_fallback"
    else:
        planner_label = "static"
    rationale = plan_result.rationale if plan_result is not None else ""
    planner_fallback_reason = (
        plan_result.fallback_reason if plan_result is not None else ""
    )
    if plan_result is not None:
        total_planner_usage = plan_result.total_planner_usage
        planner_tokens = total_planner_usage.total_tokens
        planner_calls = total_planner_usage.model_calls
        recursive_used = plan_result.recursive_dispatch_used
        recursive_calls = len(plan_result.subordinate_calls)
        recursive_fallback_calls = sum(
            1 for call in plan_result.subordinate_calls if call.fallback_used
        )
    else:
        planner_tokens = 0
        planner_calls = 0
        recursive_used = False
        recursive_calls = 0
        recursive_fallback_calls = 0

    return {
        "Task": "count_frequency",
        "Topology": f"hierarchy_{shape_label}",
        "Shape": shape_label,
        "Planner": planner_label,
        "PlannerModel": plan_result.plan.metadata.get("planner_model_name", "")
        if plan_result is not None
        else "",
        "WorkerModel": args.model_name,
        "PlannerRationale": rationale,
        "PlannerFallbackReason": planner_fallback_reason,
        "PlannerTokens": planner_tokens,
        "PlannerCalls": planner_calls,
        "RecursiveDispatch": recursive_used,
        "RecursiveCalls": recursive_calls,
        "RecursiveFallbackCalls": recursive_fallback_calls,
        "PlannerRetryAttempts": plan_result.planner_retry_attempts
        if plan_result is not None
        else 0,
        "PlannerAttemptsTotal": (1 + plan_result.planner_retry_attempts)
        if plan_result is not None
        else 0,
        "FanoutSchedule": plan.fanout_schedule,
        "Layers": plan.layers,
        "Depth": len(plan.layers),
        "RoleCounts": role_counts,
        "Soldiers": plan.n_soldiers,
        "Agents": plan.n_total,
        "ArraySize": int(global_task["array_length"]),
        "ValueMin": int(global_task["value_min"]),
        "ValueMax": int(global_task["value_max"]),
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
        "Status": "ok",
        "Error": "",
    }


def _role_counts(plan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in plan.nodes:
        key = node.role.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_failed_row(
    *,
    global_task: dict[str, Any],
    fanout: list[int],
    args: argparse.Namespace,
    error: Exception,
) -> dict[str, Any]:
    shape_label = shape_label_for_fanout(fanout)
    return {
        "Task": "count_frequency",
        "Topology": f"hierarchy_{shape_label}",
        "Shape": shape_label,
        "Planner": args.planner,
        "PlannerModel": "",
        "WorkerModel": args.model_name,
        "PlannerRationale": "",
        "PlannerFallbackReason": "",
        "PlannerTokens": 0,
        "PlannerCalls": 0,
        "RecursiveDispatch": False,
        "RecursiveCalls": 0,
        "RecursiveFallbackCalls": 0,
        "PlannerRetryAttempts": 0,
        "PlannerAttemptsTotal": 0,
        "FanoutSchedule": list(fanout),
        "Layers": [],
        "Depth": len(fanout) + 1,
        "RoleCounts": {},
        "Soldiers": expected_total_agents(fanout) - 1
        if len(fanout) == 1
        else None,
        "Agents": expected_total_agents(fanout),
        "ArraySize": int(global_task["array_length"]),
        "ValueMin": int(global_task["value_min"]),
        "ValueMax": int(global_task["value_max"]),
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
    generate_report(rows, args.output_dir)


def generate_report(rows: list[dict[str, Any]], output_dir: Path) -> None:
    report_path = output_dir / "experiment_report.md"
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# Hierarchy Sweep Report (M2: static multi-layer)\n\n")
        handle.write("## Configuration\n\n")
        if rows:
            first = rows[0]
            handle.write(f"- Model: `{first['Model']}`\n")
            handle.write(f"- Provider: `{first['Provider']}`\n")
            handle.write(f"- Seed: `{first['Seed']}`\n")
            handle.write(f"- Max rounds: `{first['MaxRounds']}`\n")
        handle.write("\n## Results\n\n")
        handle.write(markdown_table(rows) + "\n\n")
        failed = [row for row in rows if row["Status"] != "ok"]
        if failed:
            handle.write("## Failures\n\n")
            for row in failed:
                handle.write(
                    f"- shape `{row['Shape']}` on size {row['ArraySize']}: "
                    f"{row['Error']}\n"
                )


def print_results_table(rows: list[dict[str, Any]]) -> None:
    print("\nHierarchy sweep results:")
    print(markdown_table(rows))


# Rough per-call token defaults used by the dry-run preview. They are
# deliberately conservative so the printed cost is more likely to over-
# estimate than under-estimate; the user can override via CLI flags.
PREVIEW_AGENT_INPUT_TOKENS = 1500
PREVIEW_AGENT_OUTPUT_TOKENS = 400
PREVIEW_PLANNER_INPUT_TOKENS = 700
PREVIEW_PLANNER_OUTPUT_TOKENS = 200


def print_dry_run_preview(args: argparse.Namespace) -> None:
    """Print an LLM-call / token / cost estimate for the planned sweep."""
    rows = _build_preview_rows(args)
    if not rows:
        print("No configurations to preview.")
        return

    planner_model_name = args.planner_model_name or args.model_name
    print("\nDry-run preview (no LLM calls made):")
    print(
        f"Models: planner={planner_model_name}, workers={args.model_name}"
    )
    print(_preview_markdown_table(rows))

    totals = _aggregate_preview_totals(rows)
    cost_estimate = _estimate_preview_cost(totals, args)
    note = (
        " (LLM planner: emperor's actual shape will be chosen at runtime; "
        "estimates use --planner-fallback-shape)"
        if args.planner == "llm"
        else ""
    )
    print(
        f"\nTotal LLM calls (typical / worst): "
        f"{totals['typical_calls']} / {totals['worst_calls']}{note}"
    )
    print(
        "  planner: "
        f"{totals['planner_calls']} call(s)"
    )
    print(
        "  agents : "
        f"{totals['typical_agent_calls']} typical / "
        f"{totals['worst_agent_calls']} worst"
    )
    print(
        f"Estimated tokens (typical): "
        f"{totals['typical_input_tokens']:,} input + "
        f"{totals['typical_output_tokens']:,} output"
    )
    print(
        f"Estimated cost (typical) at "
        f"${args.cost_input_per_million}/M input + "
        f"${args.cost_output_per_million}/M output: "
        f"${cost_estimate['typical']:.4f}"
    )
    print(
        f"Estimated cost (worst, max_rounds): "
        f"${cost_estimate['worst']:.4f}"
    )
    if args.planner == "llm":
        print(
            "\nNote: emperor LLM may pick any shape within "
            f"max_depth={args.max_depth}, "
            f"max_n_agents={args.max_n_agents}, "
            f"max_fanout_per_layer={args.max_fanout_per_layer}. "
            f"Preview uses fallback shape '{args.planner_fallback_shape}' "
            "for n_total estimates."
        )
    if args.max_parallel_agents is None:
        print(
            "\nNote: --max-parallel-agents is unset. The runner will step "
            "every agent in parallel each round, which may exceed provider "
            "rate limits on real LLMs. Pass --max-parallel-agents 4 (or "
            "similar) for safety."
        )


def _build_preview_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if args.planner == "static":
        shapes = resolve_shapes(args)
        for array_size in args.array_sizes:
            for fanout in shapes:
                rows.append(_preview_row(fanout, array_size, args))
    else:
        fallback_fanout = shape_label_to_fanout(args.planner_fallback_shape)
        for array_size in args.array_sizes:
            rows.append(_preview_row(fallback_fanout, array_size, args))
    return rows


def _preview_row(
    fanout: list[int],
    array_size: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    n_total = expected_total_agents(fanout)
    depth = len(fanout) + 1
    typical_rounds = max(2, 2 * (depth - 1))
    typical_rounds = min(typical_rounds, args.max_rounds)
    worst_rounds = args.max_rounds

    planner_calls = 0
    if args.planner == "llm":
        planner_calls = 1
        if args.recursive_dispatch:
            layer_sizes = [1]
            for f in fanout:
                layer_sizes.append(layer_sizes[-1] * f)
            # one call per non-root, non-leaf parent (emperor handled by
            # the top-level planning call, soldiers are leaves)
            planner_calls += sum(layer_sizes[1:-1])

    typical_agent_calls = n_total * typical_rounds
    worst_agent_calls = n_total * worst_rounds

    return {
        "Shape": shape_label_for_fanout(fanout),
        "Depth": depth,
        "Agents": n_total,
        "ArraySize": array_size,
        "PlannerCalls": planner_calls,
        "TypicalRounds": typical_rounds,
        "WorstRounds": worst_rounds,
        "TypicalAgentCalls": typical_agent_calls,
        "WorstAgentCalls": worst_agent_calls,
        "TypicalTotalCalls": planner_calls + typical_agent_calls,
        "WorstTotalCalls": planner_calls + worst_agent_calls,
    }


def _preview_markdown_table(rows: list[dict[str, Any]]) -> str:
    columns = [
        "Shape",
        "Depth",
        "Agents",
        "ArraySize",
        "PlannerCalls",
        "TypicalRounds",
        "TypicalAgentCalls",
        "WorstAgentCalls",
        "TypicalTotalCalls",
        "WorstTotalCalls",
    ]
    table = ["| " + " | ".join(columns) + " |"]
    table.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in sorted(rows, key=lambda item: (item["ArraySize"], item["Agents"])):
        table.append(
            "| " + " | ".join(str(row.get(col, "")) for col in columns) + " |"
        )
    return "\n".join(table)


def _aggregate_preview_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    planner_calls = sum(row["PlannerCalls"] for row in rows)
    typical_agent_calls = sum(row["TypicalAgentCalls"] for row in rows)
    worst_agent_calls = sum(row["WorstAgentCalls"] for row in rows)
    return {
        "planner_calls": planner_calls,
        "typical_agent_calls": typical_agent_calls,
        "worst_agent_calls": worst_agent_calls,
        "typical_calls": planner_calls + typical_agent_calls,
        "worst_calls": planner_calls + worst_agent_calls,
        "typical_input_tokens": (
            planner_calls * PREVIEW_PLANNER_INPUT_TOKENS
            + typical_agent_calls * PREVIEW_AGENT_INPUT_TOKENS
        ),
        "typical_output_tokens": (
            planner_calls * PREVIEW_PLANNER_OUTPUT_TOKENS
            + typical_agent_calls * PREVIEW_AGENT_OUTPUT_TOKENS
        ),
        "worst_input_tokens": (
            planner_calls * PREVIEW_PLANNER_INPUT_TOKENS
            + worst_agent_calls * PREVIEW_AGENT_INPUT_TOKENS
        ),
        "worst_output_tokens": (
            planner_calls * PREVIEW_PLANNER_OUTPUT_TOKENS
            + worst_agent_calls * PREVIEW_AGENT_OUTPUT_TOKENS
        ),
    }


def _estimate_preview_cost(
    totals: dict[str, int],
    args: argparse.Namespace,
) -> dict[str, float]:
    input_rate = float(args.cost_input_per_million) / 1_000_000.0
    output_rate = float(args.cost_output_per_million) / 1_000_000.0
    return {
        "typical": (
            totals["typical_input_tokens"] * input_rate
            + totals["typical_output_tokens"] * output_rate
        ),
        "worst": (
            totals["worst_input_tokens"] * input_rate
            + totals["worst_output_tokens"] * output_rate
        ),
    }


def markdown_table(rows: list[dict[str, Any]]) -> str:
    columns = [
        "Planner",
        "PlannerModel",
        "WorkerModel",
        "Shape",
        "Depth",
        "Soldiers",
        "Agents",
        "ArraySize",
        "RoundsToConsensus",
        "RMSE",
        "NormalizedRMSE",
        "ExactMatch",
        "ConsensusReached",
        "RunCompleted",
        "FallbackUsed",
        "PlannerFallbackReason",
        "PlannerTokens",
        "PlannerCalls",
        "PlannerRetryAttempts",
        "RecursiveCalls",
        "RecursiveFallbackCalls",
        "TotalModelCalls",
        "TotalTokenCost",
        "Status",
    ]
    if not rows:
        return "(no rows)"
    table = ["| " + " | ".join(columns) + " |"]
    table.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in sorted(
        rows, key=lambda item: (item["ArraySize"], item["Depth"], item["Agents"])
    ):
        values = []
        for column in columns:
            value = row.get(column)
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
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)


def load_row(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def raw_result_path(
    output_dir: Path,
    shape_label: str,
    array_size: int,
    seed: int,
) -> Path:
    return (
        output_dir
        / "raw_data"
        / f"hier_{shape_label}_size{array_size}_seed{seed}.json"
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def count_key_sorter(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


if __name__ == "__main__":
    main()
