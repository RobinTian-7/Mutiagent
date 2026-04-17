"""Tests for routing module behavior."""

import random

from src.schemas.claims import Claim
from src.routing.claim_router import ReinforcedRouter, UniformRouter
from src.routing.topology_filter import get_visible_claims
from src.topology import ChainTopology


def _make_claims(n: int = 5) -> list[Claim]:
    return [
        Claim(claim_id=f"c{i}", agent_id=f"agent_{i % 3}", root_claim_id=f"c{i}")
        for i in range(n)
    ]


def test_uniform_router_returns_valid_claim():
    claims = _make_claims()
    router = UniformRouter()
    activity = {}
    selected = router.select_claim(claims, activity)
    assert selected in claims


def test_reinforced_router_returns_valid_claim():
    claims = _make_claims()
    router = ReinforcedRouter(beta=0.15)
    activity = {"c0": 10, "c1": 1, "c2": 1}
    selected = router.select_claim(claims, activity)
    assert selected in claims


def test_reinforced_router_prefers_active_claims():
    """With high beta, the most active claim should be selected most often."""
    random.seed(42)
    claims = _make_claims(3)
    router = ReinforcedRouter(beta=2.0)  # Strong reinforcement
    activity = {"c0": 100, "c1": 1, "c2": 1}

    counts = {c.claim_id: 0 for c in claims}
    for _ in range(1000):
        selected = router.select_claim(claims, activity)
        counts[selected.claim_id] += 1

    # c0 should be selected far more often
    assert counts["c0"] > counts["c1"]
    assert counts["c0"] > counts["c2"]


def test_topology_filter():
    agents = ["agent_0", "agent_1", "agent_2"]
    topo = ChainTopology(agents)

    claims = [
        Claim(claim_id="c0", agent_id="agent_0", root_claim_id="c0"),
        Claim(claim_id="c1", agent_id="agent_1", root_claim_id="c1"),
        Claim(claim_id="c2", agent_id="agent_2", root_claim_id="c2"),
    ]

    # agent_0 in chain can see agent_0 (self) and agent_1 (neighbor)
    visible = get_visible_claims("agent_0", claims, topo)
    visible_ids = {c.claim_id for c in visible}
    assert "c0" in visible_ids  # own claim
    assert "c1" in visible_ids  # neighbor
    assert "c2" not in visible_ids  # not neighbor in chain
