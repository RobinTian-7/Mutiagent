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

import re
from abc import ABC, abstractmethod


class Topology(ABC):
    """Abstract topology defining agent communication visibility."""

    def __init__(self, agent_ids: list[str]):
        self.agent_ids = list(agent_ids)
        self._n = len(self.agent_ids)

    @abstractmethod
    def get_neighbors(self, agent_id: str, round_idx: int = 0) -> list[str]:
        """Return agent IDs visible to this agent at a workflow round.

        ``round_idx`` is ignored by static topologies and used by time-varying
        topologies such as one-peer exponential graphs. The interface models
        physical communication visibility only; claim selection remains owned by
        the routing layer.
        """
        ...

    def can_communicate(
        self,
        from_agent: str,
        to_agent: str,
        round_idx: int = 0,
    ) -> bool:
        """Check if from_agent can send messages to to_agent."""
        return to_agent in self.get_neighbors(from_agent, round_idx=round_idx)

    @property
    def name(self) -> str:
        base_name = self.__class__.__name__.replace("Topology", "")
        return re.sub(r"(?<!^)(?=[A-Z])", "_", base_name).lower()

    @property
    def n_agents(self) -> int:
        """Number of agents in this topology."""
        return self._n
