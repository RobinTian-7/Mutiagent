"""Held-out validation objective for QueenBee skill evolution.

This implements the scoring half of the paper's "accept a skill update only if
it improves a held-out objective" rule. :func:`validation_objective` measures a
skill bank by asking, for each held-out condition, which topology the emperor
planner would select and how good that topology actually is on the held-out
data. The result (``J_val``) is uniformly lower-is-better, so a candidate bank
is an improvement iff its ``J_val`` is no larger than the current bank's.

The companion *gate* lives in :mod:`exp_graph.mas.consolidation`; it computes
``J_val`` before and after applying a patch batch to a cloned bank and only
commits the patches when the held-out objective does not regress.

``validation_rows`` use the same aggregate-row dict shape ministers consume
(``Topology``/``Agents``/``ArraySize``/``MeanFinalRMSE``/...), so callers can
pass held-out aggregate rows straight through.
"""

# ============================================================
# 【模块导读】QueenBee 技能进化的留出集(held-out)验证目标。
# 实现论文规则"只有改进留出目标才接受技能更新"中的打分一半：
# validation_objective 对每个留出条件问两件事——皇帝(规划 LLM)会选哪个
# 拓扑、该拓扑在留出数据上实际表现如何。结果 J_val 统一为越低越好，
# 候选技能库只有在 J_val 不高于现库时才算改进。
# 与之配套的"门"(gate)在 exp_graph.mas.consolidation：对克隆库先后计算
# 补丁批次前/后的 J_val，留出目标不退步才提交补丁。
# validation_rows 与大臣(minister)消费的聚合行字典同构，可直接透传。
# ============================================================

from __future__ import annotations

from collections import defaultdict
from statistics import fmean
from typing import Any

from exp_graph.mas.objective_metrics import primary_loss
from exp_graph.mas.planner import EmperorPlanner
from exp_graph.mas.schemas import ObjectiveName, ObjectiveSpec, PlannerRequest
from exp_graph.mas.skill_bank import SkillBank

# 中文：当规划器在某条件下选中一个没有任何留出测量的拓扑时，在该条件
#   已观测的最差损失之上再加这个惩罚——未测量(因此未验证)的拓扑绝不能
#   看起来比最差的已测量选项更好。
# Penalty added on top of the worst observed loss in a condition when the
# planner selects a topology that has no held-out measurement there. Selecting
# an unmeasured (and therefore unvalidated) topology should never look better
# than the worst measured option.
_UNMEASURED_PENALTY = 1.0


# 【职责】计算技能库 bank 在留出行上的 J_val（越低越好），是验证门的打分函数。
# - 按 (Agents, ArraySize, task_family) 分组出条件；每个条件让皇帝规划器选拓扑，
#   再查该拓扑在留出行里的损失；选了没测量过的拓扑记 max_loss+1.0（惩罚项）。
# - J_val = 各条件损失的均值；validation_rows 为空返回 0.0（无留出数据时门为空操作）。
def validation_objective(
    bank: SkillBank,
    validation_rows: list[dict[str, Any]],
    *,
    objective_name: ObjectiveName = "balanced",
) -> float:
    """Return ``J_val`` (lower is better) for ``bank`` on held-out rows.

    For each distinct condition (grouped by ``(Agents, ArraySize)``) the emperor
    planner selects a topology; we look up that topology's lower-is-better loss
    in the held-out rows for the condition. If the chosen topology has no row in
    the condition we charge ``max_loss_in_condition + 1.0``. ``J_val`` is the
    mean over conditions. Empty ``validation_rows`` returns ``0.0`` so the gate
    is a no-op when no held-out data is available.
    """
    if not validation_rows:
        return 0.0

    objective = ObjectiveSpec.from_name(objective_name)
    planner = EmperorPlanner(bank)
    grouped = _group_rows_by_condition(validation_rows)

    condition_losses: list[float] = []
    for (n_agents, array_size, task_family), rows in grouped.items():
        loss_by_topology = _losses_by_topology(rows)
        request = PlannerRequest(
            task_family=task_family,
            n_agents=n_agents,
            array_size=array_size,
            objective=objective,
        )
        chosen_topology = planner.plan(request).topology_name
        if chosen_topology in loss_by_topology:
            condition_losses.append(loss_by_topology[chosen_topology])
        else:
            worst = max(loss_by_topology.values()) if loss_by_topology else 0.0
            condition_losses.append(worst + _UNMEASURED_PENALTY)

    return fmean(condition_losses) if condition_losses else 0.0


# 【职责】把留出行按条件键 (n_agents, array_size, task_family) 分组；
# 兼容两套字段名（n_agents/Agents 等），task_family 缺省为 count_frequency。
def _group_rows_by_condition(
    validation_rows: list[dict[str, Any]],
) -> dict[tuple[int, int | None, str], list[dict[str, Any]]]:
    grouped: dict[tuple[int, int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for row in validation_rows:
        n_agents = _row_int(row, "n_agents", "Agents")
        if n_agents is None:
            n_agents = 1
        array_size = _row_int(row, "array_size", "ArraySize")
        task_family = str(
            row.get("task_family")
            or row.get("TaskFamily")
            or "count_frequency"
        )
        grouped[(n_agents, array_size, task_family)].append(row)
    return grouped


# 【职责】把一个条件内的行映射成 {拓扑: 越低越好的损失}。
# - 同一拓扑多行取均值；优先用已统一为损失的 mean_primary_loss，否则把
#   越高越好的主指标经 primary_loss 转换，最后兜底 RMSE 风格列（CF 行必有）。
def _losses_by_topology(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Map each topology in a condition to its lower-is-better loss.

    When several rows share a topology in one condition (rare for aggregate
    rows) the mean loss is used. ``mean_primary_loss`` is preferred because it is
    already converted to a uniform loss; otherwise a higher-is-better primary
    metric is converted via :func:`primary_loss`, falling back to the RMSE-style
    columns that count-frequency rows always carry.
    """
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        topology = str(row.get("topology_name") or row.get("Topology") or "")
        loss = _row_loss(row)
        if loss is not None:
            grouped[topology].append(loss)
    return {topology: fmean(values) for topology, values in grouped.items() if values}


# 【职责】读出单行的"越低越好"主损失；读不到返回 None（该行被跳过）。
def _row_loss(row: dict[str, Any]) -> float | None:
    """Read a single row's lower-is-better primary loss, or ``None``."""
    value = _row_float(row, "mean_primary_loss")
    if value is not None:
        return value
    primary = _row_float(row, "MeanPrimaryMetric")
    if primary is not None:
        metric_name = str(
            row.get("primary_metric_name") or row.get("PrimaryMetricName") or "rmse"
        )
        return primary_loss(metric_name, primary)
    return _row_float(row, "mean_rmse", "MeanFinalRMSE", "MeanPrimaryMetric")


def _row_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in {None, ""}:
            continue
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _row_int(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if value in {None, ""}:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
    return None
