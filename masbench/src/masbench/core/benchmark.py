"""Benchmark adapter interface."""
# ============================================================
# 【模块导读】benchmark 适配器接口：定义所有 benchmark 数据源的抽象基类，
# 统一产出归一化后的 BenchmarkInstance 实例（供 benchmark 框架逐实例读取）。
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from masbench.core.instance import BenchmarkInstance


# 【职责】某个 benchmark 的归一化 BenchmarkInstance 实例来源（抽象基类）。
class BenchmarkAdapter(ABC):
    """A source of normalized BenchmarkInstances for one benchmark."""

    name: str

    # 【职责】产出实例，可选地用 benchmark 专属过滤器（filters）收窄范围。
    @abstractmethod
    def iter_instances(self, **filters: Any) -> Iterable[BenchmarkInstance]:
        """Yield instances, optionally narrowed by benchmark-specific filters."""
        ...
