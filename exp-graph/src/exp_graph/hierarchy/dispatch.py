"""Per-agent dispatch tree derived from a hierarchy plan.

A *dispatch tree* is the explicit "派活" record from emperor:

- For each minister / sub-manager: which slice of the global array its
  sub-tree should aggregate, plus a short instruction.
- For each soldier: the exact ``[start, end)`` shard it should count.

The static planner builds this mechanically from the plan's shard ranges. The
LLM planner (M3) may either provide an explicit dispatch tree of its own or
omit it; in the omitted case we fall back to the mechanical version so the
plan still has a consistent dispatch record visible in trace.

Dispatch entries are serialisable; they live both in ``HierarchyPlan.metadata``
(for traceability) and in each agent's ``local_observation`` (so prompts can
quote the emperor's instruction back at the agent).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from exp_graph.hierarchy.plan import HierarchyPlan, Role


class DispatchEntry(BaseModel):
    """One agent's dispatch instruction from the emperor."""

    agent_id: int
    role: str
    layer: int
    parent_id: int | None = None
    children_ids: list[int] = Field(default_factory=list)
    soldier_index: int | None = None
    shard_indices: tuple[int, int] | None = None
    aggregated_slice: tuple[int, int] | None = None
    instruction: str = ""
    source: str = "static"


class DispatchTree(BaseModel):
    """Whole-organisation dispatch record."""

    entries: dict[int, DispatchEntry]
    source: str = "static"
    rationale: str = ""

    @model_validator(mode="after")
    def _check_entries(self) -> "DispatchTree":
        if not self.entries:
            raise ValueError("DispatchTree must contain at least one entry")
        return self

    def for_agent(self, agent_id: int) -> DispatchEntry | None:
        return self.entries.get(int(agent_id))


def build_static_dispatch_tree(
    plan: HierarchyPlan,
    *,
    array_length: int | None = None,
    rationale: str = "",
) -> DispatchTree:
    """Derive a dispatch tree mechanically from the plan structure."""
    array_length = (
        int(array_length)
        if array_length is not None
        else int(plan.metadata.get("array_length") or 0)
    )

    soldier_ranges = _soldier_ranges(plan, array_length)
    aggregated_by_id: dict[int, tuple[int, int]] = {}
    for soldier_node in plan.soldier_nodes:
        if soldier_node.soldier_index is None:
            continue
        aggregated_by_id[soldier_node.agent_id] = soldier_ranges[
            soldier_node.soldier_index
        ]

    for layer_idx in sorted({node.layer for node in plan.nodes}, reverse=True):
        for node in plan.nodes:
            if node.layer != layer_idx or node.role == Role.SOLDIER:
                continue
            if not node.children_ids:
                continue
            child_slices = [
                aggregated_by_id[child_id]
                for child_id in node.children_ids
                if child_id in aggregated_by_id
            ]
            if child_slices:
                start = min(slice_[0] for slice_ in child_slices)
                end = max(slice_[1] for slice_ in child_slices)
                aggregated_by_id[node.agent_id] = (start, end)

    entries: dict[int, DispatchEntry] = {}
    for node in plan.nodes:
        if node.role == Role.SOLDIER:
            shard = soldier_ranges[node.soldier_index] if node.soldier_index is not None else None
            instruction = (
                f"Count integer frequencies in array[{shard[0]}:{shard[1]}) "
                f"and report your partial."
                if shard is not None
                else "Count your assigned shard and report your partial."
            )
            entries[node.agent_id] = DispatchEntry(
                agent_id=node.agent_id,
                role=node.role.value,
                layer=node.layer,
                parent_id=node.parent_id,
                children_ids=list(node.children_ids),
                soldier_index=node.soldier_index,
                shard_indices=shard,
                aggregated_slice=shard,
                instruction=instruction,
                source="static",
            )
            continue

        slice_ = aggregated_by_id.get(node.agent_id)
        if node.role == Role.EMPEROR:
            instruction = (
                "Aggregate frequency partials reported by your ministers and "
                "publish the global FREQ_JSON answer."
            )
        elif node.role == Role.MINISTER:
            window = (
                f" covering array[{slice_[0]}:{slice_[1]})"
                if slice_ is not None
                else ""
            )
            instruction = (
                f"Oversee soldiers {list(node.children_ids)}{window}. "
                "Aggregate their partials and forward the running merge."
            )
        else:  # SUB_MANAGER
            window = (
                f" covering array[{slice_[0]}:{slice_[1]})"
                if slice_ is not None
                else ""
            )
            instruction = (
                f"Oversee sub-tree {list(node.children_ids)}{window}. "
                "Aggregate sub-tree partials and forward upstream."
            )
        entries[node.agent_id] = DispatchEntry(
            agent_id=node.agent_id,
            role=node.role.value,
            layer=node.layer,
            parent_id=node.parent_id,
            children_ids=list(node.children_ids),
            soldier_index=None,
            shard_indices=None,
            aggregated_slice=slice_,
            instruction=instruction,
            source="static",
        )
    return DispatchTree(
        entries=entries,
        source="static",
        rationale=rationale,
    )


