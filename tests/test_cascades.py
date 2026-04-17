"""Tests for cascade extraction."""

from src.schemas.claims import Claim, ClaimType
from src.schemas.events import Event, EventType
from src.reconstruction.cascades import extract_cascades


def test_single_cascade():
    claims = [
        Claim(claim_id="c1", agent_id="a0", root_claim_id="c1"),
        Claim(claim_id="c2", agent_id="a1", root_claim_id="c1",
              parent_claim_ids=["c1"]),
        Claim(claim_id="c3", agent_id="a2", root_claim_id="c1",
              parent_claim_ids=["c1"]),
    ]
    cascades = extract_cascades(claims)
    assert len(cascades) == 1
    assert cascades[0].root_claim_id == "c1"
    assert cascades[0].size == 3


def test_multiple_cascades():
    claims = [
        Claim(claim_id="c1", agent_id="a0", root_claim_id="c1"),
        Claim(claim_id="c2", agent_id="a1", root_claim_id="c1",
              parent_claim_ids=["c1"]),
        Claim(claim_id="c10", agent_id="a2", root_claim_id="c10"),
        Claim(claim_id="c11", agent_id="a3", root_claim_id="c10",
              parent_claim_ids=["c10"]),
    ]
    cascades = extract_cascades(claims)
    assert len(cascades) == 2
    sizes = sorted([c.size for c in cascades])
    assert sizes == [2, 2]


def test_cascade_with_events():
    claims = [
        Claim(claim_id="c1", agent_id="a0", root_claim_id="c1"),
        Claim(claim_id="c2", agent_id="a1", root_claim_id="c1",
              parent_claim_ids=["c1"]),
    ]
    events = [
        Event(event_id="e1", agent_id="a0", event_type=EventType.PROPOSE_CLAIM,
              claim_id="c1", root_claim_id="c1"),
        Event(event_id="e2", agent_id="a1", event_type=EventType.REVISE_CLAIM,
              claim_id="c2", root_claim_id="c1"),
    ]
    cascades = extract_cascades(claims, events)
    assert cascades[0].tce == 2


def test_empty_input():
    cascades = extract_cascades([], [])
    assert cascades == []
