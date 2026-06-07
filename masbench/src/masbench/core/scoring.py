"""Generic, benchmark-agnostic score record (not RMSE-bound)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
