"""Static (non-LLM) hierarchy planners.

The static planner is the ``Emperor decides everything ahead of time, by code``
case from the meeting notes. It is deterministic, requires no LLM call, and
serves both as a runnable baseline and as the ground-truth shape that later
LLM planners must remain compatible with.

M1 covers ``fanout_schedule=[N]`` (1 emperor + N soldiers, no middle layer).
M2 generalizes this to arbitrary ``fanout_schedule = [F1, ..., FL]``:

- Layer 0: 1 emperor.
- Layer 1: ``F1`` ministers (or soldiers if ``L==1``).
- Layer 2: ``F1 * F2`` sub-managers (or soldiers if ``L==2``).
- ...
- Layer L: ``prod(F)`` soldiers (always leaves).

Soldier shards are split into ``prod(F)`` near-equal contiguous ranges in
soldier-index order. Middle layers carry empty shards and aggregate inbox
partials only.
"""

from __future__ import annotations

from math import prod

from exp_graph.hierarchy.plan import AgentNode, HierarchyPlan, Role


def build_static_hierarchy_plan(
    fanout_schedule: list[int],
    *,
    array_length: int | None = None,
) -> HierarchyPlan:
    """Build a static hierarchy plan from a fan-out schedule."""
    if not fanout_schedule:
        raise ValueError("fanout_schedule must contain at least one element")
    if any(int(f) < 1 for f in fanout_schedule):
        raise ValueError("fanout values must be positive integers")

    fanout = [int(f) for f in fanout_schedule]
    layer_sizes = [1]
    for f in fanout:
        layer_sizes.append(layer_sizes[-1] * f)
    n_total = sum(layer_sizes)
    n_soldiers = layer_sizes[-1]
    n_layers_with_emperor = len(layer_sizes)

    layer_offsets = [0]
    for size in layer_sizes[:-1]:
        layer_offsets.append(layer_offsets[-1] + size)

    nodes: list[AgentNode] = [
        AgentNode(
            agent_id=0,
            role=Role.EMPEROR,
            layer=0,
            parent_id=None,
            children_ids=[],
            soldier_index=None,
            shard_indices=None,
        )
    ]

    soldier_index = 0
    for layer_idx in range(1, n_layers_with_emperor):
        size = layer_sizes[layer_idx]
        offset = layer_offsets[layer_idx]
        parent_offset = layer_offsets[layer_idx - 1]
        f = fanout[layer_idx - 1]
        role = _role_for_layer(layer_idx, n_layers_with_emperor)

        for i in range(size):
            agent_id = offset + i
            parent_id = parent_offset + (i // f)
            assigned_soldier_index: int | None = None
            if role == Role.SOLDIER:
                assigned_soldier_index = soldier_index
                soldier_index += 1
            nodes.append(
                AgentNode(
                    agent_id=agent_id,
                    role=role,
                    layer=layer_idx,
                    parent_id=parent_id,
                    children_ids=[],
                    soldier_index=assigned_soldier_index,
                    shard_indices=None,
                )
            )

    for node in nodes:
        if node.parent_id is not None:
            nodes[node.parent_id].children_ids.append(node.agent_id)

    if array_length is not None:
        ranges = _equal_shard_ranges(n_soldiers, array_length)
        for node in nodes:
            if node.role == Role.SOLDIER and node.soldier_index is not None:
                node.shard_indices = ranges[node.soldier_index]

    plan = HierarchyPlan(
        n_total=n_total,
        layers=layer_sizes,
        nodes=nodes,
        fanout_schedule=fanout,
        metadata={
            "planner": "static",
            "shape": "+".join(str(size) for size in layer_sizes),
            "n_soldiers": n_soldiers,
            "split_strategy": "equal_shard_by_index",
            "array_length": array_length,
            "depth": len(fanout) + 1,
        },
    )
    return plan


def build_emperor_soldiers_plan(
    n_soldiers: int,
    *,
    array_length: int | None = None,
) -> HierarchyPlan:
    """Back-compat wrapper for the M1 ``[N]`` shape (1 emperor + N soldiers)."""
    if n_soldiers < 1:
        raise ValueError("n_soldiers must be at least 1")
    return build_static_hierarchy_plan(
        [n_soldiers],
        array_length=array_length,
    )


def shape_label_to_fanout(label: str) -> list[int]:
    """Parse a shape label like ``"2x4"`` or ``"8"`` into a fan-out schedule."""
    cleaned = str(label).strip().lower().replace(" ", "")
    if not cleaned:
        raise ValueError("shape label must be non-empty")
    parts = cleaned.split("x")
    fanout = []
    for part in parts:
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(
                f"shape label {label!r} contains non-integer segment {part!r}"
            ) from exc
        if value < 1:
            raise ValueError(f"shape label {label!r} contains a non-positive segment")
        fanout.append(value)
    return fanout


def shape_label_for_fanout(fanout_schedule: list[int]) -> str:
    """Render a canonical shape label like ``"2x4"`` for a fan-out schedule."""
    if not fanout_schedule:
        return ""
    return "x".join(str(int(f)) for f in fanout_schedule)


def expected_total_agents(fanout_schedule: list[int]) -> int:
    """Return ``1 + sum(prod(prefix))`` for a fan-out schedule."""
    if not fanout_schedule:
        return 1
    sizes = [1]
    for f in fanout_schedule:
        sizes.append(sizes[-1] * int(f))
    return sum(sizes)


def expected_n_soldiers(fanout_schedule: list[int]) -> int:
    """Return the number of leaf soldiers implied by a fan-out schedule."""
    if not fanout_schedule:
        return 1
    return prod(int(f) for f in fanout_schedule)


def _role_for_layer(layer_idx: int, n_layers_with_emperor: int) -> Role:
    if layer_idx == 0:
        return Role.EMPEROR
    if layer_idx == n_layers_with_emperor - 1:
        return Role.SOLDIER
    if layer_idx == 1:
        return Role.MINISTER
    return Role.SUB_MANAGER


def _equal_shard_ranges(
    n_soldiers: int,
    array_length: int,
) -> list[tuple[int, int]]:
    """Split ``array_length`` indices into ``n_soldiers`` near-equal ranges."""
    if array_length < 0:
        raise ValueError("array_length must be non-negative")
    if n_soldiers < 1:
        raise ValueError("n_soldiers must be positive")

    base_size, remainder = divmod(array_length, n_soldiers)
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for soldier_index in range(n_soldiers):
        size = base_size + (1 if soldier_index < remainder else 0)
        ranges.append((cursor, cursor + size))
        cursor += size
    return ranges
