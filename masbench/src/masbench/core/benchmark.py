"""Benchmark adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from masbench.core.instance import BenchmarkInstance


class BenchmarkAdapter(ABC):
    """A source of normalized BenchmarkInstances for one benchmark."""

    name: str

    @abstractmethod
    def iter_instances(self, **filters: Any) -> Iterable[BenchmarkInstance]:
        """Yield instances, optionally narrowed by benchmark-specific filters."""
        ...
