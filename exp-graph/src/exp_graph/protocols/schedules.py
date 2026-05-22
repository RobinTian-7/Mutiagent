"""Finite directed communication schedules for protocol experiments."""

from __future__ import annotations

import math
import random

from pydantic import BaseModel, Field


class CommunicationStep(BaseModel):
    """One simultaneous directed communication step."""

    step_idx: int
    transmissions: list[tuple[int, int]] = Field(default_factory=list)
    description: str = ""

    @property
    def active_senders(self) -> set[int]:
        return {src for src, _ in self.transmissions}

    @property
    def active_receivers(self) -> set[int]:
        return {dst for _, dst in self.transmissions}


def build_protocol_schedule(
    topology_name: str,
    n_agents: int,
    *,
    star_center: int = 0,
    include_star_broadcast: bool = False,
    random_seed: int = 0,
) -> list[CommunicationStep]:
    """Build the finite communication protocol for the requested topology."""
    if n_agents < 1:
        raise ValueError("n_agents must be positive")
    if not 0 <= star_center < n_agents:
        raise ValueError("star_center must be a valid agent id")
    if n_agents == 1:
        return []

    topology = topology_name.strip().lower()
    if topology == "chain":
        return [
            CommunicationStep(
                step_idx=idx,
                transmissions=[(idx, idx + 1)],
                description=f"chain: agent {idx} sends to agent {idx + 1}",
            )
            for idx in range(n_agents - 1)
        ]

    if topology == "tree":
        return _build_binary_reduce_tree_schedule(n_agents)

    if topology == "star":
        leaves = [agent_id for agent_id in range(n_agents) if agent_id != star_center]
        schedule = [
            CommunicationStep(
                step_idx=0,
                transmissions=[(leaf, star_center) for leaf in leaves],
                description=f"star: leaves send to center agent {star_center}",
            )
        ]
        if include_star_broadcast:
            schedule.append(
                CommunicationStep(
                    step_idx=1,
                    transmissions=[(star_center, leaf) for leaf in leaves],
                    description=f"star: center agent {star_center} broadcasts",
                )
            )
        return schedule

    if topology == "mesh":
        return _build_mesh_propagation(n_agents)

    if topology in {
        "mesh_star",
        "mesh_sink",
        "mesh_dag_star",
        "mesh_dag_sink",
    }:
        return _build_mesh_protocol(n_agents, aggregation="star")

    if topology == "dag_mesh":
        return _build_dag_mesh_schedule(n_agents)

    if topology in {"random", "random_dag"}:
        return _build_random_dag_schedule(n_agents, random_seed=random_seed)

    if topology == "static_exponential_dag":
        return _build_static_exponential_dag_schedule(n_agents)

    if topology in {
        "one_peer_exponential_dag",
        "one_peer_exponential_dag_vote",
    }:
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="vote",
        )

    if topology == "one_peer_exponential_dag_tree":
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="tree",
        )

    if topology == "one_peer_exponential_dag_star":
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="star",
        )

    if topology in {
        "one_peer_exponential_dag_static",
        "one_peer_exponential_dag_static_exponential_dag",
    }:
        return _build_one_peer_exponential_dag_protocol(
            n_agents,
            aggregation="static_exponential_dag",
        )

    if topology in {"two_stage_layer", "layer_two_stage", "two_stage"}:
        return _build_two_stage_layer_schedule(n_agents)

    if topology in {
        "balanced_log_layer",
        "balance_log_layer",
        "layer_balanced_log",
        "layer_balance_log",
        "balanced_log",
        "balance_log",
    }:
        return _build_balanced_log_layer_schedule(n_agents)

    if topology == "static_exponential":
        return _build_static_exponential_propagation(n_agents)

    if topology in {
        "static_exponential_star",
        "static_exponential_sink",
        "static_exponential_dag_star",
        "static_exponential_dag_sink",
    }:
        return _build_static_exponential_protocol(n_agents, aggregation="star")

    if topology == "one_peer_exponential":
        tau = _tau(n_agents)
        return [
            CommunicationStep(
                step_idx=step_idx,
                transmissions=_dedupe_edges(
                    (src, (src + 2**step_idx) % n_agents)
                    for src in range(n_agents)
                ),
                description=(
                    "one_peer_exponential: "
                    f"distance {2**step_idx} peer phase"
                ),
            )
            for step_idx in range(tau)
        ]

    raise ValueError(f"unsupported protocol topology: {topology_name}")


def _tau(n_agents: int) -> int:
    return max(1, math.ceil(math.log2(n_agents)))


