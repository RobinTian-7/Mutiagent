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

from __future__ import annotations

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
