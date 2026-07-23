"""Organization operators that compile to finite protocol graph specs."""

from __future__ import annotations

from dataclasses import dataclass

from exp_graph.protocols import (
    ProtocolGraphSpec,
    ProtocolStepSpec,
    build_protocol_schedule,
)


@dataclass(frozen=True)
class OrganizationOperator:
    """Declarative description of an organization operator."""

    name: str
    description: str


OPERATOR_REGISTRY: dict[str, OrganizationOperator] = {
    "local_solve": OrganizationOperator("local_solve", "Agents solve local shards."),
    "peer_propagate": OrganizationOperator(
        "peer_propagate",
        "Agents spread partial beliefs through one-peer exponential propagation.",
    ),
    "mesh_broadcast": OrganizationOperator(
        "mesh_broadcast",
        "Agents broadcast to all other agents in one dense step.",
    ),
    "tree_reduce": OrganizationOperator(
        "tree_reduce",
        "Agents reduce information through a binary tree into the final sink.",
    ),
    "star_sink": OrganizationOperator(
        "star_sink",
        "Non-sink agents send to the final sink in one gather step.",
    ),
    "vote_select": OrganizationOperator(
        "vote_select",
        "Final selection uses vote across answer holders.",
    ),
    "average_select": OrganizationOperator(
        "average_select",
        "Final selection prefers averaged full-coverage answers.",
    ),
    "fallback": OrganizationOperator(
        "fallback",
        "Planner records a fallback organization policy.",
    ),
}


def compose_protocol_from_operators(
    *,
    name: str,
    n_agents: int,
    operators: list[str],
    max_messages: int | None = None,
) -> ProtocolGraphSpec:
    """Compile supported operator compositions into a finite protocol spec."""
    normalized = [operator.strip().lower() for operator in operators]
    topology = topology_for_operator_chain(normalized)
    schedule = build_protocol_schedule(topology, n_agents)
    steps = [
        ProtocolStepSpec(
            transmissions=step.transmissions,
            description=step.description,
            operator=operator_for_description(step.description, normalized),
        )
        for step in schedule
    ]
    metadata: dict[str, object] = {
        "compiled_from_topology": topology,
        "planner_generated": True,
    }
    if max_messages is not None:
        metadata["max_messages"] = max_messages
    return ProtocolGraphSpec(
        name=name,
        n_agents=n_agents,
        steps=steps,
        operators=normalized,
        metadata=metadata,
    )


def topology_for_operator_chain(operators: list[str]) -> str:
    """Return the nearest supported topology for an operator chain."""
    operator_set = set(operators)
    if "peer_propagate" in operator_set and "star_sink" in operator_set:
        return "one_peer_exponential_dag_star"
    if "peer_propagate" in operator_set and "tree_reduce" in operator_set:
        return "one_peer_exponential_dag_tree"
    if "peer_propagate" in operator_set:
        return "one_peer_exponential_dag_vote"
    if "mesh_broadcast" in operator_set and "star_sink" in operator_set:
        return "mesh_star"
    if "mesh_broadcast" in operator_set:
        return "mesh"
    if "tree_reduce" in operator_set:
        return "tree"
    if "star_sink" in operator_set:
        return "star"
    return "chain"


def operator_for_description(description: str, operators: list[str]) -> str:
    """Infer the dominant organization operator for a compiled schedule step."""
    text = description.lower()
    if "one_peer" in text:
        return "peer_propagate"
    if "mesh" in text and "aggregation" not in text:
        return "mesh_broadcast"
    if "tree" in text or "reduction" in text:
        return "tree_reduce"
    if "star" in text or "sink" in text or "gather" in text:
        return "star_sink"
    return next((item for item in operators if item != "local_solve"), "custom")
