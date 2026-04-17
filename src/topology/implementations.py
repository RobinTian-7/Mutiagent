"""Concrete topology implementations.

Paper reference (Sec 3.1):
  Chain, Star, Mesh (fully connected) are among the topologies used.
  "denser topologies (mesh, star) support longer-lived cascades than
   locally connected structures (chain)"
"""

from __future__ import annotations

from src.topology.base import Topology


class ChainTopology(Topology):
    """Linear chain: agent i can communicate with agents i-1 and i+1.

    Paper: "locally connected structure" with restricted propagation.
    """

    def get_neighbors(self, agent_id: str) -> list[str]:
        idx = self.agent_ids.index(agent_id)
        neighbors = []
        if idx > 0:
            neighbors.append(self.agent_ids[idx - 1])
        if idx < self._n - 1:
            neighbors.append(self.agent_ids[idx + 1])
        return neighbors


class StarTopology(Topology):
    """Star: a central hub connected to all others; spokes only see the hub.

    Paper: "star" topology produces stronger reinforcement than chain.
    The first agent is the hub.
    """

    @property
    def hub(self) -> str:
        return self.agent_ids[0]

    def get_neighbors(self, agent_id: str) -> list[str]:
        if agent_id == self.hub:
            return [a for a in self.agent_ids if a != self.hub]
        return [self.hub]


class MeshTopology(Topology):
    """Fully connected mesh: every agent can communicate with every other.

    Paper: "fully connected" topology — "denser topologies support
    longer-lived cascades."
    """

    def get_neighbors(self, agent_id: str) -> list[str]:
        return [a for a in self.agent_ids if a != agent_id]


# --- Extensibility stubs ---
# These topologies are mentioned in the paper but not fully specified.
# TODO: Implement tree, hierarchical, sparse mesh, dynamic reputation
# when paper provides sufficient detail.