def _build_binary_reduce_tree_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build a balanced binary reduction tree into the final agent."""
    schedule: list[CommunicationStep] = []
    stride = 1
    step_idx = 0
    while stride < n_agents:
        transmissions: list[tuple[int, int]] = []
        block_size = stride * 2
        for block_start in range(0, n_agents, block_size):
            left_sink = min(block_start + stride - 1, n_agents - 1)
            right_sink = min(block_start + block_size - 1, n_agents - 1)
            if left_sink < right_sink:
                transmissions.append((left_sink, right_sink))
        if transmissions:
            schedule.append(
                CommunicationStep(
                    step_idx=step_idx,
                    transmissions=transmissions,
                    description=(
                        "tree: binary reduction "
                        f"stride={stride} into right-block sinks"
                    ),
                )
            )
            step_idx += 1
        stride *= 2
    return schedule


def _build_dag_mesh_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build a dense DAG swept in topological destination order."""
    return [
        CommunicationStep(
            step_idx=dst - 1,
            transmissions=[(src, dst) for src in range(dst)],
            description=f"dag_mesh: all predecessors send to agent {dst}",
        )
        for dst in range(1, n_agents)
    ]


def _build_random_dag_schedule(
    n_agents: int,
    *,
    random_seed: int,
) -> list[CommunicationStep]:
    """Build a seeded sparse random DAG swept in destination order.

    Agent ids define the DAG topological order, so edges always point from a
    lower id to a higher id. A chain backbone is always present to guarantee
    every source can eventually reach the final sink agent ``n_agents - 1``.
    Extra forward edges are sampled with a modest density so the baseline stays
    sparse and comparable to the other finite protocols.
    """
    rng = random.Random(random_seed)
    edge_probability = min(0.5, max(0.25, math.log2(n_agents) / n_agents))
    edges: set[tuple[int, int]] = {
        (src, src + 1)
        for src in range(n_agents - 1)
    }
    for src in range(n_agents):
        for dst in range(src + 2, n_agents):
            if rng.random() < edge_probability:
                edges.add((src, dst))

    schedule: list[CommunicationStep] = []
    for dst in range(1, n_agents):
        transmissions = [
            (src, dst)
            for src in range(dst)
            if (src, dst) in edges
        ]
        schedule.append(
            CommunicationStep(
                step_idx=len(schedule),
                transmissions=transmissions,
                description=(
                    "random_dag: seeded random predecessors "
                    f"send to agent {dst} "
                    f"(seed={random_seed}, p={edge_probability:.3f})"
                ),
            )
        )
    return schedule


def _build_mesh_propagation(n_agents: int) -> list[CommunicationStep]:
    """Build one dense all-to-all mesh propagation step."""
    return [
        CommunicationStep(
            step_idx=0,
            transmissions=[
                (src, dst)
                for src in range(n_agents)
                for dst in range(n_agents)
                if src != dst
            ],
            description="mesh: all agents broadcast to all other agents",
        )
    ]


def _build_mesh_protocol(
    n_agents: int,
    *,
    aggregation: str,
) -> list[CommunicationStep]:
    """Build mesh propagation followed by a final reducer into one sink."""
    schedule = _build_mesh_propagation(n_agents)
    if aggregation == "star":
        tail = _build_star_sink_gather_schedule(
            n_agents,
            description_prefix="mesh",
        )
    else:
        raise ValueError(f"unsupported mesh aggregation: {aggregation}")
    return _renumber_schedule([*schedule, *tail])


