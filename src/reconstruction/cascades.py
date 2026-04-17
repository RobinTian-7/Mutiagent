"""Cascade extraction from claims.

Paper reference (Sec 3.2):
  "Each claim is associated with a root identifier, which defines a cascade
   as the set of all claims that share the same root."
  C_r = {c_i ∈ C | root(c_i) = c_r}

Paper (Appendix B.5):
  "Given a root claim c_root, we define its coordination cascade as the
   reachable subgraph of all downstream claim and event instances
   associated with that root."
"""

from __future__ import annotations

from collections import defaultdict

from src.schemas.cascades import Cascade
from src.schemas.claims import Claim
from src.schemas.events import Event


def extract_cascades(
    claims: list[Claim],
    events: list[Event] | None = None,
) -> list[Cascade]:
    """Extract cascades by grouping claims and events by root_claim_id.

    Paper: "Cascades are connected subgraphs of G corresponding to the
    propagation of reasoning initiated by a single claim."
    """
    # Group claims by root_claim_id
    claims_by_root: dict[str, list[str]] = defaultdict(list)
    for claim in claims:
        root = claim.root_claim_id
        if root:
            claims_by_root[root].append(claim.claim_id)

    # Group events by root_claim_id
    events_by_root: dict[str, list[str]] = defaultdict(list)
    if events:
        for event in events:
            root = event.root_claim_id
            if root:
                events_by_root[root].append(event.event_id)

    cascades = []
    for root_id, claim_ids in claims_by_root.items():
        cascades.append(
            Cascade(
                root_claim_id=root_id,
                claim_ids=claim_ids,
                event_ids=events_by_root.get(root_id, []),
            )
        )

    return cascades


def get_cascade_sizes(cascades: list[Cascade]) -> list[int]:
    """Get list of cascade sizes (|C_r|) for distributional analysis."""
    return [c.size for c in cascades]


def export_cascade_summary(cascades: list[Cascade]) -> list[dict]:
    """Export cascade summary as JSON-serializable list."""
    return [
        {
            "root_claim_id": c.root_claim_id,
            "cascade_size": c.size,
            "tce": c.tce,
            "claim_ids": c.claim_ids,
        }
        for c in cascades
    ]
