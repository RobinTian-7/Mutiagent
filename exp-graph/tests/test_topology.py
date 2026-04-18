from exp_graph.topology import create_topology, topology_names


def test_static_exponential_neighbor_correctness() -> None:
    topology = create_topology("static_exponential")

    assert topology.get_neighbors(agent_id=0, round_idx=0, n_agents=8) == [1, 2, 4]
    assert topology.get_neighbors(agent_id=6, round_idx=3, n_agents=8) == [7, 0, 2]


def test_one_peer_exponential_round_alignment_correctness() -> None:
    topology = create_topology("one_peer_exponential")

    assert topology.get_neighbors(agent_id=0, round_idx=0, n_agents=8) == [1]
    assert topology.get_neighbors(agent_id=0, round_idx=1, n_agents=8) == [2]
    assert topology.get_neighbors(agent_id=0, round_idx=2, n_agents=8) == [4]
    assert topology.get_neighbors(agent_id=0, round_idx=3, n_agents=8) == [1]
    assert topology.get_neighbors(agent_id=7, round_idx=2, n_agents=8) == [3]


def test_one_peer_exponential_non_power_of_two_still_runs() -> None:
    topology = create_topology("one_peer_exponential")

    assert topology.get_neighbors(agent_id=0, round_idx=0, n_agents=6) == [1]
    assert topology.get_neighbors(agent_id=0, round_idx=1, n_agents=6) == [2]
    assert topology.get_neighbors(agent_id=0, round_idx=2, n_agents=6) == [4]
    assert topology.get_neighbors(agent_id=0, round_idx=3, n_agents=6) == [1]


def test_topology_interface_consistency() -> None:
    for name in topology_names():
        topology = create_topology(name)
        neighbors = topology.get_neighbors(agent_id=1, round_idx=0, n_agents=4)
        assert isinstance(neighbors, list)
        assert all(isinstance(neighbor, int) for neighbor in neighbors)
        assert 1 not in neighbors
        assert all(0 <= neighbor < 4 for neighbor in neighbors)


def test_basic_topologies() -> None:
    assert create_topology("chain").get_neighbors(1, 0, 4) == [0, 2]
    assert create_topology("star").get_neighbors(0, 0, 4) == [1, 2, 3]
    assert create_topology("star").get_neighbors(3, 0, 4) == [0]
    assert create_topology("mesh").get_neighbors(2, 0, 4) == [0, 1, 3]
