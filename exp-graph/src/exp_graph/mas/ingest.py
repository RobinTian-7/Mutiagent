"""CSV ingestion helpers for MAS skill evolution."""

# ============================================================
# 【模块导读】MAS 技能进化的 CSV 摄入辅助。
# - 读取实验目录的 aggregate_summary.csv / run_summary.csv；
# - 把聚合行转换为进化用的证据字典(统一主损失、桥接 mean_rmse)并按拓扑分组。
# ============================================================
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from exp_graph.mas.objective_metrics import primary_loss


# 【职责】把 CSV 读成字典行列表。
def read_csv_rows(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


# 【职责】加载实验目录：返回 {"aggregate": 聚合行, "runs": 单次运行行}。
def load_experiment_directory(directory: Path | str) -> dict[str, list[dict[str, Any]]]:
    path = Path(directory)
    return {
        "aggregate": read_csv_rows(path / "aggregate_summary.csv"),
        "runs": read_csv_rows(path / "run_summary.csv"),
    }


# 【职责】把聚合行(aggregate row)转成技能进化用的证据字典列表(键转小写蛇形)。
def aggregate_rows_to_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for row in rows:
        has_rmse = "MeanFinalRMSE" in row and row["MeanFinalRMSE"] not in (None, "")
        has_primary = "MeanPrimaryMetric" in row and row["MeanPrimaryMetric"] not in (
            None,
            "",
        )
        # 中文：通用基准(如 Silo-Bench 成功率)给出的主指标可能是越高越好。
        #   把它转成统一的越低越好主损失，以接入与 CF RMSE 相同的评分/进化机制。
        # Generic benchmarks (e.g. Silo-Bench success-rate) emit a primary metric
        # that may be higher-is-better. Convert it to a uniform lower-is-better
        # loss so it slots into the same scoring/evolution machinery as CF RMSE.
        mean_primary_loss: float | None = None
        primary_metric_name: str | None = None
        if row.get("mean_primary_loss") is not None:
            # Evolution may provide a denser staged loss than the public report
            # metric. Preserve that explicit training signal verbatim.
            mean_primary_loss = float(row["mean_primary_loss"])
            primary_metric_name = str(
                row.get("primary_metric_name", "evolution_stage_score")
            )
        elif has_primary:
            primary_metric_name = str(row.get("PrimaryMetricName", "rmse"))
            mean_primary_loss = primary_loss(
                primary_metric_name,
                float(row["MeanPrimaryMetric"]),
            )

        # 中文：桥接：CF 行的 mean_rmse 仍由 MeanFinalRMSE 逐字节驱动；
        #   没有 MeanFinalRMSE 的通用行则复用主损失，作为下游评分读取的
        #   越低越好精度信号。
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
        # 中文：携带"已执行调度"(protocol_spec)的行在转换后保留该字段，供
        #   _best_protocol_spec 把它存到技能卡上(select_then_refine 的回放锚点)。
        #   CF 行从不携带 -> 不新增键。
        # Rows that carry the EXECUTED schedule keep it through conversion so
        # ``_best_protocol_spec`` can store it on skill cards (the
        # select_then_refine replay anchor). CF rows never carry it -> no new key.
        if row.get("protocol_spec") is not None:
            item["protocol_spec"] = row["protocol_spec"]
        # 中文：信息目标与结构来源随行透传——技能卡的模式隔离与 clean 入库判定
        #   都从这里读取。CF 行从不携带 -> 不新增键。
        # information_goal / provenance ride through so cards inherit the mode
        # namespace and clean-admission provenance. CF rows never carry them.
        if row.get("information_goal"):
            item["information_goal"] = row["information_goal"]
        if row.get("provenance"):
            item["provenance"] = row["provenance"]
        if row.get("planner_mode"):
            item["planner_mode"] = row["planner_mode"]
        for key in (
            "case_id",
            "seed",
            "program_validity",
            "structural_coverage",
            "submission_rate",
            "evolution_partial",
            "evolution_success",
            "evolution_stage",
            "evolution_stage_score",
            "graph_generation_failed",
            "program_generation_failed",
            "python_generation_failed",
            "python_failure_category",
            "python_source",
            "program_sha256",
            "ast_policy_version",
            "execution_contract_version",
            "worker_contract",
            "repair_attempts",
            "runtime_trace_summary",
            "python_artifacts_dir",
            "python_innovation_strategy",
            "python_parent_skill_id",
            "python_exposed_insight_ids",
            "python_used_insight_ids",
            "python_mutation_provenance",
            "selected_skill_id",
            "hot_start_source",
            "hot_start_protocol",
            "hot_start_branch",
            "hot_start_pair_id",
            "hot_start_parent_skill_id",
            "hot_start_context_skill_ids",
            "hot_start_context_exposed_to_architect",
        ):
            if row.get(key) is not None:
                item[key] = row[key]
        evidence.append(item)
    return evidence


# 【职责】把证据字典按 topology_name 分组。
def group_evidence_by_topology(
    evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        grouped.setdefault(str(item["topology_name"]), []).append(item)
    return grouped
