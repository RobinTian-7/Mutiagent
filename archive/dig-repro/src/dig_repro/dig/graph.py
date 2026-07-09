"""DIG graph export."""

from __future__ import annotations

import networkx as nx


def build_dig_graph(*, events, activations) -> dict:
    graph = nx.DiGraph()
    for event in events.values():
        graph.add_node(
            f"event:{event.event_id}",
            kind="event",
            event_type=event.event_type.value,
            logical_time=event.created_at,
            final_answer=event.final_answer,
            lineage_id=event.lineage_id,
        )
    for activation in activations:
        graph.add_node(
            f"activation:{activation.activation_id}",
            kind="activation",
            agent_id=activation.agent_id,
            logical_time=activation.logical_time,
        )
        for event_id in activation.processed_event_ids + activation.waited_event_ids + activation.rerouted_event_ids + activation.discarded_event_ids:
            if f"event:{event_id}" in graph:
                graph.add_edge(f"event:{event_id}", f"activation:{activation.activation_id}")
        for event_id in activation.produced_event_ids:
            if f"event:{event_id}" in graph:
                graph.add_edge(f"activation:{activation.activation_id}", f"event:{event_id}")
    ordered = sorted(activations, key=lambda item: item.logical_time)
    for left, right in zip(ordered, ordered[1:]):
        graph.add_edge(
            f"activation:{left.activation_id}",
            f"activation:{right.activation_id}",
            kind="temporal",
        )
    return {
        "nodes": [{"id": node_id, **attrs} for node_id, attrs in graph.nodes(data=True)],
        "edges": [{"source": source, "target": target, **attrs} for source, target, attrs in graph.edges(data=True)],
        "activation_timeline": [
            {
                "activation_id": activation.activation_id,
                "agent_id": activation.agent_id,
                "logical_time": activation.logical_time,
            }
            for activation in ordered
        ],
    }

