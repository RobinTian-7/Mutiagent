import pytest

from exp_graph.hierarchy import (
    HierarchyTopology,
    build_emperor_soldiers_plan,
    build_static_hierarchy_plan,
)


def test_emperor_sees_all_soldiers_and_each_soldier_sees_emperor() -> None:
    plan = build_emperor_soldiers_plan(n_soldiers=4)
    topology = HierarchyTopology(plan)

    assert topology.get_neighbors(agent_id=0, round_idx=0, n_agents=5) == [1, 2, 3, 4]
    for soldier_id in (1, 2, 3, 4):
        assert topology.get_neighbors(
            agent_id=soldier_id,
            round_idx=0,
            n_agents=5,
        ) == [0]


def test_topology_rejects_population_mismatch() -> None:
    plan = build_emperor_soldiers_plan(n_soldiers=2)
    topology = HierarchyTopology(plan)

    with pytest.raises(ValueError):
        topology.get_neighbors(agent_id=0, round_idx=0, n_agents=4)


def test_topology_neighbor_round_independence() -> None:
    plan = build_emperor_soldiers_plan(n_soldiers=3)
    topology = HierarchyTopology(plan)

    for round_idx in range(5):
        assert topology.get_neighbors(
            agent_id=0, round_idx=round_idx, n_agents=4
        ) == [1, 2, 3]
        assert topology.get_neighbors(
            agent_id=2, round_idx=round_idx, n_agents=4
        ) == [0]


def test_three_layer_topology_routes_minister_parent_and_children() -> None:
    plan = build_static_hierarchy_plan([2, 4])
    topology = HierarchyTopology(plan)
    n = plan.n_total

    assert topology.get_neighbors(agent_id=0, round_idx=0, n_agents=n) == [1, 2]
    assert topology.get_neighbors(agent_id=1, round_idx=0, n_agents=n) == [3, 4, 5, 6, 0]
    assert topology.get_neighbors(agent_id=2, round_idx=0, n_agents=n) == [7, 8, 9, 10, 0]
    for soldier_id in (3, 4, 5, 6):
        assert topology.get_neighbors(
            agent_id=soldier_id,
            round_idx=0,
            n_agents=n,
        ) == [1]
    for soldier_id in (7, 8, 9, 10):
        assert topology.get_neighbors(
            agent_id=soldier_id,
            round_idx=0,
            n_agents=n,
        ) == [2]


def test_four_layer_topology_routes_sub_manager_layer() -> None:
    plan = build_static_hierarchy_plan([2, 2, 2])
    topology = HierarchyTopology(plan)
    n = plan.n_total

    minister_ids = [node.agent_id for node in plan.nodes if node.layer == 1]
    sub_manager_ids = [node.agent_id for node in plan.nodes if node.layer == 2]
    assert minister_ids == [1, 2]
    assert sub_manager_ids == [3, 4, 5, 6]

    for sm_id in sub_manager_ids:
        sm = plan.node(sm_id)
        neighbors = topology.get_neighbors(
            agent_id=sm_id,
            round_idx=0,
            n_agents=n,
        )
        assert neighbors[-1] == sm.parent_id
        assert sorted(neighbors[:-1]) == sorted(sm.children_ids)
