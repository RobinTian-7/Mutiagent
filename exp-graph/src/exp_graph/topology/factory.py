"""Topology factory."""

from __future__ import annotations

from exp_graph.topology.base import Topology
from exp_graph.topology.implementations import (
    ChainTopology,
    MeshTopology,
    OnePeerExponentialTopology,
    RingTopology,
    StarTopology,
    StaticExponentialTopology,
)


TOPOLOGIES: dict[str, type[Topology]] = {
    "chain": ChainTopology,
    "ring": RingTopology,
    "star": StarTopology,
    "mesh": MeshTopology,
    "static_exponential": StaticExponentialTopology,
    "one_peer_exponential": OnePeerExponentialTopology,
}


def create_topology(name: str) -> Topology:
    """Create a topology implementation by config name."""
    try:
        return TOPOLOGIES[name]()
    except KeyError as exc:
        valid = ", ".join(sorted(TOPOLOGIES))
        raise ValueError(f"Unknown topology '{name}'. Valid options: {valid}") from exc


def topology_names() -> list[str]:
    """Return supported topology names."""
    return sorted(TOPOLOGIES)
