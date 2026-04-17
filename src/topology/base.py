"""Base topology interface.

Paper reference (Sec 3.1):
  Topologies tested: chain, star, tree, hierarchical, fully connected,
  sparse mesh, dynamic reputation.
  "LangGraph enforces the specified topology and manages message routing."

Topology determines who can communicate with whom — the physical
communication graph. This is separate from claim routing (which claim
to act on next).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Topology(ABC):
    """Abstract topology defining agent communication visibility."""

    def __init__(self, agent_ids: list[str]):
        self.agent_ids = list(agent_ids)
        self._n = len(self.agent_ids)

    @abstractmethod
    def get_neighbors(self, agent_id: str) -> list[str]:
        """Return agent IDs that this agent can communicate with."""
        ...

    def can_communicate(self, from_agent: str, to_agent: str) -> bool:
        """Check if from_agent can send messages to to_agent."""
        return to_agent in self.get_neighbors(from_agent)

    @property
    def name(self) -> str:
        return self.__class__.__name__.lower().replace("topology", "")