def attach_dispatch_to_plan(
    plan: HierarchyPlan,
    dispatch: DispatchTree,
) -> HierarchyPlan:
    """Return a new plan with the dispatch tree recorded in metadata."""
    new_metadata = dict(plan.metadata)
    new_metadata["dispatch_tree"] = {
        "source": dispatch.source,
        "rationale": dispatch.rationale,
        "entries": {
            str(agent_id): entry.model_dump(mode="json")
            for agent_id, entry in dispatch.entries.items()
        },
    }
    return plan.model_copy(update={"metadata": new_metadata})


def _soldier_ranges(
    plan: HierarchyPlan,
    array_length: int,
) -> list[tuple[int, int]]:
    """Soldier shard ranges, preferring plan-recorded ranges when available."""
    declared = [node.shard_indices for node in plan.soldier_nodes]
    if all(item is not None for item in declared):
        return [tuple(item) for item in declared]  # type: ignore[misc]

    if array_length <= 0:
        return [(0, 0) for _ in declared]
    base_size, remainder = divmod(int(array_length), plan.n_soldiers)
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for soldier_index in range(plan.n_soldiers):
        size = base_size + (1 if soldier_index < remainder else 0)
        ranges.append((cursor, cursor + size))
        cursor += size
    return ranges


def parse_llm_dispatch(
    plan: HierarchyPlan,
    raw_dispatch: Any,
    *,
    array_length: int | None,
    rationale: str = "",
) -> DispatchTree | None:
    """Parse a raw dispatch payload from emperor LLM, or return ``None`` on failure.

    The expected raw shape is ``{"agent_X": {"slice": [a, b], "instruction": "..."}, ...}``
    or ``{"agent_X": "instruction text"}``. Any agent missing in the raw payload is
    filled in from the static dispatch so the tree is always complete.
    """
    if raw_dispatch is None or not isinstance(raw_dispatch, dict):
        return None
    static = build_static_dispatch_tree(plan, array_length=array_length)
    entries: dict[int, DispatchEntry] = {}
    seen_any = False
    for key, value in raw_dispatch.items():
        agent_id = _parse_agent_key(key)
        if agent_id is None or agent_id < 0 or agent_id >= plan.n_total:
            continue
        base = static.entries.get(agent_id)
        if base is None:
            continue
        instruction, shard, slice_ = _parse_llm_dispatch_value(value)
        merged = base.model_copy(
            update={
                "instruction": instruction or base.instruction,
                "shard_indices": shard if shard is not None else base.shard_indices,
                "aggregated_slice": slice_
                if slice_ is not None
                else base.aggregated_slice,
                "source": "llm",
            }
        )
        entries[agent_id] = merged
        seen_any = True
    if not seen_any:
        return None
    for agent_id, base in static.entries.items():
        entries.setdefault(agent_id, base)
    return DispatchTree(
        entries=entries,
        source="llm" if seen_any else "static",
        rationale=rationale,
    )


def _parse_agent_key(key: Any) -> int | None:
    text = str(key).strip().lower()
    if text.startswith("agent_"):
        text = text[len("agent_") :]
    if text.startswith("agent"):
        text = text[len("agent") :]
    text = text.lstrip("_-:")
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_llm_dispatch_value(
    value: Any,
) -> tuple[str, tuple[int, int] | None, tuple[int, int] | None]:
    if isinstance(value, str):
        return value, None, None
    if not isinstance(value, dict):
        return "", None, None
    instruction = str(value.get("instruction") or "").strip()
    shard = _parse_pair(value.get("shard") or value.get("shard_indices"))
    slice_ = _parse_pair(value.get("slice") or value.get("aggregated_slice"))
    return instruction, shard, slice_


def _parse_pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        start = int(value[0])
        end = int(value[1])
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return (start, end)


class ChildAssignment(BaseModel):
    """Child-level dispatch decision produced by one parent's LLM call."""

    agent_id: int
    shard_indices: tuple[int, int] | None = None
    aggregated_slice: tuple[int, int] | None = None
    instruction: str = ""


class SubordinateDispatchDecision(BaseModel):
    """One parent's recursive dispatch decision over its direct children."""

    parent_id: int
    parent_slice: tuple[int, int]
    children: dict[int, ChildAssignment]
    rationale: str = ""
    source: str = "llm"


