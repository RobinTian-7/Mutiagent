"""Append-only evidence ingestion for MAS skill evolution."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from exp_graph.mas.schemas import EvidenceRecord


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_csv_rows(path: Path | str) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_evidence_jsonl(records: list[EvidenceRecord], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
    return output_path


def read_evidence_jsonl(path: Path | str) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(EvidenceRecord.model_validate(json.loads(line)))
    return records


def ingest_experiment_evidence(directory: Path | str) -> list[EvidenceRecord]:
    """Convert an experiment output directory into append-only evidence records."""
    root = Path(directory)
    created_at = utc_now()
    records: list[EvidenceRecord] = []
    records.extend(_aggregate_records(root, created_at))
    records.extend(_run_records(root, created_at))
    records.extend(_trace_dynamics_records(root, created_at))
    return _dedupe_records(records)


def default_evidence_output_path(
    *,
    experiment_dir: Path | str,
    evidence_dir: Path | str,
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    name = f"{Path(experiment_dir).name}_{stamp}.jsonl"
    return Path(evidence_dir) / name


def _aggregate_records(root: Path, created_at: str) -> list[EvidenceRecord]:
    records = []
    for row in read_csv_rows(root / "aggregate_summary.csv"):
        topology = str(row.get("Topology", ""))
        n_agents = _int(row.get("Agents"))
        array_size = _int(row.get("ArraySize"))
        evidence_id = _evidence_id("aggregate", topology, n_agents, None, row)
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                source_dir=str(root),
                source_type="aggregate",
                topology_name=topology,
                n_agents=n_agents,
                metrics={
                    "array_size": array_size,
                    "merge_mode": row.get("MergeMode"),
                    "init_mode": row.get("InitMode"),
                    "runs": _int(row.get("Runs")),
                    "mean_rmse": _float(row.get("MeanFinalRMSE")),
                    "std_rmse": _float(row.get("StdFinalRMSE")),
                    "mean_norm_l1": _float(row.get("MeanFinalNormalizedL1Error")),
                    "exact_match_rate": _float(row.get("ExactMatchRate")),
                    "mean_steps": _float(row.get("MeanTotalSteps")),
                    "mean_messages": _float(row.get("MeanTotalMessages")),
                    "mean_model_calls": _float(row.get("MeanTotalModelCalls")),
                    "mean_token_cost": _float(row.get("MeanTokenCost")),
                    "mean_fallbacks": _float(row.get("MeanDeterministicFallbacks")),
                    "mean_vote_top_ratio": _float(row.get("MeanVoteTopRatio")),
                },
                created_at=created_at,
            )
        )
    return records


def _run_records(root: Path, created_at: str) -> list[EvidenceRecord]:
    records = []
    for row in read_csv_rows(root / "run_summary.csv"):
        topology = str(row.get("Topology", ""))
        n_agents = _int(row.get("Agents"))
        seed = _int(row.get("Seed"))
        evidence_id = _evidence_id("run", topology, n_agents, seed, row)
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                source_dir=str(root),
                source_type="run",
                topology_name=topology,
                n_agents=n_agents,
                seed=seed,
                metrics={
                    "array_size": _int(row.get("ArraySize")),
                    "merge_mode": row.get("MergeMode"),
                    "init_mode": row.get("InitMode"),
                    "provider": row.get("Provider"),
                    "model": row.get("Model"),
                    "total_steps": _int(row.get("TotalSteps")),
                    "total_messages": _int(row.get("TotalMessages")),
                    "total_model_calls": _int(row.get("TotalModelCalls")),
                    "token_cost": _int(row.get("TotalPromptTokens"))
                    + _int(row.get("TotalCompletionTokens")),
                    "total_fallbacks": _int(row.get("TotalDeterministicFallbacks")),
                    "final_rmse": _float(row.get("FinalRMSE")),
                    "final_norm_l1": _float(row.get("FinalNormalizedL1Error")),
                    "final_exact_match": _bool(row.get("FinalExactMatch")),
                    "vote_rmse": _float(row.get("VoteRMSE")),
                    "average_rmse": _float(row.get("AverageRMSE")),
                    "vote_average_disagreement_rmse": _float(
                        row.get("VoteAverageDisagreementRMSE")
                    ),
                },
                risk_tags=_run_risk_tags(row),
                created_at=created_at,
            )
        )
    return records


def _trace_dynamics_records(root: Path, created_at: str) -> list[EvidenceRecord]:
    global_rows = read_csv_rows(root / "global_step_metrics.csv")
    agent_rows = read_csv_rows(root / "agent_step_metrics.csv")
    trace_stats = _trace_jsonl_stats(root / "traces")
    records: list[EvidenceRecord] = []

    grouped_global: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in global_rows:
        grouped_global[
            (str(row.get("Topology", row.get("topology", ""))),
             _int(row.get("Agents")),
             _int(row.get("Seed")))
        ].append(row)

    grouped_agent: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in agent_rows:
        grouped_agent[
            (str(row.get("Topology", row.get("topology", ""))),
             _int(row.get("Agents")),
             _int(row.get("Seed")))
        ].append(row)

    for key, rows in grouped_global.items():
        topology, n_agents, seed = key
        final_global = _last_by_step(rows)
        initial_global = _first_by_step(rows)
        final_agent_rows = _final_agent_rows(grouped_agent.get(key, []))
        trace_key = _run_prefix(topology, n_agents, seed)
        stats = trace_stats.get(trace_key, {})
        dynamics = {
            "coverage_growth": _coverage_growth(initial_global, final_global),
            "aggregation_reliability": _aggregation_reliability(
                topology=topology,
                n_agents=n_agents,
                final_agent_rows=final_agent_rows,
                final_global=final_global,
            ),
            "merge_quality": {
                "parse_error_count": stats.get("parse_error_count", 0),
                "retry_attempts": stats.get("retry_attempts", 0),
                "trace_rows": stats.get("trace_rows", 0),
                "avg_fan_in": stats.get("avg_fan_in", 0.0),
                "prompt_tokens": stats.get("prompt_tokens", 0),
                "completion_tokens": stats.get("completion_tokens", 0),
            },
        }
        risk_tags = _dynamics_risk_tags(dynamics)
        records.append(
            EvidenceRecord(
                evidence_id=f"trace:{_slug(topology)}:n{n_agents}:seed{seed}",
                source_dir=str(root),
                source_type="trace",
                topology_name=topology,
                n_agents=n_agents,
                seed=seed,
                dynamics=dynamics,
                risk_tags=risk_tags,
                created_at=created_at,
            )
        )
    return records


def _trace_jsonl_stats(trace_dir: Path) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    if not trace_dir.exists():
        return stats
    for path in trace_dir.glob("*.jsonl"):
        run_key = _trace_path_key(path)
        trace_rows = 0
        parse_errors = 0
        retry_attempts = 0
        prompt_tokens = 0
        completion_tokens = 0
        fan_ins: list[float] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                trace_rows += 1
                if row.get("parse_error"):
                    parse_errors += 1
                retry_attempts += _int(row.get("retry_attempts"))
                prompt_tokens += _int(row.get("prompt_tokens"))
                completion_tokens += _int(row.get("completion_tokens"))
                fan_ins.append(float(len(row.get("neighbors") or [])))
        stats[run_key] = {
            "trace_rows": trace_rows,
            "parse_error_count": parse_errors,
            "retry_attempts": retry_attempts,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "avg_fan_in": fmean(fan_ins) if fan_ins else 0.0,
        }
    return stats


def _coverage_growth(initial: dict[str, Any], final: dict[str, Any]) -> dict[str, object]:
    initial_mean = _float(initial.get("mean_coverage"))
    final_mean = _float(final.get("mean_coverage"))
    initial_max = _float(initial.get("max_coverage"))
    final_max = _float(final.get("max_coverage"))
    return {
        "initial_mean_coverage": initial_mean,
        "final_mean_coverage": final_mean,
        "mean_coverage_gain": final_mean - initial_mean,
        "initial_max_coverage": initial_max,
        "final_max_coverage": final_max,
        "max_coverage_gain": final_max - initial_max,
        "final_full_coverage_agents": _int(final.get("full_coverage_agents")),
    }


def _aggregation_reliability(
    *,
    topology: str,
    n_agents: int,
    final_agent_rows: list[dict[str, Any]],
    final_global: dict[str, Any],
) -> dict[str, object]:
    sink_id = n_agents - 1
    sink_row = next(
        (row for row in final_agent_rows if _int(row.get("agent_id")) == sink_id),
        {},
    )
    best_rmse = min(
        [_float(row.get("global_rmse")) for row in final_agent_rows] or [0.0]
    )
    sink_rmse = _float(sink_row.get("global_rmse"))
    return {
        "sink_agent_id": sink_id,
        "sink_global_rmse": sink_rmse,
        "best_agent_global_rmse": best_rmse,
        "sink_best_rmse_gap": sink_rmse - best_rmse,
        "sink_coverage_ratio": _float(sink_row.get("coverage_ratio")),
        "vote_rmse": _float(final_global.get("vote_rmse")),
        "average_rmse": _float(final_global.get("average_rmse")),
        "is_sink_topology": any(
            token in topology
            for token in ["star", "tree", "sink", "dag_mesh", "random"]
        ),
    }


def _dynamics_risk_tags(dynamics: dict[str, object]) -> list[str]:
    tags: list[str] = []
    coverage = dynamics.get("coverage_growth", {})
    aggregation = dynamics.get("aggregation_reliability", {})
    merge = dynamics.get("merge_quality", {})
    if isinstance(coverage, dict) and _float(coverage.get("mean_coverage_gain")) <= 0:
        tags.append("coverage_stall")
    if isinstance(aggregation, dict) and _float(aggregation.get("sink_best_rmse_gap")) > 0:
        tags.append("sink_quality_gap")
    if isinstance(merge, dict) and _int(merge.get("retry_attempts")) > 0:
        tags.append("merge_retry_burden")
    if isinstance(merge, dict) and _int(merge.get("parse_error_count")) > 0:
        tags.append("merge_parse_error")
    return tags


def _run_risk_tags(row: dict[str, Any]) -> list[str]:
    tags = []
    if not _bool(row.get("FinalExactMatch")):
        tags.append("non_exact_final")
    if _int(row.get("TotalDeterministicFallbacks")) > 0:
        tags.append("deterministic_fallback")
    return tags


def _last_by_step(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: _float(row.get("step_idx")), default={})


def _first_by_step(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(rows, key=lambda row: _float(row.get("step_idx")), default={})


def _final_agent_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    final_step = max(_float(row.get("step_idx")) for row in rows)
    return [row for row in rows if _float(row.get("step_idx")) == final_step]


def _trace_path_key(path: Path) -> str:
    match = re.search(r"_n(?P<n>\d+)_seed(?P<seed>\d+)\.jsonl$", path.name)
    if not match:
        return path.stem
    prefix = path.name[: match.start()]
    topology = prefix
    known_prefixes = [
        "cf_protocol_llm_local_solve_llm_full_merge_",
        "cf_protocol_llm_local_solve_llm_belief_merge_",
        "cf_protocol_llm_local_solve_deterministic_",
        "cf_protocol_deterministic_llm_full_merge_",
        "cf_protocol_deterministic_llm_belief_merge_",
        "cf_protocol_deterministic_deterministic_",
        "cf_protocol_",
    ]
    for known_prefix in known_prefixes:
        if prefix.startswith(known_prefix):
            topology = prefix[len(known_prefix) :]
            break
    return _run_prefix(topology, int(match.group("n")), int(match.group("seed")))


def _run_prefix(topology: str, n_agents: int, seed: int) -> str:
    return f"{topology}:n{n_agents}:seed{seed}"


def _evidence_id(
    source_type: str,
    topology: str,
    n_agents: int | None,
    seed: int | None,
    row: dict[str, Any],
) -> str:
    pieces = [source_type, _slug(topology), f"n{n_agents or 0}"]
    if seed is not None:
        pieces.append(f"seed{seed}")
    pieces.append(_slug(str(row.get("MergeMode", ""))))
    pieces.append(_slug(str(row.get("InitMode", ""))))
    return ":".join(pieces)


def _dedupe_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    seen: set[str] = set()
    unique = []
    for record in records:
        if record.evidence_id in seen:
            continue
        seen.add(record.evidence_id)
        unique.append(record)
    return unique


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_").lower()


def _float(value: Any) -> float:
    if value in {None, ""}:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    if value in {None, ""}:
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}
