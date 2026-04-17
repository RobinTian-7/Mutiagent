"""Topology-based visibility filter.

Paper reference (Sec 3.1):
  Topology determines which agents can communicate, and therefore which
  claims are visible to which agents. An agent can only act on claims
  produced by agents within its topology neighborhood (or itself).
"""

from __future__ import annotations

from src.schemas.claims import Claim
from src.topology.base import Topology


def get_visible_claims(
    agent_id: str,
    all_claims: list[Claim],
    topology: Topology,
) -> list[Claim]:
    """Filter claims to those visible to the given agent under the topology.

    An agent can see:
    - Its own claims
    - Claims from agents in its topology neighborhood
    """
    neighbors = set(topology.get_neighbors(agent_id))
    neighbors.add(agent_id)
    return [c for c in all_claims if c.agent_id in neighbors]
