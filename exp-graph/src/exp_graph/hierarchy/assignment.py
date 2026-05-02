"""Build per-agent local observations from a hierarchy plan.

The synchronous runner expects one ``local_observation`` dict per agent, in
agent-id order. For a hierarchy plan we have to:

- Reuse the task adapter's standard shard split for the soldier population
  only, so existing CF/array-search task semantics still apply.
- Re-key each shard observation by the soldier's runner-level ``agent_id``
  (rather than its ``soldier_index``), so the partials produced by
  ``initial_local_solve`` carry the same keys the runner will use to look
  agents up.
- Build empty placeholder observations for non-leaf agents (emperor and any
  middle-layer ministers / sub-managers). Each non-leaf observation is tagged
  with ``role`` and uses ``n_agents = n_soldiers`` so the existing CF
  "covered all agents" finalization rule fires once inbox partials cover
  every soldier id.
"""

from __future__ import annotations

from typing import Any

from exp_graph.hierarchy.dispatch import DispatchTree, build_static_dispatch_tree
from exp_graph.hierarchy.plan import HierarchyPlan, Role
from exp_graph.tasks.base import TaskAdapter


def build_hierarchy_local_observations(
    *,
    plan: HierarchyPlan,
    task_adapter: TaskAdapter,
    global_task: dict[str, Any],
    dispatch: DispatchTree | None = None,
) -> list[dict[str, Any]]:
    """Return one observation per agent in agent-id order.

    When ``dispatch`` is omitted a static dispatch tree is generated from the
    plan structure so prompts can always surface a non-empty assignment.
    """
    soldier_observations = task_adapter.split_into_local_observations(
        global_task=global_task,
        n_agents=plan.n_soldiers,
    )
    if len(soldier_observations) != plan.n_soldiers:
        raise RuntimeError(
            "task adapter returned "
            f"{len(soldier_observations)} observations for "
            f"{plan.n_soldiers} soldiers"
        )

    array_length = int(global_task.get("array_length", 0))
    if dispatch is None:
        dispatch = build_static_dispatch_tree(plan, array_length=array_length)

    observations: list[dict[str, Any]] = [dict() for _ in range(plan.n_total)]

    for soldier_node in plan.soldier_nodes:
        if soldier_node.soldier_index is None:
            raise RuntimeError(
                f"soldier node {soldier_node.agent_id} has no soldier_index; "
                "planner contract violated"
            )
        default_obs = dict(soldier_observations[soldier_node.soldier_index])
        observation = _build_soldier_observation(
            plan=plan,
            global_task=global_task,
            dispatch=dispatch,
            soldier_node=soldier_node,
            default_obs=default_obs,
        )
        observations[soldier_node.agent_id] = observation

    for node in plan.nodes:
        if node.role == Role.SOLDIER:
            continue
        observations[node.agent_id] = _build_non_leaf_observation(
            plan=plan,
            global_task=global_task,
            soldier_observations=soldier_observations,
            node=node,
            dispatch=dispatch,
        )

    _validate_soldier_shards_partition_array(observations, plan, array_length)
    return observations


def _validate_soldier_shards_partition_array(
    observations: list[dict[str, Any]],
    plan: HierarchyPlan,
    array_length: int,
) -> None:
    """Sanity check that LLM-provided shards still cover the array exactly once."""
    if array_length <= 0:
        return
    soldier_ranges = []
    for soldier_node in plan.soldier_nodes:
        observation = observations[soldier_node.agent_id]
        soldier_ranges.append(
            (
                int(observation["shard_start"]),
                int(observation["shard_end_exclusive"]),
            )
        )
    soldier_ranges.sort(key=lambda pair: pair[0])
    cursor = 0
    for start, end in soldier_ranges:
        if start != cursor or end < start:
            raise ValueError(
                f"hierarchy dispatch produced non-partitioning soldier shards "
                f"around index {start}; sorted ranges={soldier_ranges}"
            )
        cursor = end
    if cursor != array_length:
        raise ValueError(
            f"hierarchy dispatch ended at offset {cursor} but array_length="
            f"{array_length}; sorted ranges={soldier_ranges}"
        )


def _build_soldier_observation(
    *,
    plan: HierarchyPlan,
    global_task: dict[str, Any],
    dispatch: DispatchTree,
    soldier_node,
    default_obs: dict[str, Any],
) -> dict[str, Any]:
    """Produce a soldier observation, honoring the dispatch tree's shard."""
    observation = dict(default_obs)
    entry = dispatch.for_agent(soldier_node.agent_id)
    if (
        entry is not None
        and entry.shard_indices is not None
        and global_task.get("task_name") == "count_frequency"
        and "array" in global_task
    ):
        start, end = entry.shard_indices
        array = list(global_task.get("array") or [])
        if 0 <= start <= end <= len(array):
            observation["array_shard"] = array[start:end]
            observation["global_offset"] = int(start)
            observation["shard_start"] = int(start)
            observation["shard_end_exclusive"] = int(end)

    observation["agent_id"] = soldier_node.agent_id
    observation["role"] = Role.SOLDIER.value
    observation["soldier_index"] = soldier_node.soldier_index
    observation["hierarchy_n_soldiers"] = plan.n_soldiers
    observation["hierarchy_emperor_id"] = plan.emperor_id
    observation["hierarchy_layer"] = soldier_node.layer
    observation["hierarchy_parent_id"] = soldier_node.parent_id
    observation["assignment"] = _assignment_payload(dispatch, soldier_node.agent_id)
    return observation


def _assignment_payload(
    dispatch: DispatchTree,
    agent_id: int,
) -> dict[str, Any] | None:
    entry = dispatch.for_agent(agent_id)
    if entry is None:
        return None
    payload: dict[str, Any] = {
        "instruction": entry.instruction,
        "source": entry.source,
    }
    if entry.shard_indices is not None:
        payload["shard_indices"] = list(entry.shard_indices)
    if entry.aggregated_slice is not None:
        payload["aggregated_slice"] = list(entry.aggregated_slice)
    if entry.children_ids:
        payload["children_ids"] = list(entry.children_ids)
    if entry.parent_id is not None:
        payload["parent_id"] = entry.parent_id
    return payload


def _build_non_leaf_observation(
    *,
    plan: HierarchyPlan,
    global_task: dict[str, Any],
    soldier_observations: list[dict[str, Any]],
    node,
    dispatch: DispatchTree,
) -> dict[str, Any]:
    """Build an empty-shard observation for an emperor or middle-layer node."""
    template = soldier_observations[0] if soldier_observations else {}
    task_name = template.get("task_name") or global_task.get("task_name") or "unknown"
    array_length = int(global_task.get("array_length", 0))
    value_min = int(template.get("value_min", global_task.get("value_min", 0)))
    value_max = int(template.get("value_max", global_task.get("value_max", 0)))

    return {
        "task_name": task_name,
        "agent_id": node.agent_id,
        "role": node.role.value,
        "soldier_index": None,
        "array_shard": [],
        "global_offset": 0,
        "shard_start": 0,
        "shard_end_exclusive": 0,
        "n_agents": plan.n_soldiers,
        "array_length": array_length,
        "value_min": value_min,
        "value_max": value_max,
        "hierarchy_n_soldiers": plan.n_soldiers,
        "hierarchy_emperor_id": plan.emperor_id,
        "hierarchy_layer": node.layer,
        "hierarchy_parent_id": node.parent_id,
        "hierarchy_children_ids": list(node.children_ids),
        "assignment": _assignment_payload(dispatch, node.agent_id),
    }
