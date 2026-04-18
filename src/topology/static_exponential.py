"""Static exponential communication topology.

This module implements the physical communication pattern inspired by
``Exponential Graph is Provably Efficient for Decentralized Deep Training``
(arXiv 2110.13363). It only controls which neighbor states an agent can see;
it does not alter claim routing, Claim DAG reconstruction, or DTI.
"""

from __future__ import annotations

import math

from src.topology.base import Topology


class StaticExponentialTopology(Topology):
    """Directed static exponential graph over agent indices.

    For ``n`` agents, agent ``i`` can read from agents at cyclic distances
    ``1, 2, 4, ...`` up to ``2 ** (ceil(log2(n)) - 1)``. This is the directed
    first version requested for the physical communication layer.
    """

    @property
    def tau(self) -> int:
        """Number of exponential distances used by the topology."""
        if self._n <= 1:
            return 0
        return math.ceil(math.log2(self._n))

    def get_neighbors(self, agent_id: str, round_idx: int = 0) -> list[str]:
        if self._n <= 1:
            return []

        idx = self.agent_ids.index(agent_id)
        neighbors = []
        for k in range(self.tau):
            neighbor_idx = (idx + (2**k)) % self._n
            if neighbor_idx != idx:
                neighbors.append(self.agent_ids[neighbor_idx])
        return neighbors
