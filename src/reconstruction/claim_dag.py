"""Claim DAG reconstruction from event traces.

Paper reference (Appendix B.5):
  "We reconstruct coordination structures from event traces in two stages:
   (i) subtask-tree construction from delegation events, and
   (ii) claim-DAG construction from claim-level lineage fields."

  "Claims form a separate structure that captures how reasoning evolves.
   Each claim is represented as a node indexed by claim_id.
   Directed edges are created from every element of parent_claim_ids
   to the current claim."
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from src.schemas.claims import Claim
from src.schemas.events import Event


def reconstruct_claim_dag(claims: list[Claim]) -> nx.DiGraph:
    """Build the claim DAG G = (C, E_c) from claim lineage.

    Paper (Sec 3.2): "(c_i, c_j) ∈ E_c if c_i ∈ P(c_j)"
    Edges go from parent to child.

    Returns:
        NetworkX DiGraph with claim_id as node labels.
    """
    g = nx.DiGraph()

    for claim in claims:
        g.add_node(
            claim.claim_id,
            agent_id=claim.agent_id,
            claim_type=claim.claim_type.value,
            root_claim_id=claim.root_claim_id,
            claim_depth=claim.claim_depth,
        )
        for parent_id in claim.parent_claim_ids:
            g.add_edge(parent_id, claim.claim_id)

    return g


def reconstruct_subtask_tree(claims: list[Claim], events: list[Event]) -> nx.DiGraph:
    """Build the subtask tree from delegation events.

    Paper (Appendix B.5): "For each delegate_subtask event, we create a new
    subtask node and add a directed edge from parent_subtask_id to subtask_id."
    """
    from src.schemas.events import EventType

    g = nx.DiGraph()

    for event in events:
        if event.event_type == EventType.DELEGATE_SUBTASK:
            if event.target_subtask_id:
                g.add_node(event.target_subtask_id, agent_id=event.agent_id)
                # Find parent subtask from the target claim's subtask
                if event.target_claim_id:
                    parent_claim = next(
                        (c for c in claims if c.claim_id == event.target_claim_id),
                        None,
                    )
                    if parent_claim and parent_claim.subtask_id:
                        g.add_edge(parent_claim.subtask_id, event.target_subtask_id)

    return g


def export_claim_dag(dag: nx.DiGraph) -> dict[str, Any]:
    """Export claim DAG as JSON-serializable dict."""
    return {
        "nodes": [
            {"id": n, **dag.nodes[n]} for n in dag.nodes
        ],
        "edges": [
            {"source": u, "target": v} for u, v in dag.edges
        ],
        "num_nodes": dag.number_of_nodes(),
        "num_edges": dag.number_of_edges(),
    }
