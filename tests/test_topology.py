"""Tests for topology visibility and neighbor correctness."""

from src.topology import ChainTopology, StarTopology, MeshTopology


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