def _build_static_exponential_dag_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build sparse exponential predecessor layers in destination order."""
    tau = _tau(n_agents)
    schedule: list[CommunicationStep] = []
    for dst in range(1, n_agents):
        transmissions = [
            (dst - 2**phase, dst)
            for phase in range(tau)
            if dst - 2**phase >= 0
        ]
        if transmissions:
            schedule.append(
                CommunicationStep(
                    step_idx=len(schedule),
                    transmissions=transmissions,
                    description=(
                        "static_exponential_dag: exponential predecessors "
                        f"send to agent {dst}"
                    ),
                )
            )
    return schedule


def _build_static_exponential_propagation(
    n_agents: int,
) -> list[CommunicationStep]:
    """Build repeated fixed exponential-edge propagation phases."""
    tau = _tau(n_agents)
    transmissions = _dedupe_edges(
        (src, (src + 2**phase) % n_agents)
        for src in range(n_agents)
        for phase in range(tau)
    )
    return [
        CommunicationStep(
            step_idx=step_idx,
            transmissions=transmissions,
            description="static_exponential: fixed exponential edges",
        )
        for step_idx in range(tau)
    ]


def _build_static_exponential_protocol(
    n_agents: int,
    *,
    aggregation: str,
) -> list[CommunicationStep]:
    """Build static exponential propagation followed by one final sink."""
    schedule = _build_static_exponential_propagation(n_agents)
    if aggregation == "star":
        tail = _build_star_sink_gather_schedule(
            n_agents,
            description_prefix="static_exponential",
        )
    else:
        raise ValueError(
            f"unsupported static exponential aggregation: {aggregation}"
        )
    return _renumber_schedule([*schedule, *tail])


def _build_one_peer_exponential_dag_propagation(
    n_agents: int,
) -> list[CommunicationStep]:
    """Build wrapping one-peer exponential propagation phases.

    Each phase uses distance 2^k (mod n_agents), so high-index agents wrap
    around and send to low-index agents (e.g. round 0: 7→0; round 1: 6→0,
    7→1).  After ceil(log2(n)) phases every agent holds all n agents' data.
    """
    schedule: list[CommunicationStep] = []
    for phase in range(_tau(n_agents)):
        distance = 2**phase
        transmissions = [
            (src, (src + distance) % n_agents)
            for src in range(n_agents)
        ]
        schedule.append(
            CommunicationStep(
                step_idx=len(schedule),
                transmissions=transmissions,
                description=(
                    "one_peer_exponential_dag: "
                    f"distance {distance} propagation"
                ),
            )
        )
    return schedule


def _build_one_peer_exponential_dag_protocol(
    n_agents: int,
    *,
    aggregation: str,
) -> list[CommunicationStep]:
    """Build one-peer DAG propagation followed by an optional final reducer."""
    schedule = _build_one_peer_exponential_dag_propagation(n_agents)
    if aggregation == "vote":
        return schedule
    if aggregation == "tree":
        tail = _build_binary_reduce_tree_schedule(n_agents)
    elif aggregation == "star":
        tail = _build_star_sink_gather_schedule(
            n_agents,
            description_prefix="one_peer_exponential_dag",
        )
    elif aggregation == "static_exponential_dag":
        tail = _build_static_exponential_dag_schedule(n_agents)
    else:
        raise ValueError(f"unsupported one-peer DAG aggregation: {aggregation}")
    return _renumber_schedule([*schedule, *tail])


def _build_star_sink_gather_schedule(
    n_agents: int,
    *,
    description_prefix: str,
) -> list[CommunicationStep]:
    """Build a single star gather into the final agent as protocol sink."""
    sink = n_agents - 1
    return [
        CommunicationStep(
            step_idx=0,
            transmissions=[
                (src, sink)
                for src in range(n_agents)
                if src != sink
            ],
            description=(
                f"{description_prefix} aggregation: "
                f"star gather to agent {sink}"
            ),
        )
    ]


def _build_two_stage_layer_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build input -> hidden -> final-sink dense layered communication."""
    sink = n_agents - 1
    non_sink = list(range(sink))
    if not non_sink:
        return []
    if len(non_sink) == 1:
        return [
            CommunicationStep(
                step_idx=0,
                transmissions=[(non_sink[0], sink)],
                description="two_stage_layer: only input agent sends to final sink",
            )
        ]

    split_idx = math.ceil(len(non_sink) / 2)
    input_layer = non_sink[:split_idx]
    hidden_layer = non_sink[split_idx:]
    schedule = [
        CommunicationStep(
            step_idx=0,
            transmissions=[
                (src, dst)
                for src in input_layer
                for dst in hidden_layer
            ],
            description="two_stage_layer: input layer sends to hidden layer",
        ),
        CommunicationStep(
            step_idx=1,
            transmissions=[(src, sink) for src in hidden_layer],
            description="two_stage_layer: hidden layer sends to final sink",
        ),
    ]
    return [step for step in schedule if step.transmissions]


def _build_balanced_log_layer_schedule(n_agents: int) -> list[CommunicationStep]:
    """Build log-depth balanced layers with adjacent-layer dense edges."""
    sink = n_agents - 1
    non_sink = list(range(sink))
    if not non_sink:
        return []

    layer_count = max(1, math.ceil(math.log2(n_agents)))
    layers = _partition_contiguous(non_sink, layer_count)
    layers.append([sink])

    schedule: list[CommunicationStep] = []
    for step_idx, (src_layer, dst_layer) in enumerate(zip(layers, layers[1:])):
        transmissions = [
            (src, dst)
            for src in src_layer
            for dst in dst_layer
        ]
        if transmissions:
            schedule.append(
                CommunicationStep(
                    step_idx=step_idx,
                    transmissions=transmissions,
                    description=(
                        "balanced_log_layer: dense adjacent-layer transfer "
                        f"layer {step_idx} -> {step_idx + 1}"
                    ),
                )
            )
    return schedule


def _partition_contiguous(items: list[int], layer_count: int) -> list[list[int]]:
    """Split ordered agent ids into near-equal contiguous non-empty layers."""
    if not items:
        return []
    layer_count = max(1, min(layer_count, len(items)))
    base_size, remainder = divmod(len(items), layer_count)
    layers: list[list[int]] = []
    cursor = 0
    for layer_idx in range(layer_count):
        size = base_size + (1 if layer_idx < remainder else 0)
        layers.append(items[cursor : cursor + size])
        cursor += size
    return layers


def _renumber_schedule(schedule: list[CommunicationStep]) -> list[CommunicationStep]:
    """Return a schedule with contiguous step indices."""
    return [
        step.model_copy(update={"step_idx": step_idx})
        for step_idx, step in enumerate(schedule)
    ]


def _dedupe_edges(edges) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    ordered: list[tuple[int, int]] = []
    for src, dst in edges:
        edge = (int(src), int(dst))
        if edge[0] == edge[1] or edge in seen:
            continue
        seen.add(edge)
        ordered.append(edge)
    return ordered
