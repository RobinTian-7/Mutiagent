"""Topology interface for physical neighbor communication."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Topology(ABC):
    """Physical communication topology.

    Topology controls which previous-round outboxes are visible to an agent.
    It does not decide task logic, belief updates, consensus, or final answers.
    """

    name: str

    @abstractmethod
    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        """Return neighbor agent ids visible at a global communication round."""
        ...


def validate_agent_id(agent_id: int, n_agents: int) -> None:
    """Raise if an agent id is outside the active population."""
    if n_agents < 1:
        raise ValueError("n_agents must be positive")
    if agent_id < 0 or agent_id >= n_agents:
        raise ValueError(f"agent_id {agent_id} out of range for {n_agents} agents")
