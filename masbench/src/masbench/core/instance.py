"""Normalized cross-benchmark task instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchmarkInstance:
    """One benchmark task instance, normalized across benchmarks.

    ``shards[i]`` is the private data held by agent ``i``. ``ground_truth`` is the
    expected global answer (kept out of agent-visible context by the adapter).
    """

    benchmark: str
    case_id: str
    case_name: str
    n_agents: int
    shards: list[Any]
    ground_truth: Any
    task_prompt: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.n_agents < 1:
            raise ValueError("n_agents must be positive")
        if len(self.shards) != self.n_agents:
            raise ValueError(
                f"expected {self.n_agents} shards, got {len(self.shards)}"
            )
