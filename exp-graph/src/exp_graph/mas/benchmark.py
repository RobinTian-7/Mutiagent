"""Paper-style benchmark reporting for MAS skill evolution."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from exp_graph.mas.matrix import objective_score


class BenchmarkReportResult(BaseModel):
    """Artifacts written by the benchmark reporter."""

    output_dir: str
    method_count: int
    condition_count: int
    summary_csv: str
    by_condition_csv: str
    report_json: str
    report_markdown: str
    warnings: list[str] = Field(default_factory=list)


def build_benchmark_report(
    *,
    fixed_collected_dir: Path | str,
    v0_collected_dir: Path | str,
    v1_collected_dir: Path | str,
    output_dir: Path | str,
) -> BenchmarkReportResult:
    """Compare fixed, frozen, LLM-free, and evolved planner results."""
    fixed = _load_conditions(Path(fixed_collected_dir))
    v0 = _load_conditions(Path(v0_collected_dir))
    v1 = _load_conditions(Path(v1_collected_dir))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    oracle_rows = _oracle_rows(fixed)
    if not oracle_rows:
        warnings.append("No fixed-topology oracle rows found; regret values are unavailable.")

    rows: list[dict[str, Any]] = []
    rows.extend(_fixed_method_rows(fixed, oracle_rows))
    rows.extend(_planner_method_rows(v0, "frozen_skillbank_v0", "skill_grounded", oracle_rows))
    rows.extend(_planner_method_rows(v0, "llm_free", "llm_free", oracle_rows))
    rows.extend(_planner_method_rows(v1, "evolved_skillbank_v1", "skill_grounded", oracle_rows))
    rows.extend(_oracle_method_rows(oracle_rows))

    method_rows = _aggregate_methods(rows)
    method_order = [
        "fixed_tree",
        "fixed_one_peer_exponential_dag_star",
        "fixed_mesh_star",
        "llm_free",
        "frozen_skillbank_v0",
        "evolved_skillbank_v1",
        "oracle_best_topology",
    ]
    method_rows.sort(
        key=lambda row: (
            method_order.index(row["method"])
            if row["method"] in method_order
            else len(method_order),
            row["method"],
        )
    )
    rows.sort(key=lambda row: (row["method"], row["condition_key"], row.get("topology_name", "")))

    report = {
        "created_at": _now(),
        "inputs": {
            "fixed_collected_dir": str(fixed_collected_dir),
            "v0_collected_dir": str(v0_collected_dir),
            "v1_collected_dir": str(v1_collected_dir),
        },
        "method_summary": method_rows,
        "by_condition": rows,
        "claim_draft": _claim_draft(method_rows),
        "warnings": warnings,
    }
    summary_csv = out / "benchmark_summary.csv"
    by_condition_csv = out / "benchmark_by_condition.csv"
    report_json = out / "benchmark_report.json"
    report_md = out / "benchmark_report.md"
    _write_csv(summary_csv, method_rows)
    _write_csv(by_condition_csv, rows)
    _write_json(report_json, report)
    report_md.write_text(_format_markdown_report(report), encoding="utf-8")
    return BenchmarkReportResult(
        output_dir=str(out),
        method_count=len(method_rows),
        condition_count=len({row["condition_key"] for row in rows}),
        summary_csv=str(summary_csv),
        by_condition_csv=str(by_condition_csv),
        report_json=str(report_json),
        report_markdown=str(report_md),
        warnings=warnings,
    )


def _load_conditions(collected_dir: Path) -> list[dict[str, Any]]:
    path = collected_dir / "cross_seed_metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"missing collected metrics: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    conditions = payload.get("conditions", [])
    if not isinstance(conditions, list):
        raise ValueError(f"invalid conditions payload: {path}")
    return [condition for condition in conditions if isinstance(condition, dict)]


def _oracle_rows(fixed_conditions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fixed_conditions:
        if row.get("planner_policy") != "fixed_topology":
            continue
        groups[_base_condition_key(row)].append(row)
    return {
        key: max(rows, key=objective_score)
        for key, rows in sorted(groups.items())
        if rows
    }


def _fixed_method_rows(
    fixed_conditions: list[dict[str, Any]],
    oracle_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for row in fixed_conditions:
        if row.get("planner_policy") != "fixed_topology":
            continue
        topology = str(row.get("topology_name", "unknown"))
        rows.append(_benchmark_row(f"fixed_{topology}", row, oracle_rows))
    return rows


def _planner_method_rows(
    conditions: list[dict[str, Any]],
    method: str,
    planner_policy: str,
    oracle_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for row in conditions:
        if row.get("planner_policy") == planner_policy:
            rows.append(_benchmark_row(method, row, oracle_rows))
    return rows


def _oracle_method_rows(
    oracle_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _benchmark_row("oracle_best_topology", row, oracle_rows, oracle_override=True)
        for row in oracle_rows.values()
    ]


def _benchmark_row(
    method: str,
    condition: dict[str, Any],
    oracle_rows: dict[str, dict[str, Any]],
    *,
    oracle_override: bool = False,
) -> dict[str, Any]:
    key = _base_condition_key(condition)
    score = objective_score(condition)
    oracle = oracle_rows.get(key)
    oracle_score = objective_score(oracle) if oracle else None
    regret = 0.0 if oracle_override else (
        float(oracle_score) - score if oracle_score is not None else None
    )
    return {
        "method": method,
        "condition_key": key,
        "objective": condition.get("objective"),
        "n_agents": condition.get("n_agents"),
        "array_size": condition.get("array_size"),
        "merge_mode": condition.get("merge_mode"),
        "init_mode": condition.get("init_mode"),
        "planner_policy": condition.get("planner_policy"),
        "topology_name": condition.get("topology_name"),
        "oracle_topology": oracle.get("topology_name") if oracle else "",
        "run_count": int(condition.get("run_count", 0) or 0),
        "score": score,
        "oracle_score": oracle_score,
        "regret_vs_oracle": regret,
        "mean_rmse": float(condition.get("mean_rmse", 0.0) or 0.0),
        "std_rmse": float(condition.get("std_rmse", 0.0) or 0.0),
        "exact_match_rate": float(condition.get("exact_match_rate", 0.0) or 0.0),
        "mean_messages": float(condition.get("mean_messages", 0.0) or 0.0),
        "mean_model_calls": float(condition.get("mean_model_calls", 0.0) or 0.0),
        "mean_token_cost": float(condition.get("mean_token_cost", 0.0) or 0.0),
        "valid_plan_rate": float(condition.get("valid_plan_rate", 0.0) or 0.0),
        "skill_grounding_rate": float(condition.get("skill_grounding_rate", 0.0) or 0.0),
        "fallback_rate": float(condition.get("fallback_rate", 0.0) or 0.0),
        "full_coverage_wrong_answer_rate": float(
            condition.get("full_coverage_wrong_answer_rate", 0.0) or 0.0
        ),
    }


def _aggregate_methods(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["method"])].append(row)
    summary = []
    for method, method_rows in sorted(groups.items()):
        run_count = sum(max(1, int(row.get("run_count", 0))) for row in method_rows)
        unique_conditions = len({row["condition_key"] for row in method_rows})
        summary.append(
            {
                "method": method,
                "condition_count": unique_conditions,
                "row_count": len(method_rows),
                "run_count": run_count,
                "mean_rmse": _weighted(method_rows, "mean_rmse"),
                "regret_vs_oracle": _weighted(method_rows, "regret_vs_oracle"),
                "mean_token_cost": _weighted(method_rows, "mean_token_cost"),
                "mean_messages": _weighted(method_rows, "mean_messages"),
                "mean_model_calls": _weighted(method_rows, "mean_model_calls"),
                "exact_match_rate": _weighted(method_rows, "exact_match_rate"),
                "valid_plan_rate": _weighted(method_rows, "valid_plan_rate"),
                "skill_grounding_rate": _weighted(method_rows, "skill_grounding_rate"),
                "fallback_rate": _weighted(method_rows, "fallback_rate"),
                "full_coverage_wrong_answer_rate": _weighted(
                    method_rows,
                    "full_coverage_wrong_answer_rate",
                ),
            }
        )
    return summary


def _weighted(rows: list[dict[str, Any]], key: str) -> float:
    total_weight = 0
    total = 0.0
    for row in rows:
        value = row.get(key)
        if value is None or value == "":
            continue
        weight = max(1, int(row.get("run_count", 0)))
        total_weight += weight
        total += float(value) * weight
    return total / total_weight if total_weight else 0.0


def _base_condition_key(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "objective": row.get("objective"),
            "n_agents": row.get("n_agents"),
            "array_size": row.get("array_size"),
            "merge_mode": row.get("merge_mode"),
            "init_mode": row.get("init_mode"),
        },
        sort_keys=True,
    )


def _claim_draft(method_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_method = {row["method"]: row for row in method_rows}
    evolved = by_method.get("evolved_skillbank_v1", {})
    frozen = by_method.get("frozen_skillbank_v0", {})
    llm_free = by_method.get("llm_free", {})
    oracle = by_method.get("oracle_best_topology", {})
    return {
        "regret_reduction_vs_frozen_percent": _percent_reduction(
            frozen.get("regret_vs_oracle"),
            evolved.get("regret_vs_oracle"),
        ),
        "regret_reduction_vs_llm_free_percent": _percent_reduction(
            llm_free.get("regret_vs_oracle"),
            evolved.get("regret_vs_oracle"),
        ),
        "token_overhead_vs_oracle_percent": _percent_overhead(
            evolved.get("mean_token_cost"),
            oracle.get("mean_token_cost"),
        ),
        "text": _claim_text(evolved, frozen, llm_free, oracle),
    }


def _claim_text(
    evolved: dict[str, Any],
    frozen: dict[str, Any],
    llm_free: dict[str, Any],
    oracle: dict[str, Any],
) -> str:
    vs_frozen = _percent_reduction(
        frozen.get("regret_vs_oracle"),
        evolved.get("regret_vs_oracle"),
    )
    vs_llm = _percent_reduction(
        llm_free.get("regret_vs_oracle"),
        evolved.get("regret_vs_oracle"),
    )
    token_overhead = _percent_overhead(
        evolved.get("mean_token_cost"),
        oracle.get("mean_token_cost"),
    )
    return (
        "On held-out test conditions, evolved_skillbank_v1 reduced "
        f"regret_vs_oracle by {_fmt_percent(vs_frozen)} versus frozen_skillbank_v0 "
        f"and by {_fmt_percent(vs_llm)} versus llm_free, while token cost was "
        f"{_fmt_percent(token_overhead)} relative to oracle_best_topology."
    )


def _percent_reduction(before: Any, after: Any) -> float | None:
    if before in {None, ""} or after in {None, ""}:
        return None
    before_value = float(before)
    if before_value == 0:
        return None
    return 100.0 * (before_value - float(after)) / abs(before_value)


def _percent_overhead(value: Any, baseline: Any) -> float | None:
    if value in {None, ""} or baseline in {None, ""}:
        return None
    baseline_value = float(baseline)
    if baseline_value == 0:
        return None
    return 100.0 * (float(value) - baseline_value) / baseline_value


def _format_markdown_report(report: dict[str, Any]) -> str:
    rows = report["method_summary"]
    lines = [
        "# MAS Skill Evolution Benchmark",
        "",
        "## Claim Draft",
        "",
        str(report["claim_draft"]["text"]),
        "",
        "## Main Table",
        "",
        (
            "| Method | Regret vs Oracle ↓ | RMSE ↓ | Token Cost ↓ | Messages ↓ | "
            "Valid Plan ↑ | Skill Grounding ↑ | Fallback ↓ | Full Coverage Wrong ↑ |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["method"]),
                    _fmt_float(row.get("regret_vs_oracle")),
                    _fmt_float(row.get("mean_rmse")),
                    _fmt_float(row.get("mean_token_cost")),
                    _fmt_float(row.get("mean_messages")),
                    _fmt_float(row.get("valid_plan_rate")),
                    _fmt_float(row.get("skill_grounding_rate")),
                    _fmt_float(row.get("fallback_rate")),
                    _fmt_float(row.get("full_coverage_wrong_answer_rate")),
                ]
            )
            + " |"
        )
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.append("")
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fmt_float(value: Any) -> str:
    if value in {None, ""}:
        return "n/a"
    return f"{float(value):.4f}"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
