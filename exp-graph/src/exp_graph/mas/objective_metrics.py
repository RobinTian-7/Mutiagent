"""Uniform primary-objective handling for MAS skill evolution.

Historically the QueenBee evolution loop assumed the primary task metric was a
count-frequency RMSE, where *lower is better*. To support arbitrary benchmarks
(e.g. Silo-Bench success-rate, where *higher is better*) without forking the
scoring/evolution machinery, we convert every primary metric into a uniform
lower-is-better **primary loss** via :func:`primary_loss`.

The existing scoring code already treats its accuracy signal as lower-is-better
(``min_max_normalize(..., invert=True)``), so once a metric is expressed as a
loss it slots into the same machinery unchanged.
"""

# ============================================================
# 【模块导读】MAS 技能进化的统一主目标处理。
# - 历史上 QueenBee 进化循环假设主指标是 count_frequency 的 RMSE(越低越好)；
# - 为支持任意基准(如 Silo-Bench 成功率，越高越好)而不分叉评分/进化机制，
#   primary_loss 把每个主指标统一转换成越低越好的主损失；
# - 既有评分代码本就按越低越好处理精度信号(min_max_normalize(..., invert=True))，
#   指标一旦表示为损失，即可不加改动地接入同一机制。
# ============================================================
from __future__ import annotations

# 中文：值越大越好的主指标名集合。这些指标按 1 - value 转为损失(截断到 [0,1])。
#   其余名字(包括 "rmse" 与缺失/空名)视为本就越低越好的损失，原样透传。
# Primary-metric names where a larger value means a better outcome. These are
# converted to a loss as ``1 - value`` (clamped to ``[0, 1]``). Any other name
# (including ``"rmse"`` or an absent/empty name) is treated as already being a
# lower-is-better loss and passed through unchanged.
HIGHER_IS_BETTER_METRICS: frozenset[str] = frozenset(
    {
        "success",
        "success_rate",
        "exact_match",
        "primary",
        "partial",
    }
)


# 【职责】把任意主指标换算成统一的"越低越好"主损失。
# - metric_name 为 "rmse"(或空/None/其他越低越好名)时原样返回 metric_value，
#   count_frequency 的 RMSE 路径行为完全不变；
# - 越高越好名(见 HIGHER_IS_BETTER_METRICS)返回 1 - value 并截断到 [0,1]：
#   满分 1.0 -> 损失 0.0，完全失败 0.0 -> 损失 1.0。
def primary_loss(metric_name: str | None, metric_value: float) -> float:
    """Return a uniform lower-is-better loss for any primary metric.

    - ``metric_name == "rmse"`` (or empty / ``None`` / any other lower-is-better
      name) returns ``metric_value`` unchanged, so the count-frequency RMSE path
      behaves exactly as before.
    - A higher-is-better name (see :data:`HIGHER_IS_BETTER_METRICS`) returns
      ``1 - metric_value`` clamped to ``[0, 1]`` so a perfect score (1.0) maps to
      loss 0.0 and a total failure (0.0) maps to loss 1.0.
    """
    value = float(metric_value)
    name = (metric_name or "").strip().lower()
    if name in HIGHER_IS_BETTER_METRICS:
        loss = 1.0 - value
        if loss < 0.0:
            return 0.0
        if loss > 1.0:
            return 1.0
        return loss
    return value
