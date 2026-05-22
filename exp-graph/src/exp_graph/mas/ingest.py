"""CSV ingestion helpers for MAS skill evolution."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


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
        evidence.append(
            {
                "topology_name": row["Topology"],
                "n_agents": int(row["Agents"]),
                "array_size": int(row["ArraySize"]),
                "merge_mode": row["MergeMode"],
                "init_mode": row.get("InitMode", "deterministic"),
                "runs": int(row["Runs"]),
                "mean_rmse": float(row["MeanFinalRMSE"]),
                "std_rmse": float(row["StdFinalRMSE"]),
                "mean_norm_l1": float(row["MeanFinalNormalizedL1Error"]),
                "exact_match_rate": float(row["ExactMatchRate"]),
                "mean_steps": float(row["MeanTotalSteps"]),
                "mean_messages": float(row["MeanTotalMessages"]),
                "mean_model_calls": float(row["MeanTotalModelCalls"]),
                "mean_token_cost": float(row["MeanTokenCost"]),
                "mean_vote_top_ratio": float(row["MeanVoteTopRatio"]),
            }
        )
    return evidence


def group_evidence_by_topology(
    evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        grouped.setdefault(str(item["topology_name"]), []).append(item)
    return grouped
