"""Generic, benchmark-agnostic score record (not RMSE-bound)."""
# ============================================================
# 【模块导读】通用、与 benchmark 无关的评分记录（不绑定 RMSE），
# 记录一次实例跑完流水线后的成败与开销指标。
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# 【职责】一道 benchmark 实例跑完整条流水线后的结果记录。
# - success 成败；partial 部分正确度；n_messages/n_model_calls/tokens 为开销；
#   final_answer 最终答案；extra 额外信息。
@dataclass
class ScoreResult:
    """Outcome of running one benchmark instance through the pipeline."""

    success: bool
    partial: float | None = None
    n_messages: int = 0
    n_model_calls: int = 0
    tokens: int = 0
    final_answer: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
