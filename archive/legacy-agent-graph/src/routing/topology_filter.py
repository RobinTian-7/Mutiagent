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
    round_idx: int = 0,
) -> list[Claim]:
    """Filter claims to those visible to the given agent under the topology.

    An agent can see:
    - Its own claims
    - Claims from agents in its physical topology neighborhood for this round

    The returned objects are structured ``Claim`` records. This keeps physical
    neighbor communication separate from claim routing and avoids exchanging
    free-form chain-of-thought transcripts.
    """
    neighbors = set(topology.get_neighbors(agent_id, round_idx=round_idx))
    neighbors.add(agent_id)
    return [c for c in all_claims if c.agent_id in neighbors]
