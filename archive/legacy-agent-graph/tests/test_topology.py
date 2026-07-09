"""Tests for topology visibility and neighbor correctness."""

from src.topology import (
    ChainTopology,
    MeshTopology,
    OnePeerExponentialTopology,
    StarTopology,
    StaticExponentialTopology,
    create_topology,
    topology_names,
)


AGENTS = [f"agent_{i}" for i in range(5)]


def test_chain_endpoints():
    topo = ChainTopology(AGENTS)
    # First agent only sees next
    assert topo.get_neighbors("agent_0") == ["agent_1"]
    # Last agent only sees previous
    assert topo.get_neighbors("agent_4") == ["agent_3"]


def test_chain_middle():
    topo = ChainTopology(AGENTS)
    neighbors = topo.get_neighbors("agent_2")
    assert set(neighbors) == {"agent_1", "agent_3"}


def test_star_hub_sees_all():
    topo = StarTopology(AGENTS)
    hub_neighbors = topo.get_neighbors("agent_0")
    assert set(hub_neighbors) == {"agent_1", "agent_2", "agent_3", "agent_4"}


def test_star_spoke_sees_only_hub():
    topo = StarTopology(AGENTS)
    assert topo.get_neighbors("agent_3") == ["agent_0"]


def test_mesh_all_connected():
    topo = MeshTopology(AGENTS)
    for agent in AGENTS:
        neighbors = topo.get_neighbors(agent)
        assert len(neighbors) == 4
        assert agent not in neighbors


def test_can_communicate():
    topo = ChainTopology(AGENTS)
    assert topo.can_communicate("agent_0", "agent_1")
    assert not topo.can_communicate("agent_0", "agent_3")


def test_mesh_symmetric():
    topo = MeshTopology(AGENTS)
    for a in AGENTS:
        for b in AGENTS:
            if a != b:
                assert topo.can_communicate(a, b)


def test_static_exponential_neighbor_correctness_power_of_two():
    agents = [f"agent_{i}" for i in range(8)]
    topo = StaticExponentialTopology(agents)

    assert topo.tau == 3
    assert topo.get_neighbors("agent_0") == ["agent_1", "agent_2", "agent_4"]
    assert topo.get_neighbors("agent_6") == ["agent_7", "agent_0", "agent_2"]


def test_static_exponential_neighbor_correctness_non_power_of_two():
    agents = [f"agent_{i}" for i in range(6)]
    topo = StaticExponentialTopology(agents)

    assert topo.tau == 3
    assert topo.get_neighbors("agent_0") == ["agent_1", "agent_2", "agent_4"]
    assert topo.get_neighbors("agent_4") == ["agent_5", "agent_0", "agent_2"]


def test_one_peer_exponential_round_robin_neighbor_correctness():
    agents = [f"agent_{i}" for i in range(8)]
    topo = OnePeerExponentialTopology(agents)

    assert topo.tau == 3
    assert topo.has_periodic_exact_averaging_guarantee
    assert topo.get_neighbors("agent_0", round_idx=0) == ["agent_1"]
    assert topo.get_neighbors("agent_0", round_idx=1) == ["agent_2"]
    assert topo.get_neighbors("agent_0", round_idx=2) == ["agent_4"]
    assert topo.get_neighbors("agent_0", round_idx=3) == ["agent_1"]
    assert topo.get_neighbors("agent_5", round_idx=2) == ["agent_1"]


def test_one_peer_exponential_non_power_of_two_runs_as_heuristic():
    agents = [f"agent_{i}" for i in range(6)]
    topo = OnePeerExponentialTopology(agents)

    assert topo.tau == 3
    assert not topo.has_periodic_exact_averaging_guarantee
    assert topo.get_neighbors("agent_0", round_idx=0) == ["agent_1"]
    assert topo.get_neighbors("agent_0", round_idx=1) == ["agent_2"]
    assert topo.get_neighbors("agent_0", round_idx=2) == ["agent_4"]
    assert topo.get_neighbors("agent_0", round_idx=3) == ["agent_1"]


def test_topology_factory_and_interface_consistency():
    for name in topology_names():
        topo = create_topology(name, AGENTS)
        for agent_id in AGENTS:
            neighbors = topo.get_neighbors(agent_id, round_idx=0)
            assert isinstance(neighbors, list)
            assert agent_id not in neighbors
            assert all(neighbor in AGENTS for neighbor in neighbors)