def parse_subordinate_dispatch(
    *,
    parent_node,
    parent_slice: tuple[int, int],
    children_nodes,
    raw_payload: Any,
    rationale: str = "",
) -> SubordinateDispatchDecision | None:
    """Parse a minister/sub-manager LLM dispatch and validate the partition.

    Returns ``None`` when the payload cannot be coerced into a valid disjoint
    cover of ``parent_slice`` over the expected children. The caller is
    expected to fall back to ``mechanical_equal_split_children`` in that case.
    """
    if not isinstance(raw_payload, dict):
        return None
    children_payload = raw_payload.get("children")
    if not isinstance(children_payload, dict):
        return None

    expected_ids = {child.agent_id for child in children_nodes}
    children_by_id = {child.agent_id: child for child in children_nodes}
    parsed: dict[int, ChildAssignment] = {}

    for key, value in children_payload.items():
        agent_id = _parse_agent_key(key)
        if agent_id is None or agent_id not in expected_ids:
            return None
        if agent_id in parsed:
            return None
        if not isinstance(value, dict):
            return None
        instruction = str(value.get("instruction") or "").strip()
        shard = _parse_pair(value.get("shard") or value.get("shard_indices"))
        slice_ = _parse_pair(
            value.get("slice")
            or value.get("aggregated_slice")
            or value.get("range")
        )
        child = children_by_id[agent_id]
        if child.role == Role.SOLDIER:
            range_ = shard or slice_
            if range_ is None:
                return None
            parsed[agent_id] = ChildAssignment(
                agent_id=agent_id,
                shard_indices=range_,
                aggregated_slice=range_,
                instruction=instruction,
            )
        else:
            range_ = slice_ or shard
            if range_ is None:
                return None
            parsed[agent_id] = ChildAssignment(
                agent_id=agent_id,
                shard_indices=None,
                aggregated_slice=range_,
                instruction=instruction,
            )

    if set(parsed.keys()) != expected_ids:
        return None

    if not _validate_partition_over_slice(
        slices=[parsed[agent_id].aggregated_slice for agent_id in parsed],
        parent_slice=parent_slice,
    ):
        return None

    return SubordinateDispatchDecision(
        parent_id=parent_node.agent_id,
        parent_slice=parent_slice,
        children=parsed,
        rationale=rationale.strip(),
        source="llm",
    )


def mechanical_equal_split_children(
    *,
    parent_node,
    parent_slice: tuple[int, int],
    children_nodes,
) -> SubordinateDispatchDecision:
    """Build a deterministic equal-split decision used as fallback or default."""
    start, end = parent_slice
    length = max(0, end - start)
    n_children = len(children_nodes)
    if n_children < 1:
        return SubordinateDispatchDecision(
            parent_id=parent_node.agent_id,
            parent_slice=parent_slice,
            children={},
            rationale="no children to dispatch to",
            source="static",
        )
    base, remainder = divmod(length, n_children)
    cursor = start
    children: dict[int, ChildAssignment] = {}
    for idx, child in enumerate(children_nodes):
        size = base + (1 if idx < remainder else 0)
        child_start = cursor
        child_end = cursor + size
        cursor = child_end
        if child.role == Role.SOLDIER:
            instruction = (
                f"Count integer frequencies in array[{child_start}:{child_end})."
            )
            children[child.agent_id] = ChildAssignment(
                agent_id=child.agent_id,
                shard_indices=(child_start, child_end),
                aggregated_slice=(child_start, child_end),
                instruction=instruction,
            )
        else:
            instruction = (
                f"Oversee subordinates {list(child.children_ids)} "
                f"covering array[{child_start}:{child_end})."
            )
            children[child.agent_id] = ChildAssignment(
                agent_id=child.agent_id,
                shard_indices=None,
                aggregated_slice=(child_start, child_end),
                instruction=instruction,
            )
    return SubordinateDispatchDecision(
        parent_id=parent_node.agent_id,
        parent_slice=parent_slice,
        children=children,
        rationale="equal-split fallback",
        source="static",
    )


def apply_subordinate_decision(
    dispatch: DispatchTree,
    decision: SubordinateDispatchDecision,
    *,
    decision_source_label: str,
) -> DispatchTree:
    """Return a new dispatch tree with one parent's decision applied to its children."""
    new_entries = dict(dispatch.entries)
    for agent_id, assignment in decision.children.items():
        base = new_entries.get(agent_id)
        if base is None:
            continue
        new_entries[agent_id] = base.model_copy(
            update={
                "shard_indices": assignment.shard_indices
                if assignment.shard_indices is not None
                else base.shard_indices,
                "aggregated_slice": assignment.aggregated_slice
                if assignment.aggregated_slice is not None
                else base.aggregated_slice,
                "instruction": assignment.instruction or base.instruction,
                "source": decision_source_label,
            }
        )
    return dispatch.model_copy(update={"entries": new_entries})


def _validate_partition_over_slice(
    *,
    slices: list[tuple[int, int] | None],
    parent_slice: tuple[int, int],
) -> bool:
    if any(item is None for item in slices):
        return False
    typed = [item for item in slices if item is not None]
    sorted_slices = sorted(typed, key=lambda pair: pair[0])
    if not sorted_slices:
        return False
    if sorted_slices[0][0] != parent_slice[0]:
        return False
    if sorted_slices[-1][1] != parent_slice[1]:
        return False
    cursor = sorted_slices[0][0]
    for start, end in sorted_slices:
        if start != cursor:
            return False
        if end < start:
            return False
        cursor = end
    return cursor == parent_slice[1]
