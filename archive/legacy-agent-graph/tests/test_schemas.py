"""Tests for schema validation."""

from src.schemas.claims import Claim, ClaimStatus, ClaimType
from src.schemas.events import Event, EventType
from src.schemas.subtasks import Subtask, SubtaskStatus
from src.schemas.cascades import Cascade


def test_claim_creation():
    c = Claim(claim_id="c1", agent_id="agent_0", content="test claim")
    assert c.claim_id == "c1"
    assert c.claim_type == ClaimType.PROPOSED
    assert c.claim_status == ClaimStatus.ACTIVE
    assert c.parent_claim_ids == []
    assert c.root_claim_id == "c1"  # Self-root when no parents


def test_claim_with_parents():
    c = Claim(
        claim_id="c2",
        agent_id="agent_1",
        parent_claim_ids=["c1"],
        root_claim_id="c1",
        claim_type=ClaimType.REVISED,
    )
    assert c.parent_claim_ids == ["c1"]
    assert c.root_claim_id == "c1"
    assert c.claim_type == ClaimType.REVISED


def test_merged_claim():
    c = Claim(
        claim_id="c5",
        agent_id="agent_2",
        parent_claim_ids=["c2", "c3", "c4"],
        root_claim_id="c1",
        claim_type=ClaimType.MERGED,
        claim_depth=3,
    )
    assert len(c.parent_claim_ids) == 3
    assert c.claim_type == ClaimType.MERGED


def test_event_creation():
    e = Event(
        event_id="e1",
        agent_id="agent_0",
        event_type=EventType.PROPOSE_CLAIM,
        claim_id="c1",
    )
    assert e.event_type == EventType.PROPOSE_CLAIM


def test_merge_event():
    e = Event(
        event_id="e5",
        agent_id="agent_2",
        event_type=EventType.MERGE_CLAIMS,
        claim_id="c5",
        parent_claim_ids=["c2", "c3"],
    )
    assert e.event_type == EventType.MERGE_CLAIMS
    assert len(e.parent_claim_ids) == 2


def test_subtask_creation():
    s = Subtask(subtask_id="s1", description="test subtask")
    assert s.subtask_status == SubtaskStatus.PENDING
    assert s.parent_subtask_id is None


def test_cascade():
    c = Cascade(
        root_claim_id="c1",
        claim_ids=["c1", "c2", "c3"],
        event_ids=["e1", "e2"],
    )
    assert c.size == 3
    assert c.tce == 2


def test_claim_types_are_strings():
    """Verify enum serialization works for JSONL output."""
    for ct in ClaimType:
        assert isinstance(ct.value, str)
    for et in EventType:
        assert isinstance(et.value, str)
