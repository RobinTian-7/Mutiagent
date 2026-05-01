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

    def format_consensus_key_instructions(self) -> str:
        """Return task-specific consensus-key guidance for solver prompts."""
        return (
            "consensus_key should be a short task-specific key suitable for "
            "cheap grouping. Use UNKNOWN when the current evidence is insufficient."
        )

    def format_adjudication_context(self, global_task: dict[str, Any]) -> dict[str, Any]:
        """Return the task context allowed in final LLM adjudication.

        This context must not include labels or ground-truth answers. Concrete
        adapters should override this when the task dictionary contains private
        evaluation fields.
        """
        blocked_keys = {
            "answer",
            "answer_index",
            "answer_key",
            "expected_answer",
            "ground_truth",
            "label",
        }
        return {
            key: value
            for key, value in global_task.items()
            if key not in blocked_keys
        }
