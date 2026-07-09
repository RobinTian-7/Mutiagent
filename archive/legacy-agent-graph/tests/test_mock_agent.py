"""Tests for the runnable mock agent policy."""

from src.agents.mock_agent import mock_agent_action
from src.schemas.claims import Claim, ClaimType
from src.schemas.events import EventType


def test_mock_merge_stays_within_selected_cascade():
    """Merge parents should share the selected claim's root id."""
    selected = Claim(claim_id="c1", agent_id="a0", root_claim_id="c1")
    same_root = Claim(
        claim_id="c2",
        agent_id="a1",
        root_claim_id="c1",
        parent_claim_ids=["c1"],
        claim_type=ClaimType.REVISED,
    )
    other_root = Claim(claim_id="c10", agent_id="a2", root_claim_id="c10")

    event, claim = mock_agent_action(
        agent_id="a3",
        visible_claims=[selected, same_root, other_root],
        selected_claim=selected,
        action_probs={EventType.MERGE_CLAIMS: 1.0},
    )

    assert event.event_type == EventType.MERGE_CLAIMS
    assert set(event.parent_claim_ids) == {"c1", "c2"}
    assert claim.root_claim_id == "c1"


def test_mock_merge_falls_back_when_cascade_has_one_visible_claim():
    """Do not fabricate cross-root merges when only one same-root claim is visible."""
    selected = Claim(claim_id="c1", agent_id="a0", root_claim_id="c1")
    other_root = Claim(claim_id="c10", agent_id="a2", root_claim_id="c10")

    event, claim = mock_agent_action(
        agent_id="a3",
        visible_claims=[selected, other_root],
        selected_claim=selected,
        action_probs={EventType.MERGE_CLAIMS: 1.0},
    )

    assert event.event_type == EventType.REVISE_CLAIM
    assert event.parent_claim_ids == ["c1"]
    assert claim.root_claim_id == "c1"
