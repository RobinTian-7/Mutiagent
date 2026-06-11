"""CSV ingestion helpers for MAS skill evolution."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from exp_graph.mas.objective_metrics import primary_loss


def read_csv_rows(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_experiment_directory(directory: Path | str) -> dict[str, list[dict[str, Any]]]:
    path = Path(directory)
    return {
        "aggregate": read_csv_rows(path / "aggregate_summary.csv"),
        "runs": read_csv_rows(path / "run_summary.csv"),
    }


def aggregate_rows_to_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for row in rows:
        has_rmse = "MeanFinalRMSE" in row and row["MeanFinalRMSE"] not in (None, "")
        has_primary = "MeanPrimaryMetric" in row and row["MeanPrimaryMetric"] not in (
            None,
            "",
        )
        # Generic benchmarks (e.g. Silo-Bench success-rate) emit a primary metric
        # that may be higher-is-better. Convert it to a uniform lower-is-better
        # loss so it slots into the same scoring/evolution machinery as CF RMSE.
        mean_primary_loss: float | None = None
        primary_metric_name: str | None = None
        if has_primary:
            primary_metric_name = str(row.get("PrimaryMetricName", "rmse"))
            mean_primary_loss = primary_loss(
                primary_metric_name,
                float(row["MeanPrimaryMetric"]),
            )

        # Bridge: CF rows keep mean_rmse driven by MeanFinalRMSE byte-for-byte.
        # Generic rows without MeanFinalRMSE reuse the primary loss as the
        # lower-is-better accuracy signal downstream scoring reads.
        if has_rmse:
            mean_rmse = float(row["MeanFinalRMSE"])
        elif mean_primary_loss is not None:
            mean_rmse = mean_primary_loss
        else:
            mean_rmse = 0.0

        item: dict[str, Any] = {
            "topology_name": row["Topology"],
            "n_agents": int(row["Agents"]),
            "array_size": int(row.get("ArraySize", 0) or 0),
            "merge_mode": row["MergeMode"],
            "init_mode": row.get("InitMode", "deterministic"),
            "runs": int(row["Runs"]),
            "mean_rmse": mean_rmse,
            "std_rmse": float(row.get("StdFinalRMSE", 0.0) or 0.0),
            "mean_norm_l1": float(row.get("MeanFinalNormalizedL1Error", 0.0) or 0.0),
            "exact_match_rate": float(row.get("ExactMatchRate", 0.0) or 0.0),
            "mean_steps": float(row["MeanTotalSteps"]),
            "mean_messages": float(row["MeanTotalMessages"]),
            "mean_model_calls": float(row["MeanTotalModelCalls"]),
            "mean_token_cost": float(row["MeanTokenCost"]),
            "mean_vote_top_ratio": float(row.get("MeanVoteTopRatio", 0.0) or 0.0),
        }
        if mean_primary_loss is not None:
            item["mean_primary_loss"] = mean_primary_loss
            item["primary_metric_name"] = primary_metric_name
        # Rows that carry the EXECUTED schedule keep it through conversion so
        # ``_best_protocol_spec`` can store it on skill cards (the
        # select_then_refine replay anchor). CF rows never carry it -> no new key.
        if row.get("protocol_spec") is not None:
            item["protocol_spec"] = row["protocol_spec"]
        evidence.append(item)
    return evidence


def group_evidence_by_topology(
    evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        grouped.setdefault(str(item["topology_name"]), []).append(item)
    return grouped
