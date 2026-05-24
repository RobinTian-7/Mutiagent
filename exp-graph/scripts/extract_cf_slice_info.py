#!/usr/bin/env python3
"""Extract useful slice, topology, and merge information from one CF MAS run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize one count-frequency MAS run from a protocol_result.json "
            "or a run/job directory."
        )
    )
    parser.add_argument("run", type=Path, help="protocol_result.json or run directory")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the extracted machine-readable summary.",
    )
    parser.add_argument(
        "--max-slice-preview",
        type=int,
        default=12,
        help="How many values from each local array shard to show.",
    )
    parser.add_argument(
        "--top-errors",
        type=int,
        default=5,
        help="How many largest per-value count errors to show.",
    )
    args = parser.parse_args()

    protocol_path = _resolve_protocol_path(args.run)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    extracted = extract_run(data, protocol_path, args.max_slice_preview)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(extracted, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(render_markdown(extracted, top_errors=args.top_errors))


def _resolve_protocol_path(path: Path) -> Path:
    if path.is_file():
        return path
    direct = path / "protocol_result.json"
    if direct.exists():
        return direct
    matches = sorted(path.rglob("protocol_result.json"))
    if not matches:
        raise SystemExit(f"no protocol_result.json found under {path}")
    if len(matches) > 1:
        raise SystemExit(
            f"found {len(matches)} protocol_result.json files; pass one run/job dir"
        )
    return matches[0]


def extract_run(
    data: dict[str, Any],
    protocol_path: Path,
    max_slice_preview: int,
) -> dict[str, Any]:
    local_slices = _local_slices(data, max_slice_preview)
    true_by_agent = {
        row["agent_id"]: row["true_counts"] for row in local_slices
    }
    traces = [
        _trace_snapshot(trace, true_by_agent)
        for trace in sorted(
            data.get("agent_step_traces", []),
            key=lambda item: (int(item.get("round_idx", 0)), int(item.get("agent_id", 0))),
        )
    ]
    final_counts = _normalize_counts(data.get("final_result", {}).get("final_counts", {}))
    truth_counts = _normalize_counts(data.get("global_task", {}).get("answer_counts", {}))
    return {
        "protocol_path": str(protocol_path),
        "run_id": data.get("run_id"),
        "config": _config_summary(data.get("config", {})),
        "global_task": _global_task_summary(data.get("global_task", {})),
        "schedule": data.get("schedule", []),
        "local_slices": local_slices,
        "trace_snapshots": traces,
        "final": {
            "aggregation_method": data.get("final_result", {}).get("aggregation_method"),
            "selected_primary": data.get("final_result", {}).get("selected_primary"),
            "answer_agent_ids": data.get("final_result", {}).get("answer_agent_ids", []),
            "exact_match": data.get("final_result", {}).get("exact_match"),
            "rmse": data.get("final_result", {}).get("rmse"),
            "normalized_l1_error": data.get("final_result", {}).get(
                "normalized_l1_error"
            ),
            "truth_counts": truth_counts,
            "final_counts": final_counts,
            "count_diff": _count_diff(final_counts, truth_counts),
        },
        "totals": {
            "steps": data.get("total_steps"),
            "messages": data.get("total_messages"),
            "model_calls": data.get("total_model_calls"),
            "prompt_tokens": data.get("total_prompt_tokens"),
            "completion_tokens": data.get("total_completion_tokens"),
            "retry_attempts": data.get("total_retry_attempts"),
            "deterministic_fallbacks": data.get("total_deterministic_fallbacks"),
        },
    }


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    roles = config.get("llm_role_summary", {})
    return {
        "topology_name": config.get("topology_name"),
        "n_agents": config.get("n_agents"),
        "seed": config.get("seed"),
        "merge_mode": config.get("merge_mode"),
        "init_mode": config.get("init_mode"),
        "soldier_model": config.get("model_name"),
        "soldier_provider": config.get("llm_provider"),
        "role_models": {
            role: {
                "platform": item.get("platform"),
                "model_name": item.get("model_name"),
                "thinking_enabled": item.get("thinking_enabled"),
            }
            for role, item in roles.items()
            if isinstance(item, dict)
        },
    }


def _global_task_summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_name": task.get("task_name"),
        "array_length": task.get("array_length"),
        "value_min": task.get("value_min"),
        "value_max": task.get("value_max"),
        "answer_counts": _normalize_counts(task.get("answer_counts", {})),
    }


def _local_slices(data: dict[str, Any], max_slice_preview: int) -> list[dict[str, Any]]:
    rows = []
    for state in data.get("final_agent_states", []):
        obs = state.get("local_observation", {})
        agent_id = int(obs.get("agent_id", len(rows)))
        shard = list(obs.get("array_shard", []))
        rows.append(
            {
                "agent_id": agent_id,
                "shard_start": obs.get("shard_start"),
                "shard_end_exclusive": obs.get("shard_end_exclusive"),
                "shard_length": len(shard),
                "shard_preview": shard[:max_slice_preview],
                "true_counts": _counts_from_values(shard),
            }
        )
    return sorted(rows, key=lambda row: int(row["agent_id"]))


def _trace_snapshot(
    trace: dict[str, Any],
    true_by_agent: dict[int, dict[str, int]],
) -> dict[str, Any]:
    belief = trace.get("parsed_belief_state", {})
    structured = belief.get("structured_state", {})
    if not isinstance(structured, dict):
        structured = {}
    known_sources = [int(item) for item in structured.get("known_sources", [])]
    model_counts = _normalize_counts(structured.get("merged_counts", {}))
    expected_counts = _sum_counts(true_by_agent, known_sources)
    diff = _count_diff(model_counts, expected_counts)
    inbox = trace.get("inbox", [])
    return {
        "round_idx": trace.get("round_idx"),
        "communication_round": trace.get("communication_round"),
        "agent_id": trace.get("agent_id"),
        "neighbors": trace.get("neighbors", []),
        "inbox_senders": [
            item.get("sender_id", item.get("agent_id"))
            for item in inbox
            if isinstance(item, dict)
        ],
        "known_sources": known_sources,
        "status": belief.get("status"),
        "model_counts": model_counts,
        "expected_counts_for_known_sources": expected_counts,
        "model_count_sum": sum(model_counts.values()),
        "expected_count_sum": sum(expected_counts.values()),
        "count_diff": diff,
        "exact_for_known_sources": all(value == 0 for value in diff.values()),
        "l1_error_for_known_sources": sum(abs(value) for value in diff.values()),
        "prompt_tokens": trace.get("prompt_tokens", 0),
        "completion_tokens": trace.get("completion_tokens", 0),
        "retry_attempts": trace.get("retry_attempts", 0),
        "parse_error": trace.get("parse_error"),
    }


def _counts_from_values(values: list[Any]) -> dict[str, int]:
    counts = Counter(str(int(value)) for value in values)
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _normalize_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(count)
        for key, count in sorted(
            value.items(),
            key=lambda item: int(item[0]) if str(item[0]).lstrip("-").isdigit() else str(item[0]),
        )
    }


def _sum_counts(
    true_by_agent: dict[int, dict[str, int]],
    agent_ids: list[int],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for agent_id in agent_ids:
        counts.update(true_by_agent.get(agent_id, {}))
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _count_diff(observed: dict[str, int], expected: dict[str, int]) -> dict[str, int]:
    keys = sorted(set(observed) | set(expected), key=lambda item: int(item))
    return {key: observed.get(key, 0) - expected.get(key, 0) for key in keys}


def render_markdown(extracted: dict[str, Any], *, top_errors: int) -> str:
    lines: list[str] = []
    cfg = extracted["config"]
    totals = extracted["totals"]
    final = extracted["final"]
    lines.append("# CF MAS Slice Run Summary")
    lines.append("")
    lines.append(f"- protocol: `{extracted['protocol_path']}`")
    lines.append(f"- topology: `{cfg['topology_name']}`")
    lines.append(f"- seed: `{cfg['seed']}`")
    lines.append(f"- agents: `{cfg['n_agents']}`")
    lines.append(f"- soldier: `{cfg['soldier_provider']}:{cfg['soldier_model']}`")
    lines.append(f"- merge/init: `{cfg['merge_mode']}` / `{cfg['init_mode']}`")
    lines.append(
        "- totals: "
        f"steps={totals['steps']}, messages={totals['messages']}, "
        f"model_calls={totals['model_calls']}, "
        f"tokens={int(totals['prompt_tokens'] or 0) + int(totals['completion_tokens'] or 0)}"
    )
    lines.append(
        "- final: "
        f"exact={final['exact_match']}, rmse={final['rmse']}, "
        f"selected_primary={final['selected_primary']}, "
        f"answer_agent_ids={final['answer_agent_ids']}"
    )
    lines.append("")

    lines.append("## Role Models")
    for role, item in sorted(cfg.get("role_models", {}).items()):
        lines.append(
            f"- {role}: {item['platform']} / {item['model_name']} "
            f"/ thinking={item['thinking_enabled']}"
        )
    lines.append("")

    lines.append("## Topology Schedule")
    for step in extracted["schedule"]:
        transmissions = ", ".join(
            f"{src}->{dst}" for src, dst in step.get("transmissions", [])
        )
        lines.append(
            f"- step {step.get('step_idx')}: {transmissions} "
            f"({step.get('description', '')})"
        )
    lines.append("")

    lines.append("## Local Slices")
    lines.append(
        "| agent | range | len | preview | true local counts |"
    )
    lines.append("| --- | --- | ---: | --- | --- |")
    for row in extracted["local_slices"]:
        lines.append(
            f"| {row['agent_id']} | "
            f"{row['shard_start']}..{row['shard_end_exclusive']} | "
            f"{row['shard_length']} | "
            f"`{row['shard_preview']}` | "
            f"`{row['true_counts']}` |"
        )
    lines.append("")

    lines.append("## Merge Trace")
    lines.append(
        "| round | receiver | from | known sources | count sum | exact? | L1 error | tokens |"
    )
    lines.append("| ---: | ---: | --- | --- | --- | --- | ---: | ---: |")
    for snap in extracted["trace_snapshots"]:
        tokens = int(snap.get("prompt_tokens") or 0) + int(
            snap.get("completion_tokens") or 0
        )
        lines.append(
            f"| {snap['round_idx']} | {snap['agent_id']} | "
            f"`{snap['inbox_senders']}` | `{snap['known_sources']}` | "
            f"{snap['model_count_sum']}/{snap['expected_count_sum']} | "
            f"{snap['exact_for_known_sources']} | "
            f"{snap['l1_error_for_known_sources']} | {tokens} |"
        )
    lines.append("")

    lines.append("## Final Count Error")
    lines.append(f"- truth: `{final['truth_counts']}`")
    lines.append(f"- final: `{final['final_counts']}`")
    largest = sorted(
        final["count_diff"].items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )[:top_errors]
    lines.append(f"- largest diffs: `{dict(largest)}`")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
