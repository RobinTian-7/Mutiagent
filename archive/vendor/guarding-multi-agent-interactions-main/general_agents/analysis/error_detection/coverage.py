"""
coverage.py

Coverage computation for DIG analysis.
Implements backward traversal through solid edges to determine reachability.
"""

from typing import Dict, List

from ...core.dig import GraphNode, GraphEdge


def compute_rule_coverage(
    nodes: List[GraphNode],
    edges: List[GraphEdge],
    activation_inputs: Dict[str, List[str]],
    activation_outputs: Dict[str, List[str]],
    event_source: Dict[str, str],
) -> Dict[str, Dict[str, List[str]]]:
    """
    Coverage for alternating activation/event graph with direct vs soft edges.
    Returns node_id -> {"direct": [...], "soft": [...], "dashed": [...]}.
    Only traverses through solid edges (non-deleted, non-unconsumed, non-wait, non-system).
    """
    # Separate solid edges from dashed edges
    # Solid edges: can be traversed for coverage
    # Dashed edges: only highlighted if directly connected, not traversed
    solid_edges = [
        e for e in edges 
        if not e.meta.get("deleted", False) 
        and not e.meta.get("unconsumed", False)
        and not e.meta.get("wait", False)
        and not e.meta.get("system_event", False)
    ]
    
    dashed_edges = [
        e for e in edges 
        if e.meta.get("deleted", False) 
        or e.meta.get("unconsumed", False)
        or e.meta.get("wait", False)
        or e.meta.get("system_event", False)
    ]
    
    # Build lookup for solid edges only (for traversal)
    edges_by_src: Dict[str, List[GraphEdge]] = {}
    for e in solid_edges:
        edges_by_src.setdefault(e.src, []).append(e)
    
    # Build lookup for dashed edges (for direct highlighting only)
    dashed_by_src: Dict[str, List[GraphEdge]] = {}
    dashed_by_dst: Dict[str, List[GraphEdge]] = {}
    for e in dashed_edges:
        dashed_by_src.setdefault(e.src, []).append(e)
        dashed_by_dst.setdefault(e.dst, []).append(e)

    producer_edge_for_event: Dict[str, str] = {}
    for e in solid_edges:
        producer_edge_for_event[e.dst] = e.id

    event_out_edge_ids: Dict[str, List[str]] = {
        ev_id: [edge.id for edge in edges_by_src.get(ev_id, [])]
        for ev_id in {e.src for e in solid_edges}
    }

    results: Dict[str, Dict[str, List[str]]] = {}
    max_iters = 5000

    for n in nodes:
        if n.meta.get("type") == "event":
            direct_edges: set[str] = set(event_out_edge_ids.get(n.id, []))
            prod_edge = producer_edge_for_event.get(n.id)
            if prod_edge:
                direct_edges.add(prod_edge)
            
            # Add directly connected dashed edges (but don't traverse through them)
            dashed_edge_ids = [e.id for e in dashed_by_src.get(n.id, [])]
            
            results[n.id] = {
                "direct": sorted(direct_edges), 
                "soft": [],
                "dashed": dashed_edge_ids  # Dashed edges highlighted but not traversed
            }
            continue

        start_aid = n.id
        covered_events: set[str] = set()
        direct_edges: set[str] = set()
        soft_edges: set[str] = set()
        dashed_edge_ids: set[str] = set()

        pending = [start_aid]
        processed: set[str] = set()
        iterations = 0

        while pending:
            iterations += 1
            if iterations > max_iters:
                break

            aid = pending.pop(0)
            if aid in processed:
                continue

            outputs = activation_outputs.get(aid, [])
            if aid != start_aid and outputs and not set(outputs).issubset(covered_events):
                pending.append(aid)
                continue

            for ev_id in activation_inputs.get(aid, []):
                # Check if there's a solid edge from this event to this activation
                has_solid_edge = False
                for eo in edges_by_src.get(ev_id, []):
                    if eo.dst == aid:
                        has_solid_edge = True
                        direct_edges.add(eo.id)
                        break
                
                # Only traverse through this event if we came via a solid edge
                if not has_solid_edge:
                    continue
                
                covered_events.add(ev_id)
                
                # Add producer edge (activation -> event) and traverse backward if solid
                prod_edge = producer_edge_for_event.get(ev_id)
                if prod_edge:
                    direct_edges.add(prod_edge)
                    # Traverse to the source activation that created this event
                    src_aid = event_source.get(ev_id)
                    if src_aid:
                        pending.append(src_aid)
            
            # Add dashed edges directly connected to this activation (incoming only)
            for dashed in dashed_by_dst.get(aid, []):
                dashed_edge_ids.add(dashed.id)

            processed.add(aid)

        results[start_aid] = {
            "direct": sorted(direct_edges), 
            "soft": sorted(soft_edges),
            "dashed": sorted(dashed_edge_ids)  # Dashed edges highlighted but not traversed
        }

    return results
