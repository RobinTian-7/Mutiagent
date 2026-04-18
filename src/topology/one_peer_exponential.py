"""One-peer exponential communication topology.

This is the time-varying physical topology inspired by arXiv 2110.13363.
Each round exposes exactly one exponential-distance peer per agent. The
theoretical periodic exact-averaging result applies cleanly when the number of
nodes is a power of two; for other sizes this implementation is an engineering
mixing heuristic that keeps the same cyclic schedule.
"""

from __future__ import annotations

import math

from src.topology.base import Topology


class OnePeerExponentialTopology(Topology):
    """Directed one-peer exponential graph over agent indices.

    Round ``0`` uses distance ``1``, round ``1`` uses distance ``2``, round
    ``2`` uses distance ``4``, and so on, cycling every ``ceil(log2(n))``
    rounds. Each agent sees a single peer per round.
    """

    @property
    def tau(self) -> int:
        """Cycle length for exponential distances."""
        if self._n <= 1:
            return 0
        return math.ceil(math.log2(self._n))

    @property
    def has_periodic_exact_averaging_guarantee(self) -> bool:
        """Whether the paper's exact-averaging condition holds for this size."""
        return self._n > 1 and (self._n & (self._n - 1)) == 0

    def get_neighbors(self, agent_id: str, round_idx: int = 0) -> list[str]:
        if self._n <= 1:
            return []
        if round_idx < 0:
            raise ValueError("round_idx must be non-negative")

        idx = self.agent_ids.index(agent_id)
        distance = 2 ** (round_idx % self.tau)
        neighbor_idx = (idx + distance) % self._n
        if neighbor_idx == idx:
            return []
        return [self.agent_ids[neighbor_idx]]
