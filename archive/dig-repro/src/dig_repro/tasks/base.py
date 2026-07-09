"""Task interface for DIG benchmarks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TaskAdapter(ABC):
    task_name: str

    @abstractmethod
    def build_problem_instance(self, *, difficulty: str, seed: int, **kwargs: Any) -> dict[str, Any]:
        """Build one benchmark instance."""

    @abstractmethod
    def format_problem_spec(self, problem: dict[str, Any]) -> str:
        """Human-readable task spec for prompts."""

    @abstractmethod
    def all_item_ids(self, problem: dict[str, Any]) -> list[int]:
        """Return root coverage ids for the task."""

    @abstractmethod
    def split_coverage(
        self,
        problem: dict[str, Any],
        coverage_ids: list[int],
        n_parts: int,
    ) -> list[list[int]]:
        """Split one subproblem into smaller coverage sets."""

    @abstractmethod
    def fetch_raw_data(
        self,
        problem: dict[str, Any],
        coverage_ids: list[int],
    ) -> dict[str, Any]:
        """Fetch raw task data for a specific coverage set."""

    @abstractmethod
    def solve_raw_data_payload(
        self,
        problem: dict[str, Any],
        raw_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Programmatic helper used by deterministic tests/planners."""

    @abstractmethod
    def merge_solution_payloads(
        self,
        problem: dict[str, Any],
        solutions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Merge multiple partial solutions."""

    @abstractmethod
    def is_complete_solution(
        self,
        problem: dict[str, Any],
        solution_payload: dict[str, Any],
    ) -> bool:
        """Return whether a solution covers the root problem."""

    @abstractmethod
    def compute_rmse(
        self,
        problem: dict[str, Any],
        solution_payload: dict[str, Any] | None,
    ) -> float | None:
        """Compute RMSE against the task ground truth."""

    @abstractmethod
    def normalize_solution(
        self,
        problem: dict[str, Any],
        solution_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Normalize a final solution for metrics and export."""

    def recommended_split_threshold(self, problem: dict[str, Any]) -> int:
        return max(8, len(self.all_item_ids(problem)) // 8)
