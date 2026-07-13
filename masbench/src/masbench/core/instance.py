"""Normalized cross-benchmark task instance."""
# ============================================================
# 【模块导读】跨 benchmark 归一化的任务实例数据模型：把不同 benchmark 的一道
# 任务统一表示为 shards（各 agent 私有分片）+ ground_truth（期望的全局答案）。
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# 【职责】一道 benchmark 任务实例，跨 benchmark 归一化。
# - shards[i]：agent i 持有的私有数据分片；ground_truth：期望的全局答案
#   （适配器负责不让它进入 agent 可见上下文）。
# - task_prompt：任务提示模板；meta：额外元信息（如 is_segmented 分段标记）。
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

    # 【职责】构造后校验：n_agents 必须为正，且 shards 数量与 n_agents 一致。
    def __post_init__(self) -> None:
        if self.n_agents < 1:
            raise ValueError("n_agents must be positive")
        if len(self.shards) != self.n_agents:
            raise ValueError(
                f"expected {self.n_agents} shards, got {len(self.shards)}"
            )

    # 【职责】是否为分段任务：每个 agent 各有自己的期望输出，而非共享一个答案。
    # - 分段实例不能用单一投票全局答案打分；引擎按 meta['expected_outputs'][i]
    #   对每个 agent 分别评分。
    @property
    def segmented(self) -> bool:
        """True iff each agent has its OWN expected answer (not one shared one).

        Segmented instances cannot be scored by the single voted global answer;
        the engine grades each agent against ``meta['expected_outputs'][i]``.
        """
        return bool(self.meta.get("is_segmented", False))
