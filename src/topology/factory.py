"""Topology factory for configuration-driven runs."""

from __future__ import annotations

from collections.abc import Callable

from src.topology.base import Topology
from src.topology.implementations import ChainTopology, MeshTopology, StarTopology
from src.topology.one_peer_exponential import OnePeerExponentialTopology
from src.topology.static_exponential import StaticExponentialTopology


TOPOLOGY_REGISTRY: dict[str, type[Topology]] = {
    "chain": ChainTopology,
    "star": StarTopology,
    "mesh": MeshTopology,
    "static_exponential": StaticExponentialTopology,
    "one_peer_exponential": OnePeerExponentialTopology,
}


def create_topology(name: str, agent_ids: list[str]) -> Topology:
    """Create a topology by configuration name."""
    try:
        topology_cls: Callable[[list[str]], Topology] = TOPOLOGY_REGISTRY[name]
    except KeyError as exc:
        valid = ", ".join(sorted(TOPOLOGY_REGISTRY))
        raise ValueError(f"Unknown topology '{name}'. Valid options: {valid}") from exc
    return topology_cls(agent_ids)


def topology_names() -> list[str]:
    """Return supported topology names."""
    return sorted(TOPOLOGY_REGISTRY)
