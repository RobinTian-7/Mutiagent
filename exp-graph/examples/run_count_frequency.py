"""Run a distributed counting-frequency topology experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from exp_graph.configs import ExperimentConfig
from exp_graph.runner import SynchronousRunner
from exp_graph.tasks import CountFrequencyTaskAdapter
from exp_graph.topology import topology_names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run counting frequency with a selectable communication topology."
    )
    parser.add_argument(
        "--topology",
        choices=topology_names(),
        default="one_peer_exponential",
        help="Communication topology used for neighbor visibility.",
    )
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--array-size", type=int, default=1000)
    parser.add_argument("--value-min", type=int, default=0)
    parser.add_argument("--value-max", type=int, default=9)
    parser.add_argument(
        "--llm-provider",
        choices=["fake", "openai", "auto"],
        default="fake",
        help="fake is deterministic and offline; openai uses OPENAI_API_KEY.",
    )
    parser.add_argument("--model-name", default="gpt-4o-mini")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for real LLM providers.",
    )
    parser.add_argument(
        "--json-retry-attempts",
        type=int,
        default=2,
        help="Number of retry calls after invalid belief_state JSON.",
    )
    parser.add_argument("--consensus-threshold", type=float, default=0.8)
    parser.add_argument("--final-accept-threshold", type=float, default=0.7)
    parser.add_argument("--adjudication-margin", type=float, default=0.1)
    parser.add_argument(
        "--use-llm-adjudicator",
        action="store_true",
        help="Allow one compact final LLM adjudication when top groups are close.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory for per-agent prompt/response JSONL traces.",
    )
    parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable agent prompt/response traces.",
    )
    parser.add_argument(
        "--no-save-prompts",
        action="store_true",
        help="Keep trace metadata and responses but omit raw prompts.",
    )
    parser.add_argument(
        "--retain-traces",
        action="store_true",
        help="Also keep full agent traces in ExperimentResult memory.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_adapter = CountFrequencyTaskAdapter()
    global_task = task_adapter.build_global_task(
        array_size=args.array_size,
        seed=args.seed,
        value_min=args.value_min,
        value_max=args.value_max,
    )
    config = ExperimentConfig(
        topology_name=args.topology,
        n_agents=args.n_agents,
        max_rounds=args.max_rounds,
        seed=args.seed,
        model_name=args.model_name,
        llm_provider=args.llm_provider,
        temperature=args.temperature,
        json_retry_attempts=args.json_retry_attempts,
        consensus_threshold=args.consensus_threshold,
        final_accept_threshold=args.final_accept_threshold,
        adjudication_margin=args.adjudication_margin,
        use_llm_adjudicator=args.use_llm_adjudicator,
        trace_enabled=not args.no_trace,
        save_prompts=not args.no_save_prompts,
        retain_traces=args.retain_traces,
        trace_dir=args.trace_dir,
    )
    result = SynchronousRunner(
        config=config,
        task_adapter=task_adapter,
        global_task=global_task,
    ).run()

    print("Distributed counting frequency")
    print(f"topology: {args.topology}")
    print(f"n_agents: {args.n_agents}")
    print(f"array_size: {global_task['array_length']}")
    print(f"value_range: [{global_task['value_min']}, {global_task['value_max']}]")
    print(f"expected_counts: {json.dumps(global_task['answer_counts'], sort_keys=True)}")
    print(f"expected_key: {global_task['answer_key']}")
    print(f"final_key: {result.final_result.final_key}")
    print(f"final_answer: {result.final_result.final_answer_text}")
    print(f"stop_reason: {result.stop_reason}")
    print(f"aggregation_method: {result.final_result.aggregation_method}")
    print(f"consensus_reached: {result.final_result.consensus_reached}")
    print(f"rounds_to_consensus: {result.metrics.rounds_to_consensus}")
    print(f"final_accuracy: {result.metrics.final_accuracy}")
    print(f"total_model_calls: {result.metrics.total_model_calls}")
    print(f"total_token_cost: {result.metrics.total_token_cost}")
    if result.trace_path:
        print(f"trace_path: {result.trace_path}")
    print("round_summary:")
    for log in result.round_logs:
        print(
            "  "
            f"round={log.round_idx} "
            f"top_key={log.consensus.top_key} "
            f"top_ratio={log.consensus.top_ratio:.3f} "
            f"active_keys={log.consensus.active_keys}"
        )
    print("metrics_json:")
    print(json.dumps(result.metrics.model_dump(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
