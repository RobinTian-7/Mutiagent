import pytest

from exp_graph.hierarchy import (
    HierarchyPlan,
    Role,
    build_emperor_soldiers_plan,
    build_static_hierarchy_plan,
    expected_n_soldiers,
    expected_total_agents,
    shape_label_for_fanout,
    shape_label_to_fanout,
)
from exp_graph.hierarchy.planner_static import _equal_shard_ranges


def test_emperor_soldiers_plan_invariants() -> None:
    plan = build_emperor_soldiers_plan(n_soldiers=4, array_length=10)

    assert plan.n_total == 5
    assert plan.n_soldiers == 4
    assert plan.layers == [1, 4]
    assert plan.fanout_schedule == [4]
    assert plan.emperor_id == 0
    assert plan.soldier_ids == [1, 2, 3, 4]
    assert plan.children_of(0) == [1, 2, 3, 4]
    assert plan.parent_of(1) == 0
    assert plan.emperor.role == Role.EMPEROR
    for node in plan.soldier_nodes:
        assert node.role == Role.SOLDIER
        assert node.parent_id == 0
        assert node.children_ids == []


def test_emperor_soldiers_shard_ranges_cover_array_without_overlap() -> None:
    plan = build_emperor_soldiers_plan(n_soldiers=3, array_length=10)
    soldier_ranges = [node.shard_indices for node in plan.soldier_nodes]

    assert soldier_ranges == [(0, 4), (4, 7), (7, 10)]
    cursor = 0
    for start, end in soldier_ranges:
        assert start == cursor
        cursor = end
    assert cursor == 10


def test_equal_shard_ranges_handles_remainder() -> None:
    assert _equal_shard_ranges(3, 10) == [(0, 4), (4, 7), (7, 10)]
    assert _equal_shard_ranges(4, 9) == [(0, 3), (3, 5), (5, 7), (7, 9)]
    assert _equal_shard_ranges(5, 5) == [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]


def test_plan_rejects_zero_soldiers() -> None:
    with pytest.raises(ValueError):
        build_emperor_soldiers_plan(n_soldiers=0)


def test_plan_layers_must_match_n_total() -> None:
    plan = build_emperor_soldiers_plan(n_soldiers=2)
    bad_nodes = list(plan.nodes)
    with pytest.raises(ValueError):
        HierarchyPlan(
            n_total=plan.n_total,
            layers=[1, 5],
            nodes=bad_nodes,
        )


def test_three_layer_plan_assigns_minister_role_and_correct_fanout() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=8)

    assert plan.layers == [1, 2, 8]
    assert plan.n_total == 11
    assert plan.n_soldiers == 8
    assert plan.fanout_schedule == [2, 4]

    minister_ids = [
        node.agent_id for node in plan.nodes if node.role == Role.MINISTER
    ]
    soldier_ids = [
        node.agent_id for node in plan.nodes if node.role == Role.SOLDIER
    ]

    assert minister_ids == [1, 2]
    assert soldier_ids == [3, 4, 5, 6, 7, 8, 9, 10]
    assert plan.children_of(0) == [1, 2]
    assert plan.children_of(1) == [3, 4, 5, 6]
    assert plan.children_of(2) == [7, 8, 9, 10]
    assert plan.parent_of(7) == 2
    assert plan.parent_of(2) == 0


def test_three_layer_plan_assigns_disjoint_complete_shard_ranges() -> None:
    plan = build_static_hierarchy_plan([2, 4], array_length=20)
    soldier_ranges = [node.shard_indices for node in plan.soldier_nodes]

    assert soldier_ranges == [
        (0, 3),
        (3, 6),
        (6, 9),
        (9, 12),
        (12, 14),
        (14, 16),
        (16, 18),
        (18, 20),
    ]
    cursor = 0
    for start, end in soldier_ranges:
        assert start == cursor
        cursor = end
    assert cursor == 20


def test_four_layer_plan_uses_sub_manager_role() -> None:
    plan = build_static_hierarchy_plan([2, 2, 2], array_length=8)

    assert plan.layers == [1, 2, 4, 8]
    assert plan.n_total == 15
    assert plan.fanout_schedule == [2, 2, 2]
    assert {node.role for node in plan.nodes} == {
        Role.EMPEROR,
        Role.MINISTER,
        Role.SUB_MANAGER,
        Role.SOLDIER,
    }
    sub_managers = [
        node for node in plan.nodes if node.role == Role.SUB_MANAGER
    ]
    assert len(sub_managers) == 4
    for sm in sub_managers:
        assert sm.layer == 2
        assert plan.node(sm.parent_id).role == Role.MINISTER
        for child_id in sm.children_ids:
            assert plan.node(child_id).role == Role.SOLDIER


def test_emperor_soldiers_wrapper_matches_general_planner() -> None:
    a = build_emperor_soldiers_plan(n_soldiers=4, array_length=12)
    b = build_static_hierarchy_plan([4], array_length=12)

    assert a.layers == b.layers
    assert a.n_total == b.n_total
    assert a.fanout_schedule == b.fanout_schedule
    assert [node.role for node in a.nodes] == [node.role for node in b.nodes]
    assert [node.shard_indices for node in a.nodes] == [
        node.shard_indices for node in b.nodes
    ]


def test_shape_label_round_trip() -> None:
    assert shape_label_to_fanout("8") == [8]
    assert shape_label_to_fanout("2x4") == [2, 4]
    assert shape_label_to_fanout("4X4") == [4, 4]
    assert shape_label_to_fanout("4x2x4") == [4, 2, 4]
    assert shape_label_for_fanout([2, 4]) == "2x4"
    assert shape_label_for_fanout([8]) == "8"


def test_expected_total_agents_matches_planner() -> None:
    for fanout in ([8], [2, 4], [4, 4], [4, 2, 4]):
        plan = build_static_hierarchy_plan(fanout)
        assert expected_total_agents(fanout) == plan.n_total
        assert expected_n_soldiers(fanout) == plan.n_soldiers


def test_planner_rejects_invalid_fanout_inputs() -> None:
    with pytest.raises(ValueError):
        build_static_hierarchy_plan([])
    with pytest.raises(ValueError):
        build_static_hierarchy_plan([0, 4])
    with pytest.raises(ValueError):
        build_static_hierarchy_plan([2, -1])
