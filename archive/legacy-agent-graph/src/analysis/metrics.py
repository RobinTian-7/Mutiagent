"""Analysis metrics from the paper's observables.

Paper reference (Sec 3.3):
  - Cascade size: |C_r| = Σ_{c_i ∈ C_r} 1  (Eq. 1)
  - TCE: TCE(c_r) = Σ_{e_k ∈ E_r} 1  (Eq. 2)
  - Top-k contribution share: S_k(c_r) = Σ_{a ∈ Top-k} n_a(c_r) / Σ_{a ∈ A} n_a(c_r) (Eq. 3)
  - Extreme-event scaling: x_max(N) = max_{c_r} |C_r|

Paper (Sec 3.3, Table 1):
  - Delegation cascade size: subtask tree node count
  - Revision wave: chain length of revise_claim events
  - Contradiction burst: distinct agents contradicting same parent
  - Merge fan-in: parent count in merge_claims event
"""

from __future__ import annotations

from collections import Counter, defaultdict

from src.schemas.cascades import Cascade
from src.schemas.claims import Claim
from src.schemas.events import Event, EventType


def compute_tce(cascades: list[Cascade]) -> list[int]:
    """Total Cognitive Effort per cascade (Paper Eq. 2)."""
    return [c.tce for c in cascades]


def compute_cascade_sizes(cascades: list[Cascade]) -> list[int]:
    """Cascade sizes (Paper Eq. 1)."""
    return [c.size for c in cascades]


def compute_top_k_contribution(
    claims: list[Claim],
    cascades: list[Cascade],
    k_fractions: list[float] = [0.10, 0.25, 0.50],
    agent_ids: list[str] | None = None,
) -> dict[str, dict]:
    """Top-k contribution share per cascade (Paper Eq. 3).

    Paper: S_k(c_r) = Σ_{a ∈ Top-k} n_a(c_r) / Σ_{a ∈ A} n_a(c_r)

    Returns dict mapping cascade root_id to contribution metrics.
    """
    claim_index = {c.claim_id: c for c in claims}
    results = {}

    for cascade in cascades:
        # Count claims per agent in this cascade
        agent_counts: Counter = Counter()
        for cid in cascade.claim_ids:
            claim = claim_index.get(cid)
            if claim:
                agent_counts[claim.agent_id] += 1

        total = sum(agent_counts.values())
        if total == 0:
            continue

        # Sort agents by contribution (descending)
        sorted_agents = agent_counts.most_common()

        shares = {}
        for frac in k_fractions:
            if agent_ids:
                k = max(1, int(len(agent_ids) * frac))
            else:
                k = max(1, int(len(sorted_agents) * frac))

            top_k_count = sum(count for _, count in sorted_agents[:k])
            shares[f"top_{int(frac*100)}pct"] = top_k_count / total

        results[cascade.root_claim_id] = {
            "cascade_size": cascade.size,
            "tce": cascade.tce,
            "num_contributing_agents": len(agent_counts),
            **shares,
        }

    return results


def compute_delegation_cascade_sizes(events: list[Event]) -> list[int]:
    """Delegation cascade sizes from subtask tree.

    Paper Table 1: "Number of events in the subtask tree rooted at a
    delegate_subtask event."
    """
    # Group delegation events by their subtask chains
    delegation_events = [e for e in events if e.event_type == EventType.DELEGATE_SUBTASK]
    if not delegation_events:
        return []

    # Count events per root subtask
    subtask_events: dict[str, int] = defaultdict(int)
    for e in delegation_events:
        subtask_events[e.root_claim_id] += 1

    return list(subtask_events.values())


def compute_revision_wave_lengths(claims: list[Claim]) -> list[int]:
    """Revision wave lengths.

    Paper Table 1: "Length of a chain of revise_claim events linked
    by parent_claim_id."
    """
    from src.schemas.claims import ClaimType

    revised = [c for c in claims if c.claim_type == ClaimType.REVISED]
    if not revised:
        return []

    # Build parent→child map for revised claims
    children: dict[str, list[str]] = defaultdict(list)
    revised_ids = {c.claim_id for c in revised}
    revised_map = {c.claim_id: c for c in revised}

    for c in revised:
        for pid in c.parent_claim_ids:
            children[pid].append(c.claim_id)

    # Find chain starts (revised claims whose parent is not also revised)
    chain_starts = []
    for c in revised:
        parents_revised = any(pid in revised_ids for pid in c.parent_claim_ids)
        if not parents_revised:
            chain_starts.append(c.claim_id)

    # Trace chains
    lengths = []
    for start in chain_starts:
        length = 1
        current = start
        while children.get(current):
            # Follow the first revised child (chains are linear)
            revised_children = [ch for ch in children[current] if ch in revised_ids]
            if not revised_children:
                break
            current = revised_children[0]
            length += 1
        lengths.append(length)

    return lengths


def compute_contradiction_burst_sizes(claims: list[Claim]) -> list[int]:
    """Contradiction burst sizes.

    Paper Table 1: "Number of distinct agents issuing contradict_claim
    on the same parent claim."

    ASSUMPTION (A4): temporal window τ = 1 step (not enforced here;
    all contradictions of the same parent are grouped).
    """
    from src.schemas.claims import ClaimType

    contradictions = [c for c in claims if c.claim_type == ClaimType.CONTRADICTORY]
    if not contradictions:
        return []

    # Group by parent claim
    parent_agents: dict[str, set[str]] = defaultdict(set)
    for c in contradictions:
        for pid in c.parent_claim_ids:
            parent_agents[pid].add(c.agent_id)

    return [len(agents) for agents in parent_agents.values()]


def compute_merge_fan_in(events: list[Event]) -> list[int]:
    """Merge fan-in sizes.

    Paper Table 1: "Number of parent_claim_ids referenced by a single
    merge_claims event."
    """
    merge_events = [e for e in events if e.event_type == EventType.MERGE_CLAIMS]
    return [len(e.parent_claim_ids) for e in merge_events]


def export_contribution_metrics(
    contribution: dict[str, dict],
) -> list[dict]:
    """Export top-k contribution metrics as JSON-serializable list."""
    return [
        {"root_claim_id": root_id, **metrics}
        for root_id, metrics in contribution.items()
    ]
