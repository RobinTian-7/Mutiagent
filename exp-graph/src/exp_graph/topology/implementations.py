"""Concrete physical communication topologies."""

from __future__ import annotations

import math

from exp_graph.topology.base import Topology, validate_agent_id


class ChainTopology(Topology):
    """Simple undirected chain."""

    name = "chain"

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        neighbors = []
        if agent_id > 0:
            neighbors.append(agent_id - 1)
        if agent_id < n_agents - 1:
            neighbors.append(agent_id + 1)
        return neighbors


class StarTopology(Topology):
    """Hub-and-spoke topology with agent 0 as the hub."""

    name = "star"

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        if n_agents == 1:
            return []
        if agent_id == 0:
            return list(range(1, n_agents))
        return [0]


class MeshTopology(Topology):
    """Fully connected mesh for the first implementation."""

    name = "mesh"

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        return [idx for idx in range(n_agents) if idx != agent_id]


class StaticExponentialTopology(Topology):
    """Directed static exponential graph.

    Agent ``i`` sees cyclic neighbors at distances ``1, 2, 4, ...`` up to
    ``ceil(log2(n_agents))`` phases. This first version is intentionally
    directed and can be extended later for bidirectional variants.
    """

    name = "static_exponential"

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        if n_agents == 1:
            return []

        tau = math.ceil(math.log2(n_agents))
        neighbors = []
        for phase in range(tau):
            neighbor = (agent_id + (2**phase)) % n_agents
            if neighbor != agent_id:
                neighbors.append(neighbor)
        return neighbors


class OnePeerExponentialTopology(Topology):
    """Directed time-varying one-peer exponential graph."""

    name = "one_peer_exponential"

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        if round_idx < 0:
            raise ValueError("round_idx must be non-negative")
        if n_agents == 1:
            return []

        tau = math.ceil(math.log2(n_agents))
        distance = 2 ** (round_idx % tau)
        neighbor = (agent_id + distance) % n_agents
        if neighbor == agent_id:
            return []
        return [neighbor]


class RingTopology(Topology):
    """Undirected ring (cyclic chain): each agent connects to its two neighbours,
    wrapping around so agent 0 and agent n-1 are also adjacent."""

    name = "ring"

    def get_neighbors(
        self,
        agent_id: int,
        round_idx: int,
        n_agents: int,
    ) -> list[int]:
        validate_agent_id(agent_id, n_agents)
        if n_agents == 1:
            return []
        if n_agents == 2:
            return [1 - agent_id]
        return [(agent_id - 1) % n_agents, (agent_id + 1) % n_agents]


def is_power_of_two(value: int) -> bool:
    """Return whether ``value`` is a positive power of two."""
    return value > 0 and (value & (value - 1)) == 0
