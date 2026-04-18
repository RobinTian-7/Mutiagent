"""Task adapter interface.

Task-specific logic belongs behind this interface so the multi-agent runtime
can test communication topology effects without knowing task semantics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TaskAdapter(ABC):
    """Pluggable task interface."""

    task_name: str

    @abstractmethod
    def build_global_task(self, **kwargs: Any) -> dict[str, Any]:
        """Build or normalize a global task shared by all agents."""
        ...

    @abstractmethod
    def split_into_local_observations(
        self,
        global_task: dict[str, Any],
        n_agents: int,
    ) -> list[dict[str, Any]]:
        """Split the shared task into per-agent local observations."""
        ...

    @abstractmethod
    def initial_local_solve(self, local_observation: dict[str, Any]) -> dict[str, Any]:
        """Return an initial belief_state from only local observation."""
        ...

    @abstractmethod
    def normalize_consensus_key(self, key_or_proposal: str | None) -> str:
        """Normalize task-specific answer keys for grouping and voting."""
        ...

    @abstractmethod
    def evaluate_final_answer(
        self,
        global_task: dict[str, Any],
        final_key: str | None,
    ) -> bool:
        """Evaluate whether the final key solves the global task."""
        ...

    @abstractmethod
    def format_task_prompt_context(
        self,
        global_task: dict[str, Any],
        local_observation: dict[str, Any],
    ) -> str:
        """Format task context for an agent prompt."""
        ...
